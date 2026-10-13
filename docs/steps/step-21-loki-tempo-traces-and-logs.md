# Step 21 · Loki + Tempo: from a spike to the exact trace and log line

*Step 21 of 38 · Phase E · Observability*

## At a glance

| | |
|---|---|
| **Goal** | Give traces and logs a proper home, and connect all three signals (metrics, traces, logs) so investigating becomes clicking instead of searching. **Tempo** stores every trace. **Loki** stores every container's log lines. **Grafana** links them both ways. The journey: from a latency spike on a dashboard, open the exact request behind it (an *exemplar*), see its trace across services, jump to that request's log lines, and back again. |
| **Time** | About 2 hours. |
| **You'll end up with** | `tempo` (3.0.x, single process) with 7-day retention and a *metrics generator* that turns traces into request-rate metrics and a service graph; `loki` (3.7.x) with 7-day retention, receiving logs over OTLP; every container's output shipped by Docker's own log driver to the Collector, with **no Docker socket mounted**; the Collector grouping logs by service, masking tokens and emails in the log text, and sending traces to Tempo and logs to Loki; Grafana data sources wired for metric → trace → logs → trace; the two deprecated Collector exporter names fixed (already corrected in Step 20 in this repo); ADR-0021. |
| **New words** | Trace backend, log aggregation, Loki stream, label vs log text, LogQL, line filter, parser, TraceQL, exemplar, span metrics, service graph, remote write, logging driver, dual logging, structured metadata, retention. |

## The big idea

> **ANALOGY · THE AIRPORT AFTER A DELAYED FLIGHT**
> The departures board shows that flights from gate 12 are late today. That's a **metric**.
>
> You pick one late flight and pull its timeline: boarding 14:02, doors closed 14:31, pushback 14:58. The 27
> minutes are obvious. That's a **trace**.
>
> Then you read the logbook entries stamped with that flight number: "baggage loader fault at 14:35". That's the
> **logs**.
>
> Each step is one click because the flight number is written on everything. Tempo is the timeline archive, Loki
> is the logbook archive, and the **trace id is the flight number**.

```text
 1 · Grafana dashboard           2 · Tempo trace                      3 · Loki log lines
 p95 search latency jumps        rag-api  POST /v1/search  ████████   {service_name="rag-api"}
        .  •  <- exemplar          opa    v1/data/...      ██           |= "4bf92f35…"
       / \/                        rag-api post_check         █       ERROR query/policy mismatch:
  ____/                                                                dropped [4]  trace_id: 4bf92f35…
 a dot = one real request's      the slow span is obvious;            "View trace"  <- back again
 trace id                        "Logs for this span"  ->

      One id, three stores: the trace id in the exemplar, the spans and every log line connects them all.
```

*Figure 66. The investigation journey. A dot on a latency graph (an exemplar) carries one real request's
trace id; the trace in Tempo shows the slow step; "Logs for this span" opens exactly that request's lines in
Loki; each log line links back to its trace.*

## What we're doing

1. Run Tempo (traces) and Loki (logs) in single-process mode with retention.
2. Send all container output to the Collector with Docker's `fluentd` log driver, with the service name
   attached to every line.
3. Extend the Collector: group logs by service, name them, scrub and mask secrets in log text; export traces
   to Tempo and logs to Loki.
4. Let Prometheus accept Tempo's span metrics and service graph, and store exemplars.
5. Wire Grafana's data sources so every signal links to the others.
6. Test the whole journey end to end, then record ADR-0021.

## Why we're doing this

> **WHY THIS MATTERS**
> During an incident, time goes into *finding* things: which request, which service, which log file, which
> minute. The usual approach is to SSH into machines and grep logs. It doesn't scale, doesn't survive container
> restarts, and gives everyone with access to the machine access to all its data.
>
> Central, connected, retention-managed traces and logs turn a 2-hour hunt into a 2-minute path. For RAG, that
> path answers the questions users actually ask:
>
> - "Why was my answer slow?"
> - "Why didn't I see that document?"

| Need | How this step meets it |
|---|---|
| Keep traces, searchable | Tempo + TraceQL, 7-day retention |
| Keep every container's logs | Docker fluentd log driver → Collector → Loki, 7-day retention |
| Logs survive container restarts | Stored in Loki, not in the container |
| Find one request's logs | Trace id on every log line; Loki line filter |
| From a graph to the cause | Exemplars: metric points carry a trace id |
| See who calls whom | Service graph and span metrics generated from traces |
| No secrets in log storage | Collector masks token, key and email patterns in the log text |
| Least privilege | No Docker socket mounted; Tempo and Loki on the internal network only |

> **IN A COMPANY**
> Centralised logs and traces are an audit and compliance requirement as much as a debugging tool. Standards
> like SOC 2 and ISO 27001 ask for log retention, access control and integrity. Privacy law (GDPR, Australia's
> Privacy Act) asks you to minimise personal data in logs and keep it only as long as needed.
>
> Grafana's LGTM stack (Loki, Grafana, Tempo, Mimir) is a common self-hosted choice; Elastic, Datadog, Splunk
> and the cloud providers' tools are the usual alternatives. Because our services speak OpenTelemetry,
> switching is a Collector exporter change.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Trace backend (Tempo) | Stores traces and finds them by id or by query. Tempo indexes very little, so it's cheap. |
| TraceQL | Tempo's query language, e.g. `{resource.service.name="rag-api" && duration > 2s}`. |
| Log aggregation (Loki) | Collects logs from every container into one searchable store. |
| Stream / label | A Loki stream is all lines with the same labels (e.g. `service_name="rag-api"`). Labels are the only indexed part. |
| LogQL | Loki's query language: pick streams by label, then filter (`\|= "text"`) and parse (`\| json`). |
| Structured metadata | Extra per-line facts Loki stores without making them labels: searchable, but no index bloat. |
| Exemplar | A sample trace id attached to a metric data point, so a graph can link to a real request. |
| Span metrics / service graph | Request rate, errors and duration per service, and who-calls-whom, computed from traces by Tempo. |
| Remote write | The protocol Tempo uses to push those generated metrics into Prometheus. |
| Logging driver | Where Docker sends a container's stdout/stderr: `json-file` (default, local) or `fluentd` (to a network endpoint), for example. |
| Dual logging | Docker keeps a local copy even with a remote driver, so `docker compose logs` still works. |

> **IN PLAIN ENGLISH**
> A **line filter** (`|= "abc"`) keeps only lines containing that text; a **parser** (`| json`) turns each
> line's JSON into fields you can filter on (`| level="ERROR"`). **Retention** is how long the store keeps data
> before deleting it: 7 days here for both traces and logs.

### How logs and traces get there

```text
 Our services                    OTLP                OTel Collector                     Tempo
 OTel SDK: spans  ─────────────────────────────────► traces: scrub, redact, batch ─────► traces · 7 days
                                                                                          │
 Every container      Docker engine                  logs :24224                          │ span metrics +
 stdout / stderr ───► fluentd log driver ──────────► group by service                     │ service graph
 (JSON logs +         + service label                name the service                     │ (remote write)
  trace_id)                                          scrub, redact attributes             ▼
                                                     mask tokens in the TEXT        Prometheus
                                                     batch ───────────────────────► Loki        metrics + exemplars
                                                                                     logs · 7 days

        No Docker socket is mounted anywhere: the engine pushes logs out, nobody reaches in.
```

*Figure 67. The data paths. Our services send spans over OTLP. Every container's output goes from the Docker
engine's log driver to the Collector, which groups, names and cleans it. Traces go to Tempo, logs to Loki,
and Tempo's generated metrics to Prometheus.*

> **WHY THE DOCKER LOG DRIVER, NOT A LOG AGENT WITH THE DOCKER SOCKET?**
> Many guides run a log agent (Promtail, Alloy, Fluent Bit) that mounts `/var/run/docker.sock` to discover
> containers and read their logs. Promtail itself is deprecated in favour of Alloy, but the socket problem is
> the same for all of them.
>
> The Docker socket is **root access to your whole machine**: anything that can talk to it can start a
> privileged container. Instead, we let the Docker engine *push* each container's output to the Collector
> using the built-in `fluentd` driver (the Collector speaks that protocol). Nothing reaches into Docker.
>
> Two settings matter:
>
> - `fluentd-async`: containers start even if the Collector is down. Lines are buffered, then dropped if it
>   stays down.
> - `labels`: adds the Compose service name to every line.

### What Loki indexes, and what it doesn't

```text
 Loki: index a few LABELS, scan the text            Full-text search engines (OpenSearch, Elastic)
 ┌────────────────────────────────────────────┐     index every word of every line
 │ stream labels (indexed, few values)        │     fast arbitrary search…
 │ service_name="rag-api" detected_level="error"│   …at several times the storage and RAM
 ├────────────────────────────────────────────┤     good for: security analytics, ad-hoc search
 │ log text (compressed chunks, scanned)      │     (OpenSearch already runs, from Step 13)
 │ |= "4bf92f35…" | json | msg=~"mismatch.*"   │
 └────────────────────────────────────────────┘
 cheap to store · fast when labels narrow it first

 Never use user ids, trace ids or request ids as Loki labels: millions of streams.
 Put them in the text (or metadata).
```

*Figure 68. Loki indexes only a few labels and scans compressed text for the rest, which keeps it cheap.
Full-text engines index every word: faster arbitrary search, far more storage. Never put ids in labels.*

> **WATCH OUT · LABELS MUST HAVE FEW VALUES**
> Each unique combination of labels is a separate stream. `service_name` (about 20 values) and level (5
> values) are fine. User ids, trace ids or request ids as labels would create millions of streams and grind
> Loki to a halt. That's the same cardinality rule as metrics in Step 20. Ids belong in the log text (or
> structured metadata) and are found with a line filter: `|= "4bf92f35…"`.

## How to do it

On the Mac, in the project folder:

```bash
cd ~/dev/rag-platform
git switch -c feat/loki-tempo
mkdir -p infra/config/{tempo,loki}
```

### 1 · Tempo

Tempo 3 changed its architecture: the old "ingester" path is gone, and the scalable mode needs Kafka. For one
machine, the single-process mode (`-target=all`) runs every component in one binary without Kafka, and that's
what we use. The file is [`infra/config/tempo/tempo.yaml`](../../infra/config/tempo/tempo.yaml):

```yaml
# Tempo 3, single process ("-target=all"): every component in one binary, no Kafka needed.
stream_over_http_enabled: true                  # lets Grafana stream search results as they arrive

server:
  http_listen_port: 3200                        # query API (Grafana) and /ready
  log_level: info
  log_format: json

distributor:
  receivers:
    otlp:
      protocols:
        grpc: { endpoint: "0.0.0.0:4317" }      # only the Collector sends here (internal network)

storage:
  trace:
    backend: local                              # dev: local disk. Production: object storage (our SeaweedFS S3)
    wal: { path: /var/tempo/wal }
    local: { path: /var/tempo/blocks }

backend_worker:                                 # compaction + retention run in-process in single-binary mode
  compaction:
    block_retention: 168h                       # keep traces 7 days

# Turn traces into metrics: request rate, errors and duration per service and span ("span metrics"),
# and who-calls-whom ("service graph"), written to Prometheus.
metrics_generator:
  registry:
    external_labels: { source: tempo }
  storage:
    path: /var/tempo/generator/wal
    remote_write:
      - url: http://prometheus:9090/api/v1/write
        send_exemplars: true

overrides:
  defaults:
    metrics_generator:
      processors: [span-metrics, service-graphs]

usage_report:
  reporting_enabled: false                      # no phoning home
```

> **READING THE TEMPO CONFIG**
> - The receiver listens on OTLP gRPC inside the Compose network only. Services never send to Tempo directly;
>   the Collector does, after scrubbing.
> - Local storage is for development. In production, Tempo stores blocks in object storage: our SeaweedFS S3
>   from Step 14 would work.
> - The metrics generator reads every span and writes two kinds of metrics to Prometheus:
>   - **span metrics**: `traces_spanmetrics_calls_total`, plus latency per service and span name;
>   - the **service graph**: `traces_service_graph_request_total{client, server}`. Grafana draws the graph as
>     a picture of who calls whom.
> - `usage_report` off: no anonymous usage data sent to Grafana Labs.

### 2 · Loki

The file is [`infra/config/loki/loki.yaml`](../../infra/config/loki/loki.yaml):

```yaml
# Loki, single process: stores logs cheaply by indexing only a few LABELS, not the text itself.
auth_enabled: false                             # single tenant; Loki sits on the internal network only

server:
  http_listen_port: 3100
  log_level: info
  log_format: json

common:
  path_prefix: /loki
  replication_factor: 1
  ring:
    kvstore: { store: inmemory }
  storage:
    filesystem:                                 # dev: local disk. Production: object storage (S3)
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules

schema_config:
  configs:
    - from: "2026-01-01"
      store: tsdb                               # current index format
      object_store: filesystem
      schema: v13
      index: { prefix: index_, period: 24h }

limits_config:
  retention_period: 168h                        # keep logs 7 days
  allow_structured_metadata: true               # OTLP attributes kept as searchable metadata, not labels
  max_query_lookback: 168h

compactor:
  working_directory: /loki/compactor
  retention_enabled: true                       # actually delete old logs
  delete_request_store: filesystem

analytics:
  reporting_enabled: false
```

> **READING THE LOKI CONFIG**
> - `auth_enabled: false`: a single tenant. Loki has no login of its own, so it stays on the internal
>   network (only Grafana and the Collector talk to it).
> - `schema: v13` with `tsdb`: the current index format. The `from` date is when this schema starts; future
>   schema changes add a new entry with a later date.
> - Retention needs **two** settings: `retention_period` says how long, and `compactor.retention_enabled`
>   actually deletes. Forgetting the second is a classic way to fill a disk.
> - `allow_structured_metadata`: OTLP attributes that aren't labels are kept per line as searchable metadata.

### 3 · The Collector: traces to Tempo, logs to Loki

Two names changed in this Collector version, which logs a warning for the old ones: the `otlphttp` exporter
is now `otlp_http` and the gRPC `otlp` exporter is now `otlp_grpc`. Step 20's config already used
`otlp_http/prometheus` in this repo. The complete file is
[`infra/config/otel-collector/config.yaml`](../../infra/config/otel-collector/config.yaml); the new parts are:

```yaml
receivers:
  fluent_forward:                                # container stdout/stderr, sent by Docker's "fluentd" log driver
    endpoint: 0.0.0.0:24224

processors:
  # 2. Container logs arrive from Docker's log driver, all containers over one connection. Each line
  #    carries its Compose service name (the driver's "labels" option). Regroup lines by that value,
  #    so every group belongs to exactly one service, then name the service after it.
  groupbyattrs/container:
    keys: [com.docker.compose.service]
  transform/container-logs:
    log_statements:
      - context: resource
        conditions: ['attributes["com.docker.compose.service"] != nil']
        statements:
          - set(attributes["service.name"], attributes["com.docker.compose.service"])
          - delete_key(attributes, "com.docker.compose.service")
      - context: log
        statements:
          - delete_key(attributes, "fluent.tag")
  # ... attributes/scrub and redaction as in Step 19 ...
  # The redaction processor checks ATTRIBUTES. A log line's text is its BODY, so mask that too.
  transform/redact-log-body:
    log_statements:
      - context: log
        statements:
          - replace_pattern(body, "eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+", "****")
          - replace_pattern(body, "sk-[A-Za-z0-9_-]{16,}", "****")
          - replace_pattern(body, "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}", "****")

exporters:
  otlp_grpc/tempo:                               # traces -> Tempo (Step 21)
    endpoint: tempo:4317
    tls: { insecure: true }                      # inside the Compose network only
  otlp_http/prometheus:                          # metrics -> Prometheus's OTLP endpoint (Step 20)
    endpoint: http://prometheus:9090/api/v1/otlp
    tls: { insecure: true }
  otlp_http/loki:                                # logs -> Loki's OTLP endpoint (Step 21)
    endpoint: http://loki:3100/otlp
    tls: { insecure: true }

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, attributes/scrub, redaction, resource, batch]
      exporters: [otlp_grpc/tempo]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, resource, batch]
      exporters: [otlp_http/prometheus]
    logs:
      receivers: [otlp, fluent_forward]
      processors: [memory_limiter, groupbyattrs/container, transform/container-logs, attributes/scrub,
                   redaction, transform/redact-log-body, resource, batch]
      exporters: [otlp_http/loki]
```

The `debug` exporter that printed traces and logs since Step 19 is gone: they now have real homes.

> **THE TWO NEW LOG PROCESSORS, EXPLAINED**
> - `groupbyattrs/container`: the Docker engine sends every container's lines over one connection, so a batch
>   can mix services. This processor regroups lines by their Compose service label, and the transform then
>   names each group. The end-to-end test interleaved two services' lines in the same batches: 0 lines were
>   mislabelled. Setting the name on a mixed batch would have mislabelled them.
> - `transform/redact-log-body`: the redaction processor from Step 19 checks attributes, but a log line's
>   text is its *body*. This applies the same three patterns (JWT, API key, email) to the text. A test line
>   `login failed for carol@example.com, token eyJ…` was stored as `login failed for ****, token ****`.

### 4 · Ship every container's output

One shared logging block at the top of [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml),
used by every service except the Collector itself (it can't ship its own logs to itself; it keeps Docker's
default local log):

```yaml
x-logging: &to-collector
  driver: fluentd
  options:
    fluentd-address: 127.0.0.1:24224          # the Collector's published port (the Docker engine connects)
    fluentd-async: "true"                     # never block a container because the Collector is down
    labels: com.docker.compose.service        # attach the Compose service name to every line
    tag: docker
```

Every service except `otel-collector` gets one line:

```yaml
    logging: *to-collector
```

and the Collector publishes one more port, on localhost only:

```yaml
    ports:
      - "127.0.0.1:4317:4317"
      - "127.0.0.1:4318:4318"
      - "127.0.0.1:13133:13133"
      - "127.0.0.1:24224:24224"               # Step 21: container logs from the Docker engine
```

> **IN PLAIN ENGLISH · WHY 127.0.0.1 AND NOT otel-collector?**
> The log driver runs inside the Docker *engine*, not inside a container on the Compose network, so it can't
> resolve the name `otel-collector`. It connects to the port the Collector publishes on the host's loopback.

> **TIP · DOCKER COMPOSE LOGS KEEPS WORKING**
> With a remote driver, Docker still keeps a local copy of recent output (dual logging). Quick looks with
> `docker compose logs rag-api` (or `just logs rag-api`) work as before, and Loki holds the searchable 7-day
> history.

### 5 · Run Tempo and Loki; let Prometheus accept generated metrics and exemplars

Added to the Compose file (images pinned by tag and digest, the Step 9 method):

```yaml
  tempo:
    image: grafana/tempo:3.0.3@sha256:0296560ac66f8a3600d7fb3014a52c189d4d9c3549ad6ff441bf2409855d68d5
    command: ["-target=all", "-config.file=/etc/tempo.yaml"]
    volumes:
      - ../config/tempo/tempo.yaml:/etc/tempo.yaml:ro
      - tempo-data:/var/tempo
    ports: ["127.0.0.1:3200:3200"]                            # query API, for curl checks; Grafana uses tempo:3200
    logging: *to-collector
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    restart: unless-stopped
    deploy: { resources: { limits: { memory: 1g, cpus: "1" } } }

  loki:
    image: grafana/loki:3.7.7@sha256:d70e4659623f3e109af669cae76fe2a5dd5be54e2298fe8aed380d982fbc2500
    command: ["-config.file=/etc/loki/loki.yaml"]
    volumes:
      - ../config/loki/loki.yaml:/etc/loki/loki.yaml:ro
      - loki-data:/loki
    ports: ["127.0.0.1:3100:3100"]
    logging: *to-collector
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    restart: unless-stopped
    deploy: { resources: { limits: { memory: 1g, cpus: "1" } } }

volumes:
  tempo-data:
  loki-data:
```

Prometheus gets two more flags:

```yaml
    command:
      # …Step 20 flags, plus:
      - --web.enable-remote-write-receiver         # Tempo's span metrics + service graph arrive here
      - --enable-feature=exemplar-storage          # keep the trace ids attached to metric points
```

and two more scrape jobs in [`infra/config/prometheus/prometheus.yml`](../../infra/config/prometheus/prometheus.yml),
so the existing `TargetDown` alert covers them:

```yaml
  - job_name: tempo                           # Step 21: trace storage health
    static_configs: [{ targets: ["tempo:3200"] }]

  - job_name: loki                            # Step 21: log storage health
    static_configs: [{ targets: ["loki:3100"] }]
```

> **WATCH OUT · REMOTE WRITE ACCEPTS DATA FROM ANYONE WHO CAN REACH IT**
> `--web.enable-remote-write-receiver` lets any client write metrics into Prometheus, real or fake. Keep
> Prometheus on the internal network and `127.0.0.1`, as we do. In production, put authentication in front
> of it.

### 6 · Connect everything in Grafana

The links between signals are data-source settings, provisioned as code in
[`infra/config/grafana/provisioning/datasources/datasources.yaml`](../../infra/config/grafana/provisioning/datasources/datasources.yaml)
(complete, updated). `$$` is a literal `$`: Grafana would otherwise read `$name` in a provisioning file as an
environment variable.

```yaml
  - name: Prometheus
    ...
    jsonData:
      timeInterval: 15s
      exemplarTraceIdDestinations:            # metric point -> its example trace in Tempo
        - name: trace_id
          datasourceUid: tempo

  - name: Tempo
    uid: tempo
    type: tempo
    url: http://tempo:3200
    jsonData:
      streamingEnabled: { search: true }
      serviceMap: { datasourceUid: prometheus }     # service graph from Tempo's generated metrics
      nodeGraph: { enabled: true }
      tracesToLogsV2:                         # span -> the log lines of the same request in Loki
        datasourceUid: loki
        filterByTraceID: true
        spanStartTimeShift: "-5m"
        spanEndTimeShift: "5m"
        tags: [{ key: service.name, value: service_name }]
      tracesToMetrics:                        # span -> that service's request rate in Prometheus
        datasourceUid: prometheus
        spanStartTimeShift: "-5m"
        spanEndTimeShift: "5m"
        tags: [{ key: service.name, value: service }]
        queries:
          - name: Request rate
            query: sum(rate(traces_spanmetrics_calls_total{$$__tags}[5m]))

  - name: Loki
    uid: loki
    type: loki
    url: http://loki:3100
    jsonData:
      maxLines: 1000
      derivedFields:                          # log line -> its trace (our JSON logs carry "trace_id")
        - name: TraceID
          matcherType: regex
          matcherRegex: '"trace_id": ?"(\w+)"'
          url: "$${__value.raw}"
          datasourceUid: tempo
          urlDisplayLabel: View trace
```

**The four links**

| From | To | Setting |
|---|---|---|
| A point on a Prometheus graph | Its example trace | `exemplarTraceIdDestinations` (label `trace_id`) |
| A span in Tempo | That request's log lines | `tracesToLogsV2` (trace id filter, `service.name` → `service_name`) |
| A span in Tempo | That service's request rate | `tracesToMetrics` (span metrics) |
| A log line in Loki | Its trace | `derivedFields`: a regex finds `"trace_id": "…"` in our JSON logs |

The regex was checked against a real rag-api log line. If you change the log format (Step 19's
`JsonFormatter`), update it too; `tests/test_loki_tempo.py` checks this automatically by formatting a log
line with the real `JsonFormatter` inside a span and running the regex over it.

### 7 · Bring it up and walk the journey

```bash
just up && just ps                                             # tempo and loki take ~15 s to become ready
curl -s localhost:3200/ready; echo                             # ready
curl -s localhost:3100/ready; echo                             # ready
just api-demo                                                  # sign in as alice; a few searches
```

In Grafana (<http://localhost:3000>):

1. **Explore → Prometheus**: query
   `histogram_quantile(0.95, sum by (le) (rate(rag_search_duration_seconds_bucket[5m])))` and switch on
   **Exemplars**. Dots appear on the line.
2. Click a dot → **Query with Tempo**. That request's trace opens: rag-api, OPA, LiteLLM, Postgres spans, with
   timings.
3. On the rag-api span → **Logs for this span**. Loki shows that request's log lines, and only those.
4. On a log line → **View trace**. You're back at the trace.
5. **Explore → Tempo → Service graph**. The boxes and arrows show who calls whom, with rates and error
   percentages.

> **TIP · USEFUL QUERIES**
>
> | Question | Query |
> |---|---|
> | Errors from rag-api in the last hour (LogQL) | `{service_name="rag-api"} \| json \| level="ERROR"` |
> | Everything about one request (LogQL) | `{service_name=~".+"} \|= "4bf92f35…"` |
> | Failed sign-ins in Keycloak's JSON logs (LogQL) | `{service_name="keycloak"} \|= "LOGIN_ERROR"` |
> | Slow searches (TraceQL) | `{resource.service.name="rag-api" && name="POST /v1/search" && duration > 1s}` |
> | Searches where the post-check dropped something (TraceQL) | `{name="rag.authz.post_check" && span.rag.dropped > 0}` |
> | Who calls whom (PromQL) | `sum by (client, server) (rate(traces_service_graph_request_total[5m]))` |

### 8 · What the end-to-end test proved

Before the chapter was written, the whole path ran for real: Tempo 3.0.3, Loki 3.7.7, Prometheus 3.13.4, the
Collector, OPA with tracing and rag-api. Log lines were sent exactly as Docker's log driver sends them. The
checks:

- **Trace from a log line**: the `trace_id` in rag-api's "query/policy mismatch" error line opened its trace
  in Tempo, with 10 spans from rag-api and OPA. A TraceQL search found the `rag.authz.post_check` spans.
- **Logs from a trace**: `{service_name="rag-api"} |= "<that trace id>"` returned exactly that request's
  lines; `| json | level="ERROR"` found the error.
- **Masking in log text**: a Keycloak line with an email and a token was stored as
  `login failed for ****, token ****`.
- **No mislabelling**: two services' lines, interleaved in the same batches, arrived under the right
  `service_name`, with 0 mixed up.
- **Exemplars**: the search-latency histogram carried a trace id that opened a real trace in Tempo.
- **Generated metrics**: span metrics for `rag-api` and `opa`, and service-graph edges `user → rag-api` and
  `rag-api → opa`.
- **No deprecation warnings** from the Collector after the two renames.

The same checks were repeated for this repository; see *Notes for this repository* below.

### 9 · Record the decision

```bash
just adr "Use Tempo and Loki for traces and logs"
```

The result is [`docs/adr/0021-use-tempo-and-loki-for-traces-and-logs.md`](../adr/0021-use-tempo-and-loki-for-traces-and-logs.md):
Tempo 3 single-process with 7-day retention and a metrics generator; Loki with tsdb v13 and enforced 7-day
retention; the fluentd driver instead of a socket-mounting agent; masking in attributes *and* log bodies;
alternatives (Jaeger, OpenSearch/Elastic, Promtail/Alloy with `docker.sock`, SaaS); consequences; and when to
revisit (object storage and multi-node, multi-tenancy, longer retention for compliance; Step 23's audit log is
separate and tamper-evident).

```bash
git add -A
git commit -m "feat(observability): Tempo + Loki, Docker log driver to the Collector, exemplars and linked Grafana data sources"
git push -u origin feat/loki-tempo
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Two-minute investigations**: metric → exemplar → trace → logs → back, all by clicking.
- Every container's logs in one place, searchable for 7 days, surviving restarts.
- **No privileged log agent**: the Docker engine pushes; no socket is mounted.
- Secrets masked before storage, in attributes and in the log text itself.
- Metrics for free from traces: request rate, errors, latency per service, and a live service map.
- Cheap storage: Loki and Tempo index little and compress well.
- Vendor-neutral: OTLP in, OTLP out; swap backends in the Collector.

## Drawbacks and risks

- Two more stateful services to size, back up (or accept losing) and monitor (`TargetDown` covers them).
- Local disk only: a full disk stops ingestion. Retention and size limits matter; production uses object
  storage.
- Loki searches scan text: a query without a narrow label selector over a long range is slow. Always start
  with `{service_name="…"}`.
- The async log driver can drop lines if the Collector is down long enough. Acceptable for operational logs;
  never for audit records (Step 23).
- Masking is pattern-based: unusual secret formats slip through. The rule remains: don't log secrets or
  content.
- No login on Loki, Tempo or Prometheus: internal network and `127.0.0.1` only.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Tempo + Loki (our choice) | Grafana's low-cost trace and log stores | Self-hosted, Grafana-centred, cost-sensitive |
| Jaeger | CNCF trace backend with its own UI | Existing Jaeger expertise, or no Grafana |
| OpenSearch / Elasticsearch | Full-text log search and analytics | Heavy ad-hoc search, security analytics (SIEM) |
| ClickHouse-based (SigNoz, HyperDX, ClickStack) | All signals in one column store | One backend for everything, SQL-like queries |
| Grafana Alloy / Fluent Bit / Vector | Log and telemetry agents | Kubernetes node agents, complex routing |
| SaaS (Datadog, Honeycomb, Grafana Cloud, cloud-native tools) | Managed storage and UI | No appetite to operate storage |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local platform | Single-process Tempo + Loki on local disk (this step) |
| Production, one cluster | Tempo and Loki on object storage; Kafka-based Tempo when scaling out |
| Kubernetes | Collector or Alloy as a node agent reading container log files; no Docker socket |
| Security analytics or audit search | OpenSearch or a SIEM, fed by the same Collector |
| Strict privacy regime | Short retention, masking in the Collector, access-controlled Grafana folders |

## Common mistakes

- High-cardinality Loki labels (user, trace or request ids).
- Retention configured but never enforced (`compactor.retention_enabled` missing).
- Mounting the Docker socket into a log agent "just for logs".
- Masking attributes but not the log body, where most secrets actually end up.
- Free-text logs without a trace id, so logs and traces can't be joined.
- Querying Loki without a label selector over days of data.
- Copying Tempo 2 configs (`ingester`, `compactor` blocks) into Tempo 3.
- Ignoring deprecation warnings until a Collector upgrade removes the old name.

## Done when

- [ ] `tempo` (3.0.x) and `loki` (3.7.x) are running, `/ready` returns `ready`, and both have 7-day retention
- [ ] Every service except the Collector uses the `to-collector` logging block; `docker compose logs` still works
- [ ] Loki shows `service_name` values for your services; a Keycloak or rag-api line containing a token shows `****`
- [ ] A rag-api trace in Tempo includes spans from OPA and LiteLLM
- [ ] In Grafana: an exemplar opens its trace, "Logs for this span" shows that request's lines, and "View trace" returns
- [ ] The service graph shows `user → rag-api → opa` and `rag-api → litellm`
- [ ] The Collector logs no deprecation warnings
- [ ] ADR-0021 is merged through a PR

## Recap

> **RECAP**
> Traces now live in Tempo and logs in Loki, each kept for 7 days and fed through the Collector, which masks
> secrets even inside log text.
>
> Every container's output reaches it via Docker's own log driver, so no privileged agent and no Docker
> socket. Lines are grouped and named by service, and the test showed none mislabelled.
>
> Grafana links the signals: exemplar → trace → logs → trace. Tempo also turns traces into span metrics and a
> service graph.
>
> That completes the operational view. The next steps add the LLM-specific view: Step 22, Langfuse, records
> prompts, retrieved context and answers for debugging and evaluation, under access control and retention
> rules.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/config/tempo/tempo.yaml` | Tempo 3 single-process config: OTLP gRPC from the Collector, local storage, 7-day retention, metrics generator remote-writing span metrics and the service graph (with exemplars) to Prometheus. |
| `infra/config/loki/loki.yaml` | Loki config: single tenant, tsdb v13 schema, 7-day retention enforced by the compactor, structured metadata for OTLP attributes. |
| `infra/config/otel-collector/config.yaml` | Updated: `fluent_forward` receiver for container logs, grouping and naming by Compose service, log-body masking, `otlp_grpc/tempo` and `otlp_http/loki` exporters replacing `debug`. |
| `infra/compose/compose.yaml` | Updated: the `x-logging: &to-collector` fluentd block on every service except the Collector, the Collector's `24224` port, the `tempo` and `loki` services and volumes, Prometheus's remote-write and exemplar flags. |
| `infra/config/prometheus/prometheus.yml` | Updated: `tempo` and `loki` scrape jobs. |
| `infra/config/grafana/provisioning/datasources/datasources.yaml` | Updated (complete): Tempo and Loki data sources and the four cross-links (exemplars, traces-to-logs, traces-to-metrics, derived fields). |
| `tests/test_loki_tempo.py` | New tests: configs, masking regexes run over a sample line, logging block on every service, no Docker socket, pinned images, Grafana links, the derived-field regex against a real `JsonFormatter` line, ADR; Tempo and Loki validate their own configs when Docker is available; live readiness checks. |
| `tests/test_otel_collector.py`, `tests/test_monitoring.py` | Updated for this step's Collector pipelines and port, and Prometheus's new flags and scrape jobs. |
| `docs/adr/0021-use-tempo-and-loki-for-traces-and-logs.md` | ADR-0021, plus its row in `docs/adr/README.md`. |
| `docs/steps/step-21-loki-tempo-traces-and-logs.md` | This write-up. |

## Notes for this repository

- **Image digests.** The guide prints `@sha256:<digest>`; the real digests were taken from pulling
  `grafana/tempo:3.0.3` (`sha256:0296560a…`) and `grafana/loki:3.7.7` (`sha256:d70e4659…`).
- **Deprecated exporter names.** Step 20 in this repo already used `otlp_http/prometheus`; this step adds the
  `otlp_grpc/tempo` and `otlp_http/loki` exporters and removes `debug`. The Collector started with no
  deprecation warnings.
- **Validated here (Linux container, Docker):**
  - `tempo -config.verify`, `loki -verify-config` and `otelcol validate` all accept the committed configs
    (the first two also run as tests in `tests/test_loki_tempo.py`).
  - A scratch stack of the real images (Tempo 3.0.3, Loki 3.7.7, Prometheus 3.13.4 with the committed
    `prometheus.yml` and the two new flags, Collector 0.162.0, Grafana 13.2.3 with the committed
    provisioning), started with `cap_drop: ALL` as in Compose. Both `/ready` endpoints answered `ready`.
  - A trace was posted to the Collector over OTLP (rag-api server span, an OPA client call, an OPA server
    span, a `rag.authz.post_check` span with `rag.dropped=4`). Tempo returned it by id with the
    `authorization` attribute deleted and an email attribute shown as `****`; both TraceQL queries above found
    it.
  - Two containers logging through Docker's real `fluentd` driver (the options from `x-logging`) with
    different `com.docker.compose.service` labels, running at the same time: Loki listed `service_name`
    values `keycloak` and `rag-api`, 6 lines each, 0 mislabelled; the Keycloak line with an email, a JWT and an
    `sk-` key was stored as `LOGIN_ERROR login failed for ****, token **** key ****`;
    `{service_name="rag-api"} |= "<trace id>" | json | level="ERROR"` returned exactly the error line.
  - Prometheus received `traces_service_graph_request_total` with edges `user → rag-api` and `rag-api → opa`,
    `traces_spanmetrics_calls_total` for both services, exemplars carrying the trace id, and the `tempo` and
    `loki` scrape targets were `up`.
  - Grafana reported the Prometheus, Tempo ("Streaming test succeeded") and Loki data sources healthy, and
    the provisioned links had `$$` turned into `$` as intended.
- **Not run here:** the full `just up` stack and the click-through in Grafana's UI (it needs the Mac's native
  models, the decrypted secrets and a browser). The `user → rag-api → litellm` edge appears once real searches
  go through LiteLLM.
- **Exemplar label names.** Our rag-api histograms arrive in Prometheus over OTLP with exemplars labelled
  `trace_id`, which is what `exemplarTraceIdDestinations` uses. Tempo's own generated span metrics label their
  exemplars `traceID`; that's why the guide's walk-through starts from `rag_search_duration_seconds`.
- **No new `just` recipes** were added: the chapter uses the existing `just up`, `just ps`, `just logs` and
  `just api-demo`.
