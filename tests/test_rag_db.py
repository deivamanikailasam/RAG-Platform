"""Step 11: the rag-db Postgres + pgvector service, its roles, migrations, demo and backups.

The static tests read the committed files and check the rules the guide sets (digest pin,
localhost-only port, tuning, file-based secrets for four roles, one-time init script with
least-privilege grants, the core-tables migration, the dbmate / backup recipes, backups/
gitignored).

The live tests run only when a real rag-db is reachable on 127.0.0.1:5432 AND the role
passwords are in the environment (e.g. `just with-secrets uv run pytest tests/test_rag_db.py`
after `just up` and `just db-migrate up`). They run scripts/pg_demo.py against a tiny fake
gateway that returns deterministic bag-of-words embeddings, then prove the role boundaries.
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
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
INIT = REPO / "infra" / "config" / "rag-db" / "init" / "01-roles.sh"
MIGRATIONS = REPO / "infra" / "db" / "rag" / "migrations"
JUSTFILE = REPO / "justfile"
DEMO = REPO / "scripts" / "pg_demo.py"
ROLE_SECRETS = {
    "rag_db_superuser_password": "POSTGRES_PASSWORD",
    "rag_db_migrator_password": "RAG_DB_MIGRATOR_PASSWORD",
    "rag_db_app_password": "RAG_DB_APP_PASSWORD",
    "rag_db_readonly_password": "RAG_DB_READONLY_PASSWORD",
}


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def _rag_db() -> dict[str, Any]:
    service = _compose()["services"]["rag-db"]
    assert isinstance(service, dict)
    return service


def _settings() -> dict[str, str]:
    """The `-c name=value` server settings from the service command."""
    command = _rag_db()["command"]
    assert command[0] == "postgres"
    flags, values = command[1::2], command[2::2]
    assert set(flags) == {"-c"}
    return dict(value.split("=", 1) for value in values)


# --- Compose service ------------------------------------------------------------------------


def test_image_is_pgvector_on_postgres_17_pinned_by_digest() -> None:
    assert re.fullmatch(r"pgvector/pgvector:0\.8\.\d+-pg17@sha256:[0-9a-f]{64}", _rag_db()["image"])


def test_rag_db_is_localhost_only_and_hardened() -> None:
    service = _rag_db()
    assert service["ports"] == ["127.0.0.1:5432:5432"]
    assert service["environment"] == {
        "POSTGRES_DB": "rag",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD_FILE": "/run/secrets/rag_db_superuser_password",
    }
    assert service["volumes"] == [
        "rag-db-data:/var/lib/postgresql/data",
        "../config/rag-db/init:/docker-entrypoint-initdb.d:ro",
    ]
    assert (COMPOSE.parent / "../config/rag-db/init").resolve() == INIT.parent
    assert "rag-db-data" in _compose()["volumes"]
    assert service["shm_size"] == "1g"
    assert service["restart"] == "unless-stopped"
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["deploy"]["resources"]["limits"] == {"memory": "4g", "cpus": "4"}
    assert service["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U postgres -d rag"]


def test_rag_db_is_tuned_for_vectors_and_observable() -> None:
    assert _settings() == {
        "shared_buffers": "1GB",
        "effective_cache_size": "3GB",
        "maintenance_work_mem": "1GB",
        "work_mem": "32MB",
        "max_connections": "100",
        "shared_preload_libraries": "pg_stat_statements",
        "log_min_duration_statement": "500",
        "password_encryption": "scram-sha-256",
    }


def test_four_role_passwords_come_from_secret_files() -> None:
    # Step 20 adds the monitoring role's password (rag_metrics, see tests/test_monitoring.py)
    # Step 23 adds the three audit-database roles (see tests/test_audit_db.py)
    assert _rag_db()["secrets"] == [
        *ROLE_SECRETS,
        "rag_db_metrics_password",
        "audit_db_migrator_password",
        "audit_db_writer_password",
        "audit_db_reader_password",
    ]
    secrets = _compose()["secrets"]
    for name, env in ROLE_SECRETS.items():
        assert secrets[name] == {"environment": env}


def test_new_role_passwords_are_generated_and_documented() -> None:
    generator = (REPO / "scripts" / "new-dev-secrets.sh").read_text()
    example = (REPO / ".env.example").read_text()
    for env in ROLE_SECRETS.values():
        assert f"\n{env}=$(rand)\n" in generator  # letters/digits only: safe inside a URL
        assert re.search(rf"^{env}=<generated", example, re.MULTILINE)


# --- one-time init script -------------------------------------------------------------------


def test_init_script_is_executable_and_strict() -> None:
    assert os.access(INIT, os.X_OK)
    text = INIT.read_text()
    assert text.startswith("#!/bin/bash\n")
    assert "set -euo pipefail" in text
    assert "-v ON_ERROR_STOP=1" in text
    assert "<<'SQL'" in text  # quoted heredoc: the shell never expands anything inside the SQL
    subprocess.run(["bash", "-n", str(INIT)], check=True)  # noqa: S603, S607 - fixed argv


def test_init_script_creates_least_privilege_roles_without_exposing_passwords() -> None:
    text = INIT.read_text()
    for role, var, secret in (
        ("rag_migrator", "migrator_pw", "rag_db_migrator_password"),
        ("rag_app", "app_pw", "rag_db_app_password"),
        ("rag_readonly", "ro_pw", "rag_db_readonly_password"),
    ):
        assert f'-v {var}="$(cat /run/secrets/{secret})"' in text
        assert re.search(rf"CREATE ROLE {role}\s+LOGIN PASSWORD :'{var}';", text)
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in text
    assert "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;" in text
    assert "REVOKE ALL ON DATABASE rag FROM PUBLIC;" in text
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC;" in text
    assert "CREATE SCHEMA rag AUTHORIZATION rag_migrator;" in text
    grants = " ".join(text.split())
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_app;" in grants
    assert "GRANT USAGE, SELECT ON SEQUENCES TO rag_app;" in grants
    assert "GRANT SELECT ON TABLES TO rag_readonly;" in grants
    assert re.search(r"ALTER ROLE rag_app\s+SET statement_timeout = '30s';", text)
    assert "ALTER ROLE rag_readonly SET default_transaction_read_only = on;" in text


# --- migrations -----------------------------------------------------------------------------


def _core_migration() -> str:
    files = sorted(MIGRATIONS.glob("*.sql"))
    assert [re.sub(r"^\d{14}_", "", f.name) for f in files][:1] == ["create_core_tables.sql"]
    return files[0].read_text()


def test_core_migration_has_up_and_down() -> None:
    sql = _core_migration()
    up, down = sql.split("-- migrate:down")
    assert up.lstrip().startswith("-- migrate:up")
    for table in ("collections", "documents", "chunks"):
        assert f"CREATE TABLE rag.{table} (" in up
        assert f"DROP TABLE rag.{table};" in down
    # Children are dropped before their parents.
    assert down.index("rag.chunks") < down.index("rag.documents") < down.index("rag.collections")


def test_core_migration_enforces_the_embedding_contract_and_indexes() -> None:
    sql = " ".join(_core_migration().split())
    assert "embedding halfvec(1024) NOT NULL" in sql
    assert "USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64)" in sql
    assert (
        "content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED" in sql
    )
    assert "ON rag.chunks USING gin (content_tsv)" in sql
    assert "ON rag.documents USING gin (acl_groups)" in sql
    assert "ON rag.documents USING gin (metadata jsonb_path_ops)" in sql
    assert "WHERE deleted_at IS NULL" in sql
    assert "CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))" in sql
    assert "REFERENCES rag.documents (id) ON DELETE CASCADE" in sql
    assert "REFERENCES rag.collections (id) ON DELETE CASCADE" in sql


# --- just recipes, Brewfile, .gitignore -----------------------------------------------------


def test_migrations_run_as_the_migrator_on_localhost() -> None:
    text = JUSTFILE.read_text()
    match = re.search(r'^rag_db_url\s*:=\s*"([^"]+)"', text, re.MULTILINE)
    assert match
    url = match.group(1)
    assert url.startswith("postgres://rag_migrator:$RAG_DB_MIGRATOR_PASSWORD@127.0.0.1:5432/rag?")
    # pgvector's types live in "public"; a search_path of only "rag" breaks `halfvec`.
    assert "search_path=rag,public" in url
    assert "dbmate --migrations-dir infra/db/rag/migrations --no-dump-schema {{args}}" in text
    for recipe in ("db-migrate", "db-psql:", "db-backup:", "db-restore-test:"):
        assert f"\n{recipe}" in text
    assert "pg_dump -U postgres -d rag -Fc > backups/rag-" in text
    assert "pg_restore -U postgres -d rag_restore_test --no-owner" in text


def test_dbmate_installed_and_backups_never_committed() -> None:
    assert re.search(r'^brew "dbmate"', (REPO / "bootstrap" / "Brewfile").read_text(), re.MULTILINE)
    assert "backups/" in (REPO / ".gitignore").read_text().splitlines()


# --- live database (opt-in) -----------------------------------------------------------------


def _db_reachable() -> bool:
    if not os.environ.get("RAG_DB_APP_PASSWORD"):
        return False
    try:
        socket.create_connection(("127.0.0.1", 5432), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(
    not _db_reachable(), reason="needs rag-db on 127.0.0.1:5432 and RAG_DB_*_PASSWORD"
)


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


def _psql_as(role: str, password_env: str, sql: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PGPASSWORD": os.environ[password_env]}
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        ["psql", "-h", "127.0.0.1", "-U", role, "-d", "rag", "-v", "ON_ERROR_STOP=1", "-c", sql],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@live
def test_demo_filters_by_access_group(fake_gateway_url: str) -> None:
    env = {**os.environ, "LLM_GATEWAY_URL": fake_gateway_url, "INGESTION_GATEWAY_KEY": "sk-test"}
    result = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, str(DEMO)], env=env, capture_output=True, text=True, check=True
    )
    staff, executives = result.stdout.split("user in ['all-staff', 'executives']:")
    assert "Exec offsite" not in staff  # the restricted document never reaches ordinary staff
    assert "Salary bands 2026" not in result.stdout  # nobody here is in "hr"
    assert executives.strip().splitlines()[0].endswith("[restricted]  Exec offsite")


@live
def test_app_role_cannot_change_the_schema() -> None:
    result = _psql_as("rag_app", "RAG_DB_APP_PASSWORD", "DROP TABLE rag.chunks;")
    assert result.returncode != 0
    assert "must be owner of table chunks" in result.stderr


@live
def test_readonly_role_cannot_write() -> None:
    if not os.environ.get("RAG_DB_READONLY_PASSWORD"):
        pytest.skip("needs RAG_DB_READONLY_PASSWORD")
    result = _psql_as("rag_readonly", "RAG_DB_READONLY_PASSWORD", "DELETE FROM rag.chunks;")
    assert result.returncode != 0
    assert "read-only transaction" in result.stderr
