"""Telemetry: one connected trace per search, useful attributes, metrics, and NO secrets or
content."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag_common.prompts import Registry
from rag_common.telemetry import JsonFormatter  # setup_telemetry is no longer imported here

# The REAL registry, as shipped (the same path as conftest.PROMPTS)
PROMPTS = Path(__file__).resolve().parents[3] / "prompts"

if TYPE_CHECKING:  # type hints only: the objects themselves arrive as fixtures
    from conftest import FakeIdP

QUESTION = "What is the salary of Carol Chen?"  # the kind of text that must never reach telemetry
SPANS: InMemorySpanExporter
METRICS: InMemoryMetricReader


@pytest.fixture(autouse=True)
def _exporters(otel: tuple[InMemorySpanExporter, InMemoryMetricReader]) -> None:
    global SPANS, METRICS
    SPANS, METRICS = otel


@pytest.fixture
def searched(client: TestClient, idp: FakeIdP) -> str:
    SPANS.clear()
    token = idp.mint()
    r = client.post(
        "/v1/search", json={"query": QUESTION}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    return token


def test_one_trace_with_every_stage(searched: str) -> None:
    spans = {s.name: s for s in SPANS.get_finished_spans()}
    assert {"POST /v1/search", "rag.authz.decide", "rag.retrieve", "rag.authz.post_check"} <= set(
        spans
    )
    assert len({s.context.trace_id for s in spans.values()}) == 1  # all one request
    server = spans["POST /v1/search"]
    for name in ("rag.authz.decide", "rag.retrieve", "rag.authz.post_check"):
        parent = spans[name].parent
        assert parent is not None
        assert parent.trace_id == server.context.trace_id


def test_useful_attributes(searched: str) -> None:
    spans = {s.name: s for s in SPANS.get_finished_spans()}
    retrieve = spans["rag.retrieve"].attributes or {}
    assert retrieve["rag.candidates"] == 1
    assert retrieve["rag.query.chars"] == len(QUESTION)
    assert retrieve["enduser.id"] == "8f1c0000-alice"
    assert (spans["rag.authz.decide"].attributes or {})["rag.authz.allow"] is True
    assert (spans["rag.authz.post_check"].attributes or {})["rag.dropped"] == 0


def test_no_token_and_no_question_text_in_any_span(searched: str) -> None:
    for span in SPANS.get_finished_spans():
        dumped = json.dumps(dict(span.attributes or {}), default=str) + span.name
        assert searched not in dumped, f"token leaked into span {span.name}"
        assert "Carol" not in dumped, f"question text leaked into span {span.name}"


def test_metrics_count_searches(searched: str) -> None:
    data = METRICS.get_metrics_data()
    assert data is not None
    names = {
        m.name: m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
    }
    assert {"rag.search.requests", "rag.search.duration", "rag.authz.decisions"} <= set(names)
    ok = [
        p.value
        for p in names["rag.search.requests"].data.data_points
        if isinstance(p, NumberDataPoint) and p.attributes == {"outcome": "ok"}
    ]
    assert ok, "no successful search was counted"
    assert ok[0] >= 1


def test_log_lines_carry_the_trace_id() -> None:
    with trace.get_tracer("test").start_as_current_span("work") as span:
        record = logging.LogRecord("rag_api", logging.INFO, __file__, 1, "hello", None, None)
        line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "hello"
    assert line["trace_id"] == format(span.get_span_context().trace_id, "032x")


def test_latency_buckets_are_in_seconds(searched: str) -> None:
    data = METRICS.get_metrics_data()
    assert data is not None
    hist = next(
        m
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == "rag.search.duration"
    )
    bounds = list(hist.data.data_points[0].explicit_bounds)  # type: ignore[union-attr]
    assert 2 in bounds  # an edge exactly at the 2-second objective
    assert bounds[0] < 0.1  # fine resolution for fast searches, not the millisecond defaults


def test_alert_worthy_counters_start_at_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # Step 20, bug 2: a counter born at its first incident is invisible to increase(). Starting the
    # service must create the search and dropped-document counters at 0.
    import rag_api.main as main

    monkeypatch.setattr(main, "setup_logging", lambda: None)  # keep the test's own providers
    monkeypatch.setattr(main, "setup_telemetry", lambda _name: lambda: None)
    # Start-up also loads the prompt registry (Step 24): use the real one, without env settings
    registry = Registry.load(PROMPTS)
    monkeypatch.setattr(main, "get_prompts", lambda: registry)
    monkeypatch.setattr(main, "get_prompt_label", lambda: "production")
    with TestClient(main.app):  # entering the context runs lifespan() start-up
        pass
    data = METRICS.get_metrics_data()
    assert data is not None
    points = {
        (m.name, tuple(sorted((p.attributes or {}).items())))
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        for p in m.data.data_points
    }
    assert ("rag.search.dropped_documents", ()) in points
    assert ("rag.search.requests", (("outcome", "error"),)) in points
    assert ("rag.search.requests", (("outcome", "ok"),)) in points
