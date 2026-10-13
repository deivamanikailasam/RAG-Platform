# Step 19 · OpenTelemetry Collector: one pipe for traces, metrics and logs

*Step 19 of 38 · Phase E · Observability*

## At a glance

| | |
|---|---|
| **Goal** | Make the platform observable. Every service sends traces (what happened inside each request), metrics (numbers over time) and logs (events) in one standard format, OpenTelemetry (OTLP), to a single Collector. The Collector cleans the data (removes secrets, masks tokens and emails), labels it and forwards it to whichever backends we choose. A whole search, across rag-api, OPA, LiteLLM, the embedder and Postgres, becomes one connected trace. |
| **Time** | About 2 hours. |
| **You'll end up with** | An `otel-collector` service (contrib 0.162.x) with memory protection, secret scrubbing and redaction, batching and a health check; a shared `rag_common.telemetry` module: one call sets up traces, metrics and JSON logs carrying the trace id, and flushes on shutdown; rag-api instrumented: automatic spans for HTTP, OPA calls, gateway calls and SQL, plus RAG spans (policy decision, retrieval, embedding, post-check) and four metrics; LiteLLM, OPA and Keycloak sending their own spans into the same traces; 5 new tests proving one trace per search, useful attributes, working metrics, and no token or question text in any span; ADR-0019. |
| **New words** | Observability, telemetry, signal, trace, span, parent/child span, span attributes, resource, context propagation, traceparent (W3C Trace Context), metric (counter, histogram), structured logging, log–trace correlation, OTLP, Collector, receiver / processor / exporter / pipeline, instrumentation (automatic vs manual), semantic conventions, GenAI conventions, sampling (head / tail), cardinality, redaction. |

## The big idea

> **ANALOGY · THE PARCEL TRACKING SYSTEM**
> When a parcel goes missing, a good courier company doesn't ask every depot to search its notebooks. Each
> parcel has a tracking number, and every depot scans it on the way in and out:
>
> - **Trace:** the full journey of one parcel, depot by depot, with times.
> - **Metrics:** the control-room wall: parcels per hour, average delivery time, how many are late.
> - **Logs:** the notes a driver writes: "address unclear, left at reception".
>
> Because every scan, number and note carries the same tracking number, you can go from "deliveries are slow
> today" (metric) to "this parcel waited 3 hours at depot B" (trace) to "the sorting machine at B jammed" (log) in
> three clicks.
>
> OpenTelemetry is the scanning standard. The Collector is the central sorting office every scan goes through
> before it's stored.

```text
        Metrics                       Traces                           Logs
   Is something wrong?          Where is it wrong?               Why is it wrong?

   numbers over time            one request, step by step        individual events
   searches/s · p95 latency     which service, which call,       with details and errors
   errors · tokens · cost       how long each took               (JSON lines)

                        Glued together by the trace id
        a spike on a dashboard → an example trace → the log lines of that exact request
```

*The three signals and the questions they answer. Metrics say something is wrong, traces say where, logs say
why, and the trace id connects all three.*

## What we're doing

1. Run the OpenTelemetry Collector: receive OTLP, protect memory, scrub and redact secrets, label, batch, export.
2. Write `rag_common.telemetry`: tracer and meter setup from standard `OTEL_*` variables, JSON logs with trace
   ids, flush on shutdown.
3. Instrument rag-api: automatic HTTP, httpx and SQL spans, plus RAG-specific spans and metrics.
4. Test the telemetry itself: one trace, the right attributes, metrics, and no secrets or question text.
5. Turn on tracing in LiteLLM, OPA and Keycloak so their spans join our traces.
6. Watch a request flow through, then record ADR-0019.

## Why we're doing this

> **WHY THIS MATTERS**
> A RAG answer passes through many services: authentication, policy, embedding, vector search, reranking
> (later), generation (later). When someone says "it's slow" or "it gave a weird answer", you need to know which
> step, in which request, without guessing.
>
> LLM systems add their own questions:
>
> - How many tokens did this cost?
> - How long did the model take to start answering?
> - Which documents were retrieved?
>
> Observability built in now, while the platform is small, is cheap. Bolted on after an incident, it is expensive
> and always incomplete.

| Need | How this step meets it |
|---|---|
| Find the slow step in one request | Traces with a span per step, across services |
| Spot problems early | Metrics: request counts, latency histograms, policy decisions, dropped documents |
| Understand an error | JSON logs carrying the trace id |
| Follow a request across services | W3C `traceparent` header, propagated automatically |
| Never leak secrets or personal data | No content in spans by design; Collector deletes risky keys and masks token- and email-like values |
| Change backends without touching code | Services speak OTLP; only the Collector's config names the destinations |
| Survive overload | `memory_limiter` first, `batch` last |

> **IN A COMPANY**
> OpenTelemetry is the CNCF standard for telemetry, supported by every major vendor (Datadog, Dynatrace,
> New Relic, Honeycomb, Grafana, Elastic, Splunk) and all three clouds. Companies standardise on it so they can
> switch vendors without re-instrumenting and run a Collector layer that enforces data governance: no secrets,
> no personal data, consistent labels.
>
> For AI systems, the GenAI semantic conventions (`gen_ai.*` attribute names) are becoming the common
> language for model calls, so tools like Langfuse (Step 22) and vendor dashboards understand each other.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Span | One timed step: name, start, duration, status and attributes. Spans nest: parent and children. |
| Trace | All the spans of one request, across all services, sharing one trace id. |
| Attributes | Key–value facts on a span, e.g. `rag.candidates = 5`. |
| Resource | Facts about the process sending data: `service.name`, version, environment. |
| Context propagation | Passing the trace id to the next service, in the `traceparent` HTTP header (W3C standard). |
| Metric: counter / histogram | A number that only goes up (requests) / a distribution of values (latencies), from which p50/p95/p99 are computed. |
| Structured logging | Logs as JSON objects instead of free text, so they can be searched by field. |
| OTLP | The OpenTelemetry protocol for sending all three signals (gRPC on 4317, HTTP on 4318). |
| Collector | A service that receives, processes and exports telemetry. Receivers → processors → exporters form a pipeline. |
| Automatic vs manual instrumentation | Libraries that create spans for you (HTTP, SQL) vs spans you add for your own logic (retrieval). |
| Semantic conventions | Agreed attribute names (`http.request.method`, `gen_ai.request.model`) so every tool understands them. |
| Sampling | Keeping only some traces. Head sampling decides at the start; tail sampling decides after seeing the whole trace (e.g. keep all errors). |
| Cardinality | How many distinct values a label has. User ids as metric labels create millions of series: never do that. |

> **IN PLAIN ENGLISH**
> *Observability* is being able to answer new questions about a running system from the outside, without
> shipping new code. *Telemetry* is the data that makes it possible, and each kind (traces, metrics, logs) is
> called a *signal*. *Redaction* means masking a value (`****`) so the record survives but the secret doesn't.

### What a trace shows you

```text
ONE SEARCH = ONE TRACE (trace id 4bf9…), times in ms         0    30    60    90   120   150   180
POST /v1/search                      rag-api                 |████████████████████████████████████|
  rag.authz.decide                   rag-api                 |██|
    POST opa …/decision              opa                      |█|
  rag.retrieve                       rag-api                    |████████████████████████████|
    embeddings embedder              rag-api                    |██████████████████████|   ← the slow part is obvious:
      litellm_request                litellm                     |█████████████████████|     embedding, not the database
        POST embedder (TEI)          litellm                      |███████████████████|
    SELECT rag.chunks …              rag-db                                             |████|
  rag.authz.post_check               rag-api                                                 |█|
```

*One search as a trace waterfall (illustrative timings). Each bar is a span; indentation shows parent and child.
The policy decision, embedding call (through LiteLLM to the embedder), database query and post-check are all
visible, and the slow step stands out immediately.*

### Where telemetry goes

```text
  rag-api       SDK: traces · metrics ──┐        OpenTelemetry Collector
  litellm       otel callback ──────────┤   receive        process (in order)       export
  keycloak      built-in tracing ───────┼─► OTLP           1. memory_limiter        debug (today)  ─► Prometheus  metrics · Step 20
  opa           distributed_tracing ────┤   gRPC :4317     2. attributes/scrub                     ─► Tempo       traces  · Step 21
  later: workers, evals (same SDK) ─────┘   HTTP :4318     3. redaction                            ─► Loki        logs    · Step 21
                                                           4. resource                             ─► any vendor  Datadog, Honeycomb…
                                                           5. batch
                                     one config file · no code changes in services
```

*Every service sends OTLP to one Collector. It receives, processes in a fixed order (protect memory, scrub,
redact, label, batch) and exports. Today it prints to its own log; Steps 20–21 add Prometheus, Tempo and Loki by
editing only this config.*

> **WATCH OUT · TELEMETRY IS A DATA-LEAK CHANNEL**
> Traces and logs are copied into more systems, kept longer and read by more people than your database. A
> question like "What is Carol Chen's salary?" is personal data. A token in a span is a working credential.
> Our rules:
>
> 1. **Never put content in telemetry by default.** We record the question's length, not its text.
> 2. **Never record secrets.** Instrumentations don't capture headers unless told to.
> 3. **The Collector enforces it anyway:** it deletes risky keys and masks token- and email-shaped values from any
>    service, including ones you didn't write.
>
> Capturing prompts and answers for debugging is sometimes needed. That happens in a controlled tool with access
> control and retention: Langfuse, Step 22.

## How to do it

On the Mac, in the project folder:

```bash
cd ~/dev/rag-platform
git switch -c feat/otel
```

### 1 · The Collector

There are several Collector distributions:

- **core:** a minimal set of components.
- **contrib:** everything, including the `redaction` processor we need.
- **your own build**, made with the OpenTelemetry Collector Builder, containing only the components you use.
  That's the production choice, because it has a smaller attack surface (Phase G).

We use contrib, pinned (0.162.0 at the time of writing). The config is
[`infra/config/otel-collector/config.yaml`](../../infra/config/otel-collector/config.yaml):

```yaml
# OpenTelemetry Collector: the platform's single entry point for traces, metrics and logs.
# Pipeline per signal:   receivers -> processors (in order) -> exporters

extensions:
  health_check:                                  # GET :13133/ -> 200 when the pipelines are running
    endpoint: 0.0.0.0:13133

receivers:
  otlp:                                          # the standard OpenTelemetry protocol
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }
      http: { endpoint: 0.0.0.0:4318 }

processors:
  # 1. FIRST: refuse data instead of crashing when memory runs short.
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20

  # 2. Remove things that must never be stored, whatever a service sends by mistake.
  attributes/scrub:
    actions:
      - { key: http.request.header.authorization, action: delete }
      - { key: http.request.header.cookie, action: delete }
      - { key: db.query.parameters, action: delete }
      - { key: gen_ai.input.messages, action: delete }     # prompt content (opt-in only, Project 9)
      - { key: gen_ai.output.messages, action: delete }    # answer content
  redaction:
    allow_all_keys: true                         # keep every attribute…
    blocked_values:                              # …but mask any VALUE that looks like a secret
      - "eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+"   # JWTs
      - "sk-[A-Za-z0-9_-]{16,}"                                  # LiteLLM / OpenAI-style keys
      - "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}"        # email addresses
    summary: info                                # count what was masked, in redaction.* attributes

  # 3. Label everything with where it came from.
  resource:
    attributes:
      - { key: deployment.environment.name, value: dev, action: upsert }

  # 4. LAST: send in batches (far fewer, larger requests).
  batch:
    timeout: 2s
    send_batch_size: 1024

exporters:
  debug:                                         # print to the Collector's own log; real backends come next:
    verbosity: basic                             #   Prometheus (Step 20), Tempo + Loki (Step 21)

service:
  extensions: [health_check]
  telemetry:
    logs: { level: info, encoding: json }
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, attributes/scrub, redaction, resource, batch]
      exporters: [debug]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, resource, batch]
      exporters: [debug]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, attributes/scrub, redaction, resource, batch]
      exporters: [debug]
```

> **WHY THIS PROCESSOR ORDER**
>
> 1. **`memory_limiter` first:** if the Collector is about to run out of memory, it refuses new data (senders
>    retry) rather than crashing and losing everything.
> 2. **Scrub and redact before anything is stored or forwarded:** deletion of known-risky keys, then pattern
>    masking of values. The `summary` setting adds `redaction.masked.count`, so you can see that masking happened
>    without seeing what was masked.
> 3. **`resource`:** labels everything with the environment, so dev and prod data never mix.
> 4. **`batch` last:** groups data into fewer, larger sends.
>
> Metrics skip scrubbing and redaction: they carry numbers and short labels, never content.

Let the Collector check its own config before you run it:

```bash
docker run --rm -v "$PWD/infra/config/otel-collector:/cfg:ro" \
  otel/opentelemetry-collector-contrib:0.162.0 validate --config=/cfg/config.yaml && echo VALID
```

Then add the service to [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml):

```yaml
services:
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.162.0@sha256:39923a8e431bd1f57be82411999d389fcfe40857492e4365456d97a4c1f74be6
    command: ["--config=/etc/otelcol/config.yaml"]
    volumes:
      - ../config/otel-collector/config.yaml:/etc/otelcol/config.yaml:ro
    ports:
      - "127.0.0.1:4317:4317"                 # OTLP gRPC: native macOS processes and scripts can send too
      - "127.0.0.1:4318:4318"                 # OTLP HTTP
      - "127.0.0.1:13133:13133"               # health check
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    restart: unless-stopped
    deploy:
      resources:
        limits: { memory: 512m, cpus: "1" }   # memory_limiter works as a percentage of this
```

The image contains only the Collector (no shell), so there's no container healthcheck. Check it from the host
instead: `curl -s localhost:13133/` returns status JSON. Services that send telemetry never fail when the Collector
is down; their exporters drop data and retry.

> **TIP**
> `memory_limiter` with `limit_percentage: 80` reads the container's memory limit (512 MB), so the Collector
> starts refusing data at about 409 MB with a 102 MB spike allowance. You can see those exact numbers in its first
> log lines ("Memory limiter configured").

### 2 · Shared telemetry setup

```bash
uv add --package rag-common opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
uv add --package rag-api opentelemetry-instrumentation-fastapi \
  opentelemetry-instrumentation-httpx opentelemetry-instrumentation-psycopg
```

The module is [`libs/rag-common/src/rag_common/telemetry.py`](../../libs/rag-common/src/rag_common/telemetry.py).
Its essentials:

```python
class JsonFormatter(logging.Formatter):
    """One JSON object per line, carrying the current trace and span id."""

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


def setup_telemetry(service_name, *, span_exporter=None, metric_reader=None) -> Callable[[], None]:
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return lambda: None
    resource = Resource.create({"service.name": service_name})   # + OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES
    tracer_provider = TracerProvider(resource=resource)           # sampler from OTEL_TRACES_SAMPLER
    if span_exporter is None:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)
    reader = metric_reader or PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    def shutdown() -> None:
        tracer_provider.shutdown()   # flushes pending spans
        meter_provider.shutdown()    # exports the final metric values

    return shutdown
```

The standard variables it understands:

```text
OTEL_SERVICE_NAME=rag-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=dev,service.version=0.1.0
OTEL_TRACES_SAMPLER=parentbased_traceidratio        OTEL_TRACES_SAMPLER_ARG=1.0
OTEL_SDK_DISABLED=true                               (switch everything off)
```

> **READING THE SETUP**
>
> - **Configuration through `OTEL_*` variables:** these are the standard names every OpenTelemetry SDK understands
>   (Python, Java, Go…). Operations teams configure all services the same way.
> - **Resource:** `service.name` plus anything in `OTEL_RESOURCE_ATTRIBUTES` (version, environment) is attached to
>   every span and metric.
> - **Batch processor in real runs** (sends in the background, never slows requests); **simple processor in tests**
>   (immediate, so tests can check right away).
> - **Metrics every 15 s** by default; the dashboard's resolution (Step 20).
> - **The returned `shutdown()`:** when the service stops, buffered spans and the last metric values are flushed.
>   Without it, every restart silently loses the final seconds of telemetry. The end-to-end test for this step found
>   exactly that: no metrics arrived until shutdown flushing was added.
> - **JSON logs with `trace_id`:** logs go to stdout (the container platform collects them; Loki reads them in
>   Step 21), and each line can be joined to its trace.

### 3 · Instrument rag-api

Automatic instrumentation covers the plumbing:

- **FastAPI:** one server span per request.
- **httpx:** client spans for calls to OPA and the gateway, which also inject `traceparent`, so the next service
  continues the same trace. (The OpenAI SDK used for the gateway is built on httpx, so it's covered too.)
- **psycopg:** one span per SQL statement. Statement text only, never the parameter values.

Manual spans and metrics cover what only we understand: the RAG steps. In
[`services/rag-api/src/rag_api/main.py`](../../services/rag-api/src/rag_api/main.py):

```python
tracer = trace.get_tracer("rag_api")
meter = metrics.get_meter("rag_api")

# Metrics: a few numbers you'd put on a dashboard or alert on (Step 20).
SEARCHES = meter.create_counter("rag.search.requests", unit="{request}", description="Searches by outcome")
SEARCH_TIME = meter.create_histogram("rag.search.duration", unit="s", description="End-to-end search time")
DECISIONS = meter.create_counter("rag.authz.decisions", unit="{decision}", description="Policy decisions")
DROPPED = meter.create_counter("rag.search.dropped_documents", unit="{document}",
                               description="Query/policy mismatches (should be 0)")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    shutdown_telemetry = setup_telemetry("rag-api")
    HTTPXClientInstrumentor().instrument()  # calls to OPA and the gateway: spans + traceparent header
    PsycopgInstrumentor().instrument()      # one span per SQL statement (text only, never parameters)
    yield
    shutdown_telemetry()                    # on stop: send what's still buffered


app = FastAPI(title="rag-api", version="0.1.0", lifespan=lifespan)
# One server span per request. Excluded: health checks (most of the traffic, no value) and the
# tiny internal "receive"/"send" spans (noise).
FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz", exclude_spans=["receive", "send"])
```

`authorize(action)` wraps the policy call in a `rag.authz.decide` span with `rag.authz.action` and
`rag.authz.allow`, and counts the decision in `rag.authz.decisions` (labels: `action`, `allow`). The search
endpoint times the whole search and wraps its two stages:

```python
started, outcome = time.perf_counter(), "error"
try:
    with tracer.start_as_current_span("rag.retrieve") as span:
        # Facts about the request, never its content: only the question's LENGTH is recorded.
        span.set_attributes({
            "enduser.id": p.subject,
            "rag.query.chars": len(req.query),
            "rag.k": req.k,
            "rag.filter.classifications": sorted(f.classifications),
            "rag.filter.group_count": len(f.groups),
        })
        candidates = backend.search(...)
        span.set_attribute("rag.candidates", len(candidates))
    with tracer.start_as_current_span("rag.authz.post_check") as span:
        allowed = policy.readable(p, [c.ref for c in candidates])
        dropped = [c.ref.id for c in candidates if c.ref.id not in allowed]
        span.set_attributes({"rag.returned": len(candidates) - len(dropped), "rag.dropped": len(dropped)})
    if dropped:
        DROPPED.add(len(dropped))
    outcome = "ok"
    return [c.hit for c in candidates if c.ref.id in allowed]
finally:
    SEARCHES.add(1, {"outcome": outcome})
    SEARCH_TIME.record(time.perf_counter() - started, {"outcome": outcome})
```

In [`services/rag-api/src/rag_api/search.py`](../../services/rag-api/src/rag_api/search.py) the gateway call gets a
GenAI span named the OpenTelemetry way (`"{operation} {model}"`). The HTTP call inside carries the trace id to
LiteLLM, which continues the same trace:

```python
with tracer.start_as_current_span(
    "embeddings embedder",
    kind=trace.SpanKind.CLIENT,
    attributes={"gen_ai.operation.name": "embeddings", "gen_ai.request.model": "embedder"},
) as span:
    emb = self._gw.embeddings.create(model="embedder", input=[INSTRUCTION + query], user=user)
    span.set_attribute("gen_ai.usage.input_tokens", emb.usage.prompt_tokens)
```

> **WHAT WE RECORD, AND WHAT WE DELIBERATELY DON'T**
>
> | Recorded | Why | Not recorded | Why not |
> |---|---|---|---|
> | `rag.query.chars` | Long questions behave differently | The question text | Personal or confidential content |
> | `enduser.id` (the `sub`) | Find all traces for a complaint | Username, email | A stable pseudonymous id is enough |
> | `rag.filter.classifications`, group count | Explain "why no results?" | The group names | They can reveal org structure |
> | `rag.candidates`, `rag.returned`, `rag.dropped` | Retrieval health; dropped should be 0 | Document titles | Can be sensitive |
> | `gen_ai.request.model`, `gen_ai.usage.input_tokens` | Cost and model behaviour | Embedding vectors | Large, and can leak content |

> **WATCH OUT · NEVER PUT USER IDS IN METRIC LABELS**
> `enduser.id` is fine on spans: each trace is one record. On metrics it would create one time series per user:
> thousands of series, slow dashboards, large bills. That's the cardinality problem. Metric labels must have a
> small, fixed set of values, like `outcome=ok|error` or `action=search|admin:ping`.

### 4 · Test the telemetry itself

Telemetry is code that can break silently: a missing span, a leaked token. The tests in
[`services/rag-api/tests/test_telemetry.py`](../../services/rag-api/tests/test_telemetry.py) use in-memory
exporters, so they're fast and need no Collector:

| Test | What it proves |
|---|---|
| `test_one_trace_with_every_stage` | `POST /v1/search`, `rag.authz.decide`, `rag.retrieve` and `rag.authz.post_check` all exist, share one trace id, and the RAG spans are children inside it. |
| `test_useful_attributes` | `rag.candidates == 1`, `rag.query.chars == len(question)`, `enduser.id` is the `sub`, the decision was `allow`, nothing was dropped. |
| `test_no_token_and_no_question_text_in_any_span` | Sends "What is the salary of Carol Chen?" and fails if "Carol" or the bearer token appears in any span name or attribute. |
| `test_metrics_count_searches` | `rag.search.requests`, `rag.search.duration` and `rag.authz.decisions` exist and a successful search was counted with `outcome=ok`. |
| `test_log_lines_carry_the_trace_id` | A JSON log line written inside a span carries that span's trace id. |

```bash
just check
```

> **WHAT YOU SHOULD SEE**
>
> - pytest: 31 passed in the guide's own count (the 26 from Step 18, plus 5 telemetry tests). This repository
>   has more tests around them; see "Notes for this repository".
> - The leak test: it sends a question containing a person's name and fails if that name, or the token, appears
>   in any span attribute or name.

### 5 · Join the other services into the same traces

**rag-api** (Compose: environment additions):

```yaml
      OTEL_SERVICE_NAME: rag-api
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
      OTEL_RESOURCE_ATTRIBUTES: service.version=0.1.0
      OTEL_TRACES_SAMPLER: parentbased_traceidratio
      OTEL_TRACES_SAMPLER_ARG: "1.0"            # keep every trace in dev; lower in production
```

**LiteLLM** has a built-in OpenTelemetry callback. It continues the caller's trace from the `traceparent` header,
so the gateway's spans appear under rag-api's embedding span. Message logging is switched off, so prompts and
answers never go into traces. In [`infra/config/litellm/config.yaml`](../../infra/config/litellm/config.yaml):

```yaml
litellm_settings:
  # …existing settings…
  callbacks: ["otel"]

callback_settings:
  otel:
    message_logging: false      # spans keep model, timing, tokens and cost; never the content
```

and in Compose (litellm: environment):

```yaml
      OTEL_EXPORTER: otlp_http
      OTEL_ENDPOINT: http://otel-collector:4318
      OTEL_SERVICE_NAME: litellm
```

**OPA** traces each decision. With the `traceparent` header that rag-api's httpx instrumentation sends, OPA's spans
join the request's trace (Compose, opa: add to `command`):

```yaml
      - --set=distributed_tracing.type=grpc
      - --set=distributed_tracing.address=otel-collector:4317
      - --set=distributed_tracing.service_name=opa
```

**Keycloak** traces sign-ins and token requests (Compose, keycloak: environment):

```yaml
      KC_TRACING_ENABLED: "true"
      KC_TRACING_ENDPOINT: http://otel-collector:4317
```

> **NOT EVERYTHING SPEAKS OPENTELEMETRY (YET)**
>
> - mlx-lm and TEI run natively on macOS and don't emit traces. LiteLLM's span around each call measures them from
>   the outside, which is enough to see their latency.
> - Postgres, Qdrant, OpenSearch, SeaweedFS and Valkey expose metrics in Prometheus format; Step 20 collects those.
> - The client-side spans (psycopg, httpx) already show how long each database call took, from the caller's point
>   of view.

Start everything and watch a request flow through:

```bash
just up && just ps
curl -s localhost:13133/ | jq .status                     # "Server available"
just api-demo                                             # make some traffic (sign in as alice)
docker compose -f infra/compose/compose.yaml logs otel-collector | grep -c '"otelcol.signal":"traces"'
docker compose -f infra/compose/compose.yaml logs --no-log-prefix rag-api | tail -3 | jq '{level, msg, trace_id}'
```

> **WHAT YOU SHOULD SEE**
>
> - The Collector's log shows batches of traces and metrics. For full detail of each span, temporarily set
>   `verbosity: detailed` in the config and restart the Collector.
> - rag-api's logs are JSON lines with a `trace_id`.
> - The same trace id appears in spans from rag-api, opa and litellm.
> - In the guide's own end-to-end test, a span deliberately carrying a token and an email arrived at the Collector
>   as `user **** sent Bearer ****`, with `redaction.masked.count: 1`, and its authorization attribute was gone.
>
> Reading traces in the Collector's log is clumsy, which is the point: Step 21 adds Tempo and Grafana to see them
> as waterfalls, like the one at the start of this chapter.

### 6 · Record the decision

```bash
just adr "Use OpenTelemetry and a central Collector"
```

The result is [`docs/adr/0019-use-opentelemetry-and-a-central-collector.md`](../adr/0019-use-opentelemetry-and-a-central-collector.md):
all services emit OTLP to one digest-pinned contrib Collector; the processor order is fixed; services are
configured only with `OTEL_*` variables; spans carry no content and no secrets; metric labels stay
low-cardinality; LiteLLM (message logging off), OPA and Keycloak join the same traces; sampling is parent-based
and 100% in dev. Alternatives considered: vendor agents, direct export from every service, Prometheus client
libraries only, and zero-code auto-instrumentation only. Revisit when moving to production (tail sampling, a
custom Collector build, agent + gateway Collector tiers) or when adding prompt/response capture (Langfuse, Step 22).

```bash
git add -A
git commit -m "feat(otel): Collector with scrubbing/redaction; traces, metrics and JSON logs from rag-api, OPA, LiteLLM, Keycloak"
git push -u origin feat/otel
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- See inside every request, across all services, as one trace.
- Find slow steps in seconds, not hours of guessing.
- Logs joined to traces by trace id.
- Vendor freedom: standard OTLP everywhere; destinations live in one config file.
- Governance built in: no content or secrets by design, and the Collector scrubs anything that slips through.
- Tested telemetry: spans, attributes, metrics and the "no leaks" rule are checked on every push.
- AI-ready: GenAI conventions for model calls; token usage on every embedding span.

## Drawbacks and risks

- **Overhead:** small CPU and memory costs per request; batching keeps it low. Measure it under load (Step 37).
- **Data volume and cost:** traces grow fast. In production, sample (tail sampling keeps errors and slow requests)
  and set retention.
- **Redaction is a safety net, not a guarantee.** Patterns miss things; the real protection is not recording
  content in code.
- **Semantic conventions are still evolving,** especially GenAI ones (and older HTTP attribute names still appear).
  Expect renames.
- **One more critical path for debugging:** monitor the Collector itself (Step 20 scrapes its metrics).

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| OpenTelemetry + Collector (our choice) | Open standard SDKs plus a processing pipeline | Almost always; vendor-neutral |
| Grafana Alloy | Grafana's OpenTelemetry Collector distribution | All-Grafana stack, want one agent for everything |
| Vector / Fluent Bit | Fast log (and metric) shippers | Heavy log processing; existing pipelines |
| Vendor agents | Datadog Agent, Dynatrace OneAgent… | Company already standardised on that vendor |
| OpenLLMetry / OpenLIT / Traceloop | GenAI-focused OpenTelemetry instrumentations | Many LLM SDKs to auto-instrument |
| Langfuse / Phoenix / LangSmith | LLM-specific tracing with prompt and answer views | Debugging and evaluating LLM content (Step 22) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local platform, learning | One Collector, 100% sampling, debug + local backends (Steps 19–21) |
| Production, high traffic | Agent Collectors per node + gateway Collectors; tail sampling (errors, slow, 1–10% of the rest) |
| Strict privacy rules | No content in spans; Collector redaction; separate, access-controlled LLM trace store |
| Company uses a SaaS vendor | Same code; add that vendor's OTLP exporter in the Collector |
| Need prompt/answer debugging | Langfuse with masking and retention, never general-purpose traces |

## Common mistakes

- Putting prompts, answers, documents or tokens in spans or logs.
- User ids, query text or document ids as metric labels (cardinality explosion).
- No shutdown flush, so the last telemetry before every restart is lost.
- `batch` before `memory_limiter`, or no memory limit at all.
- Breaking context propagation with a custom HTTP client that drops `traceparent`, so traces split in two.
- Instrumenting health checks: most of the traffic and no value.
- Different `service.name` spellings across environments, so dashboards don't line up.
- Logging free text instead of structured JSON, so nothing can be filtered or joined.
- Treating the Collector as optional and exporting straight to vendors from every service.

## Done when

- [ ] `otel-collector` runs (contrib 0.162.x, pinned); `curl localhost:13133/` reports it available; the config validates
- [ ] The pipeline order is `memory_limiter` → scrub → redaction → resource → batch
- [ ] `rag_common.telemetry` sets up traces, metrics and JSON logs and flushes on shutdown
- [ ] rag-api emits server, OPA, gateway, SQL and RAG spans and four metrics; health checks are not traced
- [ ] `just check` shows 31 passed (in the guide's count), including the no-leak test
- [ ] Spans from rag-api, OPA and LiteLLM share one trace id for a single search; logs carry the same id
- [ ] LiteLLM message logging is off
- [ ] ADR-0019 is merged through a PR

## Recap

> **RECAP**
> The platform now reports on itself. Every service sends traces, metrics and logs over OTLP to one Collector,
> which:
>
> - protects its memory
> - removes secrets and masks tokens and emails
> - labels the environment and batches
>
> A search is one connected trace through rag-api, OPA, LiteLLM and Postgres, with RAG-specific spans and no
> content, and each log line points back to its trace. The data only goes to the Collector's own log for now.
> Step 20 adds Prometheus and Grafana, so the metrics become dashboards and alerts.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/config/otel-collector/config.yaml` | The Collector's pipelines: OTLP in, memory limit → scrub → redact → label → batch, debug exporter out, health check on 13133. |
| `infra/compose/compose.yaml` (changed) | New `otel-collector` service (contrib 0.162.0 by digest, read-only, no capabilities, 512 MB, localhost ports); `OTEL_*` variables and a start-order dependency for rag-api; LiteLLM's OTLP/HTTP settings; OPA's `distributed_tracing` flags; Keycloak's tracing variables. |
| `infra/config/litellm/config.yaml` (changed) | Turns on LiteLLM's `otel` callback with `message_logging: false`. |
| `libs/rag-common/src/rag_common/telemetry.py` | `setup_telemetry()` (tracer + meter providers from `OTEL_*`, OTLP gRPC, shutdown flush) and `setup_logging()` / `JsonFormatter` (JSON lines with trace and span ids). |
| `libs/rag-common/pyproject.toml`, `uv.lock` (changed) | OpenTelemetry API, SDK and OTLP gRPC exporter as rag-common dependencies. |
| `libs/rag-common/tests/test_telemetry_setup.py` | The library on its own: `OTEL_SDK_DISABLED`, the JSON log format, exceptions in logs, stdout logging, and real providers picking up `OTEL_RESOURCE_ATTRIBUTES` (in a fresh process). |
| `services/rag-api/src/rag_api/main.py` (changed) | Lifespan that sets up and flushes telemetry, automatic FastAPI/httpx/psycopg instrumentation (health checks excluded), RAG spans and the four metrics. |
| `services/rag-api/src/rag_api/search.py` (changed) | The `embeddings embedder` GenAI span with model and input-token usage. |
| `services/rag-api/pyproject.toml`, `uv.lock` (changed) | The FastAPI, httpx and psycopg instrumentation packages. |
| `services/rag-api/tests/test_telemetry.py` | The guide's five telemetry tests (one trace, attributes, no leaks, metrics, log trace id). |
| `services/rag-api/tests/test_service.py` (changed) | The fake embeddings response now includes `usage`, like the real API. |
| `tests/test_otel_collector.py` | Repo-level checks: Collector config and processor order, the redaction patterns against sample values, Compose hardening and wiring of all four services, LiteLLM's callback, ADR-0019; validates the config with the real image when Docker has it; live health check when the Collector runs. |
| `tests/test_gateway.py`, `tests/test_gateway_governance.py`, `tests/test_keycloak.py`, `tests/test_rag_api.py` (changed) | Earlier static tests updated to allow the new non-secret telemetry settings. |
| `docs/adr/0019-use-opentelemetry-and-a-central-collector.md`, `docs/adr/README.md` | ADR-0019 and its index row. |
| `docs/steps/step-19-opentelemetry-collector.md` | This write-up. |

## Notes for this repository

- **The image digest is real.** `otel/opentelemetry-collector-contrib:0.162.0` resolved to
  `sha256:39923a8e…f74be6` on Docker Hub (2026-10-12), replacing the guide's `<digest>` placeholder. Refresh it
  when you want updates.
- **The config was validated by the Collector itself.** `otelcol-contrib validate` in the pinned image printed
  `VALID`, and `tests/test_otel_collector.py` repeats that check whenever Docker has the image.
- **Redaction was proven live, with the guide's exact result.** The Collector ran with the Compose hardening
  (read-only, no capabilities, 512 MB, which gave "limit_mib 409, spike_limit_mib 102") and a scratch copy of the
  config at `verbosity: detailed`. A span sent through `rag_common.telemetry` with an `http.request.header.authorization`
  attribute and the value `user carol@example.com sent Bearer eyJ….….…` arrived as `note: user **** sent Bearer ****`
  with `redaction.masked.count: 1`, the authorization attribute gone and `deployment.environment.name: dev` added.
- **rag-api was run for real against the Collector.** `uvicorn rag_api.main:app` with the Compose `OTEL_*` values
  (Keycloak deliberately unreachable): `/healthz` produced no span; `POST /v1/search` produced one
  `POST /v1/search` server span with `service.name: rag-api`, which reached the Collector at shutdown (the flush
  works); and the JSON error log line for that request carried the same `trace_id` as the span. The full multi-service
  trace (Keycloak, OPA, LiteLLM, the Mac-native embedder) needs the whole stack and the Mac, so it wasn't run here.
- **uvicorn's own access lines stay plain text.** `setup_logging()` replaces the root logger's handlers, which
  covers the application's loggers (`rag_api`, libraries); uvicorn configures its `uvicorn.access` and
  `uvicorn.error` loggers separately, so those lines are not JSON. That matches the guide's code; the server spans
  already record every request.
- **Test counts.** The guide counts 31 (its 26 API tests from Step 18 plus 5). This repository's rag-api suite is
  larger (it keeps `test_service.py`), so `services/rag-api` now shows 43 passed and 4 skipped (live OPA tests
  without the `opa` binary); the five telemetry tests are exactly the guide's. Added on top: 5 library tests in
  `libs/rag-common` and 17 repo-level tests in `tests/test_otel_collector.py` (one of them live).
- **Earlier tests were adjusted, not weakened.** Step 9/10 tests asserted that LiteLLM had no `environment` block
  (so keys never show in `docker inspect`); they now allow only the three non-secret `OTEL_*` names. The Keycloak
  and rag-api tests now expect the tracing variables and the `otel-collector` dependency.
- **`--no-log-prefix` in the log command.** `docker compose logs` prefixes each line with the container name, which
  `jq` can't parse, so the command above adds `--no-log-prefix` (as in Step 18).
- **Tracing in OPA and Keycloak** is configured exactly as the guide says but was not observed live here (it
  needs those services running with the Collector).
