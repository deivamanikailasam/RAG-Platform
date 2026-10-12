"""One-call OpenTelemetry setup shared by every service: traces, metrics and trace-aware JSON logs.

Configuration comes from the standard OTEL_* environment variables, so the same code works locally,
in Compose and in Kubernetes:

    OTEL_SERVICE_NAME=rag-api
    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=dev,service.version=0.1.0
    OTEL_TRACES_SAMPLER=parentbased_traceidratio        OTEL_TRACES_SAMPLER_ARG=1.0
    OTEL_SDK_DISABLED=true                               (switch everything off)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter


class JsonFormatter(logging.Formatter):
    """One JSON object per line, carrying the current trace and span id.

    The ids are what join a log line to its trace: in Grafana (Step 21) you click from one to the
    other. Never pass secrets or tokens to a logger; this formatter does not scrub them.
    """

    def format(self, record: logging.LogRecord) -> str:
        ctx = trace.get_current_span().get_span_context()
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if ctx.is_valid:
            entry["trace_id"] = format(ctx.trace_id, "032x")
            entry["span_id"] = format(ctx.span_id, "016x")
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)  # 12-factor: logs go to stdout, collected outside
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def setup_telemetry(
    service_name: str,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> Callable[[], None]:
    """Install global tracer and meter providers. Call once, at startup.

    Returns a shutdown function: call it when the service stops, so the last batch of spans and
    metrics is sent instead of lost. Tests pass an in-memory exporter/reader; in normal runs both
    default to OTLP over gRPC.
    """
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return lambda: None
    # Resource = facts about THIS process, attached to every span and metric.
    # Resource.create() also merges OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES.
    resource = Resource.create({"service.name": service_name})

    # Sampler: read from OTEL_TRACES_SAMPLER (default: parent-based, always on).
    tracer_provider = TracerProvider(resource=resource)
    if span_exporter is None:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    reader = metric_reader or PeriodicExportingMetricReader(
        OTLPMetricExporter(), export_interval_millis=15_000
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    def shutdown() -> None:
        tracer_provider.shutdown()  # flushes pending spans
        meter_provider.shutdown()  # exports the final metric values

    return shutdown
