"""Langfuse tracing: masked, isolated from normal telemetry, same trace id, no sensitive titles."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag_api.llmtrace import LlmTracer, build_llm_tracer, mask
from rag_api.main import app, get_llm
from rag_api.policy import DocumentRef
from rag_api.search import Candidate, Hit

if TYPE_CHECKING:  # type hints only: the objects themselves arrive as fixtures
    from conftest import FakeIdP, FakeSearch

QUESTION = "Salary of carol.chen@example.com? (pasted token eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl)"


@pytest.fixture(scope="module")
def _llm() -> tuple[LlmTracer, InMemorySpanExporter]:
    # ONE client per process: the SDK shares resources per public key, so a second client with the
    # same key would silently reuse the first one's exporter. (The app caches its client too.)
    exporter = InMemorySpanExporter()
    tracer = build_llm_tracer(
        base_url=None,
        public_key="pk-test",
        secret_key="sk-test",  # noqa: S106 - placeholder; the in-memory exporter sends nothing
        span_exporter=exporter,
    )
    return tracer, exporter


@pytest.fixture
def langfuse_spans(
    client: TestClient, _llm: tuple[LlmTracer, InMemorySpanExporter]
) -> InMemorySpanExporter:
    tracer, exporter = _llm
    exporter.clear()
    app.dependency_overrides[get_llm] = lambda: tracer
    return exporter


def _search(client: TestClient, idp: FakeIdP, search: FakeSearch) -> None:
    search.candidates = [
        *search.candidates,
        Candidate(DocumentRef(3, "confidential", ("hr",)),
                  Hit(title="Salary bands 2026", classification="confidential", score=0.8)),
    ]  # fmt: skip
    r = client.post(
        "/v1/search", json={"query": QUESTION}, headers={"Authorization": f"Bearer {idp.mint()}"}
    )
    assert r.status_code == 200
    app.dependency_overrides[get_llm]().flush()  # Langfuse exports in batches: send them now


def _attrs(exporter: InMemorySpanExporter) -> dict[str, dict[str, Any]]:
    return {s.name: dict(s.attributes or {}) for s in exporter.get_finished_spans()}


def test_mask_function() -> None:
    assert mask(data={"q": ["mail bob@example.com", "key sk-abcdefghijklmnop1234"]}) == {
        "q": ["mail ****", "key ****"]
    }


def test_search_creates_a_masked_langfuse_trace(
    client: TestClient, idp: FakeIdP, search: FakeSearch, langfuse_spans: InMemorySpanExporter
) -> None:
    _search(client, idp, search)
    spans = _attrs(langfuse_spans)
    assert {"rag-search", "retrieve"} <= set(spans)
    question = json.loads(spans["rag-search"]["langfuse.observation.input"])["question"]
    assert question == "Salary of ****? (pasted token ****)"  # email and token masked
    assert spans["rag-search"]["user.id"] == "8f1c0000-alice"  # pseudonymous id, not a name


def test_sensitive_titles_are_withheld(
    client: TestClient, idp: FakeIdP, search: FakeSearch, langfuse_spans: InMemorySpanExporter
) -> None:
    _search(client, idp, search)
    docs = json.loads(_attrs(langfuse_spans)["retrieve"]["langfuse.observation.output"])
    titles = {d["id"]: d["title"] for d in docs}
    assert titles == {1: "Remote work policy", 3: "[withheld: confidential]"}


def test_same_trace_id_as_the_otel_trace(
    client: TestClient,
    idp: FakeIdP,
    search: FakeSearch,
    langfuse_spans: InMemorySpanExporter,
    otel: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    otel[0].clear()
    _search(client, idp, search)
    server = next(s for s in otel[0].get_finished_spans() if s.name == "POST /v1/search")
    root = next(s for s in langfuse_spans.get_finished_spans() if s.name == "rag-search")
    assert root.context.trace_id == server.context.trace_id  # click from Tempo to Langfuse


def test_langfuse_content_never_reaches_normal_telemetry(
    client: TestClient,
    idp: FakeIdP,
    search: FakeSearch,
    langfuse_spans: InMemorySpanExporter,
    otel: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    otel[0].clear()
    _search(client, idp, search)
    for span in otel[0].get_finished_spans():
        dumped = json.dumps(dict(span.attributes or {}), default=str)
        assert "langfuse." not in dumped, f"Langfuse attribute leaked into OTel span {span.name}"
        assert "Salary" not in dumped
        assert "carol" not in dumped


def test_off_by_default(client: TestClient, idp: FakeIdP, search: FakeSearch) -> None:
    assert not build_llm_tracer(base_url=None, public_key=None, secret_key=None).enabled
    _search(client, idp, search)  # still works with Langfuse switched off


def test_trace_records_which_prompt_versions_were_used(
    client: TestClient, idp: FakeIdP, search: FakeSearch, langfuse_spans: InMemorySpanExporter
) -> None:
    """From any Langfuse trace you can tell exactly which prompt files produced it (Step 24)."""
    _search(client, idp, search)
    root = _attrs(langfuse_spans)["rag-search"]
    prompts = json.loads(root["langfuse.observation.metadata.prompts"])
    assert prompts == {"query-instruction": "query-instruction@1"}
