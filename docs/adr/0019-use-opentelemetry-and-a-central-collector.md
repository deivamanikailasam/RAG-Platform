# ADR-0019: Use OpenTelemetry and a central Collector

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Requests cross many services (rag-api, OPA, LiteLLM, model servers, databases). We need traces,
metrics and logs that connect, without locking into one vendor or leaking secrets and content.

## Decision
All services emit OpenTelemetry (OTLP) to otel-collector (contrib 0.162.x, digest-pinned). Pipeline
order: memory_limiter, attributes/scrub (auth/cookie headers, db parameters, gen_ai message
content), redaction (JWT, key and email patterns masked), resource (environment), batch. Services
are configured only via OTEL_* variables; rag_common.telemetry sets up traces, metrics and JSON
stdout logs with trace ids and flushes on shutdown. Spans carry no content (question length only)
and no secrets; metric labels are low-cardinality. LiteLLM (message_logging off), OPA and Keycloak
emit traces into the same traces via W3C traceparent. Sampling: parent-based, 100% in dev.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Vendor agents (Datadog, New Relic) | Turnkey dashboards | Lock-in; cost; data leaves the machine | Vendor-neutral first; any vendor is one exporter away |
| Services export directly to backends | No Collector to run | Config in every service; no central scrubbing | The Collector is our governance point |
| Prometheus client libraries only | Simple metrics | No traces; no correlation | We need all three signals linked |
| Zero-code auto-instrumentation only | No code changes | No RAG-specific spans or safe attribute choices | Use automatic + manual together |

## Consequences
+ One trace per request across services; metrics and logs joinable by trace id.
+ Backends can change by editing one config file.
+ Secrets and personal data are blocked by design and again at the Collector.
- One more service; the Collector must be sized and monitored.
- Pattern-based redaction is a safety net, not a guarantee; content rules in code remain essential.

## Revisit when
Moving to production (tail sampling, a custom Collector build, agent + gateway Collector tiers),
or adding prompt/response capture (Langfuse, Step 22).
