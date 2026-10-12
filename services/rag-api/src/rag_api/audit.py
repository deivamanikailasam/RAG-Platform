"""Audit trail (Step 23): who did what, when, and with what result, in a tamper-evident log.

The log lives in its own database. rag-api connects as `audit_writer`, a role that can do exactly
one thing: call audit.append(). It cannot read, change or delete a single row, so even a fully
compromised rag-api cannot cover its tracks.

What goes in: the user's stable id ("sub"), the app, the action, the outcome, the ids of the
documents returned and the trace id. What never goes in: names, e-mail addresses, the question
text or document content. An audit log is kept for years and read by many; it must not become
a second copy of the data it protects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import psycopg
from opentelemetry import trace
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

tracer = trace.get_tracer("rag_api.audit")

Outcome = Literal["allowed", "denied", "error"]


@dataclass(frozen=True)
class AuditEvent:
    actor: str  # the token's "sub"
    client_id: str  # the app acting for them (azp)
    action: str  # "search", "admin:ping", …
    outcome: Outcome
    resource: str  # what was acted on
    details: Mapping[str, Any] = field(default_factory=dict)  # small facts, never content
    trace_id: str | None = None  # links the event to its trace in Tempo


class AuditUnavailable(Exception):  # noqa: N818 - matches PolicyUnavailable
    """The event could not be stored. Callers must not hand out data they couldn't record."""


class AuditLog(Protocol):
    def record(self, event: AuditEvent) -> int:
        """Store the event; return its sequence number. Raises AuditUnavailable."""
        ...

    def close(self) -> None: ...


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


class PgAuditLog:
    """Writes through audit.append() over a small connection pool."""

    def __init__(
        self, *, host: str, password: str, dbname: str = "audit", port: int = 5432,
        user: str = "audit_writer", timeout: float = 2.0,
    ) -> None:  # fmt: skip
        conninfo = make_conninfo(
            host=host, port=port, dbname=dbname, user=user, password=password,
            connect_timeout=3, application_name="rag-api",
        )  # fmt: skip
        # A few warm connections; autocommit so every event is committed the moment it's appended.
        # timeout = the longest a request waits for a working connection before failing closed.
        # check = test each connection before lending it out (one tiny round trip). Without it, after
        # a database restart the pool lends out dead connections and requests fail needlessly.
        self._pool: ConnectionPool[psycopg.Connection[Any]] = ConnectionPool(
            conninfo, min_size=1, max_size=4, timeout=timeout, open=True,
            kwargs={"autocommit": True}, check=ConnectionPool.check_connection, name="audit",
        )  # fmt: skip

    def record(self, event: AuditEvent) -> int:
        with tracer.start_as_current_span("rag.audit.append") as span:
            span.set_attributes(
                {"rag.audit.action": event.action, "rag.audit.outcome": event.outcome}
            )
            try:
                with self._pool.connection() as conn:
                    row = conn.execute(
                        "SELECT audit.append(%s, %s, %s, %s, %s, %s, %s)",
                        (event.actor, event.client_id, event.action, event.outcome,
                         event.resource, Jsonb(dict(event.details)), event.trace_id),
                    ).fetchone()  # fmt: skip
            except psycopg.Error as e:  # includes the pool's timeout (a psycopg OperationalError)
                span.record_exception(e)
                raise AuditUnavailable(type(e).__name__) from e
            if row is None:  # pragma: no cover   (append() always returns a value)
                raise AuditUnavailable("append returned nothing")
            seq = int(row[0])
            span.set_attribute("rag.audit.seq", seq)
            return seq

    def close(self) -> None:
        self._pool.close()
