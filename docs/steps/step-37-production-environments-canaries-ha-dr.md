# Step 37 · Production: environments, canaries, HA/DR and online evaluation

*Step 37 of 38 · Phase I · Production & reuse*

## At a glance

| | |
|---|---|
| **Goal** | Take the platform from "runs on my Mac" to "runs in production, safely changed every week". A new release, prompt, model or index should reach users only after it has proved itself, reach them gradually, roll back by itself when it is worse, survive the loss of a machine or a whole zone, and be watched for *quality*, not just uptime, once it is live. |
| **How, in one sentence** | The same Kubernetes manifests get staging and prod overlays with a shared production component (canary releases with Argo Rollouts and automatic analysis, autoscaling, zone spreading); promotion gates check evidence, a soak in staging, online evaluation and alerts before a digest may move; CloudNativePG runs Postgres across three zones with synchronous replication and point-in-time recovery; online evaluation turns the audit log and feedback into per-release quality verdicts; readiness checks refuse a production profile with test stand-ins; the ingestion worker gets its own identity and scheduled jobs; and legal holds finally stop retention. |
| **Time** | About 5 hours (plus whatever your cloud account needs for real clusters). |
| **You'll end up with** | `deploy/envs/staging`, `deploy/envs/prod`, `deploy/components/production` and `managed-deps`: one shape, three environments · a canary `Rollout` and an `AnalysisTemplate` (Prometheus checks + an online-evaluation Job), Argo Rollouts vendored and hash-checked · `deploy/envs/promotion.yaml` + `scripts/gates.py`: what must be true before each promotion; `just promote` runs it · `rag config readiness` and a `production` profile; `rag online-eval` with a significance test and a review queue · alert rules for answer quality with unit tests, now run by a pinned `promtool` · `deploy/base/rag-ingest`: the worker and its CronJobs (retention, online evaluation) under their own OpenBao identity · `deploy/data`: a three-zone Postgres cluster with WAL archiving, nightly backups, 30-day point-in-time recovery, and a DR drill · Argo CD apps for each environment, runbooks, a cloud mapping table, five new controls in the risk register · ADR-0037. |
| **New words** | environment parity, overlay, promotion, gate, evidence, soak time, change freeze, break glass, canary release, progressive delivery, analysis run, high availability (HA), failover, synchronous replication, quorum, WAL archiving, point-in-time recovery (PITR), disaster recovery (DR), online evaluation, significance test, review queue, production readiness, workload identity, legal hold. |

## The big idea

> **ANALOGY · HOW AN AIRLINE INTRODUCES A NEW PLANE**
> A new aircraft doesn't go straight onto the busiest route. It flies test flights with the same crew procedures
> as a real flight (staging, built exactly like production). Then it flies one quiet route first, while engineers
> compare its instruments with the old fleet (a canary, with analysis); if anything looks worse, it is grounded
> automatically and the old planes keep flying. Before each step, someone checks the paperwork: certificates,
> test results, days in service (gates and evidence).
>
> Every plane has two pilots so losing one isn't a crash (replicas and failover), a black box that records every
> flight (WAL archiving: you can replay to any second), and passenger feedback that's read every week (online
> evaluation). And the airline practises emergencies before it has one (DR drills).

### Three environments, one shape (Figure 116)

```
  local                      gate      staging                      gate      prod
  your Mac (OrbStack)       ─────▶    its own cluster              ─────▶    its own cluster
  • anything signed                    • same shape as prod                    • 3 zones, HA Postgres
  • Compose services                   • canary + analysis                     • canary + analysis
  • fast feedback                      • online eval vs previous               • PITR, DR drills

  Gates (deploy/envs/promotion.yaml, scripts/gates.py)
  → staging: image-verify, readiness, search / guard / answer evaluations pass
  → prod:    same digest in staging, soaked 24 h; online eval, no critical alert; no freeze
  Every move is one digest line changed by a pull request; Argo CD deploys the merge; rollback = git revert.
  Break glass: just promote prod sha256:… "reason" — recorded.
```

A digest moves local → staging → prod only through gates. Staging needs passing offline evidence; prod needs the
same digest soaked in staging, online evaluation, no critical alert and no change freeze. Every move is one line in git.

## What we're doing

1. One shape, three environments: staging and prod overlays on the same base, with a shared production component.
2. Canary releases that compare the new release with the old one and roll back by themselves.
3. Promotion gates: evidence, soak time, online evaluation, alerts, change freezes; break glass recorded.
4. Production readiness checks for the configuration.
5. Online evaluation from the audit log and feedback, with a review queue.
6. Alerts on answer quality, unit-tested.
7. The ingestion worker with its own identity, and scheduled lifecycle jobs, with legal holds.
8. High availability and disaster recovery for the database, with a drill.
9. Argo CD per environment, and a cloud mapping for managed services.

## Why we're doing this

> **WHY THIS MATTERS**
> Production failures in RAG systems are mostly *change* failures, not crashes:
> - A prompt tweak passes CI but makes the assistant say "I don't know" twice as often for real users' questions,
>   which no labelled dataset had.
> - A new embedding model goes live everywhere at once; search quality drops for a week before anyone connects
>   the thumbs-down to the release.
> - A configuration slip ships the in-memory vector store or a missing guard to production because the profile
>   "validated".
> - A node or zone dies and takes the only database with it; or worse, a bad migration deletes rows and every
>   replica copies the mistake.
> - A worker shares the API's credentials, so a bug in one can read or write what only the other should.
> - Retention deletes evidence that a legal hold should have kept.

| Need | How this step meets it |
|---|---|
| Staging that predicts production | Same base, same production component; only names, sizes and aliases differ |
| Prove before promoting | Evidence files per digest (signature, readiness, search, guard and answer evaluations, online evaluation) |
| Don't promote what hasn't run | Prod requires the digest running in staging, for 24 hours (from git history) |
| Release gradually, roll back automatically | Argo Rollouts canary 10 → 25 → 50 → 100%, analysis all the way, abort on any failed check |
| Watch quality, not just uptime | Alerts on blocks, abstentions, thumbs down, latency; online evaluation per release |
| Configuration that is fit for production | `rag config readiness` in CI and in the gates |
| Survive machine and zone loss | Three zones; pods spread; Postgres with synchronous replica and automatic failover |
| Undo a destructive mistake | WAL archiving + nightly base backups: restore to any second in 30 days, into a new cluster |
| Least privilege per workload | The worker and jobs log in to OpenBao as `rag-ingest`; rag-api as `rag-api`; neither can read the other's secrets |
| Keep what the law says to keep | Legal holds beat retention; erasure under a hold needs a recorded override |

> **IN A COMPANY**
> This is what a change advisory board, an SRE review and a production readiness review look for: a defined path
> to production with evidence at each gate, automated rollback, measured recovery objectives with a tested
> restore, separation of duties between workloads, and monitoring of the outcome users experience. Each item here
> is a file in git and a test in CI, so the review is about your *choices* (thresholds, soak time, zones), not
> about whether the machinery exists.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Environment parity** | Staging is built from the same parts as production, so "it worked in staging" means something. |
| **Overlay / component** | Kustomize layers: a base, a reusable bundle of changes (component), and one small file per environment (overlay). |
| **Promotion, gate, evidence** | Moving a tested build to the next environment; a rule that must hold first; the file that proves it held. |
| **Soak time** | How long a release must run in staging before it may go further. |
| **Change freeze, break glass** | Periods with no changes; the recorded emergency path around the rules. |
| **Canary release** | Giving a new release a small share of traffic first, comparing it with the old one, and growing its share step by step. |
| **Analysis run** | The checks Argo Rollouts runs during a canary: queries and jobs, each pass or fail. |
| **High availability (HA), failover** | Staying up when a part fails; switching to a standby automatically. |
| **Synchronous replication, quorum** | A write counts as done only when a replica also has it; "any 1 of 2 replicas" is a quorum. |
| **WAL archiving, PITR** | Postgres's write-ahead log copied to storage continuously, so you can restore to any second (point-in-time recovery). |
| **Disaster recovery (DR)** | Getting back after something HA can't absorb: a region lost, or data destroyed by mistake. |
| **Online evaluation** | Measuring quality from real use (outcomes, citations, feedback) rather than labelled test questions. |
| **Significance test** | A check that a difference is bigger than chance would explain, given how many answers you have. |
| **Production readiness** | Whether a configuration *should* run in production, not just whether it *can*. |
| **Workload identity** | Each program logs in as itself (its Kubernetes service account), with only its own permissions. |
| **Legal hold** | An instruction to keep certain records, whatever the retention rules say, while a matter is open. |

> **IN PLAIN ENGLISH · WHY "CANARY"?**
> Miners once took a canary underground: it reacted to bad air before people did. A canary release is the same
> idea: a small share of real traffic meets the new version first, so a problem shows up on 10% of requests
> instead of all of them, and the automation pulls it back before most people notice.

## How to do it

### 1 · One shape, three environments

Local keeps its overlay from Step 29. Staging and prod are new overlays on the **same base**, plus the worker
(section 7), plus two components every real environment shares.

**`deploy/envs/prod/kustomization.yaml`** takes `base/rag-api` and `base/rag-ingest`, adds the components
`managed-deps` and `production`, sets the `rag-api` image digest (the one line `just promote prod sha256:…`
changes), and patches what is specific to prod:

- `RAG_ENVIRONMENT: prod`, `RAG_API_PROMPT_LABEL: production` (which prompt versions run, Step 24), and the
  identity provider's HTTPS issuer and JWKS URL (`https://sso.example.com/realms/rag…`);
- the HorizontalPodAutoscaler: `minReplicas: 3`, `maxReplicas: 12`;
- the AnalysisTemplate's `on-insufficient` argument: `fail` (section 2).

**`deploy/envs/staging/kustomization.yaml`** is the same file with smaller numbers (`minReplicas: 2`,
`maxReplicas: 4`), the `staging` prompt label and `on-insufficient: pass`.

The **production component** (`deploy/components/production/`) holds everything that makes an environment
production-shaped, added to staging and prod alike:

| File | What it does |
|---|---|
| `kustomization.yaml` | A Kustomize `Component`: the Rollout, AnalysisTemplate and HPA, the patches below, a configuration file, and the OpenBao image digest for the analysis Job's sidecar. |
| `deployment-patch.yaml` | The Deployment keeps describing the pod (and is what the admission policies check), but gets `replicas: 0`: the Rollout runs the pods. Adds zone spreading (hard: `DoNotSchedule`) and host spreading (soft), the `production` profile, `RAG_ENVIRONMENT`, `RAG_API_RELEASE` (from the pod label `rollouts-pod-template-hash`) and `OTEL_RESOURCE_ATTRIBUTES="service.version=$(RAG_API_RELEASE),deployment.environment.name=$(RAG_ENVIRONMENT)"`; bigger requests (500m CPU, 512 Mi) and a 1 Gi memory limit. |
| `hpa.yaml` | Autoscaling on CPU (70%), targeting the **Rollout**, min 3 (one per zone), max 12, with a 5-minute scale-down window so it doesn't flap after a burst. |
| `pdb-patch.yaml` | The disruption budget changes from `minAvailable: 1` to `maxUnavailable: 1`: with 3+ pods, a drain takes one at a time. |
| `networkpolicy-patch.yaml` | Allows port 443 out: in real environments the identity provider is HTTPS, not Keycloak's local port. |
| `ingest-patch.yaml` | The worker: 2 replicas, `RAG_PROFILE=production`. |
| `cronjob-patch.yaml` | Every CronJob's container gets `RAG_PROFILE=production` (a JSON patch by position: env index 1). |
| `kustomize-config.yaml` | Teaches kustomize that an AnalysisTemplate's Job refers to a ConfigMap, so the hashed generated name is filled in there too. |
| `rollout.yaml`, `analysis-template.yaml` | Section 2. |

The **managed-deps component** (`deploy/components/managed-deps/services.yaml`) replaces local's "everything is
on your Mac" aliases with real addresses. rag-api's settings don't change; only where each name points does:

| Name rag-api uses | Points at (replace the examples with yours) |
|---|---|
| `rag-db` | `rag-db-rw.rag-data.svc.cluster.local` (CloudNativePG's read-write service, section 8) or a managed Postgres |
| `litellm` | `litellm.ai-gateway.svc.cluster.local`: the model gateway the platform team runs for every AI application |
| `opa` | `opa.policy.svc.cluster.local` |
| `openbao` | `openbao.openbao.svc.cluster.local` |
| `keycloak` | `sso.example.com`: or your company's identity provider; only the issuer and JWKS URL matter |
| `otel-collector` | `otel-collector.observability.svc.cluster.local` |

> **READING THE OVERLAYS**
> - The Deployment still describes the pod. It's what the admission policies check (Step 29). In staging and prod
>   it has `replicas: 0`: the Rollout (next section) creates the pods from its template.
> - `RAG_API_RELEASE` comes from a pod label that Argo Rollouts sets per release. It goes into `service.version`
>   on every metric (Prometheus keeps it as a label, Step 20) and into every answer's audit record, so the canary
>   and the stable release can be compared.
> - `$(VAR)` only sees variables defined *earlier* in the list; a test checks the order, because a wrong order
>   silently produces the literal text `$(RAG_API_RELEASE)`.
> - Zone spreading is a hard rule (`DoNotSchedule`) for zones and a soft one for nodes: losing a zone loses at
>   most a third of the pods.
> - The kustomize configuration teaches kustomize that an AnalysisTemplate's Job refers to a ConfigMap, so the
>   generated name with its content hash is filled in there too. Without it, the Job would point at a ConfigMap
>   that doesn't exist.

See it rendered: `just k8s-render envs/prod` (exactly what Argo CD would apply).

### 2 · Canary releases with automatic analysis

Argo Rollouts (vendored like Argo CD, Step 29) adds a `Rollout`: it reads the pod template from the Deployment
and releases each new version gradually.

**`deploy/argo-rollouts/install/kustomization.yaml`** vendors the upstream release manifest
(`upstream/install.yaml`, v1.10.1) and records its SHA-256 in a comment
(`149148429a6f…`); a test fails if the file and the hash ever disagree. `just vendor argo-rollouts v1.10.1`
fetches a release and updates the hash; the controller image is pinned by digest (`<digest>` until you fill it
in, Step 9 method).

**`deploy/components/production/rollout.yaml`**:

- `workloadRef` points at the Deployment `rag-api` (`scaleDown: progressively`), so the pod template stays in one
  place;
- `strategy.canary`: `maxSurge: 25%`, `maxUnavailable: 0`, labels `rag-platform/track: canary|stable`;
- `analysis`: the template `rag-api-canary`, from step 1 to the end, with the canary's and the stable release's
  pod-template hashes as arguments;
- `steps`: `setWeight: 10` → pause 15 min → 25 → pause 15 min → 50 → pause 30 min → 100.

```
 10% canary ──15 min──▶ 25% ──15 min──▶ 50% ──30 min──▶ 100%: stable = new
       │                                                 any check fails:
       └──────── analysis all the way through ─────────▶ canary scaled to 0, stable keeps serving,
                                                         RagCanaryAborted → revert the PR
 Analysis (canary vs stable, by service_version):
 • errors ≤ 2%   • p95 ≤ 1.25 × stable + 0.5 s   • blocked ≤ stable + 3 pts   • abstained ≤ stable + 5 pts
 • audit failures = 0
 • after 45 min, a Job runs rag online-eval on the audit log: citations, groundedness flags, thumbs down,
   with a significance test
 • too few answers = 'insufficient': prod fails safe, quiet staging passes
```
*Figure 117. A canary release.*

What "healthy" means is written down in **`deploy/components/production/analysis-template.yaml`**, as queries
that compare the canary's `service_version` with the stable one's:

| Metric | Query (in words) | Passes when | Tolerance |
|---|---|---|---|
| `error-ratio` | errors ÷ all answers on the canary, last 10 min | ≤ 0.02 | `failureLimit: 1` |
| `latency-p95` | canary p95 − (1.25 × stable p95 + 0.5 s) | ≤ 0 | `failureLimit: 1` |
| `blocked-vs-stable` | canary blocked share − stable blocked share | ≤ 0.03 | `failureLimit: 1` |
| `abstained-vs-stable` | canary abstained share − stable abstained share | ≤ 0.05 | `failureLimit: 1` |
| `audit-failures` | audit write failures on the canary, last 10 min | = 0 | `failureLimit: 0` |
| `online-eval` | a Job: `rag online-eval --since-hours 2 --candidate <canary> --baseline <stable> --limit error_rate=0.02 --on-insufficient <arg>` | exit 0 | once, after 45 min |

Each Prometheus check runs every 2 minutes. The online-evaluation Job runs as `rag-ingest` (read-only audit
access; nothing of rag-api's), with the OpenBao Agent as a native sidecar that writes `audit_reader_dsn`, the
same hardened pod settings as everything else, and the environment's own rag-api image (the release being
rolled out).

> **READING THE ANALYSIS**
> - **Compare, don't guess.** Most checks are canary *minus* stable: if both get worse (a provider outage), the
>   canary isn't blamed. The error ratio and audit failures are absolute, because no baseline makes them
>   acceptable.
> - `or vector(0)` turns "no data yet" into 0 instead of an empty result, which Argo Rollouts would treat as an
>   error.
> - `failureLimit: 1` tolerates one bad reading (noise) and aborts on the second. Audit failures abort on the first.
> - The online-evaluation Job runs `rag online-eval` (section 5) with the worker's read-only audit access. It
>   needs enough answers to compare: in prod "not enough" fails safe; in staging, which may have little traffic,
>   it passes.
> - Without a traffic router (a service mesh, or Gateway API with the Rollouts plugin) the split follows pod
>   counts. Add one when you need exact percentages or header-based testing.

### 3 · Promotion gates

What must be true before a digest moves is a file, not a meeting: **`deploy/envs/promotion.yaml`**.

| Environment | Rules |
|---|---|
| `local` | none: anything signed may run on your Mac |
| `staging` | evidence `image-verify` (signature + provenance, Step 27), `readiness` (`rag config readiness --profile production`), `search-eval` (Step 32), `guard-eval` (Step 34), `answer-eval` (Step 35); evidence at most 14 days old |
| `prod` | `from: staging` (the **same** digest must run in staging now), `soak_hours: 24` (and have for this long, from git history), the same evidence **plus `online-eval`**, `alerts_clear: {severity: critical}` (nothing that severe firing in staging), and a freeze window `2026-12-21`–`2027-01-04` ("year-end change freeze") |

Evidence is a small JSON file CI writes per check and digest, kept as a build artefact:
`{"check": …, "digest": …, "status": "pass", "created": …, "summary": …}`, named
`<first 12 hex of the digest>-<check>.json`.

**`scripts/gates.py`** enforces the file:

- `gates.py check <env> sha256:… --evidence release-evidence/ [--alertmanager URL]` returns every reason the
  promotion must not happen (an empty list = go). It checks the digest format, freezes, that the `from`
  environment runs this digest, how long it has (via `git log --first-parent -S <digest>` on the overlay: the
  merge time is what counts, because that's when Argo CD deployed it), each evidence file (present, valid JSON,
  this digest, this check, `pass`, not older than the limit), and asks Alertmanager for active, unsilenced alerts
  matching `environment="staging"` and `severity="critical"`.
- `gates.py record <check> sha256:… pass|fail --summary "…" --out release-evidence/` writes one evidence file.

The justfile gets the recipes (in the "Production (Step 37)" section):

```bash
just gates-record search-eval sha256:3f1c…9e0f pass "recall@8 0.96"     # CI records each check
just gates-evidence sha256:3f1c…9e0f                                     # run + record all five offline checks (release.yml)
just gates staging sha256:3f1c…9e0f                                       # may it go to staging?
just gates prod sha256:3f1c…9e0f release-evidence http://alertmanager.staging:9093
just promote staging sha256:3f1c…9e0f                                     # verify, gates, one-line PR
just promote prod sha256:3f1c…9e0f "INC-1234: security fix"               # break glass: gates skipped, reason recorded
```

`just promote` now runs `just image-verify`, then the gates (unless a break-glass reason is given), switches to
a `promote/<env>-<digest prefix>` branch, changes the one digest line (`scripts/promote.py`, Step 29), commits
with the gate note ("Promotion gates passed" or "GATES SKIPPED (break glass): …"), pushes and opens the pull
request. The review still happens either way.

```
$ just gates prod sha256:3f1c9a0b7e2d4c5f6a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f
BLOCKED: staging runs nothing, not this digest: promote to staging first
BLOCKED: evidence online-eval: missing (3f1c9a0b7e2d-online-eval.json)
BLOCKED: alerts can't be checked: pass --alertmanager URL
prod <- sha256:3f1c…9e0f: 3 gate(s) failed
```

> **READING THE GATES**
> - Every failed rule is listed, not just the first, so one run tells you everything missing.
> - "Soaked for 24 hours" comes from git: the newest first-parent commit that added the digest to the staging
>   overlay, i.e. when the merge deployed it. If staging went A → B → A, the clock restarts at the last A.
> - Evidence is per digest and expires (14 days): a two-month-old evaluation says little about today's index.
> - Break glass (`just promote prod sha256:… "INC-1234: why"`) skips the gates but writes the reason into the
>   commit and pull request. The review still happens.

> **TIP**
> The guide writes the break-glass form as `--override "reason"` in places; the recipe takes the reason as its
> third argument: `just promote prod sha256:… "INC-1234: why"`.

### 4 · Production readiness

`rag config validate` (Step 30) says a profile *can* be built. **Readiness** says whether it *should* run in
production. `libs/rag-core/src/rag_core/readiness.py` returns findings, each naming its slot:

| Rule | Level |
|---|---|
| `vector_store`, `keyword_index`, `manifest`, `queue`, `memory` using `memory` / `memory-bm25` ("keeps data in one process: it is lost on restart and not shared between replicas") | error |
| `llm`, `answer_llm`, `embedder` (or its `inner`) using `scripted` / `hashing` ("a test stand-in, not a model") | error |
| `pii` missing or `none` ("personal data would be stored as found") | error |
| a missing required guard: `injection`, `context-injection` (C-INJECTION), `secrets` (C-OUTPUT), `groundedness` (C-GROUND) | error |
| `pipeline.uncited: keep` ("returns answers that cite nothing as if they were sourced") | error |
| any key named like `api_key`, `password`, `secret`, `token`, `key` with a value written into the file (references `*_file` / `*_env` are fine) | error |
| any value containing a password in a URL (`scheme://user:pass@…`) | error |
| `generator: extractive`, `cache: memory`, `reranker: term-overlap`, `pipeline.stream` not `checked` | warning |

The new **`production`** profile in `rag.yaml` extends `local`, with `pipeline: {use: standard, search_k: 8,
uncited: abstain, stream: checked}` (nothing unchecked is shown) and the full guard list.

```
$ rag config readiness --profile offline
ERROR   vector_store       'memory' keeps data in one process: it is lost on restart and not shared between replicas
ERROR   keyword_index      'memory-bm25' keeps data in one process: …
ERROR   manifest           'memory' keeps data in one process: …
ERROR   queue              'memory' keeps data in one process: …
ERROR   memory             'memory' keeps data in one process: …
ERROR   llm                'scripted' is a test stand-in, not a model
ERROR   embedder           'hashing' is a test stand-in, not a model
WARNING generator          extractive copies sentences instead of writing answers: fine only if that's the product
WARNING cache              an in-process cache isn't shared by replicas and isn't cleared by `rag reacl` in other pods: use valkey
WARNING reranker           term-overlap is the offline stand-in: use a cross-encoder (gateway or tei)
WARNING pipeline           stream: live sends words before the output guards have run; use checked unless you accept that
profile 'offline': 7 error(s), 4 warning(s)            (exit 1)

$ rag config readiness --profile production
profile 'production': 0 error(s), 0 warning(s)          (exit 0)
```

It runs in `just rag-config-check` (CI, which now also validates the `production` profile) and is one of the
promotion evidence files.

### 5 · Online evaluation

The audit log (Step 23) already records each answer's outcome, citations and guard verdicts, and now its
**release** (rag-api's `_release()`: `RAG_API_RELEASE`, or `dev` outside Kubernetes); `/v1/feedback` records
thumbs up/down by answer id. `rag online-eval` joins them.

```
 rag-api ── answer: outcome, cited ids, guard verdicts, release ──▶ audit log ──▶ rag online-eval
 people ─── thumbs up/down + reason ───────────────────────────▶ (no text:      rates per release:
                                                                 ids, counts,   abstain, blocked, cited,
                                                                 verdicts)      ungrounded, thumbs down;
                                                                                z-test vs baseline
                                                                     │
                     canary verdict pass / fail / wait ◀─────────────┤──▶ review queue: answer ids to read
                     → Rollouts, gates                                         in the trace (Step 22)
 reviewed cases become labelled questions in examples/eval/*.yaml: CI catches it next time
```
*Figure 118. Online evaluation. Prometheus sees the same outcomes as metrics (fast, per pod); online-eval joins
feedback to the release that actually answered (exact, per answer).*

`libs/rag-core/src/rag_core/online.py`:

- `Stats` counts per group (answers, answered, abstained, blocked, errors, cited, ungrounded, cache hits, rated,
  thumbs down and their reasons) and gives each rate as *(numerator, denominator)*: the denominator matters for
  the test.
- `collect(events, group_by="release")` joins `answer`, `answer.completed` (streams: the completion carries the
  final result) and `feedback` events (the latest rating wins). A stream that started and never completed counts
  as an **error**. It also builds the **review queue**: answers with a thumbs down or a groundedness flag, with
  ids and reasons only. Groups can be by `release`, `prompt`, `model` or `all`.
- `compare(candidate, baseline, margin=0.02, z=1.645, min_n=50, limits=…)` fails a metric only when the candidate
  is worse by more than the margin **and** a one-sided two-proportion z-test says it's unlikely to be chance
  (95%). Fewer than `min_n` events on either side → `insufficient`. `limits` are absolute ceilings (e.g.
  `error_rate=0.02`) that apply whatever the baseline does.
- `load_jsonl(path)` reads exported events; `load_db(dsn, since_hours)` reads `audit.events` as `audit_reader`.

The command:

```
rag online-eval (--events audit.jsonl | --dsn-file F | --dsn-env V) [--since-hours 24]
                [--candidate R --baseline R] [--group-by release] [--limit error_rate=0.02]
                [--margin 0.02] [--z 1.645] [--min-n 50]
                [--on-insufficient wait|pass|fail] [--queue review.jsonl] [--json verdict.json]
```

Exit codes drive automation: **0 pass, 1 fail, 3 not enough data yet**; `--on-insufficient` maps 3 to pass or
fail. On your Mac: `just online-eval --since-hours 6` (the recipe builds `AUDIT_READER_DSN` from the
`audit_reader` password in your SOPS file, like `just audit-verify`).

**A demo without a cluster:** `examples/online_demo.py` writes a day of synthetic audit events (no question or
answer text) for a stable release and a canary whose new prompt abstains too often, then runs the command like
the canary's Job does:

```
$ uv run python examples/online_demo.py
group                    answers      error_rate    blocked_rate    abstain_rate      cited_rate ungrounded_rate   feedback_rate       down_rate
5c4b3a291                    300           0.000           0.020           0.203           1.000           0.017           0.267           0.138
7d9f8c6b5                    900           0.000           0.020           0.079           1.000           0.043           0.291           0.080

70 answer(s) to review -> /tmp/…/review.jsonl

5c4b3a291 vs 7d9f8c6b5: FAIL
   pass         error_rate         difference +0.000 (z=0.00)
   pass         blocked_rate       difference +0.000 (z=0.00)
   fail         abstain_rate       worse by 0.124 (z=5.97)
   pass         ungrounded_rate    difference -0.026 (z=-1.84)
   pass         down_rate          difference +0.057 (z=1.54)
   pass         cited_rate         difference +0.000 (z=0.00)

exit code 1          (0 pass, 1 fail, 3 not enough data yet)
```

> **READING THE OUTPUT**
> - The abstention rate fails: 20% against 8%, worse by 12 points with z = 5.97. Chance doesn't do that with 300
>   and 900 answers.
> - Thumbs down passes, although it rose from 8% to 14%. Only about 80 canary answers were rated, and z = 1.54 is
>   within what chance produces (the bar is 1.645 for 95% confidence). That's the point of the test: without it,
>   a gate trips on noise half the time, and people learn to ignore it.
> - The review queue lists 70 answer ids with the reason. Nobody reads 70 traces; sort by reason and read ten.
>   Each real problem becomes a labelled question in `examples/eval/`, and CI catches it next time.

### 6 · Alerts on answer quality

Uptime alerts (Step 20) can't see quality. **`infra/config/prometheus/rules/rag-answers.yml`** compares the last
15 minutes with the same environment's last day, so "normal" is learned per environment rather than guessed.

Recording rules: `rag:answer_outcome:ratio_rate15m` and `…_rate1d` (share of answers by outcome per
environment), `rag:answer_latency:p95_15m`, `rag:feedback_down:ratio_rate1h`.

| Alert | Fires when | For |
|---|---|---|
| `RagGuardBlocksSpike` | blocked share > 5% **and** > 3 × the daily share (an attack, or a change that trips the guards) | 10 min |
| `RagAbstentionSpike` | abstained share > 20% **and** > 2 × the daily share (a broken index, a failed ingestion, an embedder change) | 15 min |
| `RagThumbsDownHigh` | > 30% thumbs down **and** at least 20 ratings in the hour | 30 min |
| `RagAnswerLatencyHigh` | p95 answer time > 10 s | 15 min |
| `RagScheduledJobFailed` | a Job in namespace `rag` failed (needs kube-state-metrics) | — |
| `RagCanaryAborted` | a Rollout is `Degraded` (the canary failed its analysis) | — |

All are `severity: warning` with a runbook: `docs/runbooks/answer-quality.md` (and `docs/runbooks/canary.md`
for the canary).

**`infra/config/prometheus/tests/rag_answers_test.yml`** unit-tests them: a normal day (nothing fires); blocks
jumping from 2% to 20% after a quiet day (warning, abstentions quiet); abstentions from 10% to 60% (warning,
blocks quiet); 40% thumbs down of 60 ratings an hour in prod (warning) but not of 6 ratings in staging; every
answer taking 12–15 s (warning, "p95 answer time 29s").

`promtool` joins the pinned tools (`ci/tools.yaml`, checksum-verified like the others), so the alert tests run
without Docker:

```bash
just tools promtool
just alerts-test
#  Checking rules/platform.yml       SUCCESS: 2 rules found
#  Checking rules/rag-answers.yml    SUCCESS: 10 rules found
#  Checking rules/security.yml       SUCCESS: 5 rules found
#  Checking rules/slo-rag-search.yml SUCCESS: 8 rules found
#  promtool test rules tests/rules_test.yml tests/rag_answers_test.yml   SUCCESS  SUCCESS
```

> **PER POD VERSUS PER ANSWER**
> Prometheus counts thumbs down on the pod that *received the rating*, which may not be the pod that gave the
> answer. That's fine for "people are unhappy" alerts. For "is the canary worse?", online evaluation joins each
> rating to the release that actually answered.

### 7 · The worker's own identity, scheduled jobs and legal holds

Until now the ingestion worker used rag-api's identity (Step 31 said so). Now it has its own service account,
OpenBao role and policy.

| File | What it says |
|---|---|
| `deploy/base/rag-ingest/serviceaccount.yaml` | `rag-ingest`, no automatic API token. |
| `deploy/base/rag-ingest/openbao-agent.hcl` | The agent logs in with role `rag-ingest` and writes `rag_db.json` (`database/creds/rag-ingest`), `rag_api_gateway_key`, `valkey_url`, `aws_credentials`, `pii_hmac_key` (all from `secret/data/rag-ingest`) and `audit_reader_dsn` (`database/creds/audit-reader`, a read-only DSN for online evaluation). |
| `infra/config/openbao/policies/rag-ingest.hcl` | Read `database/creds/rag-ingest`, `database/creds/audit-reader`, `secret/data/rag-ingest`. Nothing of rag-api's. |
| `scripts/vault_setup.py` | New database roles `rag-ingest` (member of `rag_app`, 1 h / 24 h, 300 s statement timeout: its own name in `pg_stat_activity` and revocable on its own) and `audit-reader` (member of `audit_reader`, 1 h / 4 h, read-only); a second Kubernetes role `rag-ingest` bound to `system:serviceaccount:rag:rag-ingest`. |
| `infra/config/rag-db/init/03-openbao.sh` | `vault_admin_audit` may now hand out `audit_reader` (WITH ADMIN OPTION). |

Store the worker's secrets and re-run the setup (your admin login):

```bash
# the object-store keys and PII key the worker already used (Steps 31-32), now under its own path;
# give it its own gateway key (just gateway-admin) and Valkey user when you can, so each is revocable alone
just vault-put rag-ingest gateway_key=RAG_API_GATEWAY_KEY valkey_url=RAG_API_VALKEY_URL \
  s3_access_key=S3_INGEST_ACCESS_KEY s3_secret_key=S3_INGEST_SECRET_KEY pii_hmac_key=RAG_PII_HMAC_KEY
just vault-setup              # the rag-ingest policy and database roles
just vault-k8s-trust          # creates the rag-ingest Kubernetes role too
```

The worker and its scheduled jobs (`deploy/base/rag-ingest/`):

- **`deployment.yaml`**: `rag worker --forever` in the rag-api image (it contains the `rag` command), the OpenBao
  Agent as a native sidecar, the same hardening as rag-api, 250m / 384 Mi requested, a 1 Gi limit (parsing large
  PDFs is the peak). Scale it on queue length, not CPU.
- **`cronjobs.yaml`**: `rag-retention` at 02:17 UTC every night (`rag retention --rules /etc/rag/retention.yaml
  --apply --json`) and `rag-online-eval` at minute 7 of every hour (`rag online-eval --dsn-file
  /run/bao/audit_reader_dsn --since-hours 24 --queue /tmp/review.jsonl`). Both `concurrencyPolicy: Forbid`,
  `startingDeadlineSeconds: 3600`, 3 successful and 5 failed jobs kept, `ttlSecondsAfterFinished` one week.
- **`networkpolicy.yaml`**: nothing in; out only DNS, Postgres, LiteLLM, OpenBao, OpenTelemetry, Valkey and object
  storage (443/9000).
- **`retention.yaml`**: the rules applied nightly (same as `examples/retention.yaml`) plus a legal hold:
  `{match: "*/tickets/2025/*", matter: "LIT-2026-014 (customer dispute)", until: null}`.
- **`kustomization.yaml`**: labels, the agent and retention ConfigMaps (content-hashed), the OpenBao image digest.

Writing the CronJobs exposed a gap: the workload policy from Step 29 checked Deployments and Pods but not Jobs or
CronJobs. **`deploy/cluster/policy-workloads.yaml`** now also matches `batch/v1` `jobs` and `cronjobs`, and finds
the pod spec at `spec.jobTemplate.spec.template.spec` for a CronJob.

Step 36 listed legal holds as missing before running retention with `--apply`. With retention now scheduled,
they're in (`libs/rag-core/src/rag_core/lifecycle.py`):

- `LegalHold(match, matter, until=None)` with `active(today)`; `RetentionPolicy.legal_holds` and `hold_for(uri)`.
- `apply_retention` skips any expired source under an active hold and reports it in `report.held`
  (`{uri, matter, age_days}`; the summary says "N kept by a legal hold"). Held items are reported, not hidden.
- `erase_source(…, policy=…, override_hold="")` refuses a held source unless a reason is given, and records
  `legal_hold_overridden: {matter, reason}` in the report. On the command line:
  `rag erase-source s3://… --rules retention.yaml --override-hold "Legal: erasure request ER-77 outweighs the hold" --apply`.

> **READING THE JOBS**
> - `concurrencyPolicy: Forbid` means a slow retention run is never joined by a second one.
> - `startingDeadlineSeconds` skips a run missed by more than an hour (say, the cluster was down) instead of
>   running a backlog; the alert tells you it didn't run.
> - Native sidecars in Jobs: the OpenBao Agent starts first and stops when the job's container finishes
>   (Kubernetes 1.29+), so the job completes instead of hanging.
> - Legal holds win over every retention rule; held items are reported, not hidden. Erasing a held document
>   needs `--override-hold "reason"`: an erasure request and a hold can conflict, and that's for your legal team
>   to decide, on the record.

### 8 · High availability and disaster recovery for the database

Locally, Postgres runs in Compose (Step 11). In staging and prod, **CloudNativePG** runs it inside Kubernetes,
with its **Barman Cloud plugin** shipping backups to object storage. `deploy/cnpg/install/kustomization.yaml`
vendors both release manifests (`cnpg-1.30.1.yaml`, sha256 `37237f14…`; plugin `v0.15.1`, sha256 `8f377ff4…`),
pins the two images by digest, and needs **cert-manager** in the cluster (operator and plugin talk over
certificates).

```
   ZONE A                       ZONE B                        ZONE C                  backup bucket
   rag-api pods                 rag-api pod                   rag-api pod             (other region,
   Postgres 1                   Postgres 2                    Postgres 3               versioned +
   primary (read-write) ─sync─▶ replica (synchronous)         replica (async/quorum)   Object Lock)
            └──────────── WAL streams from the primary to both replicas ───────────┘  WAL: continuous
                                       archive: WAL + nightly base backup ───────────▶ base: nightly, 30 days
 Lose a pod or node: replaced in seconds. Lose the primary or a zone: a synchronous replica is promoted
 (~1 min, no committed write lost). Lose data by mistake: restore to the second before it into a NEW cluster.
 Lose the region: rebuild from git + the bucket.
```
*Figure 119. High availability across three zones.*

**`deploy/data/base/`** (namespace `rag-data`, its own Argo CD project):

| File | What it sets |
|---|---|
| `cluster.yaml` | `Cluster rag-db`: 3 instances; Postgres 18 minimal image and pgvector as an **extension image** (Postgres 18's `extension_control_path`), both mirrored into your registry and pinned by digest; `synchronous: {method: any, number: 1, dataDurability: required}`; `shared_buffers: 2GB`, `max_connections: 200`, `maintenance_work_mem: 1GB` (HNSW builds), slow-query log at 2 s; `initdb` of database `rag` owned by `rag_migrator` with data checksums and `CREATE EXTENSION vector`; no superuser access; 200 Gi data + 50 Gi WAL on their own `fast-ssd` volumes; 2 CPU / 8 Gi; required anti-affinity by zone; the Barman Cloud plugin as WAL archiver. |
| `objectstore.yaml` | `ObjectStore rag-db-backups`: `retentionPolicy: 30d`, `s3://example-rag-db-backups/rag-db/`, credentials from the cloud's workload identity (`inheritFromIAMRole`), WAL `zstd` × 4 in parallel, base backups `lz4` with 2 jobs. |
| `scheduled-backup.yaml` | A base backup every night at 01:30 UTC (`"0 30 1 * * *"`: six fields, seconds first) via the plugin. |
| `databases.yaml` | `Database rag-db-audit`: the audit log's database `audit` owned by `audit_migrator`, `databaseReclaimPolicy: retain` (deleting the object never drops the audit log). The roles come from the same init scripts as locally, run once as a Job by the platform team. |
| `namespace.yaml` | `rag-data`, Pod Security `restricted`. Kept apart from `rag`: the instance pods need a Kubernetes API token to elect a primary, which rag's admission policy forbids on purpose. |
| `networkpolicy.yaml` | Into the database only: rag's pods on 5432, the instances themselves (replication) on 5432, the operator (`cnpg-system`) on 8000. |

**`deploy/data/envs/staging`** patches it smaller: 2 instances, `dataDurability: preferred`, 50 Gi + 20 Gi, 500m /
2 Gi, `shared_buffers: 512MB`, `podAntiAffinityType: preferred`, backups under `staging/` kept 7 days.
**`deploy/data/envs/prod`** takes the base as it is.

> **CAUGHT BY THE SCHEMA TEST, NOT BY READING**
> The first draft compressed base backups with `zstd`. The plugin's schema allows `zstd` for WAL but not for base
> backups; the API server refused it in the test (section 11). Every operator object here is checked against the
> operator's own schema before it reaches a cluster.

**The drill restores into a new cluster at a point in time and compares, never over production.**
`deploy/data/drills/restore-cluster.yaml` is a one-instance `Cluster rag-db-drill` bootstrapped with `recovery`
from the `rag-db` backups (`externalClusters` via the plugin), with a `recoveryTarget.targetTime`.
`scripts/dr_drill.py`:

- `render(target)` fills in the time, converted to UTC (`"2026-10-13 18:59:00+10:00"` → `"2026-10-13 08:59:00+00"`),
  refuses a time without an offset, and drops the target for "the latest point the archived WAL reaches";
- `run(target)` applies it, waits until `Ready` (up to 3 h), counts rows in `rag.documents`, `rag.chunks` and
  `rag.ingest_manifest` in both clusters (with `rag.tenant = '*'` for row-level security), records the restore
  time (your **measured RTO**), and deletes the drill cluster; zero rows restored is a failure.

```bash
uv run python scripts/dr_drill.py render "2026-10-13 08:59:00+00"   # review the manifest
just dr-drill "2026-10-13 08:59:00+00"                              # monthly, against prod's backups
```

**`docs/runbooks/disaster-recovery.md`** is the table of what fails and what to do:

| What failed | What happens by itself | What you do | Data lost (RPO) | Time (RTO) |
|---|---|---|---|---|
| One rag-api / worker pod or node | Kubernetes replaces it | nothing | none | seconds |
| Postgres primary (pod, node or zone) | CloudNativePG promotes a synchronous replica, moves `rag-db-rw` | `kubectl cnpg status rag-db -n rag-data` | none | ~1 min |
| A whole zone | pods reschedule; Postgres fails over | watch capacity | none | minutes |
| Bad data (wrong delete, bad migration) | nothing: replicas copy the mistake | point-in-time restore into a NEW cluster, then switch | to the second before | 1–2 h per 100 GB |
| The region or the cluster | nothing | new cluster, Argo CD `root.yaml`, restore from the bucket | seconds–minutes | hours |
| Qdrant / OpenSearch | derived data | `rag reindex` (Step 36) | none | hours |
| Valkey | cache and memory disposable | restart; re-enqueue if needed | conversations, cached answers | minutes |

`docs/runbooks/canary.md` covers the normal canary flow, `RagCanaryAborted` (which check failed:
`kubectl -n rag describe analysisrun <name>`; revert the promotion commit), the manual controls
(`kubectl argo rollouts abort|promote --full`, break-glass) and low traffic.

> **READING THE HA SETUP**
> - `dataDurability: required` means: if no replica can confirm a write, the write *waits*. You trade availability
>   for never losing a committed write. Staging uses `preferred` (write anyway, with a warning).
> - WAL on its own volume: a full data disk can't stop archiving, and archiving is what point-in-time recovery
>   depends on.
> - The database has its own namespace and Argo CD project. CloudNativePG's instance pods need a Kubernetes API
>   token to elect a primary, which rag's policy forbids on purpose; `rag-data` keeps Pod Security "restricted"
>   and lets only rag's pods, the operator and the replicas in.
> - Images are mirrored into your registry and pinned by digest; pgvector comes as an extension image rather
>   than a custom Postgres build.

> **WATCH OUT**
> Replicas are not backups: they copy a mistake within milliseconds. Only archived WAL and base backups undo it.
> And never restore *over* production in a panic: restore next to it, check, then switch.

### 9 · Argo CD for each environment

Each environment's cluster runs its own Argo CD. The pieces every cluster shares moved to `deploy/argocd/common`
(`projects.yaml`, `argocd.yaml`, `cluster.yaml`); local's `deploy/argocd/apps` now includes `../common` plus
`rag-api-local.yaml`. Operators and the database have their own apps:

| Folder | Contents |
|---|---|
| `deploy/argocd/common/` | Projects `platform` (now also allowed into `argo-rollouts` and `cnpg-system`, and to create the operators' webhook configurations), `rag`, and the new **`data`** project: only namespace `rag-data`, only `Namespace` cluster-wide, and only CloudNativePG `Cluster` / `Database` / `ScheduledBackup`, Barman `ObjectStore` and `NetworkPolicy` inside it ("Changes need a DBA review"). |
| `deploy/argocd/operators/` | Apps `argo-rollouts` and `cnpg` (project `platform`, sync wave −1: CRDs before anything uses them; cnpg with `prune: false` so an upgrade never deletes its CRDs and every database with them). |
| `deploy/argocd/envs/<env>/` | `kustomization.yaml` (common + operators + the two apps), `rag-data.yaml` (`rag-data-<env>`, project `data`, wave 1, `prune: false`: removing it from git must never delete a database), `rag-api.yaml` (`rag-api-<env>`, project `rag`, wave 2), and `root.yaml`, the one thing you apply by hand. |

Bootstrap a new staging or prod cluster: install Argo CD (as in Step 29), add the repository secret, then
`kubectl apply -f deploy/argocd/envs/prod/root.yaml`. Everything else comes from git.

### 10 · Managed services instead (cloud mapping)

You can swap any self-run piece for a managed service with the same interface;
`docs/architecture/cloud-mapping.md` has the full table (Kubernetes → EKS/GKE/AKS; Postgres + pgvector →
CloudNativePG or RDS/Aurora, Cloud SQL/AlloyDB, Azure Flexible; Qdrant → Qdrant Cloud; OpenSearch → Amazon
OpenSearch, Elastic Cloud, Azure AI Search (a different API: its own adapter and conformance run); object storage
→ S3 Object Lock, bucket lock, immutable Blob; Valkey → ElastiCache/Memorystore/Azure Cache; Keycloak → your IdP;
OpenBao → Secrets Manager/Secret Manager/Key Vault + workload identity; LiteLLM + Bedrock/Vertex/Azure OpenAI as
providers; models → vLLM/TGI or Bedrock/Vertex/Azure OpenAI; TEI → provider embeddings (changing the embedder =
`rag reindex`); Prometheus/Grafana, Tempo/Loki → managed equivalents with no text in logs; Langfuse stays
self-run; Argo CD + Rollouts or Flux + Flagger). Data residency applies to backups too: a cross-region copy needs
the same legal basis as the original.

### 11 · Test it

```bash
just tools promtool kubectl kube-apiserver etcd
just k8s-check            # every overlay renders; staging and prod against a real API server
just alerts-test
just audit-test           # everything
```

- **`tests/test_environments.py`** renders staging and prod with the real kustomize and sends them to a real API
  server (`tests/kube.py`) with the Argo Rollouts, CloudNativePG and Barman Cloud CRDs installed:
  every pod template (Deployments, CronJobs, the analysis Job) pinned, hardened and on the production profile;
  the worker, the jobs and the analysis Job on `rag-ingest`, its agent asking only for paths its policy allows;
  releases are canaries with analysis, the env var order is right and 443 is open; prod spreads over zones and
  keeps capacity; the database is HA with PITR; the vendored manifests match their hashes; every analysis query
  is valid PromQL (`promtool`, with the arguments filled in); the alert rules and their tests pass; the DR drill
  renders a point-in-time restore and never over production; each Argo CD app renders and stays inside its
  project; staging, prod, both database tiers and the drill manifest are accepted with strict field validation;
  a typo in a Rollout (`pauze`) is refused; an unhardened CronJob is refused by `rag-workloads-hardened`.
- **`tests/test_gates.py`** builds a copy of `deploy/envs` in its own git repository and checks: staging needs
  every offline check; evidence must be for this digest, passing and fresh; prod needs the same digest in
  staging; the soak period (and its restart after A → B → A); online evaluation and no critical alert; the change
  freeze; every overlay has rules; the CLI.
- **`libs/rag-core/tests/test_online.py`**: events joined per release with no text needed (streams completed or
  not, ratings stored as text); a clearly worse canary fails on abstentions and a similar one passes; too few
  answers is "insufficient"; absolute limits; CLI exit codes 3/0/1; the review queue and verdict files.
- **`libs/rag-core/tests/test_readiness.py`**: the production profile is ready; offline isn't and says why; each
  rule; secret references are fine; the CLI.
- **`libs/rag-core/tests/test_lifecycle.py`**: a legal hold wins over retention (and the deployed rules file
  parses); erasure under a hold needs a recorded override.
- **`tests/test_vault.py::test_the_ingestion_worker_has_its_own_identity`** against a real OpenBao and
  kube-apiserver: the worker gets its own leases (`v-kubernet-rag-inge-…`, 5 min timeout) and secrets, read-only
  audit access, none of rag-api's; neither service account can use the other's role.
- `services/rag-api/tests/test_answer_api.py::test_every_answer_record_names_the_release`.

> **WHAT THE TESTS PROVE**
> - Staging and prod are accepted by a real Kubernetes API server with Pod Security "restricted", our admission
>   policies and the schemas of Argo Rollouts, CloudNativePG and Barman Cloud, with strict field validation (a
>   misspelt field fails).
> - Every pod is pinned, hardened and uses the production profile, including CronJobs and the analysis Job; an
>   unhardened CronJob is refused.
> - Releases are canaries with analysis; every analysis query is valid PromQL; the alert rules pass their unit tests.
> - Each Argo CD app stays inside its project, and its path renders.
> - The database has three instances across zones, synchronous commit, WAL archiving and 30-day recovery; the DR
>   drill restores to a given second, never over production.
> - The gates refuse missing, failing, stale or wrong-digest evidence, a digest not in staging, an unfinished soak
>   (restarted by a rollback), firing alerts and change freezes.
> - Online evaluation joins streams and feedback correctly, fails a clearly worse canary, passes a similar one,
>   and says "insufficient" rather than guessing.
> - Readiness catches stand-ins, missing guards, inline secrets and passwords in URLs.
> - The worker's identity works against a real OpenBao: it gets its own leases and secrets and none of rag-api's,
>   and neither account can log in as the other.
> - Legal holds keep held documents through retention and make erasure need a recorded override.

### 12 · Record the decision

`docs/adr/0037-production-environments-canaries-and-recovery.md` (ADR-0037) records the decision: staging and
prod overlays on one base with a shared production component; Argo Rollouts canaries with Prometheus checks and
an online-evaluation Job; promotion rules enforced by `scripts/gates.py` with recorded break glass;
CloudNativePG over three zones with quorum synchronous commit, WAL archiving, nightly base backups to a locked
bucket in another region, 30-day PITR and monthly drills; readiness and online evaluation in rag-core; quality
alerts with tests; the worker's own identity; legal holds. Alternatives: blue/green, Flagger, managed Postgres,
manual checklists. Revisit when a service mesh is adopted, traffic allows per-tenant canaries, or the
organisation standardises on a managed database.

The risk register (`docs/compliance/risk-register.yaml`) gains five controls with tests as evidence:
**C-PROMOTION**, **C-CANARY**, **C-ONLINE-EVAL**, **C-HA-DR** and **C-WORKLOAD-ID**; C-LIFECYCLE now includes legal
holds. `just compliance-docs` regenerated the threat model and controls pages (19 threats, 30 controls).

## Benefits

- Releases that prove themselves, with evidence attached to the exact digest.
- Small blast radius and automatic rollback for bad releases.
- Quality monitored in production, per release, with a loop back into the evaluation sets.
- No lost writes on failover; recovery to the second after a mistake, practised monthly.
- Least privilege between workloads, checked against a real OpenBao.
- Configuration that can't silently ship test stand-ins.
- Everything in git and tested, so environments don't drift and reviews are about choices.

## Drawbacks and risks

- **Not run against a real cluster here.** The manifests are checked by a real API server with the operators'
  schemas, but no controller ran: the canary flow, CloudNativePG failover, backups and the DR drill must be
  exercised in your staging cluster before you rely on them.
- Operators are new dependencies to upgrade and monitor; the Barman Cloud plugin also needs cert-manager.
- Synchronous commit with `required` durability stops writes if no replica is healthy: ingestion pauses (searches
  continue). That's deliberate; be ready for the alert.
- Canary comparisons need traffic. At low volume, "insufficient" is the honest answer; prod treats it as a failure.
- Metrics per pod vs answers per release: use online evaluation, not Prometheus, for feedback by release.
- Placeholders to fill: registry names and digests, hostnames, storage classes, bucket names, Prometheus address.
- More environments cost money; a smaller staging is fine as long as its *shape* matches prod.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Blue/green deployment | Run old and new side by side, switch all traffic at once | Very small services, or when canaries can't get enough traffic |
| Flagger | Canary automation driven by a service mesh or ingress | You already run Istio, Linkerd or an ingress Flagger supports |
| Feature flags (OpenFeature, LaunchDarkly, Unleash) | Turn behaviour on for a share of users inside one release | Testing prompts or architectures per user cohort |
| Shadow traffic / mirroring | Send a copy of real requests to the new release, discard its answers | Comparing a new model without any user seeing it |
| Managed Postgres (RDS/Aurora, Cloud SQL/AlloyDB, Azure Flexible Server) | The provider runs HA and backups | Your organisation standardises on it and its pgvector version suffices |
| Patroni / Crunchy PGO / StackGres | Other Postgres HA operators | You already run one |
| pgBackRest / WAL-G | Backup tools with PITR | Postgres outside Kubernetes |
| Velero | Backs up Kubernetes objects and volumes | Recovering whole namespaces, alongside database-native backups |
| Multi-region active/passive | A warm standby cluster in another region | RTO of minutes for a region loss |
| KEDA | Autoscaling on any metric (queue length, request rate) | Scaling the worker on queue depth, rag-api on requests |
| LLM-judge sampling online | A judge model grades a sample of live answers | You need quality signals beyond feedback (cost and privacy permitting) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Internal assistant, modest traffic | Canary with long pauses; insufficient → staging pass, prod fail; synthetic traffic during rollouts |
| Customer-facing, high traffic | Canary with a traffic router; shorter pauses; per-tenant analysis |
| Prompt or architecture experiments | Feature flags per cohort, measured with online evaluation by prompt (`--group-by prompt`) |
| Regulated data, strict RPO | `dataDurability: required`, backups in another region with Object Lock, monthly drills |
| Cloud-first organisation | Managed Postgres and cache via managed-deps; keep CNPG manifests as the portable reference |
| Many tenants with different risk | Separate clusters or namespaces per tier; same overlays with different components |

## Common mistakes

- Staging that isn't production-shaped (one replica, no canary, no guards): it proves nothing.
- Promoting a digest that never ran in staging, or one that ran for ten minutes.
- Canary checks that only look at errors and latency: a RAG system usually fails by answering *worse*, not by crashing.
- Comparing rates without a significance test, then ignoring the gate after it cries wolf.
- Replicas called "backups": they copy mistakes instantly. Only archived WAL and base backups undo them.
- Restoring over production in a panic. Restore next to it, check, then switch.
- One identity for every workload.
- Retention that ignores legal holds.

## Done when

- [ ] `just k8s-check` passes: every overlay renders and staging/prod are accepted with the operators' schemas
- [ ] `just alerts-test` passes, including the answer-quality rules
- [ ] `rag config readiness --profile production` reports 0 errors
- [ ] `uv run python examples/online_demo.py` fails the canary on abstentions and explains why
- [ ] Your CI records evidence for each digest; `just gates staging sha256:…` passes for a real build
- [ ] In a real staging cluster: a canary rolls out, an intentionally bad release is aborted, `just dr-drill`
      restores and reports its time
- [ ] Placeholders (registry, hostnames, storage class, bucket, Prometheus address) are filled in
- [ ] `just audit-test` passes
- [ ] ADR-0037 is committed

## Recap

> **RECAP**
> The platform now has a path to production that catches what tests can't:
> - staging and prod with the same shape; a production profile that passes readiness
> - canary releases compared with the stable release and aborted automatically
> - promotion gates with evidence, soak time, online evaluation, alerts and freezes
> - online evaluation and quality alerts, feeding new labelled questions
> - three-zone Postgres with synchronous replication, point-in-time recovery and a DR drill
> - a separate identity for the worker and its scheduled jobs, with legal holds
>
> Next, Step 38, the last: turning all of this into a reuse kit so the next RAG project starts here: a project
> template, a small SDK over rag-core, the standards checklist, a catalogue of every option, and the wrap-up.

## What was added to the repo in this step

**Kubernetes: environments and components**

| File | Purpose |
|---|---|
| `deploy/envs/staging/kustomization.yaml`, `deploy/envs/prod/kustomization.yaml` | The two new environments: rag-api + worker, both components, the digest line, per-environment settings and sizes. |
| `deploy/components/production/*` | Rollout, AnalysisTemplate, HPA and the patches that make an environment production-shaped (zones, PDB, release id, 443 egress, production profile for worker and jobs, kustomize name references). |
| `deploy/components/managed-deps/*` | ExternalName Services pointing rag-api's names at real services. |
| `deploy/base/rag-ingest/*` | The ingestion worker, nightly retention and hourly online-evaluation CronJobs, network policy, OpenBao Agent config, retention rules with a legal hold, all as `rag-ingest`. |
| `deploy/cluster/policy-workloads.yaml` (changed) | The hardening policy now also covers Jobs and CronJobs. |
| `deploy/argo-rollouts/install/*` | Argo Rollouts v1.10.1, vendored with its SHA-256, its namespace, image pinned by digest. |
| `deploy/cnpg/install/*` | CloudNativePG 1.30.1 and the Barman Cloud plugin v0.15.1, vendored with SHA-256s, images pinned. |
| `deploy/data/base/*`, `deploy/data/envs/{staging,prod}` | The three-zone Postgres cluster, backups object store, nightly backup, audit database, namespace and network policy; staging's smaller patch. |
| `deploy/data/drills/restore-cluster.yaml` | The point-in-time restore cluster used by the DR drill. |
| `deploy/argocd/common/*` (moved from `apps/`, plus the `data` project) | What every cluster's Argo CD manages. |
| `deploy/argocd/operators/*` | Argo CD apps for the two operators. |
| `deploy/argocd/envs/{staging,prod}/*` | Each environment's Argo CD apps and its `root.yaml`. |
| `deploy/argocd/apps/kustomization.yaml` (changed) | Local now builds on `../common`. |
| `deploy/envs/promotion.yaml` | The promotion rules per environment. |

**Scripts, code and configuration**

| File | Purpose |
|---|---|
| `scripts/gates.py` | Checks the promotion rules (evidence, soak from git, alerts, freezes) and records evidence. |
| `scripts/dr_drill.py` | Renders and runs the point-in-time restore drill, measuring RTO. |
| `scripts/vault_setup.py` (changed) | `rag-ingest` and `audit-reader` database roles, the `rag-ingest` Kubernetes role. |
| `scripts/ci_tools.py` (changed) | An archive member may be named per platform (promtool). |
| `infra/config/openbao/policies/rag-ingest.hcl` | What the worker and jobs may read in OpenBao. |
| `infra/config/rag-db/init/03-openbao.sh` (changed) | Lets OpenBao hand out `audit_reader` leases. |
| `libs/rag-core/src/rag_core/readiness.py` | Production readiness rules for a profile. |
| `libs/rag-core/src/rag_core/online.py` | Online evaluation: join, rates, significance test, review queue. |
| `libs/rag-core/src/rag_core/cli.py` (changed) | `rag config readiness`, `rag online-eval`, `erase-source --rules/--override-hold`, held items in reports. |
| `libs/rag-core/src/rag_core/lifecycle.py` (changed) | Legal holds in retention and erasure. |
| `services/rag-api/src/rag_api/main.py` (changed) | The release on every answer's audit record. |
| `rag.yaml` (changed) | The `production` profile. |
| `examples/online_demo.py` | Online evaluation end to end on synthetic audit events. |
| `infra/config/prometheus/rules/rag-answers.yml` | Answer-quality recording rules and six alerts. |
| `infra/config/prometheus/tests/rag_answers_test.yml` | Five promtool unit tests for them. |
| `ci/tools.yaml` (changed), `.github/workflows/ci.yml` (changed) | promtool 3.13.4 as a pinned, checksum-verified tool, installed in CI. |
| `justfile` (changed) | `gates`, `gates-record`, `gates-evidence`, `online-eval`, `dr-drill`, `vendor`; `promote` runs the gates (break glass); `alerts-test` with pinned promtool; `rag-config-check` with readiness; `k8s-check` and `k8s-scan` cover the new folders; `k8s-bootstrap` uses `common/projects.yaml`. |
| `.pre-commit-config.yaml`, `.gitleaks.toml`, `.trivyignore.yaml`, `.gitignore` (changed) | Allow the vendored operator manifests (size, an image name in a Secret), accept a Trivy false positive on agent templates, and stop ignoring `deploy/data/`. |

**Tests**

| File | Purpose |
|---|---|
| `tests/test_environments.py` | Staging, prod, the database tier, the drill and each Argo CD app, statically and against a real API server with the operators' CRDs. |
| `tests/test_gates.py` | The promotion gates against real git history. |
| `libs/rag-core/tests/test_online.py`, `test_readiness.py` | Online evaluation and readiness. |
| `libs/rag-core/tests/test_lifecycle.py` (changed) | Legal holds. |
| `tests/test_vault.py`, `tests/test_k8s.py`, `tests/test_monitoring.py`, `tests/test_ci_tools.py`, `services/rag-api/tests/test_answer_api.py` (changed) | The worker's identity against real OpenBao; two Kubernetes roles and three Argo CD projects; the new rules; per-platform archive members; the release on answer records. |

**Documentation**

| File | Purpose |
|---|---|
| `docs/runbooks/answer-quality.md`, `canary.md`, `disaster-recovery.md` | What to do for each quality alert, an aborted canary, and every kind of failure up to a lost region. |
| `docs/architecture/cloud-mapping.md` | Managed equivalents per cloud and what to keep in mind. |
| `docs/compliance/risk-register.yaml` (+ regenerated `controls.md`, `docs/security/threat-model.md`) | Five new controls, legal holds under C-LIFECYCLE. |
| `docs/adr/0037-production-environments-canaries-and-recovery.md` | ADR-0037. |
| `docs/steps/step-37-production-environments-canaries-ha-dr.md` | This write-up. |

## Notes for this repository

- **Evidence is recorded by CI.** The chapter says CI writes the evidence files but shows no workflow change.
  Here `release.yml` has a read-only `evidence` job after `publish`: on the image's commit it runs
  `just gates-evidence <digest>` (an addition: it runs `image-verify`, `rag config readiness --profile
  production`, `search-eval`, `guard-eval` and `answer-eval`, and records each result, pass or fail, with
  `gates.py record`), then uploads `release-evidence/` as the `release-evidence` artefact. `online-eval` stays
  a manual record from staging. `tests/test_gates.py` checks the wiring and runs the recipe with stand-in
  `cosign`/`gh`; `release-evidence/` is git-ignored.
- **Vendored manifests are the real upstream files.** `deploy/argo-rollouts/install/upstream/install.yaml`,
  `deploy/cnpg/install/upstream/cnpg.yaml` and `barman-cloud.yaml` were downloaded from the projects' GitHub
  releases; their SHA-256s match the ones the guide records. They are large, so the large-file hook excludes
  them, and gitleaks allowlists the Barman manifest (its only `Secret` holds the base64 *image name*
  `ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar:v0.15.1`). The sidecar image named there is a tag: mirror
  and pin it with the other images.
- **Placeholders stay placeholders.** Image digests (`sha256:<digest>`), `ghcr.io/owner/…`, `sso.example.com`,
  `example-rag-db-backups`, `fast-ssd` and `prometheus.monitoring.svc:9090` are examples to replace; tests fill the
  digests with zeros, as in Step 29.
- **`.gitignore` ignored every `data/` folder** (Step 4, for datasets). `deploy/data/` holds manifests, so it is
  now un-ignored explicitly.
- **Argo CD layout:** the guide says the shared pieces "moved to `deploy/argocd/common`"; local's
  `deploy/argocd/apps` therefore became `../common` + `rag-api-local.yaml` (local's root app is unchanged), and the
  Step 29 test now expects three projects (`data`, `platform`, `rag`). The operators' Applications, each
  environment's `rag-api-<env>` Application and `root.yaml`, and the platform project's extra destinations and
  webhook kinds were written to make the guide's "every app stays inside its project" test pass; their full text
  isn't printed in the guide.
- **Files the guide describes but doesn't print** were written to match: the staging overlay (prod with smaller
  numbers, `staging` label, `on-insufficient: pass`), the managed-deps kustomization, the Argo Rollouts namespace
  (`baseline` enforced, like Argo CD's), the prod database overlay (the base unchanged), the online-evaluation CLI
  options beyond those shown (`--margin`, `--z`, `--min-n`, `--group-by`), `rag erase-source --rules` (where legal
  holds are read from), and the `test_lifecycle` / `test_vault` tests the guide lists by name.
- **`just online-eval`** sets `AUDIT_READER_DSN` from the existing `AUDIT_DB_READER_PASSWORD` (as the audit
  anchor and verify recipes do); the guide's recipe expects an `AUDIT_READER_DSN` line in the SOPS file instead.
- **The promote recipe keeps Step 29's `git push` and `gh pr create`.** The guide's Step 37 listing ends at the
  commit, but its text says the break-glass reason goes "into the commit and pull request".
- **Break glass syntax:** the recipe takes the reason as the third positional argument
  (`just promote prod sha256:… "INC-1234: why"`), as the guide's recipe does, though some prose writes `--override`.
- **`.trivyignore.yaml`** accepts KSV-0109 for the OpenBao Agent ConfigMaps (templates naming where secrets live,
  no values), found when `just k8s-scan` was extended to staging, prod and the database tier.
- **`audit_reader` leases** need `GRANT audit_reader TO vault_admin_audit WITH ADMIN OPTION` (added to
  `03-openbao.sh`). On an existing database volume, run that one statement as the superuser
  (`just db-psql`; role grants are cluster-wide) before `just vault-setup`.
- **Dynamic usernames are truncated** by OpenBao (`v-kubernet-rag-inge-…`), so the identity test looks for
  `-rag-inge-`.
- **Validated here:** `kubectl kustomize` for every new kustomization; kubeconform (strict); the envtest
  kube-apiserver with the operators' CRDs (all of `tests/test_environments.py` and `tests/test_k8s.py` pass);
  promtool 3.13.4 (rules and both test files); `trivy config` on staging, prod and the database tier; the OpenBao
  tests against a real OpenBao 2.7.1 and a throwaway Postgres; ruff, mypy strict, pre-commit, the full pytest
  suite. Not exercised: real Argo Rollouts / CloudNativePG controllers, a canary, a failover or a restore (they
  need a cluster with nodes, storage and a bucket).
- **Pre-existing, unrelated:** the three `tests/test_backup.py` tests fail in this container because its
  `pg_dump` is version 16 and the test Postgres is 17; they pass with matching client tools (Homebrew `libpq`).
