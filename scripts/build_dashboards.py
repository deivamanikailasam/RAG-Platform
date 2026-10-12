#!/usr/bin/env python3
"""Dashboards as code: generate Grafana dashboard JSON from short Python definitions.

Run:   just dashboards          (writes infra/config/grafana/dashboards/*.json; commit the result)
Check: just dashboards-check    (fails if the committed JSON is out of date, e.g. in CI)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "infra/config/grafana/dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}  # matches the provisioned data source
RATE = "$__rate_interval"  # Grafana picks a safe rate window for the zoom level

Panel = dict[str, Any]


class Dashboard:
    def __init__(self) -> None:
        self.panels: list[Panel] = []

    def _add(self, panel: Panel) -> None:
        panel["id"] = len(self.panels) + 1
        self.panels.append(panel)

    def row(self, title: str, y: int) -> None:
        self._add({"type": "row", "title": title, "collapsed": False, "panels": [],
                   "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}})  # fmt: skip

    def stat(self, title: str, expr: str, x: int, y: int, unit: str,
             steps: list[tuple[str, float | None]], desc: str) -> None:  # fmt: skip
        self._add({
            "type": "stat", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": 6, "h": 4},
            "targets": [{"refId": "A", "datasource": DS, "expr": expr, "instant": True}],
            "fieldConfig": {"defaults": {
                "unit": unit, "decimals": 2, "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]},
            }, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "background", "graphMode": "none", "textMode": "value"},
        })  # fmt: skip

    def series(self, title: str, targets: list[tuple[str, str]], x: int, y: int, unit: str,
               desc: str) -> None:  # fmt: skip
        self._add({
            "type": "timeseries", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": 12, "h": 8},
            "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": e, "legendFormat": legend}
                        for i, (e, legend) in enumerate(targets)],
            "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 10}},
                            "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        })  # fmt: skip

    def targets_table(self, x: int, y: int) -> None:
        self._add({
            "type": "table", "title": "Scrape targets", "description": "1 = answering, 0 = down.",
            "datasource": DS, "gridPos": {"x": x, "y": y, "w": 12, "h": 8},
            "targets": [{"refId": "A", "datasource": DS, "expr": "up", "instant": True, "format": "table"}],
            "fieldConfig": {"defaults": {
                "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None},
                                                             {"color": "green", "value": 1}]},
                "custom": {"cellOptions": {"type": "color-background"}},
            }, "overrides": []},
            "transformations": [{"id": "organize", "options": {
                "excludeByName": {"Time": True, "__name__": True}, "renameByName": {"Value": "up"}}}],
        })  # fmt: skip

    def prompts_table(self, x: int, y: int) -> None:
        """Step 24: which prompt version each environment runs right now (from rag_prompt_info)."""
        self._add({
            "type": "table", "title": "Active prompt versions",
            "description": "From the registry baked into each running rag-api. sha = first 12 hex "
                           "characters of the prompt file's SHA-256 (matches prompts.lock.json).",
            "datasource": DS, "gridPos": {"x": x, "y": y, "w": 24, "h": 6},
            "targets": [{"refId": "A", "datasource": DS, "instant": True, "format": "table",
                         "expr": "max by (label, prompt, version, sha) (rag_prompt_info)"}],
            "transformations": [{"id": "organize", "options": {
                "excludeByName": {"Time": True, "Value": True},
                "indexByName": {"label": 0, "prompt": 1, "version": 2, "sha": 3}}}],
        })  # fmt: skip

    def json(self, uid: str, title: str, annotations: list[Panel] | None = None) -> dict[str, Any]:
        return {"uid": uid, "title": title, "tags": ["rag", "slo"], "timezone": "browser",
                "schemaVersion": 41, "version": 1, "editable": False, "refresh": "30s",
                "time": {"from": "now-1h", "to": "now"}, "panels": self.panels,
                "templating": {"list": []}, "annotations": {"list": annotations or []}}  # fmt: skip


# A marker on every time-series panel whenever a prompt version starts running (Step 24):
# "did quality or latency change when rag-answer@3 went live?"
PROMPT_CHANGES = {
    "name": "Prompt version changes", "datasource": DS, "enable": True, "iconColor": "purple",
    "expr": "count by (label, prompt, version) (rag_prompt_info)"
            " unless count by (label, prompt, version) (rag_prompt_info offset 5m)",
    "step": "1m", "titleFormat": "{{prompt}} v{{version}} ({{label}})",
    "textFormat": "A new prompt version started running",
}  # fmt: skip


def otel(kind: str) -> str:
    """Sum one Collector counter over all signals; 'or vector(0)' keeps missing signals from emptying it."""
    return " + ".join(
        f"(sum(rate(otelcol_receiver_{kind}_{s}[{RATE}])) or vector(0))"
        for s in ("spans", "metric_points", "log_records")
    )


def rag_overview() -> dict[str, Any]:
    d = Dashboard()
    d.row("Search: service level objectives", 0)
    d.stat("Success rate (1h) · objective 99%", "1 - rag:search_errors:ratio_rate1h", 0, 1,
           "percentunit", [("red", None), ("orange", 0.99), ("green", 0.995)],
           "Share of searches that did not fail, last hour.")  # fmt: skip
    d.stat("Error budget left (28 days)",
           '1 - (sum(increase(rag_search_requests_total{outcome="error"}[28d]))'
           " / sum(increase(rag_search_requests_total[28d]))) / 0.01",
           6, 1, "percentunit", [("red", None), ("orange", 0.25), ("green", 0.5)],
           "How much of the allowed 1% failures is still unspent this period.")  # fmt: skip
    d.stat("p95 search latency · objective < 2 s", "rag:search_latency:p95_5m", 12, 1, "s",
           [("green", None), ("orange", 1), ("red", 2)],
           "95% of searches finished faster than this (last 5 minutes).")  # fmt: skip
    d.stat("Policy/query mismatches (24h) · must be 0",
           "sum(increase(rag_search_dropped_documents_total[24h])) or vector(0)", 18, 1, "short",
           [("green", None), ("red", 0.5)],
           "Documents the SQL filter returned but the policy refused. Anything above 0 is a bug to investigate.")  # fmt: skip
    d.row("Traffic and latency", 5)
    d.series("Searches per second by outcome",
             [(f"sum by (outcome) (rate(rag_search_requests_total[{RATE}]))", "{{outcome}}")],
             0, 6, "reqps", "ok vs error. Denied requests (403) are not searches.")  # fmt: skip
    d.series("Search latency percentiles",
             [(f"histogram_quantile({q}, sum by (le) (rate(rag_search_duration_seconds_bucket[{RATE}])))",
               f"p{int(q * 100)}") for q in (0.5, 0.95, 0.99)],
             12, 6, "s", "Median, p95 and p99 of end-to-end search time.")  # fmt: skip
    d.series("Policy decisions per second",
             [(f"sum by (action, allow) (rate(rag_authz_decisions_total[{RATE}]))",
               "{{action}} · allow={{allow}}")],
             0, 14, "ops",
             "Every OPA decision. A rise in allow=false can mean misconfigured groups, or probing.")  # fmt: skip
    d.series("HTTP p95 by route (ms)",
             [(f"histogram_quantile(0.95, sum by (le, http_route) (rate(http_server_duration_milliseconds_bucket[{RATE}])))",
               "{{http_route}}")],
             12, 14, "ms", "From the FastAPI instrumentation: every endpoint, not just search.")  # fmt: skip
    d.row("Platform health", 22)
    d.targets_table(0, 23)
    d.series("Telemetry pipeline: accepted vs refused",
             [(otel("accepted"), "accepted"), (otel("refused"), "refused")], 12, 23, "short",
             "Items per second through the OpenTelemetry Collector. Refused > 0 means data loss.")  # fmt: skip
    d.row("Prompts (Step 24)", 31)
    d.prompts_table(0, 32)
    return d.json("rag-overview", "RAG platform · overview", [PROMPT_CHANGES])


DASHBOARDS = {"rag-overview.json": rag_overview}


if __name__ == "__main__":
    check = "--check" in sys.argv
    stale = []
    for name, build in DASHBOARDS.items():
        text = json.dumps(build(), indent=2) + "\n"
        path = OUT / name
        if check:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.write_text(text)
            print("wrote", path.relative_to(OUT.parents[3]))
    if stale:
        sys.exit(f"out of date (run `just dashboards`): {', '.join(stale)}")
