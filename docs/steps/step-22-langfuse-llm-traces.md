# Step 22 · Langfuse: LLM traces with content, under control

*Step 22 of 38 · Phase E · Observability*

## At a glance

| | |
|---|---|
| **Goal** | Add the AI engineer's view. Langfuse stores **what was asked**, **what was retrieved** and (from Step 33) **what was answered**, so you can debug bad answers, compare prompts and run evaluations. |
| **Why it's separate** | This is exactly the content Steps 19–21 deliberately kept out of operational telemetry. So it gets its own store and its own access rules, and three safeguards: **masking in our own process**, before anything is sent; **no confidential or restricted titles or text**; and a **retention job**, because self-hosted retention is an Enterprise feature. |
| **Time** | About 2.5 hours. |
| **You'll end up with** | Langfuse 4.27 self-hosted: `langfuse-web`, `langfuse-worker`, its own Postgres, ClickHouse, a separate Valkey (`noeviction`), and a bucket on our SeaweedFS S3 with a 30-day rule · rag-api sending one Langfuse trace per search: question (masked), retrieved documents (sensitive titles withheld), pseudonymous user · the Langfuse trace using the **same trace id** as the Tempo trace, on a **separate tracer provider**, so no content leaks into Tempo · 8 new tests in the guide (masking, withheld titles, isolation, same trace id, the retention job against the SDK's real API client) · a retention job that deletes traces older than 30 days · a Grafana link from any log line to its Langfuse trace · ADR-0022. |
| **New words** | LLM observability, trace / observation / generation / retriever, session, score, project and API keys, ClickHouse, masking hook, side door, data retention, open core, headless initialisation. |

## The big idea

> **ANALOGY · THE FLIGHT DATA RECORDER**
> Air-traffic control sees every plane's position, speed and delays. That's our operational telemetry:
> everyone in operations can see it, and it never contains what was said in the cockpit.
>
> The cockpit voice recorder holds the actual conversation. It's invaluable when something goes wrong, so
> it's kept separately, opened only by investigators, and overwritten after a fixed time.
>
> Langfuse is the cockpit recorder for the RAG system:
> - It holds the real questions, the documents that came back and the answers.
> - Only a few people can open it.
> - It's cleaned of anything that shouldn't be there, and it's erased on schedule.

```text
                              one search request
                              trace id 4bf92f35…
                   spans, no content  │  masked content
              ┌───────────────────────┴───────────────────────┐
   Tempo (Steps 19–21)                               Langfuse (this step)
   WHO:     operations, on-call                      WHO:     AI engineers, evaluators
   WHAT:    timings, ids, counts                     WHAT:    question, retrieved docs, answers
   CONTENT: none, by design                          CONTENT: masked; sensitive titles withheld
   ACCESS:  wide (Grafana)                           ACCESS:  few people, own login
   KEPT:    7 days                                   KEPT:    30 days (our retention job)

   Same trace id in both: from a slow trace in Tempo, open the same request in Langfuse.
```

*Figure 69 in the guide: two stores for the same request. Tempo holds timings and ids with no content, for a
wide operations audience. Langfuse holds masked content for a few AI engineers, kept 30 days. The shared trace
id links them.*

## What we're doing

1. Prepare Langfuse's storage: a bucket and identity on SeaweedFS with a 30-day rule, plus its own Postgres,
   ClickHouse and Valkey.
2. Run `langfuse-web` and `langfuse-worker`, initialised from code (organisation, project, API keys, admin),
   with sign-up off and telemetry off.
3. Add `rag_api.llmtrace`: a Langfuse client on its own tracer provider, a masking hook, withheld sensitive
   titles and the shared trace id.
4. Test it: masking, withholding, isolation from Tempo, same trace id, and the retention job against the SDK's
   real API client.
5. Add the retention job and a Grafana link from logs to Langfuse.
6. Record ADR-0022.

## Why we're doing this

> **WHY THIS MATTERS**
> "The answer was wrong" is the most common RAG complaint, and you can't fix it from timings alone. You need
> the actual question, which documents were retrieved and with what scores, the prompt that was built and the
> answer the model gave.
>
> Langfuse shows that for every request, and lets you:
> - score answers, by people or by an LLM judge
> - group sessions, and compare prompt versions
> - build datasets for evaluation (Step 26 and Projects 5–6)
>
> But it concentrates the most sensitive data in the platform: questions can contain personal data, and
> retrieved documents can be restricted. So it needs stricter rules than anything before.

| Need | How this step meets it |
|---|---|
| See question, retrieved documents, answer | Langfuse traces with typed observations (`chain`, `retriever`, later `generation`) |
| Content never in general telemetry | Langfuse on its own tracer provider; tested |
| No secrets or personal data | Masking hook in our process (tokens, keys, emails) before anything is sent |
| No side door around the policy | Confidential/restricted titles withheld, no document text |
| Link to operations data | Same trace id as Tempo; Grafana log → Langfuse link |
| Keep only as long as needed | Retention job, 30 days (self-hosted automatic retention is Enterprise-only) |
| Few people, own access | Langfuse login, sign-up disabled, roles per project |
| Own the data | Self-hosted: prompts and documents never leave your machine |

> **IN A COMPANY**
> LLM observability (Langfuse, LangSmith, Arize Phoenix, Weights & Biases Weave, Datadog LLM Observability) is
> now a standard part of AI platforms. The questions a review will ask:
> - Where are prompts stored, and who can read them?
> - How long are they kept?
> - Is personal data masked before it leaves the application?
> - Can someone use the trace viewer to read documents they're not cleared for?
>
> A clear "separate store, masking in-process, sensitive content withheld, retention enforced" answer is what
> passes.
>
> Note the licence and ownership: Langfuse's core is MIT (*open core*), copyright ClickHouse, Inc., which
> acquired it. A few features are under a separate Enterprise licence, including automatic data retention for
> self-hosted deployments.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **LLM observability** | Recording what an AI system was asked, what it looked up and what it answered, to debug and improve it. |
| **Trace / observation** | A trace is one request. Observations are its steps, each with a type: `chain`, `retriever`, `embedding`, `generation`, `tool`, `agent` … |
| **Generation** | An observation for one LLM call: prompt, completion, model, tokens and cost (from Step 33). |
| **Session / user / tags** | Ways to group traces: a conversation, a (pseudonymous) person, labels. |
| **Score** | A judgement attached to a trace: thumbs up/down, a 0–1 rating, an evaluator's verdict. |
| **Project and API keys** | A Langfuse project holds traces; its public key (`pk-lf-…`) identifies it, and its secret key (`sk-lf-…`) authorises writes. |
| **ClickHouse** | A fast analytics database where Langfuse stores traces and observations. |
| **Masking hook** | A function in our process that rewrites every value before it's sent to Langfuse. |
| **Side door** | A way to read data around the access policy, for example via a trace viewer. |
| **Open core** | A free (here MIT) core product plus paid Enterprise features. |
| **Headless initialisation** | Creating the organisation, project, keys and admin from configuration at first start, with no clicking. |

> **IN PLAIN ENGLISH**
> A *trace* in Langfuse is the same idea as a trace in Tempo (one request), but its steps carry the actual
> words: the question that came in and the list of documents that came back. That's why it needs a different
> home with different rules.

### What Langfuse needs to run

```text
                                                       SeaweedFS S3
                                                       bucket "langfuse"
                                                       raw events · 30-day rule
                                              1 store ▲
   rag-api                 OTLP + key       langfuse-web        2 queue     langfuse-valkey        langfuse-worker
   Langfuse SDK on its  ───────────────▶   UI + API · :3002  ───────────▶  job queue      ───────▶ 3 processes events
   OWN tracer provider                     /api/public/otel                noeviction (not                │
                                                │                          Step 15's)                     │ 4 write
                                                ▼                                                         ▼
                                           langfuse-db                                              ClickHouse
                                           Postgres: users, projects,                               traces, observations,
                                           API keys, prompts                                        scores
```

*Figure 70: rag-api sends OTLP to langfuse-web, which stores raw events in S3 and queues a job; the worker
processes it into ClickHouse; Postgres holds users, projects and keys. Its Valkey must never evict, so it can't
share Step 15's. Six moving parts for one tool: this is why many teams use Langfuse Cloud. Self-hosting keeps
every prompt on your machine.*

> **WHY LANGFUSE CAN'T REUSE STEP 15'S VALKEY**
> Langfuse's job queue (BullMQ) requires `maxmemory-policy noeviction`: if memory fills up, writes must fail
> loudly rather than silently deleting queued jobs. Our Step 15 Valkey uses `volatile-lru` because it's mainly a
> cache. `maxmemory-policy` is set per instance, not per key prefix, so the two needs can't share one instance.
> That's the "separate cache and queue instances" situation from Step 15's table, arriving for real.

### The side door, and what we record

**The side-door problem.** Carol (executive) searches. Her trace would contain the restricted "Exec offsite"
document. Dan (AI engineer) can read all Langfuse traces, but has no executive clearance in OPA. Copy that
content into the trace, and Dan reads it anyway: the policy from Step 18 is bypassed.

| What | Recorded in Langfuse? |
|---|---|
| question text | masked (tokens, keys, emails → `****`) · can be switched off |
| document id, classification, score | always recorded: enough to debug ranking |
| title of public / internal documents | recorded |
| title of confidential / restricted documents | `"[withheld: restricted]"` (or `confidential`) |
| document text (chunks) | never, in this step |
| user | pseudonymous id (`sub`), never name or email |

*Figure 71: anyone who can read traces would see every retrieved document's content; so sensitive titles are
withheld and document text is never copied. Questions are masked; users are pseudonymous ids.*

## How to do it

The guide works on a feature branch on macOS:

```bash
cd ~/dev/rag-platform
git switch -c feat/langfuse
```

### 1 · Secrets

Generate the values (the guide prints them, then you paste them into the encrypted file):

```bash
r() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-32; echo; }
echo "NEXTAUTH_SECRET $(r)"; echo "SALT $(r)"; echo "ENCRYPTION_KEY $(openssl rand -hex 32)"
echo "DB $(r)"; echo "CLICKHOUSE $(r)"; echo "VALKEY $(r)"; echo "ADMIN $(r)"
echo "S3 access $(r)"; echo "S3 secret $(r)"
echo "pk-lf-$(uuidgen | tr A-Z a-z)"; echo "sk-lf-$(uuidgen | tr A-Z a-z)"
just secrets-edit
#   LANGFUSE_NEXTAUTH_SECRET, LANGFUSE_SALT, LANGFUSE_ENCRYPTION_KEY (the 64-character hex value),
#   LANGFUSE_DB_PASSWORD, LANGFUSE_CLICKHOUSE_PASSWORD, LANGFUSE_VALKEY_PASSWORD,
#   LANGFUSE_ADMIN_PASSWORD, S3_LANGFUSE_ACCESS_KEY, S3_LANGFUSE_SECRET_KEY,
#   LANGFUSE_PUBLIC_KEY=pk-lf-…, LANGFUSE_SECRET_KEY=sk-lf-…
```

In this repository the names are also listed (with no values) in `.env.example`, and
`scripts/new-dev-secrets.sh` generates all of them for a fresh `secrets/dev.enc.env`.

> **WATCH OUT · LANGFUSE_ENCRYPTION_KEY AND LANGFUSE_SALT ARE LIKE STEP 10'S LITELLM SALT**
> They encrypt stored credentials and hash API keys. Change them later and existing keys and secrets stop
> working. Generate them once, back them up with your age key (Step 6), and never rotate them casually.

### 2 · Storage: an S3 identity and bucket, with a 30-day rule

Langfuse's documentation covers SeaweedFS directly: it needs path-style requests and an identities file (which
Step 14 already enforces). `infra/compose/compose.yaml` adds a `langfuse` identity to the object store's
identities list, limited to its own bucket, and the two secret files it reads:

```text
{"name": "langfuse",
 "credentials": [{"accessKey": "$$(cat /run/secrets/s3_langfuse_access_key)", "secretKey": "$$(cat /run/secrets/s3_langfuse_secret_key)"}],
 "actions": ["Read:langfuse", "Write:langfuse", "List:langfuse"]}
```

Then create the bucket and its lifecycle rule:

```bash
just up                                                # recreates object-store with the new identity
just s3 s3 mb s3://langfuse
just s3 s3api put-bucket-lifecycle-configuration --bucket langfuse --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-raw-events","Status":"Enabled","Filter":{"Prefix":"events/"},"Expiration":{"Days":30}}]}'
```

> **WHY A LIFECYCLE RULE ON EVENTS/**
> Langfuse writes every incoming batch to S3 first, then the worker loads it into ClickHouse. The raw copies are
> only needed for retries and recovery. Langfuse's docs recommend an expiry rule ("30 days on Langfuse Cloud");
> otherwise raw events, with their content, pile up forever.

(Tested here: deleting a trace through the API removed it from ClickHouse and Postgres but left its raw event
in `events/`. The lifecycle rule is what removes that copy.)

### 3 · Run Langfuse

`infra/compose/compose.yaml` gains a shared settings block and five services. The shared block (used by both web
and worker):

```yaml
x-langfuse-env: &langfuse-env
  NEXTAUTH_URL: http://localhost:3002
  DATABASE_URL: postgresql://langfuse:${LANGFUSE_DB_PASSWORD}@langfuse-db:5432/langfuse
  SALT: ${LANGFUSE_SALT}
  ENCRYPTION_KEY: ${LANGFUSE_ENCRYPTION_KEY}
  TELEMETRY_ENABLED: "false"                       # no usage data sent to the vendor
  CLICKHOUSE_MIGRATION_URL: clickhouse://langfuse-clickhouse:9000
  CLICKHOUSE_URL: http://langfuse-clickhouse:8123
  CLICKHOUSE_USER: langfuse
  CLICKHOUSE_PASSWORD: ${LANGFUSE_CLICKHOUSE_PASSWORD}
  CLICKHOUSE_CLUSTER_ENABLED: "false"
  REDIS_HOST: langfuse-valkey
  REDIS_PORT: "6379"
  REDIS_AUTH: ${LANGFUSE_VALKEY_PASSWORD}
  LANGFUSE_S3_EVENT_UPLOAD_BUCKET: langfuse
  LANGFUSE_S3_EVENT_UPLOAD_PREFIX: events/
  LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://object-store:8333
  LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"     # required for SeaweedFS
  LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT: http://localhost:8333   # what your BROWSER uses
  # … plus region, prefix and the S3_LANGFUSE_* keys for both event and media uploads
```

The services, in plain words:

| Service | What it is | Notable settings |
|---|---|---|
| `langfuse-db` | Postgres 17 for users, projects, API keys, prompts | password from a secret file, `pg_isready` healthcheck, 512m |
| `langfuse-clickhouse` | ClickHouse 25.12 (the version Langfuse's own Compose file uses) for traces, observations, scores | runs as `101:101`, `/ping` healthcheck, 3g |
| `langfuse-valkey` | Valkey 9.1.2 as the job queue | config written at start into a RAM-only tmpfs: `requirepass`, `maxmemory-policy noeviction`, `appendonly yes`; 512m |
| `langfuse-worker` | Processes queued events into ClickHouse | `*langfuse-env`; waits for db, ClickHouse, Valkey and the object store to be healthy; 1g |
| `langfuse-web` | UI and API, including the OTLP endpoint `/api/public/otel` | `AUTH_DISABLE_SIGNUP: "true"`, headless init (`LANGFUSE_INIT_ORG_ID/NAME`, `…PROJECT_ID/NAME`, `…PROJECT_PUBLIC_KEY/SECRET_KEY`, `…USER_EMAIL/NAME/PASSWORD`), `LANGFUSE_S3_MEDIA_UPLOAD_INTERNAL_ENDPOINT: http://object-store:8333`, published only on `127.0.0.1:3002` (3000 is Grafana's) |

All five log through the Step 21 `*to-collector` block, use `no-new-privileges`, restart unless stopped, and
have memory/CPU limits. Four new volumes hold their data, and five new Compose secrets map to the SOPS values.

> **NOTES ON THIS SETUP**
> - **Secrets as environment variables.** Langfuse reads its settings only from environment variables (no
>   `_FILE` support). They come from `sops exec-env` at start-up (Step 6), so they're never written to disk, but
>   they are visible to anyone who can run `docker inspect`. That's acceptable on a single-user machine; in
>   Kubernetes they come from a secret store (Step 28).
> - **Sign-in.** The first admin is created from configuration, and sign-up is disabled. Invite each person
>   explicitly with the Viewer role unless they need more (roles are per project: Owner, Admin, Member, Viewer).
> - **Single sign-on via Keycloak.** Langfuse supports it (`AUTH_KEYCLOAK_CLIENT_ID`,
>   `AUTH_KEYCLOAK_CLIENT_SECRET`, `AUTH_KEYCLOAK_ISSUER`, and `AUTH_DISABLE_USERNAME_PASSWORD` to force it). It
>   needs Keycloak reachable at the same address from your browser and from inside the containers. Today the
>   issuer is `localhost:8180`, which containers can't reach, so SSO is wired when the platform gets a proper
>   hostname behind an ingress (Step 29).
> - **Memory.** ClickHouse is the heaviest new piece (allow ~3 GB). With everything running, check that
>   OrbStack's memory limit (Step 3) still has headroom: `docker stats --no-stream`.

```bash
just up && just ps          # langfuse-web takes ~30-60 s on first start (migrations)
open http://localhost:3002  # sign in: admin@example.com / LANGFUSE_ADMIN_PASSWORD
```

### 4 · rag-api: one Langfuse trace per search

```bash
uv add --package rag-api "langfuse>=4.17"
```

**`services/rag-api/src/rag_api/llmtrace.py`** (new) holds everything Langfuse-specific:

- `SECRET_PATTERNS` — the same three patterns as the Collector (JWTs, `sk-` keys, email addresses).
- `mask(*, data, **_)` — the masking hook. It walks strings, dicts and lists and replaces every match with
  `****`. The SDK calls it in our process on every input, output and metadata value, before export.
- `SearchTrace.retrieved(candidates, allowed)` — records a `retrieve` observation of type `retriever` with, per
  candidate: id, classification, score, title (or `[withheld: <classification>]` for confidential/restricted)
  and whether the policy returned it; plus metadata counts (`candidates`, `returned`, `dropped_by_policy`).
- `LlmTracer.search(principal, question, k)` — a context manager that opens the root `rag-search` observation of
  type `chain`, with `trace_context` set to the **current OpenTelemetry trace id**, input
  `{"question": …, "k": …}` (or `"[not captured]"` when question capture is off), and
  `propagate_attributes(user_id=principal.subject, tags=["rag-api", "search"])`.
- `flush()` / `shutdown()` — send what's buffered (the SDK exports in batches).
- `build_llm_tracer(...)` — builds the Langfuse client on a **private `TracerProvider`**, with `mask=mask`;
  returns a no-op tracer when URL or keys are missing (unless a test injects a `span_exporter`).

> **READING THE INTEGRATION**
> - `tracer_provider=provider`: the decisive line. Without it, the Langfuse SDK attaches to the app's global
>   OpenTelemetry provider (Step 19). Every Langfuse span, with its content, would then also flow to the
>   Collector and into Tempo. A test proves this doesn't happen.
> - `trace_context=…`: the Langfuse trace takes the trace id of the current request, so the same id finds the
>   request in Tempo, Loki and Langfuse.
> - `mask`: runs in our process on every input, output and metadata value before export. The same three
>   patterns as the Collector (Steps 19 and 21) apply.
> - `retrieved(…)`: records ids, classifications, scores and whether the policy returned each document, enough
>   to debug ranking and policy. Titles of confidential and restricted documents are withheld, and document
>   text is never copied.
> - `propagate_attributes(user_id=…)`: the pseudonymous `sub`, so you can find all traces for one complaint
>   without storing names.
> - Off by default: with no Langfuse URL configured, the tracer is a no-op and nothing changes.

> **WATCH OUT · ONE LANGFUSE CLIENT PER PROCESS**
> The SDK shares its resources (exporter, HTTP client) between all clients with the same public key in a
> process. A second client with the same key silently reuses the first one's connections. The tests for this
> step tripped over exactly that. rag-api creates its client once (`@lru_cache` on `get_llm`), and so should
> every service.

**`settings.py`** gains four settings: `langfuse_base_url` (empty = LLM tracing off), `langfuse_public_key`
(`pk-lf-…`, not secret), `langfuse_secret_key` (a `SecretStr` read from `/run/secrets/rag_api_langfuse_secret_key`)
and `langfuse_capture_question` (`False` records that a question was asked, not its text).

**`main.py`** gains a cached `get_llm()` dependency; `lifespan` shuts the Langfuse client down (flushing it) on
stop, but only if it was ever created; and `/v1/search` wraps its work in `with llm.search(p, req.query, req.k)
as llm_trace:` and calls `llm_trace.retrieved(candidates, allowed)` **after** the policy post-check, so the
trace knows which candidates the policy actually returned.

**Compose (rag-api)** adds `RAG_API_LANGFUSE_BASE_URL: http://langfuse-web:3000`,
`RAG_API_LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}` and the secret file `rag_api_langfuse_secret_key`.

### 5 · Test it

The Step 19 telemetry setup can only be installed once per process, so it moves into a shared session fixture
(`otel` in `services/rag-api/tests/conftest.py`) used by both the telemetry tests and the new ones. The `client`
fixture overrides `get_llm` with `LlmTracer(None)`: Langfuse is off in every test unless one switches it on.
`test_telemetry.py` now takes its exporters from that fixture.

`services/rag-api/tests/test_llmtrace.py` builds **one** Langfuse client per module with an in-memory exporter,
then checks:

| Test | Proves |
|---|---|
| `test_mask_function` | emails and `sk-` keys are masked inside nested dicts and lists |
| `test_search_creates_a_masked_langfuse_trace` | a search creates `rag-search` and `retrieve`; the question reads `Salary of ****? (pasted token ****)`; `user.id` is `8f1c0000-alice` |
| `test_sensitive_titles_are_withheld` | titles are `{1: "Remote work policy", 3: "[withheld: confidential]"}` |
| `test_same_trace_id_as_the_otel_trace` | the Langfuse root span's trace id equals the `POST /v1/search` server span's |
| `test_langfuse_content_never_reaches_normal_telemetry` | no OTel span carries a `langfuse.` attribute, `Salary` or `carol` |
| `test_off_by_default` | no URL/keys → disabled, and search still works |

```bash
just check
```

> **WHAT YOU SHOULD SEE**
> In the guide: **40 passed** — 32 from before, 6 Langfuse tests, 2 retention tests (next section). Beyond the
> tests, the actual wire request was captured with a stand-in server, and showed: a `POST
> /api/public/otel/v1/traces` with Basic authentication (`pk-lf-…:sk-lf-…`); the question as `email ****
> please`; a restricted document as `"title": "[withheld: restricted]"`.
>
> (This repository has many more tests than the guide's count, from earlier steps' config checks; see the notes
> at the end.)

### 6 · Retention: delete what you no longer need

Self-hosted Langfuse under the MIT licence does not delete old traces by itself; automatic data retention is an
Enterprise feature. Traces hold questions and retrieval details, so keeping them forever breaks the
data-minimisation rule. A small job closes the gap, using the SDK's own API client:
**`scripts/langfuse_retention.py`**.

- `purge(client, older_than=…, batch=100)` lists traces older than the cutoff, oldest first, always page 1
  (each round deletes what it just saw, so the "next page" moves up), and deletes them with
  `client.api.trace.delete_multiple(trace_ids=…)`. Langfuse deletes asynchronously, so ids already sent can
  still be listed for a moment; the loop stops when nothing new appears and the next run picks up leftovers.
- `count(client, older_than=…)` returns the number of old traces, for `--dry-run`.
- `main()` reads `--days` (default `LANGFUSE_RETENTION_DAYS` or 30) and `--dry-run`, **refuses `--days` < 1**
  ("refusing to delete everything"), and creates `Langfuse(tracing_enabled=False)` with keys and URL from the
  `LANGFUSE_*` environment variables.
- **Added in this repository:** a fallback for Langfuse v4's default `events_only` mode, where the legacy list
  endpoint answers 404 (see the notes at the end). Then old traces are found through the v2 observations API
  (root observations with `toStartTime`, cursor-paged), collected first, and deleted in batches.

It's tested against the real SDK client with a fake Langfuse server underneath (an `httpx.MockTransport`):
`tests/test_langfuse_retention.py` checks the exact requests the SDK sends — list with `toTimestamp`, delete
with `traceIds` — so 7 traces aged 1–90 days with a batch of 2 delete as `[2, 2, 1]` and keep the 1- and
5-day-old ones, and a dry run deletes nothing. Two more tests run the same checks against a fake **v4**
server.

`justfile`:

```text
# Delete Langfuse traces older than LANGFUSE_RETENTION_DAYS (default 30). Run nightly. (Step 22)
langfuse-retention *args:
    sops exec-env secrets/dev.enc.env 'LANGFUSE_BASE_URL=http://localhost:3002 uv run python scripts/langfuse_retention.py {{args}}'
```

```bash
just langfuse-retention --dry-run   # "would delete N traces older than …"
just langfuse-retention             # deletes; schedule it nightly
```

> **TIP · SCHEDULING IT**
> On your Mac, a nightly entry in `crontab -e` such as
> `15 3 * * * cd ~/dev/rag-platform && just langfuse-retention >> ~/Library/Logs/langfuse-retention.log 2>&1`
> is enough. In Kubernetes (Step 29) it becomes a CronJob. Whatever runs it, alert if it hasn't succeeded for
> two days, because a silently failing deletion job is a compliance problem.

### 7 · From a log line to the Langfuse trace

A second derived field on the Loki data source (Step 21), next to "View trace", in
`infra/config/grafana/provisioning/datasources/datasources.yaml`:

```yaml
        - name: Langfuse
          matcherType: regex
          matcherRegex: '"trace_id": ?"(\w+)"'
          url: "http://localhost:3002/project/rag-platform/traces/$${__value.raw}"
          urlDisplayLabel: Open in Langfuse
```

The URL pattern (`/project/<project id>/traces/<trace id>`) is the one the Langfuse SDK itself builds. Clicking
it works only for people who have a Langfuse login: Grafana access alone doesn't grant content access.

### 8 · Try it

```bash
just api-up && just api-demo   # sign in as alice, then carol; search a few times
open http://localhost:3002     # Tracing → Traces
```

> **WHAT YOU SHOULD SEE**
> - A `rag-search` trace per search, with a `retrieve` observation inside it.
> - alice's trace lists *Remote work policy* and *Parking*.
> - carol's trace also lists document 4 as `[withheld: restricted]`, with its score. You can tell a restricted
>   document ranked first without anyone reading it.
> - Ask a question containing an email address: the trace shows `****`.
> - Filter by User: the value is the `sub` (a UUID), not a name.
> - From a rag-api log line in Grafana, **Open in Langfuse** goes to the same request.

### 9 · Record the decision

```bash
just adr "Use self-hosted Langfuse for LLM traces"
```

`docs/adr/0022-use-self-hosted-langfuse-for-llm-traces.md`: self-host Langfuse 4.27 (MIT core) with its own
Postgres, ClickHouse 25.12, a `noeviction` Valkey and the `langfuse` bucket (scoped identity, path-style,
30-day expiry on `events/`); sign-up off, headless init, telemetry off; rag-api on its own tracer provider with
the shared trace id, in-process masking, withheld sensitive titles, no document text, user = `sub`; a nightly
30-day retention job; SSO deferred. Alternatives: Langfuse Cloud, Arize Phoenix, LangSmith, content in Tempo
spans. Revisit when answer generation arrives (Step 33), SSO becomes possible, or volume needs ClickHouse
clustering.

The guide then commits, pushes and merges through a PR:

```bash
git add -A
git commit -m "feat(langfuse): self-hosted LLM traces with masking, withheld sensitive titles, shared trace id and retention"
git push -u origin feat/langfuse
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **See why an answer was what it was:** the question and every retrieved document, ranked and scored.
- **Content kept in its own, smaller room:** separate store, own login, few people.
- **No side door:** sensitive titles withheld, no document text, questions masked, users pseudonymous.
- **Linked to operations:** the same trace id as Tempo and Loki, one click from a log line.
- **Retention enforced** even without the Enterprise feature.
- **Ready for evaluation:** scores, datasets and prompt versions build on these traces (Steps 24 and 26,
  Projects 5–6).
- **Your data stays home:** self-hosted, telemetry off.

## Drawbacks and risks

- **Heavy:** six containers. ClickHouse needs memory, and every one needs backing up or accepting loss.
- **Masking is pattern-based:** unusual personal data (a name, an address) passes through. Switch question
  capture off (`RAG_API_LANGFUSE_CAPTURE_QUESTION=false`) where that's unacceptable.
- **Withholding limits debugging of sensitive documents.** That's deliberate; investigate those with the
  document owner, not via the trace viewer.
- **Secrets as environment variables** in Langfuse's containers.
- **The retention job must run:** monitor it; a silent failure means data kept too long.
- **Vendor and licence changes:** an open-core project owned by ClickHouse, Inc. Keep the OTel-based
  integration thin, so switching to Phoenix or another tool is cheap.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **Langfuse self-hosted (our choice)** | Open-core LLM observability, prompts, datasets, scores | You need the full toolset on your own infrastructure |
| Langfuse Cloud | The same, hosted | Data may leave your environment; you'd rather not operate it |
| Arize Phoenix | Open-source, OpenTelemetry-native tracing and evals | Lighter self-hosting, notebook-centred evaluation |
| LangSmith | LangChain's commercial platform | Heavy LangChain/LangGraph users |
| MLflow tracing / W&B Weave | Tracing inside an ML platform | Already on MLflow or W&B |
| Datadog / Dynatrace LLM Observability | Vendor APM add-ons | The company's APM vendor already covers it |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Sensitive internal documents, self-hosted platform | Self-hosted Langfuse with in-process masking and withholding (this step) |
| Public or non-sensitive data, small team | Langfuse Cloud or Phoenix, fastest start |
| Strict privacy rules (health, finance) | Capture metadata only (`capture_question=false`), never content; short retention |
| Need answer-level debugging (Step 33) | Add generation observations via LiteLLM's Langfuse callback, same masking |
| Many teams | One Langfuse project per application, roles per project, SSO (Step 29) |

## Common mistakes

- Letting the LLM-tracing SDK attach to the global tracer provider, so prompts and documents leak into general
  traces.
- Copying retrieved document text into traces, giving every trace reader a side door around the policy.
- Masking only on the server side, after the data has already left your process.
- Real names or emails as user ids instead of a pseudonymous id.
- Assuming the tool deletes old data, when self-hosted retention needs a licence or your own job.
- Sharing a cache Redis/Valkey with Langfuse's queue, so eviction silently drops ingestion jobs.
- Creating a new SDK client per request, which wastes resources and, with the same key, shares state
  unexpectedly.
- Open sign-up on a tool full of sensitive content.

## Done when

- [ ] Langfuse 4.27 runs (web, worker, Postgres, ClickHouse, its own Valkey with `noeviction`); you can sign in
      at `localhost:3002`; sign-up is disabled
- [ ] The `langfuse` bucket exists with the scoped identity and the 30-day `events/` rule
- [ ] rag-api searches appear as `rag-search` traces with a `retrieve` observation; questions masked; restricted
      titles withheld; user = `sub`
- [ ] The Langfuse trace id equals the Tempo trace id for the same request; Tempo spans contain no `langfuse.*`
      attributes
- [ ] `just check` passes (the guide's count: 40 passed)
- [ ] `just langfuse-retention --dry-run` reports a count; the nightly schedule is in place
- [ ] A Loki log line offers **Open in Langfuse**
- [ ] ADR-0022 is merged through a PR

## Recap

> **RECAP**
> The platform now has a cockpit voice recorder: self-hosted Langfuse, holding what was asked and what was
> retrieved for every search. It runs on its own storage: Postgres, ClickHouse, a non-evicting Valkey and a
> SeaweedFS bucket.
>
> Content is controlled at every step:
> - masked in our process before export
> - sensitive titles withheld, so trace readers can't bypass the policy
> - isolated from operational telemetry by a separate tracer provider (tested)
> - deleted after 30 days by our own job
>
> One trace id ties it to Tempo and Loki. That completes Phase E, observability. Phase F turns to governance,
> starting with Step 23, a hash-chained, tamper-evident audit log: a record of who did what that nobody,
> including administrators, can quietly change.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/compose/compose.yaml` | Updated: `x-langfuse-env` shared settings; `langfuse-db`, `langfuse-clickhouse`, `langfuse-valkey`, `langfuse-worker`, `langfuse-web` (all pinned by tag@digest); the `langfuse` S3 identity on the object store; rag-api's Langfuse URL, public key and secret file; four volumes and five secrets. |
| `.env.example` | Updated: every new Langfuse/S3 setting name with a description, no values. |
| `scripts/new-dev-secrets.sh` | Updated: generates all Langfuse secrets, S3 keys and the `pk-lf-`/`sk-lf-` project keys for a fresh encrypted secrets file. |
| `services/rag-api/pyproject.toml`, `uv.lock` | `langfuse>=4.17` added to rag-api (locked at 4.17.0). |
| `services/rag-api/src/rag_api/llmtrace.py` | New: masking hook, withheld sensitive titles, Langfuse client on a private tracer provider, shared trace id, pseudonymous user. |
| `services/rag-api/src/rag_api/settings.py` | Updated: the four `RAG_API_LANGFUSE_*` settings. |
| `services/rag-api/src/rag_api/main.py` | Updated: cached `get_llm()`, flush on shutdown, one Langfuse trace around every search, retrieval recorded after the policy post-check. |
| `services/rag-api/tests/conftest.py` | Updated: the shared `otel` session fixture; Langfuse off by default in the `client` fixture. |
| `services/rag-api/tests/test_telemetry.py` | Updated: uses the shared `otel` fixture. |
| `services/rag-api/tests/test_llmtrace.py` | New: the guide's six Langfuse tests. |
| `scripts/langfuse_retention.py` | New: deletes Langfuse traces older than N days (dry-run, batches, refuses `--days 0`), with a fallback for Langfuse v4's `events_only` mode. |
| `tests/test_langfuse_retention.py` | New: the guide's two retention tests plus two for the v4 fallback, using the real SDK client over `httpx.MockTransport`. |
| `justfile` | Updated: `just langfuse-retention`. |
| `infra/config/grafana/provisioning/datasources/datasources.yaml` | Updated: Loki derived field "Open in Langfuse". |
| `tests/test_langfuse.py` | New: static checks of the Compose services, settings, S3 identity, rag-api wiring, Grafana link (regex run on a real log line), recipe, secrets template and ADR. |
| `tests/test_object_storage.py`, `tests/test_rag_api.py`, `tests/test_loki_tempo.py` | Updated for the new S3 identity, rag-api's new setting/secret and the second Loki derived field. |
| `docs/adr/0022-use-self-hosted-langfuse-for-llm-traces.md` | ADR-0022, plus its row in `docs/adr/README.md`. |
| `docs/glossary.md` | Twelve new terms from this step. |
| `docs/steps/step-22-langfuse-llm-traces.md` | This write-up. |

## Notes for this repository

- **Image digests.** The guide prints `@sha256:<digest>`. The digests were looked up on Docker Hub and confirmed
  by pulling the images: `langfuse/langfuse:4.27.0` (`sha256:c9e2cab8…`), `langfuse/langfuse-worker:4.27.0`
  (`sha256:091a85c3…`), `clickhouse/clickhouse-server:25.12` (`sha256:8a790dd3…`). Postgres 17 and Valkey 9.1.2
  reuse the digests already pinned for `litellm-db` and `valkey`. The Langfuse images keep the guide's
  `docker.langfuse.com/…` names; that registry serves the same Docker Hub images.
- **`langfuse-web` memory: 2g instead of the guide's 1g.** With 1g, Langfuse 4.27's web container crash-looped
  at start-up ("JavaScript heap out of memory"): Node sizes its heap from the container limit (~500 MB at 1g).
  At 2g it started cleanly and used about 1 GB. The worker was fine at 1g.
- **Retention job and Langfuse v4 "events_only" mode (deviation, found by testing).** A fresh Langfuse 4.27
  runs with `LANGFUSE_MIGRATION_V4_WRITE_MODE=events_only` (its default). In that mode `GET /api/public/traces`
  (and `GET /api/public/traces/{id}`) answer 404 "not available … in Langfuse v4 events_only mode", so the
  guide's `purge`/`count` would fail against the real server. `DELETE /api/public/traces` still works. The
  script keeps the guide's code path and, on that specific 404, finds old traces through
  `client.api.observations.get_many(is_root_observation=True, to_start_time=…)` (cursor-paged), collects
  them, then deletes in batches. Two extra tests cover it; the guide's two tests are unchanged.
  `main()` also reads the docstring as `(__doc__ or "")` so strict mypy accepts it.
- **Tests count.** The guide expects "40 passed"; this repository has many more (config tests from every
  step). The guide's 8 new tests are all present and pass; this step adds 11 more (2 retention v4 tests and 9 in
  `tests/test_langfuse.py`).
- **Secrets.** No real values are committed. The new names are in `.env.example`, and
  `scripts/new-dev-secrets.sh` generates them into the SOPS-encrypted `secrets/dev.enc.env`.
- **Validated here (Linux container, Docker):**
  - `docker compose config` accepts the file; ruff, strict mypy and the whole test suite pass
    (289 passed, live-service tests skipped).
  - A scratch stack of the real images (object store, `langfuse-db`, `langfuse-clickhouse`, `langfuse-valkey`,
    `langfuse-worker`, `langfuse-web`) started healthy from the committed Compose file (with a local override
    only for log driver and image mirror names). Valkey reported `maxmemory-policy noeviction`; an
    unauthenticated `get` was refused with `NOAUTH`.
  - The admin created the `langfuse` bucket and the lifecycle rule (read back as `expire-raw-events`, 30 days,
    prefix `events/`). The `langfuse` identity could write its own bucket and got `AccessDenied` on
    `rag-raw-docs`.
  - Headless init worked: `/api/public/projects` with the `pk-lf-`/`sk-lf-` keys returned project
    `rag-platform` in organisation `RAG Platform`; `/api/public/health` reported version 4.27.0.
  - The real `rag_api.llmtrace` code sent a search trace inside an OpenTelemetry span: Langfuse stored it under
    the **same trace id**, the question as `email **** please`, the restricted document as
    `[withheld: restricted]` with its score, types `CHAIN` and `RETRIEVER`, and `userId` = the `sub`.
  - `scripts/langfuse_retention.py --dry-run` against the real server printed
    `would delete 0 traces older than …`; `--days 0` was refused. `purge` with a future cutoff found and deleted
    the trace; the worker logged the deletion from Postgres and ClickHouse and it disappeared from the API.
    Its raw event stayed in `events/`, which is what the 30-day lifecycle rule is for.
  - Not done here: building the rag-api image (ghcr.io blob downloads are blocked in this container), the
    Grafana click-through and the macOS-only steps (`open`, crontab). The scratch stack, its volumes and the
    pulled images were removed afterwards.
