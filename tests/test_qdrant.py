"""Step 12: Qdrant as a secured, derived vector index of rag-db.

The static tests read the committed files and check the rules the guide sets (tag + digest pin,
keys only from secret files, telemetry off, JWT RBAC on, 6333/6334 on 127.0.0.1 only and 6335
never published, the collection design, the alias, the read-only sync, scoped tokens, the
`qdrant-health` / `qdrant-snapshot` recipes).

The live tests run only when a real Qdrant is reachable on 127.0.0.1:6333 AND `QDRANT_API_KEY` is
in the environment (e.g. `just up`, then `just with-secrets uv run pytest tests/test_qdrant.py`).
The sync comparison additionally needs rag-db on 127.0.0.1:5432 with the Step 11 migration applied
and the role passwords; it loads Step 11's demo documents through a tiny fake gateway that returns
deterministic bag-of-words embeddings, mirrors them into Qdrant and checks both engines agree.
"""

import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
JUSTFILE = REPO / "justfile"
SCRIPTS = REPO / "scripts"
SETUP = SCRIPTS / "qdrant_setup.py"
SYNC = SCRIPTS / "qdrant_sync.py"
TOKEN = SCRIPTS / "qdrant_token.py"
PG_DEMO = SCRIPTS / "pg_demo.py"
VERSIONED = "rag_chunks_qwen3e06b_v1"
ALIAS = "rag_chunks"
KEY_SECRETS = {
    "qdrant_api_key": "QDRANT_API_KEY",
    "qdrant_read_only_api_key": "QDRANT_READ_ONLY_API_KEY",
}


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def _qdrant() -> dict[str, Any]:
    service = _compose()["services"]["qdrant"]
    assert isinstance(service, dict)
    return service


# --- Compose service ------------------------------------------------------------------------


def test_image_is_qdrant_1_19_pinned_by_tag_and_digest() -> None:
    assert re.fullmatch(r"qdrant/qdrant:v1\.19\.\d+@sha256:[0-9a-f]{64}", _qdrant()["image"])


def test_keys_come_from_secret_files_inside_the_container_only() -> None:
    service = _qdrant()
    assert service["entrypoint"] == ["/bin/sh", "-c"]
    (command,) = service["command"]
    assert 'QDRANT__SERVICE__API_KEY="$$(cat /run/secrets/qdrant_api_key)"' in command
    assert (
        'QDRANT__SERVICE__READ_ONLY_API_KEY="$$(cat /run/secrets/qdrant_read_only_api_key)"'
        in command
    )
    assert command.strip().endswith("exec /qdrant/entrypoint.sh")
    assert service["secrets"] == list(KEY_SECRETS)
    secrets = _compose()["secrets"]
    for name, env in KEY_SECRETS.items():
        assert secrets[name] == {"environment": env}
    # No key ever appears as a plain environment variable (it would show in `docker inspect`).
    assert not any("API_KEY" in name for name in service["environment"])


def test_telemetry_off_and_scoped_tokens_on() -> None:
    assert _qdrant()["environment"] == {
        "QDRANT__TELEMETRY_DISABLED": "true",
        "QDRANT__SERVICE__JWT_RBAC": "true",
        "QDRANT__LOG_LEVEL": "INFO",
    }


def test_only_rest_and_grpc_published_and_only_on_localhost() -> None:
    ports = _qdrant()["ports"]
    assert ports == ["127.0.0.1:6333:6333", "127.0.0.1:6334:6334"]
    assert not any("6335" in p for p in ports)  # cluster port: unauthenticated, never published


def test_storage_snapshots_health_and_limits() -> None:
    service = _qdrant()
    assert service["volumes"] == [
        "qdrant-data:/qdrant/storage",
        "qdrant-snapshots:/qdrant/snapshots",
    ]
    volumes = _compose()["volumes"]
    assert "qdrant-data" in volumes
    assert "qdrant-snapshots" in volumes
    assert service["healthcheck"]["test"] == [
        "CMD-SHELL",
        "bash -c ':> /dev/tcp/127.0.0.1/6333' || exit 1",
    ]
    assert service["restart"] == "unless-stopped"
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["deploy"]["resources"]["limits"] == {"memory": "2g", "cpus": "2"}


def test_keys_are_generated_and_documented() -> None:
    generator = (SCRIPTS / "new-dev-secrets.sh").read_text()
    example = (REPO / ".env.example").read_text()
    for env in KEY_SECRETS.values():
        assert f"\n{env}=$(openssl rand -hex 32)\n" in generator
        assert re.search(rf"^{env}=<64 hex characters", example, re.MULTILINE)


def test_health_and_snapshot_recipes() -> None:
    text = JUSTFILE.read_text()
    assert "\nqdrant-health:\n" in text
    assert "\nqdrant-snapshot:\n" in text
    assert (
        'curl -sf -H "api-key: $QDRANT_API_KEY" http://127.0.0.1:6333/collections | jq -c .' in text
    )
    assert (
        f'curl -sf -X POST -H "api-key: $QDRANT_API_KEY" http://127.0.0.1:6333/collections/{VERSIONED}/snapshots'
        in text
    )
    # The key is expanded by the shell sops starts, never by just (single quotes).
    for line in text.splitlines():
        if "QDRANT_API_KEY" in line and "sops exec-env" in line:
            assert line.strip().startswith("sops exec-env secrets/dev.enc.env '")


# --- scripts --------------------------------------------------------------------------------


def test_scripts_compile() -> None:
    for script in (SETUP, SYNC, TOKEN):
        assert os.access(script, os.X_OK)
        compile(script.read_text(), str(script), "exec")


def test_setup_designs_the_collection_as_the_guide_says() -> None:
    text = " ".join(SETUP.read_text().split())
    assert f'VERSIONED = "{VERSIONED}"' in text
    assert f'ALIAS = "{ALIAS}"' in text
    assert (
        "models.VectorParams( size=1024, distance=models.Distance.COSINE, "
        "datatype=models.Datatype.FLOAT16 )" in text
    )
    assert 'sparse_vectors_config={"sparse": models.SparseVectorParams()}' in text
    assert "models.HnswConfigDiff(m=16, ef_construct=100)" in text
    assert "type=models.ScalarType.INT8, always_ram=True" in text
    assert "KeywordIndexType.KEYWORD, is_tenant=True" in text
    for field in ("tenant_id", "acl_groups", "classification", "document_id"):
        assert f'"{field}":' in text
    assert "if not client.collection_exists(VERSIONED):" in text  # safe to re-run
    assert "models.CreateAlias(collection_name=VERSIONED, alias_name=ALIAS)" in text


def test_sync_reads_postgres_as_readonly_and_writes_through_the_alias() -> None:
    text = " ".join(SYNC.read_text().split())
    assert (
        "postgresql://rag_readonly:{os.environ['RAG_DB_READONLY_PASSWORD']}@127.0.0.1:5432/rag"
        in text
    )
    assert "WHERE d.deleted_at IS NULL" in text
    assert "id=cid," in text  # same id as Postgres
    assert 'vector={"dense": emb.to_list()}' in text  # copied, never re-embedded
    assert "qd.upsert(collection_name=ALIAS, points=points, wait=True)" in text
    assert 'api_key=os.environ["RAG_API_GATEWAY_KEY"]' in text  # a virtual key, not the master key
    assert "QuantizationSearchParams(rescore=True)" in text
    assert 'models.FieldCondition(key="tenant_id", match=models.MatchValue(value=TENANT))' in text
    assert 'models.FieldCondition(key="acl_groups", match=models.MatchAny(any=groups))' in text


def test_token_is_read_only_scoped_and_expiring() -> None:
    text = " ".join(TOKEN.read_text().split())
    assert f'COLLECTION = "{VERSIONED}"' in text
    assert '"access": [{"collection": COLLECTION, "access": "r"}]' in text
    assert '"exp": int(time.time()) + 3600' in text
    assert 'os.environ["QDRANT_API_KEY"], algorithm="HS256"' in text


# --- live Qdrant (opt-in) -------------------------------------------------------------------

QDRANT_URL = "http://127.0.0.1:6333"


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(
    not (os.environ.get("QDRANT_API_KEY") and _port_open(6333)),
    reason="needs Qdrant on 127.0.0.1:6333 and QDRANT_API_KEY",
)
live_with_db = pytest.mark.skipif(
    not (
        os.environ.get("QDRANT_API_KEY")
        and os.environ.get("RAG_DB_APP_PASSWORD")
        and os.environ.get("RAG_DB_READONLY_PASSWORD")
        and _port_open(6333)
        and _port_open(5432)
    ),
    reason="needs Qdrant, rag-db (migrated), QDRANT_API_KEY and RAG_DB_*_PASSWORD",
)


def _status(path: str, key: str | None = None, method: str = "GET") -> int:
    request = urllib.request.Request(QDRANT_URL + path, method=method)  # noqa: S310 - fixed localhost URL
    if key:
        request.add_header("api-key", key)
    if method != "GET":
        request.add_header("Content-Type", "application/json")
        request.data = b"{}"
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as err:
        return err.code


def _get(path: str) -> dict[str, Any]:
    request = urllib.request.Request(QDRANT_URL + path)  # noqa: S310 - fixed localhost URL
    request.add_header("api-key", os.environ["QDRANT_API_KEY"])
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        data = json.load(response)
    assert isinstance(data, dict)
    result = data["result"]
    assert isinstance(result, dict)
    return result


def _run(script: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, str(script)],
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture(scope="module")
def collection() -> str:
    """Run the (idempotent) setup script once for the live tests."""
    out = _run(SETUP)
    assert f"alias {ALIAS} -> {VERSIONED}" in out
    return VERSIONED


@live
def test_requests_without_the_right_key_are_rejected() -> None:
    assert _status("/collections") == 401
    assert _status("/collections", key="wrong") == 401
    ro = os.environ.get("QDRANT_READ_ONLY_API_KEY")
    if ro:
        assert _status("/collections", key=ro) == 200
        assert _status("/collections/should_not_exist", key=ro, method="PUT") == 403


@live
def test_telemetry_reporting_is_disabled_and_rbac_on() -> None:
    app = _get("/telemetry")["app"]
    assert app["version"].startswith("1.19.")
    assert app["jwt_rbac"] is True


@live
def test_collection_matches_the_design(collection: str) -> None:
    info = _get(f"/collections/{collection}")
    params = info["config"]["params"]
    assert params["vectors"]["dense"] == {"size": 1024, "distance": "Cosine", "datatype": "float16"}
    assert "sparse" in params["sparse_vectors"]
    hnsw = info["config"]["hnsw_config"]
    assert (hnsw["m"], hnsw["ef_construct"]) == (16, 100)
    assert info["config"]["quantization_config"] == {"scalar": {"type": "int8", "always_ram": True}}
    schema = info["payload_schema"]
    assert set(schema) >= {"tenant_id", "acl_groups", "classification", "document_id"}
    assert schema["tenant_id"]["params"]["is_tenant"] is True
    assert schema["document_id"]["data_type"] == "integer"
    aliases = _get(f"/collections/{collection}/aliases")["aliases"]
    assert {"alias_name": ALIAS, "collection_name": collection} in aliases


@live
def test_read_only_token_can_read_but_not_write(collection: str) -> None:
    out = _run(TOKEN)
    assert re.search(r"^read  : \d+ points$", out, re.MULTILINE)
    assert "write : rejected ->" in out
    assert "ALLOWED" not in out


def fake_embedding(text: str) -> list[float]:
    """A deterministic, normalised 1024-d bag-of-words vector: shared words -> similar vectors."""
    vec = [0.0] * 1024
    for word in re.findall(r"[a-z0-9]+", text.lower().split("query:")[-1]):
        vec[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 1024] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeEmbedder(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/v1/embeddings"
        assert body["model"] == "embedder"
        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
        data = [
            {"object": "embedding", "index": i, "embedding": fake_embedding(t)}
            for i, t in enumerate(texts)
        ]
        payload = {
            "object": "list",
            "data": data,
            "model": "embedder",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:  # silence test output
        pass


@pytest.fixture
def fake_gateway_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEmbedder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _results(out: str) -> dict[str, list[tuple[float, str, str]]]:
    """Parse '\\nuser in [...]:' blocks of '<score>  [<classification>]  <title>' lines."""
    blocks: dict[str, list[tuple[float, str, str]]] = {}
    current = ""
    for line in out.splitlines():
        if line.startswith("user in "):
            current = line
            blocks[current] = []
        elif current and (m := re.fullmatch(r"\s+([0-9.]+)\s+\[(\w+)\]\s+(.+)", line)):
            blocks[current].append((float(m.group(1)), m.group(2), m.group(3)))
    return blocks


@live_with_db
def test_sync_mirrors_postgres_and_agrees_with_pgvector(
    collection: str, fake_gateway_url: str
) -> None:
    env = {
        "LLM_GATEWAY_URL": fake_gateway_url,
        "INGESTION_GATEWAY_KEY": "sk-test",
        "RAG_API_GATEWAY_KEY": "sk-test",
    }
    pg = _results(_run(PG_DEMO, env))  # loads the Step 11 demo documents if they're missing
    out = _run(SYNC, env)
    synced = re.search(r"synced (\d+) points; Qdrant count = (\d+)", out)
    assert synced
    assert synced.group(1) == synced.group(2)  # every live chunk is in Qdrant
    qd = _results(out)
    assert list(qd) == list(pg)
    for user, pg_hits in pg.items():
        qd_hits = qd[user]
        # Same documents, same order, near-identical scores (float16 + int8 rescoring).
        assert [h[1:] for h in qd_hits] == [h[1:] for h in pg_hits]
        for (qs, _, _), (ps, _, _) in zip(qd_hits, pg_hits, strict=True):
            assert abs(qs - ps) < 0.01
    staff, executives = qd.values()
    assert all(title != "Exec offsite" for _, _, title in staff)
    assert executives[0][1:] == ("restricted", "Exec offsite")
