"""rag_common.telemetry on its own: the kill switch, JSON logs, and real providers with resources.

Tracer and meter providers are process-wide and can be installed only ONCE, so the tests that need
real providers run in a fresh Python process; this keeps the rag-api telemetry tests (which install
their in-memory providers in the main test process) independent of the order tests run in.
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import textwrap

import pytest

from rag_common.telemetry import JsonFormatter, setup_logging, setup_telemetry


def test_sdk_disabled_installs_nothing_and_returns_a_harmless_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    shutdown = setup_telemetry("disabled-service")
    shutdown()  # must not raise


def test_log_line_is_one_json_object_without_trace_ids_outside_a_span() -> None:
    record = logging.LogRecord("svc", logging.WARNING, __file__, 1, "n=%d", (3,), None)
    line = json.loads(JsonFormatter().format(record))
    assert line["level"] == "WARNING"
    assert line["logger"] == "svc"
    assert line["msg"] == "n=3"
    assert line["ts"].endswith("+00:00")
    assert "trace_id" not in line  # no active span, no ids


def test_exceptions_are_kept_in_the_json_line() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "svc", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    line = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in line["exc"]


def test_setup_logging_sends_json_to_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        setup_logging("INFO")
        logging.getLogger("svc").info("hello %s", "world")
    finally:
        root.handlers[:], level = saved
        root.setLevel(level)
    assert json.loads(out.getvalue().strip())["msg"] == "hello world"


def test_real_providers_record_spans_and_metrics_with_merged_resource_attributes() -> None:
    # In a fresh process: install real providers with in-memory exporters, record, shut down cleanly.
    code = textwrap.dedent(
        """
        import json
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from rag_common.telemetry import setup_telemetry

        spans, reader = InMemorySpanExporter(), InMemoryMetricReader()
        shutdown = setup_telemetry("probe", span_exporter=spans, metric_reader=reader)
        with trace.get_tracer("t").start_as_current_span("work"):
            pass
        metrics.get_meter("m").create_counter("probe.count").add(2, {"outcome": "ok"})
        data = reader.get_metrics_data()
        shutdown()
        span = spans.get_finished_spans()[0]
        value = data.resource_metrics[0].scope_metrics[0].metrics[0].data.data_points[0].value
        print(json.dumps({"span": span.name, "resource": dict(span.resource.attributes), "value": value}))
        """
    )
    env = {
        "OTEL_RESOURCE_ATTRIBUTES": "service.version=9.9.9,deployment.environment.name=test",
        "PATH": "",
    }
    result = subprocess.run(  # noqa: S603 - fixed code, our own interpreter
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    out = json.loads(result.stdout)
    assert out["span"] == "work"
    assert out["value"] == 2
    assert out["resource"]["service.name"] == "probe"
    assert out["resource"]["service.version"] == "9.9.9"  # from OTEL_RESOURCE_ATTRIBUTES
    assert out["resource"]["deployment.environment.name"] == "test"


@pytest.mark.parametrize(("setting", "expected"), [(None, 15000.0), ("2500", 2500.0)])
def test_metric_export_interval_honours_the_standard_setting(
    setting: str | None, expected: float
) -> None:
    # Step 20: Prometheus scrapes every 15 s, so metrics are pushed every 15 s by default, and the
    # standard OTEL_METRIC_EXPORT_INTERVAL (milliseconds) overrides it. Fresh process: providers are global.
    code = textwrap.dedent(
        """
        from opentelemetry import metrics
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from rag_common.telemetry import setup_telemetry

        shutdown = setup_telemetry("probe", span_exporter=InMemorySpanExporter())
        reader = metrics.get_meter_provider()._metric_readers[0]  # SDK internals, test only
        print(reader._export_interval_millis)
        shutdown()
        """
    )
    env = {"PATH": "", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9"}  # nothing listens there
    if setting is not None:
        env["OTEL_METRIC_EXPORT_INTERVAL"] = setting
    result = subprocess.run(  # noqa: S603 - fixed code, our own interpreter
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    )
    assert float(result.stdout.strip()) == expected
