"""Static checks for the audit log wiring (Step 23): no services needed.

The behaviour itself is tested against a real Postgres in test_audit_db.py and test_audit_chain.py
(`just audit-test`); these checks make sure the configuration that connects it all stays in place.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
BOOTSTRAP = REPO / "infra" / "config" / "rag-db" / "init" / "02-audit.sh"
MIGRATIONS = REPO / "infra" / "db" / "audit" / "migrations"
AUDIT_ENV = (
    "AUDIT_DB_MIGRATOR_PASSWORD", "AUDIT_DB_WRITER_PASSWORD", "AUDIT_DB_READER_PASSWORD",
    "S3_AUDIT_ANCHOR_ACCESS_KEY", "S3_AUDIT_ANCHOR_SECRET_KEY",
    "S3_AUDIT_READER_ACCESS_KEY", "S3_AUDIT_READER_SECRET_KEY",
)  # fmt: skip


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def test_bootstrap_script_is_executable_strict_and_reads_password_files() -> None:
    text = BOOTSTRAP.read_text()
    assert os.access(BOOTSTRAP, os.X_OK)
    assert "set -euo pipefail" in text
    assert 'SECRETS_DIR="${SECRETS_DIR:-/run/secrets}"' in text
    for role in ("migrator", "writer", "reader"):
        assert f'"$(cat "$SECRETS_DIR/audit_db_{role}_password")"' in text
        assert f"CREATE ROLE audit_{role}" in text
    assert "SUPERUSER" not in text.upper().replace("NONE OF THEM IS A SUPERUSER", "")
    assert "REVOKE ALL ON DATABASE audit FROM PUBLIC;" in text
    assert "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC" in text


def test_migration_is_forward_only_with_exact_grants() -> None:
    (migration,) = sorted(MIGRATIONS.glob("*.sql"))
    assert migration.name == "20261012090000_create_audit_log.sql"
    up, down = migration.read_text().split("-- migrate:down")
    assert "SECURITY DEFINER SET search_path = pg_catalog, pg_temp" in up
    assert "LOCK TABLE audit.events IN EXCLUSIVE MODE" in up
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE ON audit.events" in up
    grants = re.findall(r"^GRANT .*$", up, re.MULTILINE)
    assert grants == [
        "GRANT EXECUTE ON FUNCTION audit.append(text, text, text, text, text, jsonb, text) TO audit_writer;",
        "GRANT SELECT ON audit.events TO audit_reader;",
        "GRANT EXECUTE ON FUNCTION audit.verify(bigint, bigint), audit.event_body(audit.events) TO audit_reader;",
    ]
    assert "RAISE EXCEPTION 'the audit log cannot be rolled back" in down


def test_rag_db_and_rag_api_get_the_audit_passwords_as_files() -> None:
    data = _compose()
    rag_db, rag_api = data["services"]["rag-db"], data["services"]["rag-api"]
    for name in (
        "audit_db_migrator_password",
        "audit_db_writer_password",
        "audit_db_reader_password",
    ):
        assert name in rag_db["secrets"]
    assert "rag_api_audit_db_password" in rag_api["secrets"]
    assert rag_api["environment"]["RAG_API_AUDIT_DB_HOST"] == "rag-db"
    secrets = data["secrets"]
    assert secrets["audit_db_writer_password"] == {"environment": "AUDIT_DB_WRITER_PASSWORD"}
    # rag-api uses the WRITER password: the role that can only append
    assert secrets["rag_api_audit_db_password"] == {"environment": "AUDIT_DB_WRITER_PASSWORD"}


def test_new_secrets_are_generated_and_documented() -> None:
    generator = (REPO / "scripts" / "new-dev-secrets.sh").read_text()
    example = (REPO / ".env.example").read_text()
    for env in AUDIT_ENV:
        assert f"\n{env}=$(rand)\n" in generator  # letters/digits only: safe inside a URL
        assert re.search(rf"^{env}=<", example, re.MULTILINE)


def test_justfile_has_the_audit_recipes() -> None:
    text = (REPO / "justfile").read_text()
    for recipe in ("audit-bootstrap:", 'audit-migrate *args="status":', "audit-psql *args:",
                   "audit-test:", "audit-anchor:", "audit-verify:"):  # fmt: skip
        assert f"\n{recipe}\n" in text
    assert "--migrations-table audit.schema_migrations" in text
    # The anchor and verify jobs connect as the read-only role
    assert 'audit_reader_dsn := "postgres://audit_reader:' in text


def test_alert_pages_on_any_audit_write_failure() -> None:
    rules = yaml.safe_load((REPO / "infra/config/prometheus/rules/security.yml").read_text())
    [rule] = [
        r for g in rules["groups"] for r in g["rules"] if r.get("alert") == "RagAuditWriteFailing"
    ]
    assert rule["expr"] == "sum(increase(rag_audit_write_failures_total[5m])) > 0"
    assert rule["labels"] == {"severity": "critical", "service": "rag-api"}
    assert rule["annotations"]["runbook"] == "docs/runbooks/audit-log.md"
    assert (REPO / rule["annotations"]["runbook"]).is_file()
