# ADR-0021: Use Tempo and Loki for traces and logs

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Traces (Step 19) and container logs need durable, searchable storage with retention, connected to
metrics (Step 20) so investigations move from a graph to the exact request and its log lines.

## Decision
Tempo 3.0.x single-process (-target=all), local storage, 7-day block retention, metrics generator
(span metrics + service graph, remote write to Prometheus with exemplars). Loki 3.7.x single-process,
tsdb v13 schema, 7-day retention with compactor deletion, OTLP ingestion. All containers log via
Docker's fluentd driver (async, Compose service label) to the Collector's fluent_forward receiver:
no Docker socket is mounted. The Collector groups logs by service (groupbyattrs), names them, scrubs
attributes and masks JWT/key/email patterns in log bodies, then exports traces to Tempo (otlp_grpc)
and logs to Loki (otlp_http). Prometheus enables the remote-write receiver and exemplar storage.
Grafana data sources link exemplars -> traces -> logs -> traces.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Jaeger (traces) | Mature, CNCF graduated | Separate UI; Elasticsearch/Cassandra for scale | Tempo integrates with Grafana and object storage |
| OpenSearch / Elastic (logs) | Full-text search | Far heavier storage and RAM | Loki is cheaper; OpenSearch stays for search |
| Promtail / Alloy with docker.sock | Auto-discovery | Socket = root on the host; Promtail deprecated | Engine-pushed driver needs no privileges |
| SaaS (Datadog, Honeycomb, Grafana Cloud) | No operations | Cost; data leaves the machine | One exporter change if wanted later |

## Consequences
+ One-click investigation path; logs survive container restarts; retention enforced.
+ Secrets masked before storage, in attributes and in log text.
- Two more stateful services; local disk storage only (object storage in production).
- Pattern masking is a safety net; code must still avoid logging secrets and content.

## Revisit when
Moving to object storage and multi-node (Kafka-based Tempo, scalable Loki), multi-tenancy, or
longer retention for compliance (Step 23 audit log is separate and tamper-evident).
