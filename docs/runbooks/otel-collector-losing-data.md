# Runbook: OtelCollectorLosingData (warning)

**What it means:** for 5 minutes the OpenTelemetry Collector has been refusing incoming telemetry
(its memory limit was hit) or failing to deliver it to a backend. Dashboards and alerts that depend on
our own services' metrics may be incomplete, and traces/logs are being lost.

**Check first (5 minutes)**
1. Grafana → *RAG platform · overview* → "Telemetry pipeline: accepted vs refused".
2. Which counter? In Prometheus, look at `otelcol_receiver_refused_*` (memory pressure) and
   `otelcol_exporter_send_failed_*` (a backend is unreachable).
3. Collector logs: `just logs otel-collector` (look for `memory_limiter` or exporter errors).
4. Is Prometheus up and accepting OTLP? `curl -s localhost:9090/-/ready`.

**Likely causes**
- A traffic spike or a service sending far more spans than usual: the memory limiter refuses data.
- Prometheus (or, from Step 21, Tempo/Loki) is down, so exports fail.
- After a Collector upgrade: metric names changed (they have no `_total` suffix in 0.162). If this alert
  never fires again after an upgrade, check the names still match.

**Fix**
- Restart the failing backend; reduce the volume (lower `OTEL_TRACES_SAMPLER_ARG`) or raise the
  Collector's memory limit in Compose.

**Close**
- Refused and failed rates return to 0; the alert resolves after 5 minutes.
