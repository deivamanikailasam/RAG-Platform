"""The audit database itself: the chain, the roles, the append-only rule, and tamper detection."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from psycopg import errors

from rag_api.audit import AuditEvent, AuditUnavailable, PgAuditLog
from rag_common.secrets import StaticCredentials

from .conftest import REWRITE_FROM_2, append, tamper

if TYPE_CHECKING:
    from .conftest import AuditDb


def verify(db: AuditDb) -> tuple[Any, ...]:
    with db.connect("reader") as conn:
        row = conn.execute("SELECT * FROM audit.verify()").fetchone()
    assert row is not None
    return tuple(row)


def test_appends_form_a_chain(chain: AuditDb) -> None:
    assert append(chain, 3) == [1, 2, 3]
    with chain.connect("reader") as conn:
        rows = conn.execute("SELECT seq, prev_hash, hash FROM audit.events ORDER BY seq").fetchall()
    assert rows[0][1] == bytes(32)  # genesis: 32 zero bytes
    assert rows[1][1] == rows[0][2]  # each row points at the previous row's hash
    assert rows[2][1] == rows[1][2]
    assert verify(chain) == (True, 3, None, None)


def test_writer_can_only_append(chain: AuditDb) -> None:
    append(chain, 1)
    with chain.connect("writer") as conn:
        for sql in ("SELECT * FROM audit.events", "UPDATE audit.events SET actor = 'x'",
                    "DELETE FROM audit.events", "SELECT * FROM audit.verify()",
                    "INSERT INTO audit.events (seq) VALUES (99)"):  # fmt: skip
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(sql)


def test_reader_cannot_write(chain: AuditDb) -> None:
    with chain.connect("reader") as conn:
        with pytest.raises((errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction)):
            conn.execute("SELECT audit.append('x', 'c', 'search', 'allowed', 'r')")
        with pytest.raises((errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction)):
            conn.execute("UPDATE audit.events SET actor = 'x'")


@pytest.mark.parametrize(
    "sql", ["UPDATE audit.events SET actor = 'x'", "DELETE FROM audit.events",
            "TRUNCATE audit.events"],
)  # fmt: skip
def test_even_the_owner_cannot_change_rows(chain: AuditDb, sql: str) -> None:
    append(chain, 1)
    with chain.connect("migrator") as conn, pytest.raises(errors.InsufficientPrivilege) as e:
        conn.execute(sql)
    assert "append-only" in str(e.value)


def test_input_is_validated(chain: AuditDb) -> None:
    with chain.connect("writer") as conn:
        with pytest.raises(errors.CheckViolation):
            conn.execute("SELECT audit.append('u', 'c', 'search', 'maybe', 'r')")
        with pytest.raises(errors.InvalidParameterValue):
            conn.execute("SELECT audit.append('u', 'c', 'DROP TABLE', 'allowed', 'r')")
        with pytest.raises(errors.InvalidParameterValue):
            conn.execute("SELECT audit.append('u', 'c', 'search', 'allowed', 'r', '{}', 'nope')")
        with pytest.raises(errors.ProgramLimitExceeded):
            conn.execute("SELECT audit.append('u', 'c', 'search', 'allowed', 'r', %s::jsonb)",
                         ('{"x": "' + "a" * 9000 + '"}',))  # fmt: skip


def test_time_zone_does_not_change_the_hash(chain: AuditDb) -> None:
    with chain.connect("writer") as conn:
        conn.execute("SET TimeZone = 'Asia/Kolkata'")
        conn.execute("SELECT audit.append('u', 'c', 'search', 'allowed', 'r')")
    with chain.connect("reader") as conn:
        conn.execute("SET TimeZone = 'America/Los_Angeles'")
        assert conn.execute("SELECT ok FROM audit.verify()").fetchone() == (True,)


def test_concurrent_writers_never_fork_the_chain(chain: AuditDb) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: append(chain, 25, actor=f"user-{i}"), range(8)))
    seqs = sorted(s for r in results for s in r)
    assert seqs == list(range(1, 201))  # 200 events, no gaps, no duplicates
    assert verify(chain) == (True, 200, None, None)


# ---- tampering, as a superuser who switches the triggers off -------------------------------


def test_edited_row_is_detected(chain: AuditDb) -> None:
    append(chain, 5)
    tamper(chain, "UPDATE audit.events SET details = '{\"returned_ids\": []}' WHERE seq = 3")
    assert verify(chain) == (False, 2, 3, "contents changed: hash does not match the row")


def test_edited_row_with_recomputed_hash_breaks_the_next_link(chain: AuditDb) -> None:
    append(chain, 5)
    tamper(chain, """UPDATE audit.events
                     SET actor = 'someone-else',
                         hash = sha256(prev_hash || convert_to(audit.event_body(
                                (seq, occurred_at, 'someone-else', client_id, action, outcome,
                                 resource, details, trace_id, prev_hash, hash)::audit.events),
                             'UTF8'))
                     WHERE seq = 3""")  # fmt: skip
    ok, _, bad, problem = verify(chain)
    assert (ok, bad) == (False, 4)
    assert problem.startswith("link broken")


def test_deleted_row_is_detected(chain: AuditDb) -> None:
    append(chain, 5)
    tamper(chain, "DELETE FROM audit.events WHERE seq = 2")
    assert verify(chain) == (False, 1, 2, "row 2 is missing (the next row is 3)")


def test_what_the_chain_alone_cannot_catch(chain: AuditDb) -> None:
    """A full rewrite, or chopping off the newest rows, leaves a valid-looking chain.
    That's why we anchor the head outside the database (test_audit_chain.py)."""
    append(chain, 5)
    tamper(chain, REWRITE_FROM_2)
    assert verify(chain)[0] is True  # rewritten, yet "valid"
    tamper(chain, "DELETE FROM audit.events WHERE seq = 5")
    assert verify(chain)[0] is True  # newest row gone, yet "valid"


def test_migration_cannot_be_rolled_back(audit_db: AuditDb) -> None:
    result = audit_db.dbmate("rollback")
    assert result.returncode != 0
    assert "cannot be rolled back" in result.stderr
    assert "[X] 20261012090000_create_audit_log.sql" in audit_db.dbmate("status").stdout


# ---- rag-api's writer against the real database ----------------------------------------------


def test_pg_audit_log_writes_through_append(chain: AuditDb) -> None:
    info = psycopg.conninfo.conninfo_to_dict(chain.admin_dsn)
    log = PgAuditLog(host=str(info.get("host", "127.0.0.1")), port=int(str(info.get("port", 5432))),
                     credentials=StaticCredentials("audit_writer", "test-writer"))  # the throwaway test role  # fmt: skip
    try:
        event = AuditEvent("8f1c0000-alice", "rag-cli", "search", "allowed", "documents",
                           {"returned_ids": [1, 7]}, "0af7651916cd43dd8448eb211c80319c")  # fmt: skip
        assert log.record(event) == 1
        assert log.record(event) == 2
    finally:
        log.close()
    with chain.connect("reader") as conn:
        row = conn.execute(
            "SELECT actor, details, trace_id FROM audit.events WHERE seq = 1"
        ).fetchone()
    assert row == ("8f1c0000-alice", {"returned_ids": [1, 7]}, "0af7651916cd43dd8448eb211c80319c")


def test_pg_audit_log_survives_a_database_restart(chain: AuditDb) -> None:
    """Killed connections (a restart, a failover) must not turn into failed requests."""
    info = psycopg.conninfo.conninfo_to_dict(chain.admin_dsn)
    log = PgAuditLog(host=str(info.get("host", "127.0.0.1")), port=int(str(info.get("port", 5432))),
                     credentials=StaticCredentials("audit_writer", "test-writer"))  # fmt: skip
    event = AuditEvent("u", "c", "search", "allowed", "documents")
    try:
        assert log.record(event) == 1
        with chain.connect("admin") as conn:
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                         " WHERE usename = 'audit_writer'")  # fmt: skip
        assert log.record(event) == 2  # the pool noticed the dead connection and made a new one
    finally:
        log.close()


def test_pg_audit_log_fails_fast_when_the_database_is_down() -> None:
    log = PgAuditLog(host="127.0.0.1", port=1, credentials=StaticCredentials("u", "x"),
                     timeout=0.5)  # nothing listens  # fmt: skip
    started = time.monotonic()
    try:
        with pytest.raises(AuditUnavailable):
            log.record(AuditEvent("u", "c", "search", "allowed", "documents"))
    finally:
        log.close()
    assert time.monotonic() - started < 2  # a quick 503, not a hung request
