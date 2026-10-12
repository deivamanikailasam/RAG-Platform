# Step 10 · Budgets, rate limits and fallbacks

*Step 10 of 38 · Phase B · Model serving*

## At a glance

| | |
|---|---|
| **Goal** | Give the gateway a memory and a rulebook: its own Postgres database; teams and per-app virtual keys, each limited to approved models, with rate and concurrency limits and an expiry; budgets priced with internal shadow prices; and fallbacks that keep answers flowing when a model server fails. |
| **Time** | About 90 minutes. |
| **You'll end up with** | A private, unexposed gateway database with a written access policy; three app keys (RAG API, ingestion, evaluation) with the master key back to admin-only; a script that proves every control works; a fallback drill, a shadow-pricing method, and ADR-0010. |
| **New words** | Virtual key, team, allow-list, rate limit (RPM/TPM), concurrency limit, budget, budget period, shadow price, showback/chargeback, FinOps, fallback, retry, cooldown, graceful degradation, least privilege, blast radius, salt key. |

## The big idea

> **ANALOGY · COMPANY CARDS INSTEAD OF THE BOSS'S CREDIT CARD**
> In Step 9, every app borrowed the boss's credit card (the master key): unlimited, untracked per person, and a
> disaster if lost. Now each app gets its own company card:
>
> - usable only in approved shops (allowed models)
> - with a spending limit per month (budget)
> - a limit on how fast it can be swiped (rate limits)
> - an expiry date
> - a statement showing every purchase (spend logs)
>
> Cards belong to departments (teams) with their own budgets. And if a shop is closed, there's a backup shop
> (fallback). The boss's card goes back in the safe.

## What we're doing

1. Add a small, private Postgres just for the gateway (never published to your Mac).
2. Give the gateway its database URL and a salt key, both from encrypted secrets.
3. Set shadow prices for the local models, so budgets and spend reports mean something.
4. Configure retries, cooldowns and fallbacks, including where *not* to fall back.
5. Create teams and virtual keys for each app, following a written access policy.
6. Run a script that proves the allow-list, rate limit and budget each reject requests.
7. Run a fallback drill: stop a model server and watch requests keep succeeding.
8. Look at usage and spend per key and team, then write ADR-0010.

## Why we're doing this

> **WHY THIS MATTERS**
> One shared all-powerful key means one leak exposes everything, one runaway script can starve every other app of
> GPU time, and nobody can say which app used what. Per-app keys with limits apply least privilege and shrink the
> blast radius. Shadow prices make usage visible and comparable. Fallbacks turn a model outage into a slower answer
> instead of an error page.

| Risk without this step | Control added |
|---|---|
| A leaked key can use every model, forever | Per-app keys: approved models only, expiry, can be blocked instantly |
| A buggy loop or evaluation run hogs the GPU | RPM/TPM and max parallel requests per key |
| No idea what each app costs or uses | Spend tracking per key, team and model, priced with shadow prices |
| Runaway usage goes unnoticed until the month ends | Budgets per team (and optionally per key) that reject requests when exceeded |
| One model server crash takes the product down | Retries, cooldown and fallbacks to another model |
| Silent wrong results after a "helpful" fallback | Explicit rule: never fall back between embedders |

> **IN A COMPANY**
> This is AI FinOps and access governance. Platform teams issue keys per application and environment, allocate
> budgets to cost centres, show each team its usage (showback) or bill it (chargeback), and review access
> quarterly. Auditors check that credentials are scoped, expiring, revocable and logged. Everything here maps to
> those controls.

## Key ideas

*(Guide Figure 30, "Who holds what". At the top, the **master key**: admin only, locked in secrets. Below it two
teams: **rag-apps** with a budget of $50 per 30 days (shadow price) and **evaluation** with $200 per 30 days. Under
rag-apps sit the keys **rag-api-dev** (chat, embed, rerank; 60 rpm; 4 parallel) and **ingestion-dev** (embedder and
qwen-fast; high tpm; 8 parallel). Under evaluation sits **eval-harness** (all four models, budget-capped). Each key
has allowed models, rpm/tpm, max parallel, budget and expiry, and every call's spend is recorded per key, team and
model, feeding showback reports.)*

| Term | Plain-English meaning |
|---|---|
| Virtual key | A gateway-issued key for one app and environment, with its own rules. Stored (hashed) in the gateway's database. |
| Team | A group of keys sharing a budget and model list, e.g. a department or product. |
| Allow-list | The only models a key may use; anything else is refused. |
| RPM / TPM | Requests per minute / tokens per minute allowed for a key. |
| Max parallel requests | How many requests a key may have in flight at once. Crucial on one shared GPU. |
| Budget / budget period | Maximum spend before requests are refused, and how often it resets (e.g. `30d`). |
| Shadow price | An internal, notional price for something that has no bill, like your own Mac's GPU time, so usage can be compared and budgeted. |
| Showback / chargeback | Showing teams what they used / actually billing them for it. |
| Retry | Trying the same model again after a temporary error. |
| Cooldown | Temporarily skipping a backend that keeps failing, so requests stop piling onto it. |
| Fallback | Sending the request to a different model when the first one fails. |
| Graceful degradation | Continuing with reduced quality or features instead of failing completely. |
| Least privilege / blast radius | Give each identity only what it needs / how much damage one leaked credential can do. |
| Salt key | A secret LiteLLM uses to encrypt credentials stored in its database. Must never change. |

### Virtual keys and teams

> **IN PLAIN ENGLISH**
> A virtual key is a key the gateway makes up and hands to one app. The gateway keeps only a fingerprint (hash) of
> it in its database, together with the rules for that key: which models, how fast, how much, until when. A team is
> a folder of keys that share one budget and one list of models.

Because the gateway now has a database, it can remember these keys between restarts, count what each one spends,
and block any one of them instantly without touching the others or the master key.

### The gates every request passes

*(Guide Figure 31, "The order of checks". Six gates from left to right: **key valid?** (not blocked, not expired) →
**model allowed?** (on this key's list) → **within limits?** (rpm, tpm, parallel) → **within budget?** (key + team
spend) → **route + call** (retry → fallback) → **record spend** (tokens × shadow price). The first gate that fails
rejects the request with a clear status code: **401** for a bad key, **401/403** for a model not on the allow-list,
**429** for rate limits, and a **400 budget** error for spend.)*

Every request passes the same gates in order. That order matters: a blocked key never reaches the rate limiter,
and a request over its rate limit never costs any GPU time.

### Shadow pricing: putting a price on "free"

Your local models cost nothing per request, and LiteLLM **skips budget checks for zero-cost models**. Without a
price, budgets can't work and nobody can compare usage. So we set shadow prices that reflect what really is scarce
on your Mac: GPU time.

> **THE SHADOW-PRICE FORMULA**
> Pick a notional hourly rate for your GPU (e.g. $2/hour: roughly what renting comparable GPU time might cost; the
> exact number matters less than using it consistently). Then, from your Step 7 benchmarks:
>
> - output price per token = hourly rate ÷ (3,600 × decode tokens per second)
> - input price per token = hourly rate ÷ (3,600 × prefill tokens per second)
>
> Example: if the 27B model decodes at 20 tok/s, its output price is 2 ÷ 72,000 ≈ $0.0000278 per token (~$27.8 per
> million). If the fast MoE model decodes at 80 tok/s, it's ≈ $0.0000069 (~$6.9 per million). Now "this app used 3×
> more GPU than that one" becomes visible in dollars.

Why it works: a token that takes the GPU longer to produce costs more. The slow, careful 27B model therefore gets a
higher price per token than the fast MoE model, and prefill (reading the prompt, which is much faster per token
than writing the answer) gets a lower price than decode.

### Fallbacks: where they help, and where they're dangerous

*(Guide Figure 32. A request for `model="qwen-fast"` goes to qwen-fast on :8082. If it is down, times out or errors,
the gateway **retries once**, then puts it in **cooldown** (skips it for 30 s) and **falls back** to qwen-quality,
which is slower but answers. Underneath, two warnings: **embedder: NO fallback to another model**, because a
different embedder means a different vector space and its vectors can't be compared with the index (Step 8); and
**reranker: degrade gracefully in the app**: if it fails, keep the embedder's order and flag the answer as
"reranking skipped" (Capstone).)*

- **Chat models** are interchangeable enough: a question answered by the other Qwen model is still a correct
  answer, maybe slower or a little weaker.
- **Embedders are not interchangeable.** Vectors from another embedding model live in a different "meaning space";
  comparing them with the vectors in your index gives nonsense results, with no error. That is the Step 8 embedding
  contract. An embedding failure must be a visible error.
- **The reranker** only re-orders results that are already good enough. If it fails, the application keeps the
  embedder's order and says so; there is nothing for the gateway to fall back to.

## How to do it

On your Mac, in the repository:

```bash
cd ~/dev/rag-platform
git switch -c feat/gateway-governance
```

### 1 · Add the new secrets

```bash
openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-32; echo     # for LITELLM_DB_PASSWORD (letters/digits only: safe inside a URL)
openssl rand -hex 32                                            # for LITELLM_SALT_KEY
just secrets-edit          # add:  LITELLM_DB_PASSWORD=<first value>  and  LITELLM_SALT_KEY=<second value>
just secrets-keys | grep -E 'LITELLM_(DB_PASSWORD|SALT_KEY)'
```

On a fresh machine you don't need to do this by hand: `scripts/new-dev-secrets.sh` (`just secrets-init`) now
generates both values too, and `.env.example` lists the names.

> **WATCH OUT · THE SALT KEY IS FOREVER**
> LiteLLM uses `LITELLM_SALT_KEY` to encrypt credentials it stores in its database. Change it later and those
> become unreadable. It's in your encrypted secrets (backed up with your age key, Step 6). Never rotate it casually;
> if you ever must, plan it as a migration.

### 2 · Add the gateway's private database

`infra/compose/compose.yaml` gains the `litellm-db` service, LiteLLM is connected to it, and the new volume and
secrets are declared:

```yaml
services:
  litellm-db:
    image: postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24   # pin by digest (Step 9 method)
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD_FILE: /run/secrets/litellm_db_password   # official image reads the password from a file
    secrets: [litellm_db_password]
    volumes:
      - litellm-db-data:/var/lib/postgresql/data              # named volume (Step 3): fast, survives restarts
    # NO "ports:" section. Only containers on this Compose network can reach it.
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U litellm -d litellm"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 512m, cpus: "1" }

  litellm:
    # …everything from Step 9, with these changes:
    command:
      - >
        export LITELLM_MASTER_KEY="$$(cat /run/secrets/litellm_master_key)"
        TEI_API_KEY="$$(cat /run/secrets/tei_api_key)"
        LITELLM_SALT_KEY="$$(cat /run/secrets/litellm_salt_key)"
        DATABASE_URL="postgresql://litellm:$$(cat /run/secrets/litellm_db_password)@litellm-db:5432/litellm" &&
        exec litellm --config /app/config.yaml --host 0.0.0.0 --port 4000
    secrets: [litellm_master_key, tei_api_key, litellm_salt_key, litellm_db_password]
    depends_on:
      litellm-db:
        condition: service_healthy                            # don't start until the database answers

volumes:
  litellm-db-data:

secrets:
  # …existing entries, plus:
  litellm_salt_key:
    environment: LITELLM_SALT_KEY
  litellm_db_password:
    environment: LITELLM_DB_PASSWORD
```

The same wrapper from Step 9 reads the secret *files* and exports them only inside the LiteLLM process, so neither
the salt key nor the database password appears in `docker inspect`. `depends_on … service_healthy` makes Compose
wait for `pg_isready` before starting LiteLLM, so its first start doesn't fail on a database that is still booting.

> **WHY A SEPARATE DATABASE JUST FOR THE GATEWAY?**
> The gateway's data (keys, budgets, spend logs) and your RAG data (documents, vectors, from Step 11) have different
> owners, sensitivity, backup needs and retention rules. Keeping them apart means a problem in one can't corrupt the
> other, and access can be granted separately. This is the blast-radius idea applied to data.

> **WHY POSTGRES:17?**
> Newer major versions can change where data is stored inside the container (Postgres 18's official image moved its
> data directory). Stay on the version this guide uses, and treat major upgrades as a planned migration. You'll do
> one deliberately in the Capstone.

### 3 · Shadow prices, retries, cooldown and fallbacks

Fill in your own prices from your Step 7 benchmarks, using the formula above. Then update the gateway config
`infra/config/litellm/config.yaml`:

```yaml
model_list:
  - model_name: qwen-quality
    litellm_params:
      model: openai/mlx-community/Qwen3.8-27B-8bit
      api_base: http://host.docker.internal:8081/v1
      api_key: "not-used"
      timeout: 600
    model_info:
      mode: chat
      input_cost_per_token: 0.0000028     # shadow price: $2/h ÷ (3600 × prefill tok/s), see docs/finops
      output_cost_per_token: 0.0000278    # shadow price: $2/h ÷ (3600 × decode tok/s)

  - model_name: qwen-fast
    litellm_params:
      model: openai/lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit
      api_base: http://host.docker.internal:8082/v1
      api_key: "not-used"
      timeout: 120
    model_info:
      mode: chat
      input_cost_per_token: 0.0000007
      output_cost_per_token: 0.0000069

  - model_name: embedder
    litellm_params:
      model: openai/qwen3-embedding-0.6b
      api_base: http://host.docker.internal:8083/v1
      api_key: os.environ/TEI_API_KEY
    model_info:
      mode: embedding
      input_cost_per_token: 0.00000002    # cheap, but not zero, so heavy indexing still shows up
      output_cost_per_token: 0

  - model_name: reranker
    litellm_params:
      model: huggingface/BAAI/bge-reranker-v2-m3
      api_base: http://host.docker.internal:8084
      api_key: os.environ/TEI_API_KEY
    model_info:
      mode: rerank

litellm_settings:
  drop_params: true
  request_timeout: 600
  num_retries: 1                  # retry the same model once on a transient error
  allowed_fails: 3                # after 3 failures in a minute…
  cooldown_time: 30               # …skip that backend for 30 seconds
  fallbacks:                      # chat models back each other up
    - qwen-fast: [qwen-quality]   # fast is down → slower but correct answers
    - qwen-quality: [qwen-fast]   # quality is down → faster, possibly weaker answers
  # NO fallback for embedder: another embedder = another vector space (Step 8 contract)
  # NO fallback for reranker: the app skips reranking instead (graceful degradation)

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  store_model_in_db: false        # models are defined ONLY in this git-reviewed file, never in the UI
```

> **WHY `store_model_in_db: false`?**
> LiteLLM can let admins add models from its web UI. That's convenient, but it creates changes nobody reviewed and
> that aren't in git. Keeping models only in this file means every model change goes through a pull request, the
> same governance as code.

Write the method down for your future self and for auditors in **`docs/finops/shadow-pricing.md`**: the notional
GPU rate ($2.00 per hour, reviewed yearly, changes recorded there and in an ADR), the two formulas, where the tok/s
numbers come from (`docs/benchmarks/models.md`, re-priced after major model or mlx-lm changes), and a table per model
role (decode tok/s, prefill tok/s, output $/token, input $/token). The embedder has no decode; the reranker is left
at 0 (budget checks skipped).

### 4 · Start the stack and check the database

```bash
just up                                     # first start runs LiteLLM's database migrations: give it a minute
just ps                                     # both services healthy
just logs litellm                           # look for successful DB connection; Ctrl+C to stop
lsof -nP -iTCP -sTCP:LISTEN | grep 5432     # should print NOTHING: the database is not exposed to your Mac
```

> **TIP**
> To look inside the gateway database, don't publish its port; open a shell in the container instead:
> `docker compose -f infra/compose/compose.yaml exec litellm-db psql -U litellm`.

### 5 · Write the access policy, then create teams and keys

Decide who gets what on paper first. That's what an auditor will ask for. The policy lives in
**`docs/security/gateway-access-policy.md`**:

| Team | Budget | Period | Key alias | Allowed models | RPM | Max parallel | Expires | Owner |
|---|---|---|---|---|---|---|---|---|
| rag-apps | $50 | 30d | rag-api-dev | qwen-quality, qwen-fast, embedder, reranker | 60 | 4 | 90d | `<you>` |
| rag-apps | (team) | | ingestion-dev | embedder, qwen-fast | 600 | 8 | 90d | `<you>` |
| evaluation | $200 | 30d | eval-harness | qwen-quality, qwen-fast, embedder, reranker | 120 | 4 | 90d | `<you>` |

Rules:

- Master key: admin tasks only, never in application config.
- One key per application per environment; keys expire and are re-issued, not extended forever.
- New keys or wider access require a PR updating this file.
- Quarterly review: block unused keys, check spend against budgets.

A small admin tool, **`scripts/gateway_admin.py`**, wraps LiteLLM's management API with the master key. It has four
commands:

| Command | What it does | LiteLLM endpoint |
|---|---|---|
| `team <alias> --budget N [--period 30d] --models …` | Creates a team with a budget that resets every period; prints its `team_id`. | `POST /team/new` |
| `key <alias> --team-id ID --models … [--rpm] [--tpm] [--parallel] [--budget] [--expires 90d]` | Creates a virtual key in a team; options you leave out are not sent, so no limit is set for them. Prints the key **once**. | `POST /key/generate` |
| `info <key>` | Shows a key's alias, team, models, spend, budget, limits, expiry and blocked state. | `GET /key/info` |
| `block <key>` | Blocks a key immediately. | `POST /key/block` |

Two new `just` recipes run the tools with the secrets decrypted in memory only:

```make
# Gateway administration (master key, decrypted in memory)
gateway-admin *args:
    sops exec-env secrets/dev.enc.env 'uv run scripts/gateway_admin.py {{args}}'

# Prove the gateway's controls work (creates and blocks throwaway keys)
gateway-test:
    sops exec-env secrets/dev.enc.env 'uv run scripts/gateway_limits_test.py'
```

Create the teams and keys from the policy:

```bash
just gateway-admin team rag-apps   --budget 50  --models qwen-quality qwen-fast embedder reranker
just gateway-admin team evaluation --budget 200 --models qwen-quality qwen-fast embedder reranker
# copy each printed team_id into the commands below

just gateway-admin key rag-api-dev   --team-id <rag-apps-id>   --models qwen-quality qwen-fast embedder reranker --rpm 60  --parallel 4
just gateway-admin key ingestion-dev --team-id <rag-apps-id>   --models embedder qwen-fast --rpm 600 --parallel 8
just gateway-admin key eval-harness  --team-id <evaluation-id> --models qwen-quality qwen-fast embedder reranker --rpm 120 --parallel 4

just secrets-edit     # store each printed key: RAG_API_GATEWAY_KEY=…  INGESTION_GATEWAY_KEY=…  EVAL_GATEWAY_KEY=…
```

> **WATCH OUT · KEYS ARE SHOWN ONCE**
> LiteLLM stores only a hash of each virtual key, so it can check a key but can't show it again. Copy each key
> straight into `secrets/dev.enc.env`. If one is lost, block it and issue a new one.

### 6 · Prove the controls work

**`scripts/gateway_limits_test.py`** creates two throwaway teams (`test-limits` with a $100 budget, `test-budget`
with $0.0005) and two one-hour keys limited to `qwen-fast`, then checks:

1. **Allow-list:** asking for `qwen-quality` with a qwen-fast-only key → expect 401/403.
2. **Rate limit:** three quick calls with a key limited to 2 RPM → expect 200, 200, 429.
3. **Budget:** up to six 200-token calls on the tiny-budget key, three seconds apart (spend is recorded slightly
   after each call) → expect some 200s, then a budget rejection.

Finally it blocks both test keys.

```bash
just gateway-test
```

> **WHAT A PASS LOOKS LIKE**
> 1. The allow-list refuses a model the key isn't approved for.
> 2. The third request inside a minute gets 429 Too Many Requests.
> 3. After roughly one priced call, the tiny-budget key is refused with a budget exceeded error.
>
> If check 3 never fails, your prices are zero, or spend hasn't been written yet. Check the config's `model_info`
> prices, then run the test again.

### 7 · Fallback drill

```bash
launchctl bootout gui/$(id -u)/com.rag-platform.qwen-fast      # simulate the fast model crashing
just with-secrets 'curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $RAG_API_GATEWAY_KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"qwen-fast\",\"max_tokens\":30,\"messages\":[{\"role\":\"user\",\"content\":\"Say hello\"}]}" \
  | jq "{answer: .choices[0].message.content, served_by: .model}"'
just logs litellm          # look for the failed call to :8082 and the fallback to qwen-quality
just models-up             # bring the fast model back
```

> **READ THE ANSWER'S MODEL FIELD AND THE LOGS**
> The request asked for `qwen-fast`, but the answer was produced by the quality model. You'll see the fallback
> recorded in the gateway logs, and in Step 22's traces. Fallbacks are invisible to users, but must never be
> invisible to you: a fallback that fires constantly is an outage in disguise.

### 8 · See usage and spend

```bash
just with-secrets 'uv run scripts/gateway_admin.py info "$RAG_API_GATEWAY_KEY"'   # spend, limits, expiry for the RAG key
open http://127.0.0.1:4000/ui        # LiteLLM admin UI: keys, teams, spend per model (admin = master key)
```

> **WATCH OUT · THE UI IS AN ADMIN TOOL**
> It shows every key and all spend, so it's reachable only on localhost (port 4000 is bound to `127.0.0.1`). Some UI
> features in LiteLLM are enterprise-licensed; everything this step needs works through the API.

### 9 · Record the decision: ADR-0010, then merge

```bash
just adr "Govern model access with virtual keys, budgets, shadow prices and fallbacks"
```

[`docs/adr/0010-govern-model-access-with-virtual-keys-budgets-shadow-prices-and-fallbacks.md`](../adr/0010-govern-model-access-with-virtual-keys-budgets-shadow-prices-and-fallbacks.md)
records the decision: a dedicated, unpublished Postgres; teams with budgets and per-app virtual keys per the access
policy, master key admin-only; shadow prices from benchmarks; chat-only fallbacks (1 retry, 30 s cooldown after 3
fails a minute), never for embedder or reranker; models only in `config.yaml`. Rejected: the master key everywhere,
sharing the RAG Postgres, zero prices, and embedder fallback.

```bash
git add -A
git status            # check: no keys in any file except secrets/dev.enc.env (encrypted)
git commit -m "feat(gateway): virtual keys, team budgets, shadow pricing, rate limits and fallbacks"
git push -u origin feat/gateway-governance
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Least privilege by default:** each app sees only its models, at limited speed, until an expiry date.
- **Instant containment:** block a key and only that app stops. Nothing else needs changing.
- **Fair sharing of one GPU:** rate and concurrency limits stop one job starving the others.
- **Usage you can reason about:** shadow prices turn tokens into comparable costs per app, team and model, ready
  for capacity planning.
- **Resilience:** retries, cooldowns and fallbacks keep chat working through a single model failure.
- **Audit-ready:** a written access policy, a reviewed config, a proven-controls test, and an ADR.

## Drawbacks and risks

- **Another stateful service.** The gateway database must be backed up and upgraded carefully; losing it loses keys,
  teams and spend history.
- **Shadow prices are judgement calls.** They're only useful if derived consistently and kept current. Stale prices
  give misleading reports.
- **Fallbacks can hide problems.** A permanently down model can go unnoticed if the fallback always succeeds. Alert
  on fallback rate (Step 20).
- **Quality changes during fallback.** qwen-fast standing in for qwen-quality may give weaker answers. Some products
  should show a notice or refuse instead.
- **Budget enforcement isn't instant.** Spend is recorded just after each call, so a key can slightly overshoot its
  budget.
- **Key sprawl.** Without expiry and reviews, old keys accumulate. That's why keys expire and the policy has a
  quarterly review.

## Alternatives

| Area | Our choice | Alternatives | Choose the alternative when |
|---|---|---|---|
| Key management | LiteLLM virtual keys | API gateway keys (Kong, Apigee); OAuth client credentials via Keycloak (Step 17) | The company already manages all API access centrally |
| Rate limiting | Per-key RPM/TPM/parallel in LiteLLM | Redis-backed limits across replicas; Envoy/Kong rate limits | Several gateway replicas need shared counters (LiteLLM can use Redis, Step 15) |
| Cost visibility | Shadow prices + spend logs | Real cloud bills; OpenCost/Kubecost for GPU clusters; FinOps platforms | Cloud or Kubernetes deployments with real invoices |
| Fallbacks | Gateway-level between chat models | App-level fallback logic; circuit breakers in the client (Capstone) | The app needs to know and tell the user, or choose differently per task |
| State store | Dedicated Postgres | Shared Postgres with separate DB and user | Small setups where one well-run server is simpler |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| One developer, several apps on one Mac | Per-app keys + rate/parallel limits + shadow prices (this step) |
| Several teams sharing a model platform | Teams with budgets + showback reports, quarterly access reviews |
| Cloud models with real invoices | Real prices (LiteLLM's built-in price list), hard budgets and alerts, chargeback |
| Safety-critical answers (medical, legal) | No silent fallback to a weaker model: fail clearly, or tell the user (Step 34) |
| Strict audit requirements | Keys tied to identities (Keycloak, Step 17), every call traced (Step 22), audit log (Step 23) |

## Common mistakes

- **Leaving local models at zero cost.** Budgets silently never trigger.
- **Falling back between embedding models.** Retrieval quality collapses with no error.
- **Exposing the gateway database port "for debugging".** Use `docker compose exec litellm-db psql -U litellm`
  instead.
- **Rotating `LITELLM_SALT_KEY`.** Stored credentials become unreadable.
- **Creating keys without expiry, or sharing one key between apps.**
- **Managing models in the UI.** Changes bypass git review; keep `store_model_in_db: false`.
- **Not alerting on fallbacks,** so a dead model goes unnoticed for weeks.

## Done when

- [ ] `litellm-db` runs healthy, with no published port (`lsof … | grep 5432` prints nothing).
- [ ] `LITELLM_DB_PASSWORD` and `LITELLM_SALT_KEY` are in encrypted secrets; the gateway starts with the database.
- [ ] `config.yaml` has shadow prices, retries, cooldown, chat fallbacks (no embedder/reranker fallback) and
      `store_model_in_db: false`.
- [ ] `docs/finops/shadow-pricing.md` shows your derivation from real benchmarks.
- [ ] `docs/security/gateway-access-policy.md` lists teams, keys, limits, owners and review rules.
- [ ] Teams `rag-apps` and `evaluation`, and keys `rag-api-dev`, `ingestion-dev`, `eval-harness`, exist; keys are
      stored encrypted.
- [ ] `just gateway-test` shows allow-list 401/403, rate limit 429, and a budget rejection.
- [ ] The fallback drill answered a `qwen-fast` request via `qwen-quality`, and you found it in the logs.
- [ ] ADR-0010 and all files are merged through a PR.

## Recap

> **RECAP**
> The gateway now governs model access like an enterprise platform:
>
> - scoped, expiring per-app keys under team budgets
> - rate and concurrency limits that share one GPU fairly
> - shadow prices that make free local models measurable
> - fallbacks that keep chat alive, but never where they'd silently break correctness
>
> Phase B is complete: models are served, measured, secured and governed. Phase C builds the data layer, starting
> with Postgres + pgvector in Step 11.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/compose/compose.yaml` (changed) | Adds the private, digest-pinned `litellm-db` Postgres 17 (no port, named volume, healthcheck, hardening, limits) and wires LiteLLM to it with `DATABASE_URL` and `LITELLM_SALT_KEY` from secret files. |
| `infra/config/litellm/config.yaml` (changed) | Shadow prices for both chat models and the embedder, retries, cooldown, chat-only fallbacks, and `store_model_in_db: false`. |
| `scripts/new-dev-secrets.sh` (changed) | Also generates `LITELLM_DB_PASSWORD` (URL-safe) and `LITELLM_SALT_KEY` for new machines. |
| `.env.example` (changed) | Documents the two new secrets and the three per-app key names (`RAG_API_GATEWAY_KEY`, `INGESTION_GATEWAY_KEY`, `EVAL_GATEWAY_KEY`). |
| `docs/finops/shadow-pricing.md` | The shadow-pricing method, the notional GPU rate and the per-model price table. |
| `docs/security/gateway-access-policy.md` | The written access policy: teams, budgets, keys, allowed models, limits, expiry, owners and review rules. |
| `scripts/gateway_admin.py` | Admin tool for LiteLLM teams and virtual keys (`team`, `key`, `info`, `block`) using the master key. |
| `scripts/gateway_limits_test.py` | Proves the allow-list, rate limit and budget each reject requests, using throwaway keys it then blocks. |
| `justfile` (changed) | `gateway-admin` and `gateway-test` recipes, run with secrets decrypted in memory. |
| `tests/test_gateway_governance.py` | Checks the database, secrets, prices (against the pricing doc's formula), fallback and policy rules, and runs both scripts against a fake LiteLLM management API. |
| `tests/test_gateway.py` (changed) | The Step 9 checks relaxed to allow the new secrets and settings. |
| `docs/adr/0010-govern-model-access-with-virtual-keys-budgets-shadow-prices-and-fallbacks.md` | ADR-0010: the decision, alternatives, consequences and when to revisit. |
| `docs/adr/README.md` (changed) | ADR-0010 added to the index. |
| `docs/steps/step-10-budgets-rate-limits-fallbacks.md` | This write-up. |
| `docs/steps/README.md`, `docs/glossary.md`, `CHANGELOG.md` (changed) | Step index row, the new glossary terms, and the changelog entry. |

## Notes for this repository

- **The Postgres digest is real.** The guide leaves `<digest>`; here the registry was asked for the
  `postgres:17-alpine` multi-platform index on 2026-10-12 and returned `sha256:b0f9560a…2b24`, which `compose.yaml`
  pins. Re-resolve it (Step 9 method) when you upgrade, and treat a major-version change as a migration.
- **Shadow prices are the guide's worked example, not measurements.** `docs/benchmarks/models.md` has no numbers
  yet (no Apple GPU in this environment), so the pricing table uses the guide's example speeds (20 / 80 tok/s decode,
  about 10× that for prefill) which reproduce exactly the prices in the config. A test checks that every price in the
  config matches the pricing table *and* the formula, so when you re-price from your own benchmarks, update both
  together or the test fails.
- **Reranker price.** The guide's table leaves the reranker at 0 ("budget checks skipped"); the pricing doc explains
  why and how to give it a per-call price later.
- **Owner column.** `<you>` in the access policy is filled in with the repository owner, `deivamanikailasam`.
- **No real keys anywhere.** The teams and virtual keys only exist in a running gateway's database, and the keys go
  into `secrets/dev.enc.env` (encrypted, not shipped in this repository; see `secrets/README.md`). Only their names
  are in `.env.example`.
- **The secrets generator** was extended so a new machine gets `LITELLM_DB_PASSWORD` and `LITELLM_SALT_KEY` from
  `just secrets-init`; the guide's manual `openssl` + `just secrets-edit` route is still the way to add them to an
  existing file.
- **Script tweaks for strict mypy and ruff.** Both scripts are the guide's, with type parameters on `dict`
  (`dict[str, Any]`), a `cast`/`str()` where JSON values are returned, the `# noqa: S310` comment also on the
  `Request(...)` line, and long statements wrapped by the formatter. Behaviour and output lines are unchanged.
- **Step 9 tests relaxed.** Two Step 9 assertions compared the whole secrets list and the whole `litellm_settings`
  block; they now check the Step 9 parts only, and `tests/test_gateway_governance.py` checks the Step 10 additions.
- **What was validated here (Linux container, no Mac, no model servers).** `docker compose config` resolves the
  file. The real `litellm-db` service was started from the pinned digest (pulled through the `mirror.gcr.io` mirror)
  together with a stand-in for the LiteLLM container running the exact secrets wrapper: the database became healthy,
  `psql "$DATABASE_URL"` connected as `litellm` to database `litellm` (PostgreSQL 17.11), the salt key arrived
  (64 characters), `docker port` showed no published port, and `docker inspect … .Config.Env` contained no secret.
  LiteLLM itself could not be started (its image layers are blocked by this container's network), so the database
  migrations, the real allow-list/429/budget responses and the fallback drill must be run on the Mac. Both scripts
  run end to end against a fake LiteLLM management API (teams, keys, 401 for a model outside the allow-list, 429
  over RPM, 400 budget exceeded after spend is recorded, blocking). ruff, strict mypy and the whole test suite pass.
