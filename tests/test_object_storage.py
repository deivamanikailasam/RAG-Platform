"""Step 14: S3 object storage for original files with SeaweedFS.

The static tests read the committed files and check the rules the guide sets (SeaweedFS 4.x pinned by
tag + digest, identities built from secret FILES into a RAM-only tmpfs, bucket-scoped actions for
rag-ingest and rag-reader, only the S3 port published and only on 127.0.0.1, the MinIO secrets
replaced by six S3_* names, the `just s3` recipe, the setup/demo scripts and the bucket document).

The live tests run only when a real object store answers on 127.0.0.1:8333 AND the six `S3_*`
variables are set (e.g. `just up`, then `just with-secrets uv run pytest tests/test_object_storage.py`).
They run the (idempotent) setup script and prove each rule: anonymous requests refused, versioning,
lifecycle and object lock configured, bucket-scoped permissions, delete markers, expiring presigned
links and governance-mode retention. The demo test additionally needs rag-db on 127.0.0.1:5432 with
the Step 11 migration applied and RAG_DB_APP_PASSWORD.
"""

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
JUSTFILE = REPO / "justfile"
SCRIPTS = REPO / "scripts"
SETUP = SCRIPTS / "s3_setup.py"
DEMO = SCRIPTS / "s3_demo.py"
DOC = REPO / "docs" / "data" / "object-storage.md"
ADR = (
    REPO
    / "docs"
    / "adr"
    / "0014-use-seaweedfs-as-the-s3-compatible-object-store-instead-of-minio.md"
)
BUCKETS = ("rag-raw-docs", "rag-audit-archive", "rag-tmp")
IDENTITIES = ("ADMIN", "INGEST", "READER", "LANGFUSE")  # + Langfuse's own bucket (Step 22)
KEYS = tuple(f"S3_{who}_{kind}_KEY" for who in IDENTITIES for kind in ("ACCESS", "SECRET"))
SECRETS = [name.lower() for name in KEYS]


def _service() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    service = data["services"]["object-store"]
    assert isinstance(service, dict)
    return service


def _identities() -> dict[str, dict[str, Any]]:
    """Parse the identities JSON the start-up script writes, with the secret reads stubbed out."""
    (command,) = _service()["command"]
    body = command.split("<<EOF\n", 1)[1].split("\nEOF\n", 1)[0]
    body = re.sub(r"\$\$\(cat /run/secrets/(\w+)\)", r"<\1>", body)
    parsed = json.loads(body)
    return {ident["name"]: ident for ident in parsed["identities"]}


# --- Compose service ------------------------------------------------------------------------


def test_image_is_seaweedfs_4_pinned_by_tag_and_digest() -> None:
    assert re.fullmatch(r"chrislusf/seaweedfs:4\.\d+@sha256:[0-9a-f]{64}", _service()["image"])


def test_identities_file_is_built_in_ram_from_secret_files() -> None:
    service = _service()
    assert service["entrypoint"] == ["/bin/sh", "-c"]
    (command,) = service["command"]
    lines = command.strip().splitlines()
    assert lines[0] == "umask 077"  # the identities file is readable by its owner only
    assert lines[1] == "cat > /run/seaweed/s3.json <<EOF"
    assert lines[-1].startswith("exec weed mini -dir=/data -s3.config=/run/seaweed/s3.json")
    assert service["tmpfs"] == ["/run/seaweed:size=1m,mode=0700"]
    assert service["secrets"] == SECRETS
    # Every key arrives as a secret FILE, never as an environment variable of the container.
    assert "environment" not in service
    for name in SECRETS:
        assert f"$$(cat /run/secrets/{name})" in command
    top = yaml.safe_load(COMPOSE.read_text())["secrets"]
    for name, env in zip(SECRETS, KEYS, strict=True):
        assert top[name] == {"environment": env}


def test_identities_are_least_privilege_and_bucket_scoped() -> None:
    idents = _identities()
    assert set(idents) == {"admin", "rag-ingest", "rag-reader", "langfuse"}  # langfuse: Step 22
    assert idents["admin"]["actions"] == ["Admin", "Read", "Write", "List", "Tagging"]
    assert idents["rag-ingest"]["actions"] == [
        "Read:rag-raw-docs",
        "Write:rag-raw-docs",
        "List:rag-raw-docs",
        "Tagging:rag-raw-docs",
        "Read:rag-tmp",
        "Write:rag-tmp",
        "List:rag-tmp",
    ]
    assert idents["rag-reader"]["actions"] == ["Read:rag-raw-docs", "List:rag-raw-docs"]
    assert idents["langfuse"]["actions"] == ["Read:langfuse", "Write:langfuse", "List:langfuse"]
    # Nobody but admin can touch the audit archive.
    for name in ("rag-ingest", "rag-reader", "langfuse"):
        assert not any("rag-audit-archive" in a for a in idents[name]["actions"])
    assert idents["admin"]["credentials"] == [
        {"accessKey": "<s3_admin_access_key>", "secretKey": "<s3_admin_secret_key>"}
    ]


def test_only_the_s3_port_is_published_and_only_on_localhost() -> None:
    service = _service()
    assert service["ports"] == ["127.0.0.1:8333:8333"]
    assert service["volumes"] == ["object-store-data:/data"]
    assert "object-store-data" in yaml.safe_load(COMPOSE.read_text())["volumes"]


def test_hardening_healthcheck_and_limits() -> None:
    service = _service()
    assert service["healthcheck"]["test"] == ["CMD-SHELL", "nc -z 127.0.0.1 8333 || exit 1"]
    assert service["restart"] == "unless-stopped"
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["deploy"]["resources"]["limits"] == {"memory": "1g", "cpus": "2"}


# --- secrets, tools, recipes, scripts, docs -------------------------------------------------


def test_minio_secrets_are_replaced_by_six_s3_keys() -> None:
    generator = (SCRIPTS / "new-dev-secrets.sh").read_text()
    example = (REPO / ".env.example").read_text()
    for text in (generator, example):
        assert "MINIO_" not in text
        for name in KEYS:
            assert re.search(rf"^{name}=", text, re.MULTILINE), name
    assert "S3_ADMIN_ACCESS_KEY=$(gen_ak)" in generator
    assert "S3_ADMIN_SECRET_KEY=$(gen_sk)" in generator


def test_generator_key_formats(tmp_path: Path) -> None:
    """The gen_ak / gen_sk helpers make 20-character access keys and 40-character secret keys."""
    generator = (SCRIPTS / "new-dev-secrets.sh").read_text()
    helpers = "\n".join(
        line for line in generator.splitlines() if line.startswith(("gen_ak()", "gen_sk()"))
    )
    script = tmp_path / "keys.sh"
    script.write_text(f'{helpers}\necho "$(gen_ak)"\necho "$(gen_sk)"\n')
    out = subprocess.run(  # noqa: S603 - fixed argv, test-only
        ["/bin/bash", str(script)], capture_output=True, text=True, check=True
    ).stdout.split()
    assert re.fullmatch(r"[A-Z0-9]{20}", out[0])
    assert re.fullmatch(r"[A-Za-z0-9]{40}", out[1])


def test_awscli_in_brewfile_and_s3_recipe() -> None:
    assert re.search(r'^brew "awscli"', (REPO / "bootstrap" / "Brewfile").read_text(), re.MULTILINE)
    text = JUSTFILE.read_text()
    assert 's3_endpoint   := "http://127.0.0.1:8333"' in text
    recipe = text.split("\ns3 *args:\n", 1)[1]
    assert "[positional-arguments]\ns3 *args:" in text
    assert "sops exec-env secrets/dev.enc.env" in recipe
    assert 'AWS_ACCESS_KEY_ID=\\"\\$S3_ADMIN_ACCESS_KEY\\"' in recipe
    assert "aws --endpoint-url {{s3_endpoint}}" in recipe
    assert "~/.aws" not in recipe


@pytest.mark.parametrize("script", [SETUP, DEMO])
def test_scripts_compile_and_use_path_style_sigv4(script: Path) -> None:
    source = script.read_text()
    compile(source, str(script), "exec")
    assert 'signature_version="s3v4"' in source
    assert 's3={"addressing_style": "path"}' in source
    assert '"http://127.0.0.1:8333"' in source
    assert "aws_access_key_id=os.environ[" in source  # keys only from the environment


def test_setup_script_sets_the_bucket_rules() -> None:
    source = SETUP.read_text()
    assert 'VersioningConfiguration={"Status": "Enabled"}' in source
    assert '"NoncurrentVersionExpiration": {"NoncurrentDays": 90}' in source
    assert 'create("rag-audit-archive", ObjectLockEnabledForBucket=True)' in source
    assert '{"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}}' in source
    assert '"Expiration": {"Days": 1}' in source


def test_bucket_document_and_adr() -> None:
    doc = DOC.read_text()
    assert "Endpoint: http://127.0.0.1:8333 (containers: http://object-store:8333)" in doc
    for bucket in BUCKETS:
        assert f"| {bucket} |" in doc
    assert "s3_bucket, s3_key, s3_version_id, sha256" in doc
    adr = ADR.read_text()
    assert adr.startswith(
        "# ADR-0014: Use SeaweedFS as the S3-compatible object store instead of MinIO"
    )
    assert "- **Status:** Accepted" in adr


# --- live object store (opt-in) -------------------------------------------------------------

ENDPOINT = "http://127.0.0.1:8333"


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(
    not (all(os.environ.get(k) for k in KEYS) and _port_open(8333)),
    reason="needs the object store on 127.0.0.1:8333 and the six S3_* keys",
)
live_with_db = pytest.mark.skipif(
    not (
        all(os.environ.get(k) for k in KEYS)
        and os.environ.get("RAG_DB_APP_PASSWORD")
        and _port_open(8333)
        and _port_open(5432)
    ),
    reason="needs the object store, rag-db (migrated), the S3_* keys and RAG_DB_APP_PASSWORD",
)


def _client(who: str) -> "S3Client":
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        aws_access_key_id=os.environ[f"S3_{who}_ACCESS_KEY"],
        aws_secret_access_key=os.environ[f"S3_{who}_SECRET_KEY"],
    )


def _run(script: Path) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, str(script)], capture_output=True, text=True, check=True
    ).stdout


def _denied(call: Any) -> str:
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as err:
        call()
    code = err.value.response["Error"]["Code"]
    assert isinstance(code, str)
    return code


@pytest.fixture(scope="module")
def buckets() -> tuple[str, ...]:
    """Run the (idempotent) setup script for the live tests: twice, to prove re-runs are safe."""
    _run(SETUP)
    out = _run(SETUP)
    assert "rag-raw-docs       versioning=Enabled" in out
    assert "rag-audit-archive  versioning=Enabled" in out
    assert "rag-tmp            versioning=Off" in out
    return BUCKETS


@live
def test_anonymous_requests_are_refused() -> None:
    for path in ("/", "/rag-raw-docs", "/rag-raw-docs/raw/remote-work-policy.txt"):
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(ENDPOINT + path, timeout=5)  # noqa: S310 - fixed localhost URL
        assert err.value.code == 403


@live
def test_buckets_have_their_rules(buckets: tuple[str, ...]) -> None:
    admin = _client("ADMIN")
    names = {b["Name"] for b in admin.list_buckets()["Buckets"]}
    assert set(buckets) <= names
    raw = admin.get_bucket_lifecycle_configuration(Bucket="rag-raw-docs")["Rules"]
    assert raw[0]["ID"] == "expire-old-versions"
    assert raw[0]["NoncurrentVersionExpiration"]["NoncurrentDays"] == 90
    tmp = admin.get_bucket_lifecycle_configuration(Bucket="rag-tmp")["Rules"]
    assert tmp[0]["ID"] == "expire-tmp"
    assert tmp[0]["Expiration"]["Days"] == 1
    lock = admin.get_object_lock_configuration(Bucket="rag-audit-archive")
    config = lock["ObjectLockConfiguration"]
    assert config["ObjectLockEnabled"] == "Enabled"
    assert config["Rule"]["DefaultRetention"] == {"Mode": "GOVERNANCE", "Days": 1}


@live
def test_identities_only_reach_their_buckets(buckets: tuple[str, ...]) -> None:
    ingest, reader = _client("INGEST"), _client("READER")
    key = f"tests/{uuid.uuid4().hex}.txt"
    ingest.put_object(Bucket="rag-tmp", Key=key, Body=b"scratch")
    assert ingest.get_object(Bucket="rag-tmp", Key=key)["Body"].read() == b"scratch"
    assert _denied(lambda: ingest.put_object(Bucket="rag-audit-archive", Key=key, Body=b"x")) == (
        "AccessDenied"
    )
    assert _denied(lambda: ingest.create_bucket(Bucket=f"rogue-{uuid.uuid4().hex[:8]}")) == (
        "AccessDenied"
    )
    assert _denied(lambda: reader.put_object(Bucket="rag-raw-docs", Key=key, Body=b"x")) == (
        "AccessDenied"
    )
    assert _denied(lambda: reader.list_objects_v2(Bucket="rag-tmp")) == "AccessDenied"
    assert _denied(lambda: reader.list_objects_v2(Bucket="rag-audit-archive")) == "AccessDenied"
    ingest.delete_object(Bucket="rag-tmp", Key=key)


@live
def test_versioning_delete_markers_and_presigned_links(buckets: tuple[str, ...]) -> None:
    ingest, reader = _client("INGEST"), _client("READER")
    key = f"tests/{uuid.uuid4().hex}.txt"
    first = ingest.put_object(Bucket="rag-raw-docs", Key=key, Body=b"v1")["VersionId"]
    second = ingest.put_object(Bucket="rag-raw-docs", Key=key, Body=b"v2")["VersionId"]
    assert first != second
    old = reader.get_object(Bucket="rag-raw-docs", Key=key, VersionId=first)
    assert old["Body"].read() == b"v1"  # the overwrite kept the old version

    # A presigned link opens EXACTLY one version without credentials, then expires.
    url = reader.generate_presigned_url(
        "get_object", ExpiresIn=2, Params={"Bucket": "rag-raw-docs", "Key": key, "VersionId": first}
    )
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 - presigned localhost URL
        assert resp.status == 200
        assert resp.read() == b"v1"
    time.sleep(4)
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(url, timeout=5)  # noqa: S310 - presigned localhost URL
    assert err.value.code == 403

    # "Delete" only adds a marker; both versions still exist until each is removed explicitly.
    marker = ingest.delete_object(Bucket="rag-raw-docs", Key=key)
    assert marker.get("DeleteMarker") is True
    listing = ingest.list_object_versions(Bucket="rag-raw-docs", Prefix=key)
    assert len(listing.get("Versions", [])) == 2
    assert len(listing.get("DeleteMarkers", [])) == 1
    # Real erasure (right to be forgotten) = delete every version and marker.
    for version in (*listing.get("Versions", []), *listing.get("DeleteMarkers", [])):
        ingest.delete_object(Bucket="rag-raw-docs", Key=key, VersionId=version["VersionId"])
    assert not ingest.list_object_versions(Bucket="rag-raw-docs", Prefix=key).get("Versions")


@live
def test_locked_object_cannot_be_deleted_in_governance_mode(buckets: tuple[str, ...]) -> None:
    admin = _client("ADMIN")
    key = f"tests/{uuid.uuid4().hex}.json"
    put = admin.put_object(Bucket="rag-audit-archive", Key=key, Body=b'{"event":"test"}')
    head = admin.head_object(Bucket="rag-audit-archive", Key=key, VersionId=put["VersionId"])
    assert head["ObjectLockMode"] == "GOVERNANCE"
    assert head["ObjectLockRetainUntilDate"].timestamp() > time.time() + 23 * 3600
    assert (
        _denied(
            lambda: admin.delete_object(
                Bucket="rag-audit-archive", Key=key, VersionId=put["VersionId"]
            )
        )
        == "AccessDenied"
    )
    # Governance mode: a privileged user may deliberately override (compliance mode would refuse).
    admin.delete_object(
        Bucket="rag-audit-archive",
        Key=key,
        VersionId=put["VersionId"],
        BypassGovernanceRetention=True,
    )


@live_with_db
def test_demo_proves_the_rules_and_records_lineage(buckets: tuple[str, ...]) -> None:
    out = _run(DEMO)
    count = re.search(r"versions kept: (\d+)", out)
    assert count is not None
    assert int(count.group(1)) >= 2
    assert "reader PUT   : rejected -> AccessDenied" in out
    assert "presigned    : 200 b'Staff may work remotely up to two days p'" in out
    assert "locked DEL   : rejected -> AccessDenied" in out
    lineage = re.search(r"lineage      : recorded on (\d+) document row\(s\): (\S+)", out)
    assert lineage is not None
    if int(lineage.group(1)) == 0:
        pytest.skip("no 'demo://Remote work policy' row yet: run pg_demo.py (Step 11) first")

    import psycopg

    dsn = f"postgresql://rag_app:{os.environ['RAG_DB_APP_PASSWORD']}@127.0.0.1:5432/rag"
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT metadata FROM rag.documents WHERE source_uri = 'demo://Remote work policy'"
        ).fetchone()
    assert row is not None
    meta = row[0]
    assert meta["s3_bucket"] == "rag-raw-docs"
    assert meta["s3_key"] == "raw/remote-work-policy.txt"
    assert meta["s3_version_id"] == lineage.group(2)
    body = b"Staff may work remotely up to two days per week with manager approval."
    assert meta["sha256"] == hashlib.sha256(body).hexdigest()
