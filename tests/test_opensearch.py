"""Step 13: OpenSearch as a secured keyword + hybrid search engine, a derived index of rag-db.

The static tests read the committed files and check the rules the guide sets (3.x pinned by tag +
digest, admin password only from a secret file, single node with a locked 2 GB heap in a 4 GB
container, 9200 on 127.0.0.1 only and 9600 never published, a password-free healthcheck, the
least-privilege users, the index design, the hybrid pipeline, the demo's permission filters and the
`os-health` / `os-count` recipes).

The live tests run only when a real OpenSearch is reachable on 127.0.0.1:9200 AND the three
`OPENSEARCH_*_PASSWORD` variables are set (e.g. `just up`, then
`just with-secrets uv run pytest tests/test_opensearch.py`). The demo test additionally needs rag-db
on 127.0.0.1:5432 with the Step 11 migration applied and the role passwords; it loads the Step 11
and Step 13 demo documents through a tiny fake gateway that returns deterministic bag-of-words
embeddings, syncs them and checks the keyword, permission and explain behaviour (the meaning-based
"paraphrase" result needs the real embedder, so it is not asserted here).
"""

import base64
import hashlib
import json
import math
import os
import re
import socket
import ssl
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
SETUP = SCRIPTS / "os_setup.py"
DEMO = SCRIPTS / "os_demo.py"
PG_DEMO = SCRIPTS / "pg_demo.py"
INDEX, ALIAS, PIPELINE = "rag-chunks-v1", "rag-chunks", "rag-hybrid"
PASSWORDS = (
    "OPENSEARCH_ADMIN_PASSWORD",
    "OPENSEARCH_SEARCH_PASSWORD",
    "OPENSEARCH_INDEXER_PASSWORD",
)


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def _opensearch() -> dict[str, Any]:
    service = _compose()["services"]["opensearch"]
    assert isinstance(service, dict)
    return service


def _flat(path: Path) -> str:
    return " ".join(path.read_text().split())


# --- Compose service ------------------------------------------------------------------------


def test_image_is_opensearch_3_pinned_by_tag_and_digest() -> None:
    assert re.fullmatch(
        r"opensearchproject/opensearch:3\.\d+\.\d+@sha256:[0-9a-f]{64}", _opensearch()["image"]
    )


def test_admin_password_comes_from_a_secret_file_inside_the_container_only() -> None:
    service = _opensearch()
    assert service["entrypoint"] == ["/bin/bash", "-c"]
    (command,) = service["command"]
    assert (
        'export OPENSEARCH_INITIAL_ADMIN_PASSWORD="$$(cat /run/secrets/opensearch_admin_password)"'
        in command
    )
    # Hands over to the image's own entrypoint (what `docker image inspect` prints).
    assert command.strip().endswith(
        "exec /usr/share/opensearch/opensearch-docker-entrypoint.sh opensearch"
    )
    assert service["secrets"] == ["opensearch_admin_password"]
    assert _compose()["secrets"]["opensearch_admin_password"] == {
        "environment": "OPENSEARCH_ADMIN_PASSWORD"
    }
    assert not any("PASSWORD" in name for name in service["environment"])


def test_single_node_with_a_locked_fixed_heap_at_half_the_memory_limit() -> None:
    service = _opensearch()
    assert service["environment"] == {
        "discovery.type": "single-node",
        "bootstrap.memory_lock": "true",
        "OPENSEARCH_JAVA_OPTS": "-Xms2g -Xmx2g",
    }
    assert service["ulimits"] == {
        "memlock": {"soft": -1, "hard": -1},
        "nofile": {"soft": 65536, "hard": 65536},
    }
    assert service["deploy"]["resources"]["limits"] == {"memory": "4g", "cpus": "4"}


def test_only_https_api_published_and_only_on_localhost() -> None:
    ports = _opensearch()["ports"]
    assert ports == ["127.0.0.1:9200:9200"]
    assert not any("9600" in p for p in ports)  # performance analyzer stays private


def test_data_volume_password_free_healthcheck_and_hardening() -> None:
    service = _opensearch()
    assert service["volumes"] == ["opensearch-data:/usr/share/opensearch/data"]
    assert "opensearch-data" in _compose()["volumes"]
    health = service["healthcheck"]
    assert health["test"] == [
        "CMD-SHELL",
        "curl -sk -o /dev/null -w '%{http_code}' https://localhost:9200 | grep -qE '200|401'",
    ]
    assert "PASSWORD" not in " ".join(health["test"])
    assert (health["interval"], health["timeout"], health["retries"]) == ("20s", "10s", 15)
    assert health["start_period"] == "60s"
    assert service["restart"] == "unless-stopped"
    assert service["security_opt"] == ["no-new-privileges:true"]


def test_passwords_are_generated_strong_and_documented() -> None:
    generator = (SCRIPTS / "new-dev-secrets.sh").read_text()
    example = (REPO / ".env.example").read_text()
    assert "ospw() { echo \"$(openssl rand -base64 24 | tr -d '/+=\\n')#9Qx\"; }" in generator
    for env in PASSWORDS:
        assert f"\n{env}=$(ospw)\n" in generator
        assert re.search(rf"^{env}=<strong", example, re.MULTILINE)


def test_health_and_count_recipes() -> None:
    text = JUSTFILE.read_text()
    assert "\nos-health:\n" in text
    assert "\nos-count:\n" in text
    assert (
        'curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" https://127.0.0.1:9200/_cluster/health'
        ' | jq -c "{status, number_of_nodes, active_shards}"' in text
    )
    # Counting uses the read-only user, through the alias.
    assert (
        'curl -sk -u "rag_search:$OPENSEARCH_SEARCH_PASSWORD" https://127.0.0.1:9200/rag-chunks/_count | jq .count'
        in text
    )
    # Passwords are expanded by the shell sops starts, never by just (single quotes).
    for line in text.splitlines():
        if "OPENSEARCH_" in line and "sops exec-env" in line:
            assert line.strip().startswith("sops exec-env secrets/dev.enc.env '")


# --- scripts --------------------------------------------------------------------------------


def test_scripts_compile_and_are_executable() -> None:
    for script in (SETUP, DEMO):
        assert os.access(script, os.X_OK)
        compile(script.read_text(), str(script), "exec")


def test_setup_creates_least_privilege_users() -> None:
    text = _flat(SETUP)
    assert '"cluster_permissions": ["cluster_composite_ops_ro"]' in text
    assert '"index_patterns": ["rag-chunks*"], "allowed_actions": ["read"]' in text
    assert '"allowed_actions": ["crud", "create_index", "manage_aliases"]' in text
    for call in ("roles", "internalusers", "rolesmapping"):
        assert f'req("PUT", f"{{SEC}}/{call}/{{name}}"' in text
    assert 'http_auth=("admin", os.environ["OPENSEARCH_ADMIN_PASSWORD"])' in text


def test_setup_designs_the_index_as_the_guide_says() -> None:
    text = _flat(SETUP)
    assert f'INDEX, ALIAS = "{INDEX}", "{ALIAS}"' in text
    assert '"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}' in text
    assert '"type": "synonym_graph"' in text
    assert '"wfh, work from home, remote work", "pto, paid time off, annual leave",' in text
    # Synonyms only at query time: no re-index when the jargon list changes.
    assert '"filter": ["lowercase", "english_stemmer"]' in text
    assert '"filter": ["lowercase", "rag_synonyms", "english_stemmer"]' in text
    for field in ("text", "title"):
        assert (
            f'"{field}": {{ "type": "text", "analyzer": "rag_index", "search_analyzer": "rag_query",'
            in text
        )
    assert '"fields": {"raw": {"type": "keyword"}}' in text
    assert '"type": "knn_vector", "dimension": 1024' in text
    assert '"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"' in text
    assert '"parameters": {"m": 16, "ef_construction": 100}' in text
    for field in ("tenant_id", "acl_groups", "classification", "source_uri"):
        assert f'"{field}": {{"type": "keyword"}}' in text
    assert '"document_id": {"type": "long"}' in text
    assert '"aliases": {ALIAS: {}}' in text
    assert "if not admin.indices.exists(index=INDEX):" in text  # safe to re-run


def test_setup_adds_the_hybrid_pipeline() -> None:
    text = _flat(SETUP)
    assert f'"/_search/pipeline/{PIPELINE}"' in text
    assert '"normalization": {"technique": "min_max"}' in text
    assert '"technique": "arithmetic_mean", "parameters": {"weights": [0.3, 0.7]}' in text


def test_demo_writes_postgres_first_then_syncs_as_the_indexer() -> None:
    text = _flat(DEMO)
    assert "postgresql://rag_app:{os.environ['RAG_DB_APP_PASSWORD']}@127.0.0.1:5432/rag" in text
    assert "SELECT 1 FROM rag.documents WHERE source_uri = %s" in text  # idempotent
    assert "WHERE d.deleted_at IS NULL" in text
    assert 'indexer = os_client("rag_indexer", "OPENSEARCH_INDEXER_PASSWORD")' in text
    assert '"_index": ALIAS, "_id": cid,' in text  # the alias, and Postgres ids
    assert '"embedding": emb.to_list(),' in text  # copied, never re-embedded
    assert "helpers.bulk(indexer, actions, refresh=True)" in text
    assert 'api_key=os.environ["INGESTION_GATEWAY_KEY"]' in text
    assert 'api_key=os.environ["RAG_API_GATEWAY_KEY"]' in text  # virtual keys, not the master key


def test_demo_searches_read_only_with_the_permission_filter_everywhere() -> None:
    text = _flat(DEMO)
    assert 'search = os_client("rag_search", "OPENSEARCH_SEARCH_PASSWORD")' in text
    assert 'perm = [{"term": {"tenant_id": TENANT}}, {"terms": {"acl_groups": groups}}]' in text
    assert '{"bool": {"must": [{"match": {"text": q}}], "filter": perm}}' in text
    assert '"k": 10, "filter": {"bool": {"filter": perm}}' in text  # k-NN sub-query filters too
    assert '{"hybrid": {"queries": [bm25(question), knn(question)]}}' in text
    assert f'"{PIPELINE}"' in text
    assert '"explain": True' in text
    assert "INSTRUCTION + q" in text  # queries get the instruction, documents don't


# --- live OpenSearch (opt-in) ---------------------------------------------------------------

URL = "https://127.0.0.1:9200"
TLS = ssl.create_default_context()
TLS.check_hostname = False
TLS.verify_mode = ssl.CERT_NONE  # demo certificates (development only), like curl -k


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(
    not (all(os.environ.get(p) for p in PASSWORDS) and _port_open(9200)),
    reason="needs OpenSearch on 127.0.0.1:9200 and OPENSEARCH_*_PASSWORD",
)
live_with_db = pytest.mark.skipif(
    not (
        all(os.environ.get(p) for p in PASSWORDS)
        and os.environ.get("RAG_DB_APP_PASSWORD")
        and _port_open(9200)
        and _port_open(5432)
    ),
    reason="needs OpenSearch, rag-db (migrated), OPENSEARCH_*_PASSWORD and RAG_DB_APP_PASSWORD",
)
USERS = {
    "admin": "OPENSEARCH_ADMIN_PASSWORD",
    "rag_search": "OPENSEARCH_SEARCH_PASSWORD",
    "rag_indexer": "OPENSEARCH_INDEXER_PASSWORD",
}


def _call(
    path: str, user: str | None = "admin", method: str = "GET", body: Any = None
) -> tuple[int, Any]:
    request = urllib.request.Request(URL + path, method=method)  # noqa: S310 - fixed localhost URL
    if user:
        token = base64.b64encode(f"{user}:{os.environ[USERS[user]]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
        request.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(request, timeout=10, context=TLS) as response:  # noqa: S310
            return int(response.status), json.load(response)
    except urllib.error.HTTPError as err:
        return err.code, None


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
def index() -> str:
    """Run the (idempotent) setup script once for the live tests."""
    out = _run(SETUP)
    assert "users: rag_search (read), rag_indexer (write) on rag-chunks*" in out
    assert "pipeline rag-hybrid ready" in out
    return INDEX


@live
def test_unauthenticated_requests_are_rejected_and_version_is_3() -> None:
    assert _call("/", user=None)[0] == 401
    status, info = _call("/")
    assert status == 200
    assert info["version"]["number"].startswith("3.")
    status, health = _call("/_cluster/health")
    assert health["number_of_nodes"] == 1


@live
def test_index_alias_and_pipeline_match_the_design(index: str) -> None:
    _, data = _call(f"/{index}")
    settings, mappings = data[index]["settings"]["index"], data[index]["mappings"]["properties"]
    assert settings["knn"] == "true"
    assert (settings["number_of_shards"], settings["number_of_replicas"]) == ("1", "0")
    assert ALIAS in data[index]["aliases"]
    analysis = settings["analysis"]
    assert analysis["filter"]["rag_synonyms"]["type"] == "synonym_graph"
    assert analysis["analyzer"]["rag_query"]["filter"] == [
        "lowercase",
        "rag_synonyms",
        "english_stemmer",
    ]
    assert mappings["text"]["search_analyzer"] == "rag_query"
    vec = mappings["embedding"]
    assert vec["dimension"] == 1024
    assert vec["method"]["engine"] == "lucene"
    assert vec["method"]["space_type"] == "cosinesimil"
    for field in ("tenant_id", "acl_groups", "classification", "source_uri"):
        assert mappings[field]["type"] == "keyword"
    _, pipeline = _call(f"/_search/pipeline/{PIPELINE}")
    processor = pipeline[PIPELINE]["phase_results_processors"][0]["normalization-processor"]
    assert processor["normalization"]["technique"] == "min_max"
    assert processor["combination"]["parameters"]["weights"] == [0.3, 0.7]


def _tokens(analyzer: str, text: str) -> list[str]:
    _, data = _call(f"/{INDEX}/_analyze", body={"analyzer": analyzer, "text": text})
    return [t["token"] for t in data["tokens"]]


@live
def test_analyzers_stem_and_expand_synonyms_only_at_query_time(index: str) -> None:
    assert _tokens("rag_index", "Staff may WFH on Fridays") == [
        "staff",
        "mai",
        "wfh",
        "on",
        "fridai",
    ]
    query = _tokens("rag_query", "WFH on Fridays")
    assert {"wfh", "work", "from", "home", "remot"} <= set(query)
    assert "fridai" in query  # "Fridays" and "friday" end up the same term


@live
def test_users_are_least_privilege(index: str) -> None:
    doc = {"text": "x", "tenant_id": "acme", "acl_groups": ["nobody"]}
    assert _call(f"/{ALIAS}/_count", user="rag_search")[0] == 200
    assert _call(f"/{ALIAS}/_doc/probe", user="rag_search", method="PUT", body=doc)[0] == 403
    assert _call("/other-index/_search", user="rag_search")[0] == 403
    assert _call("/other-index", user="rag_indexer", method="PUT", body={})[0] == 403
    assert _call("/_plugins/_security/api/internalusers", user="rag_indexer")[0] == 403
    status, _ = _call(
        f"/{ALIAS}/_doc/probe?refresh=true", user="rag_indexer", method="PUT", body=doc
    )
    assert status in (200, 201)
    assert _call(f"/{ALIAS}/_doc/probe?refresh=true", user="rag_indexer", method="DELETE")[0] == 200


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


def _results(out: str) -> dict[str, dict[str, list[str]]]:
    """Parse 'Q: <question>' blocks of '<style>  <title> (<score>) | ...' lines into titles."""
    blocks: dict[str, dict[str, list[str]]] = {}
    current = ""
    for line in out.splitlines():
        if line.startswith("Q: "):
            current = line[3:]
            blocks[current] = {}
        elif current and (m := re.fullmatch(r"\s+(BM25|vector|hybrid)\s+(.*)", line)):
            hits = [h for h in m.group(2).split(" | ") if h]
            blocks[current][m.group(1)] = [re.sub(r" \([0-9.]+\)$", "", h) for h in hits]
    return blocks


@live_with_db
def test_demo_syncs_postgres_and_shows_keyword_strengths(index: str, fake_gateway_url: str) -> None:
    env = {
        "LLM_GATEWAY_URL": fake_gateway_url,
        "INGESTION_GATEWAY_KEY": "sk-test",
        "RAG_API_GATEWAY_KEY": "sk-test",
    }
    _run(PG_DEMO, env)  # loads the Step 11 demo collection and documents if they're missing
    out = _run(DEMO, env)
    synced = re.search(r"synced (\d+) chunks", out)
    assert synced
    assert int(synced.group(1)) >= 6  # Step 11's four documents plus this step's two
    # `just os-count` (read-only user, through the alias) equals the live chunks in Postgres.
    _, count = _call(f"/{ALIAS}/_count", user="rag_search")
    assert count["count"] == int(synced.group(1))

    results = _results(out)
    assert set(results) == {
        "POL-117 business class",
        "Can I do my job from my house on Fridays?",
        "WFH approval",
    }
    # BM25 nails the exact code; hybrid keeps it on top.
    assert results["POL-117 business class"]["BM25"][0] == "Travel policy POL-117"
    assert results["POL-117 business class"]["hybrid"][0] == "Travel policy POL-117"
    # The synonym rule lets "WFH" match the remote-work policy, which never says "WFH".
    wfh = results["WFH approval"]["BM25"]
    assert wfh[0] == "WFH requests"
    assert "Remote work policy" in wfh
    # The permission filter is on every path: an all-staff user never sees restricted documents.
    for styles in results.values():
        assert set(styles) == {"BM25", "vector", "hybrid"}
        for titles in styles.values():
            assert not {"Salary bands 2026", "Exec offsite"} & set(titles)
    assert re.search(r"^explain: sum of:", out, re.MULTILINE)
