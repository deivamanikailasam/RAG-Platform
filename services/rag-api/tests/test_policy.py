"""Authorisation wiring: the API asks the policy, obeys it, and never trusts the caller."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from rag_api.policy import DocumentRef
from rag_api.search import Candidate, Hit

if TYPE_CHECKING:  # type hints only: the objects themselves arrive as fixtures
    from conftest import FakeIdP, FakePolicy, FakeSearch


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_policy_gets_facts_from_the_token_only(
    client: TestClient, idp: FakeIdP, policy: FakePolicy, search: FakeSearch
) -> None:
    body = {"query": "hybrid work", "groups": ["executives"]}  # a sneaky extra field
    r = client.post("/v1/search", json=body, headers=bearer(idp.mint()))
    assert r.status_code == 200
    action, principal = policy.asked[0]
    assert action == "search"
    assert principal.groups == frozenset({"all-staff", "engineering"})  # not "executives"
    assert search.calls[0]["groups"] == frozenset({"all-staff", "engineering"})


def test_search_applies_the_policy_filter(
    client: TestClient, idp: FakeIdP, search: FakeSearch
) -> None:
    client.post("/v1/search", json={"query": "x"}, headers=bearer(idp.mint()))
    assert search.calls[0]["classifications"] == frozenset({"public", "internal"})
    assert search.calls[0]["user"] == "8f1c0000-alice"


def test_deny_gives_403_with_reason(client: TestClient, idp: FakeIdP, policy: FakePolicy) -> None:
    policy.allow, policy.reasons = False, ("action admin:ping requires role rag-admin",)
    r = client.get("/v1/admin/ping", headers=bearer(idp.mint()))
    assert r.status_code == 403
    assert "requires role rag-admin" in r.json()["detail"]


def test_policy_down_gives_503_not_access(
    client: TestClient, idp: FakeIdP, policy: FakePolicy
) -> None:
    policy.down = True
    r = client.post("/v1/search", json={"query": "x"}, headers=bearer(idp.mint()))
    assert r.status_code == 503  # fail closed: no decision, no data


def test_post_check_drops_what_the_query_should_not_have_returned(
    client: TestClient, idp: FakeIdP, policy: FakePolicy, search: FakeSearch
) -> None:
    # Simulate a buggy query that leaks a restricted document into the candidates.
    leaked = Candidate(
        DocumentRef(4, "restricted", ("executives",)),
        Hit(title="Exec offsite", classification="restricted", score=0.9),
    )
    search.candidates = [*search.candidates, leaked]
    policy.readable_ids = {1}  # the policy's full rule says only document 1 is readable
    r = client.post("/v1/search", json={"query": "x"}, headers=bearer(idp.mint()))
    assert [h["title"] for h in r.json()] == ["Remote work policy"]
