"""The audit trail: what gets recorded, what never does, and what happens when it can't be written."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rag_api.policy import DocumentRef
from rag_api.search import Candidate, Hit

if TYPE_CHECKING:  # type hints only: the objects themselves arrive as fixtures
    from conftest import FakeAudit, FakeIdP, FakePolicy, FakeSearch
    from fastapi.testclient import TestClient
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

QUESTION = "what is the salary of bob@example.com?"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_search_records_who_got_which_documents(
    client: TestClient, idp: FakeIdP, audit: FakeAudit, search: FakeSearch, policy: FakePolicy,
    otel: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:  # fmt: skip
    search.candidates.append(
        Candidate(DocumentRef(4, "restricted", ("executives",)),
                  Hit(id=4, title="Board minutes", classification="restricted", score=0.9))
    )  # fmt: skip
    policy.readable_ids = {1}  # the post-check drops document 4
    r = client.post("/v1/search", json={"query": QUESTION, "k": 3}, headers=bearer(idp.mint()))
    assert r.status_code == 200
    [e] = audit.events
    assert (e.actor, e.client_id, e.action, e.outcome) == (
        "8f1c0000-alice",
        "rag-cli",
        "search",
        "allowed",
    )
    assert e.details == {
        "returned_ids": [1],
        "dropped_by_policy": 1,
        "k": 3,
        "query_chars": len(QUESTION),
        "prompts": ["query-instruction@1"],  # which prompt versions shaped it (Step 24)
    }
    assert e.trace_id is not None  # links the event to its trace in Tempo
    assert len(e.trace_id) == 32
    # Never the question, the username, an e-mail address or a title
    flat = json.dumps(e.__dict__, default=str)
    for secret in ("salary", "bob@example.com", '"alice"', "Board minutes", "Remote work"):
        assert secret not in flat


def test_denied_request_is_recorded(
    client: TestClient, idp: FakeIdP, audit: FakeAudit, policy: FakePolicy
) -> None:
    policy.allow, policy.reasons = False, ("missing role rag-admin",)
    r = client.get("/v1/admin/ping", headers=bearer(idp.mint()))
    assert r.status_code == 403
    [e] = audit.events
    assert (e.action, e.outcome, e.details) == (
        "admin:ping",
        "denied",
        {"reasons": ["missing role rag-admin"]},
    )


def test_admin_action_is_recorded(client: TestClient, idp: FakeIdP, audit: FakeAudit) -> None:
    assert client.get("/v1/admin/ping", headers=bearer(idp.mint())).status_code == 200
    assert [(e.action, e.outcome) for e in audit.events] == [("admin:ping", "allowed")]


def test_no_audit_no_data(
    client: TestClient, idp: FakeIdP, audit: FakeAudit,
    otel: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:  # fmt: skip
    """Fail closed: if the event can't be stored, the documents are not handed out."""
    audit.down = True
    r = client.post("/v1/search", json={"query": "remote work"}, headers=bearer(idp.mint()))
    assert r.status_code == 503
    assert r.json() == {"detail": "Audit log unavailable"}
    assert "Remote work" not in r.text
    assert client.get("/v1/admin/ping", headers=bearer(idp.mint())).status_code == 503


def test_audit_outage_does_not_turn_a_refusal_into_an_error(
    client: TestClient, idp: FakeIdP, audit: FakeAudit, policy: FakePolicy
) -> None:
    """A refusal hands nothing out, so it stays a 403 (the lost event is counted and logged)."""
    audit.down, policy.allow = True, False
    assert client.get("/v1/admin/ping", headers=bearer(idp.mint())).status_code == 403


def test_bad_token_is_not_an_audit_event(client: TestClient, audit: FakeAudit) -> None:
    """No verified identity, no actor to record: failed sign-ins are Keycloak's events (Step 16)."""
    assert client.get("/v1/admin/ping", headers=bearer("garbage")).status_code == 401
    assert audit.events == []
