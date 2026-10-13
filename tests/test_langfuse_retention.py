"""The retention job against the real Langfuse SDK client, with a fake Langfuse server underneath."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
from langfuse import Langfuse


def _load() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/langfuse_retention.py"
    spec = importlib.util.spec_from_file_location("langfuse_retention", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retention = _load()
NOW = dt.datetime(2026, 10, 12, tzinfo=dt.UTC)


class FakeLangfuse:
    """Just enough of /api/public/traces: list (filtered by toTimestamp) and bulk delete."""

    def __init__(self, ages_in_days: list[int]) -> None:
        self.traces = {f"t{i}": NOW - dt.timedelta(days=d) for i, d in enumerate(ages_in_days)}
        self.deletes: list[list[str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/public/traces"
        if request.method == "DELETE":
            ids = json.loads(request.content)["traceIds"]
            self.deletes.append(ids)
            for i in ids:
                self.traces.pop(i, None)
            return httpx.Response(200, json={"message": "Traces deleted"})
        q = request.url.params
        cutoff = dt.datetime.fromisoformat(q["toTimestamp"].replace("Z", "+00:00"))
        old = sorted((ts, i) for i, ts in self.traces.items() if ts < cutoff)
        limit = int(q["limit"])
        data: list[dict[str, Any]] = [
            {"id": i, "timestamp": ts.isoformat(), "tags": [], "public": False,
             "environment": "dev", "htmlPath": f"/trace/{i}"}
            for ts, i in old[:limit]
        ]  # fmt: skip
        meta = {"page": 1, "limit": limit, "totalItems": len(old), "totalPages": 1}
        return httpx.Response(200, json={"data": data, "meta": meta})


class FakeLangfuseV4(FakeLangfuse):
    """A Langfuse v4 server in events_only mode: the legacy trace list answers 404, so old traces
    are found through /api/public/v2/observations (root observations, cursor-paged)."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/public/traces":
            msg = "This endpoint is not available on deployments running in Langfuse v4 events_only mode."
            return httpx.Response(404, json={"message": msg})
        if request.url.path != "/api/public/v2/observations":
            return super().handle(request)
        q = request.url.params
        assert q["isRootObservation"] == "true"
        cutoff = dt.datetime.fromisoformat(q["toStartTime"].replace("Z", "+00:00"))
        old = sorted((ts, i) for i, ts in self.traces.items() if ts < cutoff)
        start, limit = int(q.get("cursor", "0")), int(q["limit"])
        data = [
            {"id": f"obs-{i}", "traceId": i, "startTime": ts.isoformat(), "type": "CHAIN",
             "projectId": "rag-platform"}
            for ts, i in old[start : start + limit]
        ]  # fmt: skip
        more = start + limit < len(old)
        return httpx.Response(
            200, json={"data": data, "meta": {"cursor": str(start + limit) if more else None}}
        )


def _client(fake: FakeLangfuse) -> Langfuse:
    http = httpx.Client(transport=httpx.MockTransport(fake.handle))
    # A unique key per test: the SDK shares its resources (including this HTTP client) between
    # clients with the same public key in one process.
    return Langfuse(
        public_key=f"pk-test-{id(fake)}",
        secret_key="sk-test",  # noqa: S106 - placeholder for the fake server
        base_url="http://langfuse.test",
        tracing_enabled=False,
        httpx_client=http,
    )


def test_deletes_only_traces_older_than_the_cutoff_in_batches() -> None:
    fake = FakeLangfuse([1, 5, 31, 40, 45, 60, 90])  # 5 traces older than 30 days
    deleted = retention.purge(_client(fake), older_than=NOW - dt.timedelta(days=30), batch=2)
    assert deleted == 5
    assert sorted(fake.traces) == ["t0", "t1"]  # the 1- and 5-day-old traces are kept
    assert [len(b) for b in fake.deletes] == [2, 2, 1]  # batches of at most 2


def test_count_for_dry_run_deletes_nothing() -> None:
    fake = FakeLangfuse([1, 31, 40])
    assert retention.count(_client(fake), older_than=NOW - dt.timedelta(days=30)) == 2
    assert fake.deletes == []


def test_v4_events_only_server_falls_back_to_the_observations_api() -> None:
    fake = FakeLangfuseV4([1, 5, 31, 40, 45, 60, 90])
    deleted = retention.purge(_client(fake), older_than=NOW - dt.timedelta(days=30), batch=2)
    assert deleted == 5
    assert sorted(fake.traces) == ["t0", "t1"]
    assert [len(b) for b in fake.deletes] == [2, 2, 1]  # batches of at most 2


def test_v4_count_pages_through_without_deleting() -> None:
    fake = FakeLangfuseV4([1, 31, 40, 45])
    assert retention.count(_client(fake), older_than=NOW - dt.timedelta(days=30)) == 3
    assert fake.deletes == []
