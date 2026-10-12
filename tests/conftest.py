"""A real, THROWAWAY Postgres for the audit tests (Step 23).

`just audit-test` starts one and sets
AUDIT_TEST_ADMIN_DSN=postgres://postgres@127.0.0.1:55432/postgres
The fixtures DROP and recreate the `audit` database and its roles, so never point this at rag-db.
Tests skip when the variable isn't set or dbmate isn't installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
ADMIN_DSN = os.environ.get("AUDIT_TEST_ADMIN_DSN")
PASSWORDS = {"migrator": "test-migrator", "writer": "test-writer", "reader": "test-reader"}


@dataclass(frozen=True)
class AuditDb:
    admin_dsn: str

    def dsn(self, role: str, dbname: str = "audit") -> str:
        """Connection string for audit_<role> (or the superuser for role="admin")."""
        if role == "admin":
            return make_conninfo(self.admin_dsn, dbname=dbname)
        return make_conninfo(self.admin_dsn, user=f"audit_{role}", password=PASSWORDS[role],
                             dbname=dbname)  # fmt: skip

    def connect(self, role: str) -> psycopg.Connection[Any]:
        return psycopg.connect(self.dsn(role), autocommit=True)

    def dbmate(self, *args: str) -> subprocess.CompletedProcess[str]:
        p = conninfo_to_dict(self.admin_dsn)
        url = (f"postgres://audit_migrator:{PASSWORDS['migrator']}@{p.get('host', '127.0.0.1')}:"
               f"{p.get('port', 5432)}/audit?sslmode=disable")  # fmt: skip
        return subprocess.run(  # noqa: S603 - fixed arguments, test-only
            ["dbmate", "--migrations-dir", str(ROOT / "infra/db/audit/migrations"),  # noqa: S607
             "--migrations-table", "audit.schema_migrations", "--no-dump-schema", *args],
            env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True, check=False,
        )  # fmt: skip


@pytest.fixture(scope="session")
def audit_db(tmp_path_factory: pytest.TempPathFactory) -> AuditDb:
    if not ADMIN_DSN:
        pytest.skip("AUDIT_TEST_ADMIN_DSN not set (run the full suite with: just audit-test)")
    if shutil.which("dbmate") is None:
        pytest.skip("dbmate not installed")
    db = AuditDb(ADMIN_DSN)
    with psycopg.connect(db.dsn("admin", "postgres"), autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS audit WITH (FORCE)")
        for role in ("audit_migrator", "audit_writer", "audit_reader"):
            conn.execute(f"DROP ROLE IF EXISTS {role}")
    # 1. The real bootstrap script, fed passwords from files exactly like Docker secrets
    secrets = tmp_path_factory.mktemp("secrets")
    for name, value in PASSWORDS.items():
        (secrets / f"audit_db_{name}_password").write_text(value)
    p = conninfo_to_dict(ADMIN_DSN)
    env = {**os.environ, "SECRETS_DIR": str(secrets), "POSTGRES_USER": str(p.get("user", "postgres")),
           "PGHOST": str(p.get("host", "127.0.0.1")), "PGPORT": str(p.get("port", 5432))}  # fmt: skip
    if p.get("password"):
        env["PGPASSWORD"] = str(p["password"])
    subprocess.run(  # noqa: S603
        [str(ROOT / "infra/config/rag-db/init/02-audit.sh")], env=env, check=True,
        capture_output=True,
    )  # fmt: skip
    # 2. The real migration, applied by the real tool as the migrator role
    result = db.dbmate("up")
    assert result.returncode == 0, result.stderr
    return db


@pytest.fixture
def chain(audit_db: AuditDb) -> AuditDb:
    """Each test starts from an empty log. Emptying it needs superuser + triggers switched off."""
    with audit_db.connect("admin") as conn:
        conn.execute("SET session_replication_role = replica")  # skips ordinary triggers
        conn.execute("TRUNCATE audit.events")
    return audit_db


def append(db: AuditDb, n: int, actor: str = "8f1c0000-alice") -> list[int]:
    with db.connect("writer") as conn:
        return [
            conn.execute(
                "SELECT audit.append(%s, 'rag-cli', 'search', 'allowed', 'documents', %s::jsonb)",
                (actor, f'{{"returned_ids": [{i}]}}'),
            ).fetchone()[0]  # type: ignore[index]
            for i in range(n)
        ]


def tamper(db: AuditDb, sql: str) -> None:
    """What an attacker with SUPERUSER rights can do: switch triggers off and edit rows."""
    with db.connect("admin") as conn:
        conn.execute("SET session_replication_role = replica")
        conn.execute(sql)


# The strongest attack: change a row, then recompute every later hash so the chain looks perfect.
REWRITE_FROM_2 = """
UPDATE audit.events SET details = '{"returned_ids": []}' WHERE seq = 2;
DO $$
DECLARE e audit.events%ROWTYPE; prev bytea;
BEGIN
    SELECT hash INTO prev FROM audit.events WHERE seq = 1;
    FOR e IN SELECT * FROM audit.events WHERE seq >= 2 ORDER BY seq LOOP
        e.prev_hash := prev;
        e.hash := sha256(prev || convert_to(audit.event_body(e), 'UTF8'));
        UPDATE audit.events SET prev_hash = e.prev_hash, hash = e.hash WHERE seq = e.seq;
        prev := e.hash;
    END LOOP;
END $$;
"""
