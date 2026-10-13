"""/v1/search answered by rag-core's pipeline (Step 32): same token checks, same OPA decision and
post-check, same audit event; hybrid search and reranking from rag.yaml."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from rag_api.search import CoreSearch
from rag_core import config
from rag_core.ingest import IngestionPipeline, load_source
from rag_core.search import SearchPipeline
from rag_core.types import Access

if TYPE_CHECKING:  # type hints only: the objects themselves arrive as fixtures
    from conftest import FakeAudit, FakeIdP
    from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
HANDBOOK = ROOT / "examples/corpus/handbook"


@pytest.fixture(scope="module")
def core() -> CoreSearch:
    container = config.load(ROOT / "rag.yaml", "offline", env={})
    ingest = IngestionPipeline(container)
    for path in sorted(HANDBOOK.glob("*.md")):
        access = (Access("restricted", ("executives",)) if path.name == "exec-compensation.md"
                  else Access("internal", ("all-staff",)))  # fmt: skip
        ingest.ingest(load_source(f"file://{path}", access))
    settings = SimpleNamespace(
        rag_config=ROOT / "rag.yaml", rag_profile="offline", tenant="default"
    )
    return CoreSearch(settings, SearchPipeline(container))  # type: ignore[arg-type]


@pytest.fixture
def search(core: CoreSearch) -> CoreSearch:  # replaces the fake backend for this module's client
    return core


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ask(client: TestClient, idp: FakeIdP, query: str, **claims: Any) -> list[dict[str, object]]:
    token = idp.mint(**({"groups": ["all-staff"]} | claims))
    r = client.post("/v1/search", json={"query": query, "k": 3}, headers=bearer(token))
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_core_backend_finds_by_code_and_audits(
    client: TestClient, idp: FakeIdP, audit: FakeAudit
) -> None:
    hits = ask(client, idp, "My VPN shows E-4021")
    assert hits[0]["title"] == "VPN troubleshooting"
    assert len({h["id"] for h in hits}) == len(hits)  # one hit per document
    event = audit.events[-1]
    assert event.action == "search"
    assert event.details["returned_ids"] == [h["id"] for h in hits]


def test_core_backend_never_returns_what_the_policy_forbids(
    client: TestClient, idp: FakeIdP
) -> None:
    titles = [h["title"] for h in ask(client, idp, "How big is the executive bonus pool?")]
    assert "Executive compensation 2026" not in titles
    assert (
        ask(client, idp, "annual leave", groups=["contractors"]) == []
    )  # no group: nothing internal


def test_core_backend_fails_closed_without_clearance(core: CoreSearch) -> None:
    assert (
        core.search(
            "leave", groups=frozenset({"all-staff"}), classifications=frozenset(), k=3, user="x"
        )
        == []
    )


# ---- extension 01: metadata filters on /v1/search ------------------------------------------------


def test_filter_narrows_the_results_and_is_audited(
    client: TestClient, idp: FakeIdP, audit: FakeAudit
) -> None:
    token = idp.mint(groups=["all-staff"])
    body = {"query": "How many days of leave?", "k": 5,
            "filter": {"title": {"in": ["Parental leave policy", "Sick leave"]}}}  # fmt: skip
    r = client.post("/v1/search", json=body, headers=bearer(token))
    assert r.status_code == 200, r.text
    assert r.json()
    assert {h["title"] for h in r.json()} <= {"Parental leave policy", "Sick leave"}
    assert audit.events[-1].details["filter_fields"] == ["title"]  # the field, never the values


def test_filter_never_widens_what_the_policy_allows(client: TestClient, idp: FakeIdP) -> None:
    body = {"query": "executive bonus pool", "filter": {"title": "Executive compensation 2026"}}
    r = client.post("/v1/search", json=body, headers=bearer(idp.mint(groups=["all-staff"])))
    assert r.status_code == 200
    assert r.json() == []


def test_invalid_filter_is_a_422_that_says_why(client: TestClient, idp: FakeIdP) -> None:
    body = {"query": "leave", "filter": {"updated": {"after": "2025"}}}
    r = client.post("/v1/search", json=body, headers=bearer(idp.mint(groups=["all-staff"])))
    assert r.status_code == 422
    assert "unknown operator" in r.text
