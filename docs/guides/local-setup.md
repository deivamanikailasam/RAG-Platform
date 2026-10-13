# Local setup: from a new Mac to a working RAG platform

> **IN PLAIN ENGLISH**
> This guide takes you from an empty Apple Silicon Mac to the whole platform running on your desk:
> two language models and two search models running natively on the Mac's GPU, about twenty
> supporting services (databases, search engines, sign-in, policy, monitoring, audit, secrets) running
> in containers, the sample company handbook loaded, and you asking it questions and getting cited
> answers. It then shows how to run the same quality checks CI runs, and how to put the API on a local
> Kubernetes cluster managed by Argo CD. Every command below exists in this repository's
> [`justfile`](../../justfile) or scripts; each stage ends with a check so you know it worked before
> you move on.

This is the "do it all in one sitting" version of Steps 1–38. Each stage links to the step write-up
that explains *why*; read those when something here is surprising. For the path beyond your laptop,
see [production-promotion.md](production-promotion.md).

Contents: [What you need](#1-what-you-need) · [Ports](#2-ports-at-a-glance) ·
[Stage A · workstation](#stage-a--the-workstation-steps-15) · [Stage B · secrets](#stage-b--secrets-step-6) ·
[Stage C · models](#stage-c--models-on-the-gpu-steps-78) · [Stage D · data stores](#stage-d--the-data-stores-steps-1115) ·
[Stage E · gateway](#stage-e--the-model-gateway-steps-910) · [Stage F · identity and policy](#stage-f--identity-and-policy-steps-1618) ·
[Stage G · observability](#stage-g--observability-steps-1922) · [Stage H · audit](#stage-h--the-audit-log-step-23) ·
[Stage I · OpenBao](#stage-i--openbao-the-secrets-manager-step-28) · [Stage J · the API and the worker](#stage-j--rag-api-and-the-ingestion-worker-steps-17-3133) ·
[Stage K · ingest and ask](#stage-k--ingest-the-sample-corpus-and-ask-questions-steps-3135) ·
[Stage L · quality gates](#stage-l--evaluations-guards-and-ci-locally-steps-2427-3238) ·
[Stage M · Kubernetes](#stage-m--local-kubernetes-with-orbstack-and-argo-cd-step-29) ·
[Daily use](#daily-use-after-a-restart) · [Stop and reset](#stopping-and-resetting) ·
[Troubleshooting](#troubleshooting) · [Linux and other machines](#linux-and-other-machines)

---

## 1. What you need

### Hardware

The guide is written for, and measured on, a **MacBook Pro M5 Max with 128 GB unified memory**
(Apple Silicon). On Apple Silicon the CPU and GPU share one memory pool, so the models, the container
VM and macOS all draw from the same 128 GB. The guide's planning budget
([Step 3](../steps/step-03-container-runtime.md)):

| Consumer | Approximate memory |
|---|---|
| `qwen-quality` (Qwen3.8-27B, 8-bit) | ~28–30 GB |
| `qwen-fast` (Qwen3.6-35B-A3B, 4-bit, mixture of experts) | ~19–21 GB |
| Embedder + reranker (TEI) | ~2–4 GB |
| KV-cache headroom (long conversations) | ~10–20 GB |
| macOS, browser, IDE | ~12–16 GB |
| Linux VM for containers (OrbStack) | 24 GB to start, up to 32 GB |

**Disk.** The downloaded model files alone are about **50 GB** (in `~/.cache/huggingface/hub/`), plus
container images and the data volumes. Leave plenty of free space; `docker system df` shows what the
containers use.

> **WATCH OUT · SMALLER MACHINES**
> With less memory, serve smaller models: change `quality_model` / `fast_model` at the top of the
> `justfile`, the matching entries in [`infra/model-serving/models.yaml`](../../infra/model-serving/models.yaml)
> and the backends in [`infra/config/litellm/config.yaml`](../../infra/config/litellm/config.yaml).
> Applications never notice: they only ever ask for the role names `qwen-quality`, `qwen-fast`,
> `embedder` and `reranker` ([ADR-0009](../adr/0009-route-all-model-access-through-a-litellm-gateway.md)).
> The guide has not measured smaller setups; benchmark with `just bench` and record the numbers in
> [`docs/benchmarks/models.md`](../benchmarks/models.md).

### Software and accounts

| What | Why |
|---|---|
| macOS on Apple Silicon, an admin account | Homebrew needs admin rights once; MLX needs Apple Silicon |
| A GitHub account | The repository, CI, signed images (Step 27), Argo CD (Step 29) |
| A Hugging Face account and access token | Downloading the models (Step 7); stored in the macOS Keychain, never in a file |
| About a day | The guide's steps add up to far more, because they teach; this guide only builds |

You **do not** need anything installed beforehand: Stage A installs it.

---

## 2. Ports at a glance

Everything is published on **127.0.0.1 only** (the Step 3 rule): nothing on your Mac is reachable
from the network. From inside a container, use the service name instead (for example `http://litellm:4000`).

| Port | What | Runs | Step |
|---|---|---|---|
| 8081 | `qwen-quality` model server (mlx-lm) | native (launchd) | 7 |
| 8082 | `qwen-fast` model server (mlx-lm) | native (launchd) | 7 |
| 8083 / 9083 | Embedder (TEI) / its metrics | native (launchd) | 8 |
| 8084 / 9084 | Reranker (TEI) / its metrics | native (launchd) | 8 |
| 4000 | LiteLLM gateway (`/ui` admin page) | `litellm` | 9, 10 |
| 5432 | Postgres + pgvector: databases `rag` and `audit` | `rag-db` | 11, 23 |
| 6333 / 6334 | Qdrant REST (+ `/dashboard`) / gRPC | `qdrant` | 12 |
| 9200 | OpenSearch (HTTPS, self-signed in dev) | `opensearch` | 13 |
| 8333 | S3 object store (SeaweedFS) | `object-store` | 14 |
| 6379 | Valkey (cache, queues, locks) | `valkey` | 15 |
| 8180 | Keycloak (admin console `/admin/`) | `keycloak` | 16 |
| 8000 | rag-api (`/healthz`, `/v1/me`, `/v1/search`, `/v1/answer`, `/v1/feedback`) | `rag-api` | 17, 33 |
| 8181 | OPA (token required) | `opa` | 18 |
| 4317 / 4318 / 13133 / 24224 | OpenTelemetry Collector: OTLP gRPC / OTLP HTTP / health / container logs | `otel-collector` | 19, 21 |
| 9090 | Prometheus | `prometheus` | 20 |
| 9093 | Alertmanager | `alertmanager` | 20 |
| 3000 | Grafana (user `admin`) | `grafana` | 20 |
| 3200 | Tempo (traces API) | `tempo` | 21 |
| 3100 | Loki (logs API) | `loki` | 21 |
| 3002 | Langfuse (LLM traces UI) | `langfuse-web` | 22 |
| 8200 | OpenBao (secrets manager) | `openbao` | 28 |
| 8443 | Argo CD UI (only while `just argocd-ui` runs a port-forward) | Kubernetes | 29 |
| 55432 | Throwaway test Postgres (only while `just audit-test` runs) | `docker run` | 23 |

`lsof -nP -iTCP -sTCP:LISTEN` lists everything listening, if a port is already taken.

---

## Stage A · The workstation (Steps 1–5)

**1. Command-line tools and Homebrew** ([Step 1](../steps/step-01-homebrew-brewfile.md)):

```bash
xcode-select --install                                     # Apple's compilers and headers
curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o /tmp/brew-install.sh
less /tmp/brew-install.sh                                   # skim what it does, then q
/bin/bash /tmp/brew-install.sh
```

Put Homebrew and direnv into your shell: copy the lines from
[`bootstrap/home/.zprofile`](../../bootstrap/home/.zprofile) into `~/.zprofile` and from
[`bootstrap/home/.zshrc`](../../bootstrap/home/.zshrc) into `~/.zshrc`, then open a new terminal.
`brew analytics off` stops usage statistics.

**2. Get the repository.** The guide keeps it at `~/dev/rag-platform`; this repository *is* that folder.

```bash
mkdir -p ~/dev && cd ~/dev
git clone git@github.com:<owner>/rag-platform.git      # or https://…; SSH works after step 5 below
cd rag-platform
```

**3. Install every tool on the list** ([`bootstrap/Brewfile`](../../bootstrap/Brewfile)): git, gh, jq,
yq, just, direnv, uv, OrbStack, dive, age, sops, TEI, dbmate, awscli, opa, regal, libpq, kubectl, argocd.

```bash
just bootstrap            # = brew bundle --file=bootstrap/Brewfile
brew bundle check --file=bootstrap/Brewfile    # "The Brewfile's dependencies are satisfied."
```

(If `just` isn't installed yet, run `brew bundle --file=bootstrap/Brewfile` directly the first time.)

**4. Python with uv** ([Step 2](../steps/step-02-python-uv.md)):

```bash
mkdir -p ~/.config/uv && cp bootstrap/home/.config/uv/uv.toml ~/.config/uv/uv.toml   # only uv-managed Pythons
uv python install 3.12
just sync                 # = uv sync --all-packages: every workspace member, from uv.lock
```

**5. Git identity, SSH key, signed commits** ([Step 4](../steps/step-04-repository-git-adrs.md)): the
chapter's commands are scripted in [`bootstrap/git-setup.sh`](../../bootstrap/git-setup.sh):

```bash
GIT_NAME="Your Name" GIT_EMAIL="12345678+you@users.noreply.github.com" bash bootstrap/git-setup.sh
CHECK_ONLY=1 bash bootstrap/git-setup.sh       # show the current state
```

Reference copies of the resulting `~/.gitconfig` and `~/.ssh/config` are in
[`bootstrap/home/`](../../bootstrap/home/).

**6. OrbStack: memory cap, CPU, log rotation** ([Step 3](../steps/step-03-container-runtime.md)). Open
OrbStack once (it finishes installing), then:

```bash
bash bootstrap/orbstack-setup.sh                         # memory 24 GB, 8 CPUs, logs 10 MB x 3
VM_MEMORY_MIB=32768 bash bootstrap/orbstack-setup.sh     # later, only if docker stats shows pressure
```

**7. Code-quality hooks** ([Step 5](../steps/step-05-linting-formatting-pre-commit.md)):

```bash
just install-hooks        # pre-commit, commit-msg and pre-push hooks, once per clone
```

**Check Stage A:**

```bash
docker run --rm alpine uname -m        # aarch64: native arm64 containers
orb config show                        # memory_mib: 24576, cpu: 8
uv run python --version                # Python 3.12.x
just test                              # the unit tests pass (services not needed)
```

---

## Stage B · Secrets (Step 6)

> **IN PLAIN ENGLISH**
> Every password and key the platform uses is generated randomly on your machine and kept in one
> encrypted file, `secrets/dev.enc.env`. The names are readable; the values are not. Commands get the
> values only in memory, for one run. Nothing is ever written in clear text.

Full detail: [Step 6](../steps/step-06-local-secrets.md), [`secrets/README.md`](../../secrets/README.md),
[ADR-0006](../adr/0006-manage-dev-secrets-with-sops-and-age-personal-tokens-in-keychain.md).

```bash
# 1. Your age key pair (once per machine). Back up keys.txt somewhere safe and offline.
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt       # prints: Public key: age1...
chmod 600 ~/.config/sops/age/keys.txt

# 2. Put the PUBLIC key into .sops.yaml in place of age1REPLACE_WITH_YOUR_PUBLIC_KEY
age-keygen -y ~/.config/sops/age/keys.txt       # prints it again

# 3. Let direnv load the project settings (.envrc holds no values)
direnv allow

# 4. Generate every service's secret, encrypted immediately
just secrets-init                               # = scripts/new-dev-secrets.sh -> secrets/dev.enc.env
just secrets-keys                               # names only, never values

# 5. Your Hugging Face token goes into the macOS Keychain, not a file
security add-generic-password -a "$USER" -s "rag-platform/HF_TOKEN" -w    # paste the token when asked
direnv allow                                     # .envrc now exports HF_TOKEN from the Keychain
```

`just secrets-init` generates all the database, search-engine, object-store, Valkey, Keycloak, OPA,
LiteLLM, TEI, Grafana, Langfuse, audit, OpenBao, PII and backup values listed in
[`.env.example`](../../.env.example). Four groups of values are **added later by hand**, because they
only exist once something else is running:

| Name(s) | Added in | How |
|---|---|---|
| `RAG_API_GATEWAY_KEY`, `INGESTION_GATEWAY_KEY`, `EVAL_GATEWAY_KEY` | Stage E | Printed once by `just gateway-admin key …` |
| `GHCR_USER`, `GHCR_READ_TOKEN`, `ARGOCD_DEPLOY_KEY` | Stage M | Your GitHub user, a read-only package token, a deploy key |

**How to read one value** (for example a UI password): `just secrets-edit` opens the decrypted file in
your editor; read it and close **without saving**. Never run `sops -d … > .env`.

**Check Stage B:** `head -3 secrets/dev.enc.env` shows `ENC[AES256_GCM,…]` values; `git add
secrets/dev.enc.env .sops.yaml` passes the `secrets-encrypted` hook. Commit both (they are safe to
commit; your private key is not, and never leaves `~/.config/sops/age/`).

---

## Stage C · Models on the GPU (Steps 7–8)

> **IN PLAIN ENGLISH**
> Containers on a Mac can't use the GPU, so the four model servers run directly on macOS and are kept
> alive by launchd (macOS's service manager). Everything else reaches them through the gateway.

Detail: [Step 7](../steps/step-07-model-serving-mlx-lm.md), [Step 8](../steps/step-08-embedding-reranker-servers.md),
[ADR-0004](../adr/0004-orbstack-native-models-containerised-services.md),
[ADR-0007](../adr/0007-serve-local-models-natively-with-mlx-lm-behind-localhost.md),
[ADR-0008](../adr/0008-serve-embeddings-and-reranking-with-tei-natively-behind-an-api-key.md).

```bash
uv run --project infra/model-serving hf auth whoami      # uses HF_TOKEN from the Keychain
just models-download            # the two chat models (~50 GB with the others; takes a while)
just search-models-download     # Qwen3-Embedding-0.6B and bge-reranker-v2-m3
```

Record the exact revisions you downloaded (the 40-character SHA) in
[`infra/model-serving/models.yaml`](../../infra/model-serving/models.yaml), replacing the
`<40-char SHA…>` placeholders, together with the size and the licence you confirmed:

```bash
ls ~/.cache/huggingface/hub/models--mlx-community--Qwen3.8-27B-8bit/snapshots/
```

Try each server in the foreground first (Ctrl+C stops it), then install them as always-on services:

```bash
just serve-fast                 # optional foreground test; then Ctrl+C
just models-up                  # launchd agents for qwen-quality (:8081) and qwen-fast (:8082)
just search-models-up           # launchd agents for the embedder (:8083) and reranker (:8084)
```

**Check Stage C:**

```bash
just health                     # all four: "ok"
just bench                      # time to first token and tokens/s; compare docs/benchmarks/models.md
just embed-demo                 # instruction vs none, Matryoshka truncation, reranking (needs TEI_API_KEY)
just models-logs                # follow the model logs if something is DOWN
```

---

## Stage D · The data stores (Steps 11–15)

From here on, services start from one Compose file, [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml)
(project name `rag-platform`). `just up` starts **everything**; on a brand-new machine start them in
stages instead, because later services depend on keys you create along the way. To start named services
with the secrets in memory:

```bash
just with-secrets docker compose -f infra/compose/compose.yaml up -d <service> [<service> …]
```

**1. The Collector first** (every container sends its logs to it; Step 21), then the stores:

```bash
just with-secrets docker compose -f infra/compose/compose.yaml up -d otel-collector
just with-secrets docker compose -f infra/compose/compose.yaml up -d rag-db qdrant opensearch object-store valkey
just ps                          # wait until each shows (healthy); OpenSearch takes ~1 minute
```

A **new** `rag-db` volume runs the init scripts in
[`infra/config/rag-db/init/`](../../infra/config/rag-db/init/) by itself: the `rag` schema and roles
(`01-roles.sh`), the `audit` database and roles (`02-audit.sh`), and OpenBao's admin logins
(`03-openbao.sh`). (On an *existing* volume from an older checkout, use `just audit-bootstrap` and
`just vault-db-bootstrap` instead.)

**2. Database migrations** ([Step 11](../steps/step-11-postgres-pgvector.md), always as `rag_migrator`, never the superuser):

```bash
just db-migrate up
just db-migrate status           # every migration [X], including 20261013000000_rag_core.sql
                                 # and 20261014000000_lifecycle_and_tenants.sql
```

**3. Object storage buckets** ([Step 14](../steps/step-14-s3-object-storage-seaweedfs.md)): `rag-raw-docs`
(versioned), `rag-audit-archive` (object lock), `rag-tmp` (1-day expiry), and Langfuse's bucket
([Step 22](../steps/step-22-langfuse-llm-traces.md)):

```bash
just with-secrets uv run --with boto3 scripts/s3_setup.py
just s3 s3 mb s3://langfuse
just s3 s3api put-bucket-lifecycle-configuration --bucket langfuse --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-raw-events","Status":"Enabled","Filter":{"Prefix":"events/"},"Expiration":{"Days":30}}]}'
```

**4. Qdrant and OpenSearch indexes** (needed only for the `local-engines` profile; the default
`local` profile searches inside Postgres): [Step 12](../steps/step-12-qdrant-vector-database.md),
[Step 13](../steps/step-13-opensearch-keyword-hybrid-search.md).

```bash
just with-secrets uv run --with qdrant-client scripts/qdrant_setup.py      # collection + alias rag_chunks
just with-secrets uv run --with opensearch-py scripts/os_setup.py          # users, index, alias, hybrid pipeline
```

**Check Stage D:**

```bash
just db-psql                     # then \dt rag.*  and  \dx   (vector, pg_stat_statements); \q to leave
just qdrant-health               # collections listed with the admin key
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:6333/collections   # 401: no key, refused
just os-health                   # status green (yellow is normal on one node)
just s3 s3 ls                    # rag-raw-docs, rag-audit-archive, rag-tmp, langfuse
just kv-cli ping                 # PONG (as admin); anonymous access is refused
```

> **WATCH OUT · OPENSEARCH AND vm.max_map_count**
> If OpenSearch complains about `vm.max_map_count`:
> `docker run --rm --privileged alpine sysctl -w vm.max_map_count=262144` (Step 13).

---

## Stage E · The model gateway (Steps 9–10)

> **IN PLAIN ENGLISH**
> Applications never talk to a model server directly. They talk to LiteLLM, which knows where each
> model lives, retries, falls back from the fast model to the quality model, counts cost, and only
> lets each application use the models and budget it was given.

Detail: [Step 9](../steps/step-09-litellm-gateway.md), [Step 10](../steps/step-10-budgets-rate-limits-fallbacks.md),
[gateway access policy](../security/gateway-access-policy.md).

```bash
just with-secrets docker compose -f infra/compose/compose.yaml up -d litellm-db litellm
just gateway-health              # gateway :4000 alive, then the readiness JSON
just gateway-smoke               # chat, streaming, embeddings, rerank and the security checks
```

Create the teams and one virtual key per application. Each key is **shown once**: store it straight away.

```bash
just gateway-admin team rag-apps   --budget 50  --models qwen-quality qwen-fast embedder reranker
just gateway-admin team evaluation --budget 200 --models qwen-quality qwen-fast embedder reranker
# use the team ids printed above:
just gateway-admin key rag-api-dev   --team-id <rag-apps-id>   --models qwen-quality qwen-fast embedder reranker --rpm 60  --parallel 4
just gateway-admin key ingestion-dev --team-id <rag-apps-id>   --models embedder qwen-fast --rpm 600 --parallel 8
just gateway-admin key eval-harness  --team-id <evaluation-id> --models qwen-quality qwen-fast embedder reranker --rpm 120 --parallel 4
just secrets-edit                # add: RAG_API_GATEWAY_KEY=…  INGESTION_GATEWAY_KEY=…  EVAL_GATEWAY_KEY=…
```

**Check Stage E:** `just gateway-test` proves the allow-list, rate limit and budget are enforced
(it creates and blocks throwaway keys). Optional fallback drill: `launchctl bootout
gui/$(id -u)/com.rag-platform.qwen-fast`, send a chat request to `qwen-fast`, watch `just logs litellm`
fall back to `qwen-quality`, then `just models-up`. The admin UI is at <http://127.0.0.1:4000/ui>.

---

## Stage F · Identity and policy (Steps 16–18)

**Keycloak** ([Step 16](../steps/step-16-keycloak-realm-users-groups.md)) imports the realm `rag` from
[`infra/config/keycloak/realm-rag.json`](../../infra/config/keycloak/realm-rag.json) on first start.

```bash
just with-secrets docker compose -f infra/compose/compose.yaml up -d keycloak-db keycloak
just ps                          # keycloak healthy after ~30-60 s
curl -s http://localhost:8180/realms/rag/.well-known/openid-configuration | jq '{issuer, token_endpoint, jwks_uri}'
```

Replace the temporary admin with your own, as Step 16 describes: open <http://localhost:8180/admin/>,
sign in as `temp-admin` (password: `KEYCLOAK_ADMIN_PASSWORD`, read with `just secrets-edit`), in realm
**master** create your own user with the `admin` role and an OTP requirement, sign in as yourself,
then delete `temp-admin`.

Create the demo people. Each gets a **one-time password** printed once; they must change it at first sign-in:

```bash
just kc-users                    # alice (all-staff, engineering), bob (hr), carol (executives),
                                 # dave (platform-admins, MFA), erin (auditors, MFA)
just kc-whoami                   # device-flow sign-in + machine sign-in; prints the token claims
```

**OPA** ([Step 18](../steps/step-18-policy-engine-opa.md)) decides who may do what and which documents
each person may see; policies live in [`policies/`](../../policies/).

```bash
just policy-check                # fmt, strict compile, Regal lint, tests with >= 90% coverage
just with-secrets docker compose -f infra/compose/compose.yaml up -d opa
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8181/v1/data/rag/authz/decision -d '{}'   # 401: token required
```

**Check Stage F:** the discovery document shows issuer `http://localhost:8180/realms/rag`; `just
kc-whoami` prints `groups` for the person; `just policy-check` passes; OPA refuses calls without a token.

---

## Stage G · Observability (Steps 19–22)

```bash
just with-secrets docker compose -f infra/compose/compose.yaml up -d \
  prometheus alertmanager grafana postgres-exporter tempo loki
just with-secrets docker compose -f infra/compose/compose.yaml up -d \
  langfuse-db langfuse-clickhouse langfuse-valkey langfuse-worker langfuse-web
```

| Open | What you see | Sign in |
|---|---|---|
| <http://localhost:9090/targets> | Every scrape target UP (TEI only while it runs) | none (localhost only) |
| <http://localhost:9093> | Firing alerts, silences | none (localhost only) |
| <http://localhost:3000> | Dashboards: *RAG Platform → RAG platform · overview* | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| <http://localhost:3002> | Langfuse LLM traces (after Stage J) | `admin@example.com` / `LANGFUSE_ADMIN_PASSWORD` |

**Check Stage G:**

```bash
curl -s localhost:13133/ | jq .status          # "Server available" (the Collector)
curl -s localhost:3200/ready; echo             # ready (Tempo)
curl -s localhost:3100/ready; echo             # ready (Loki)
just alerts-test                               # needs promtool: just tools promtool (Step 37)
just dashboards-check                          # dashboards in git match the generator
just langfuse-retention --dry-run              # how many traces are older than 30 days
```

What each signal is for, and the SLO behind the alerts, is in
[quality-and-operations.md](quality-and-operations.md#2-observability).

---

## Stage H · The audit log (Step 23)

The `audit` database was created with the volume (Stage D). Apply its migration (rollback is refused by design):

```bash
just audit-migrate up
just audit-migrate status                       # [X] 20261012090000_create_audit_log.sql
just audit-psql -c '\du audit_*'                # audit_migrator, audit_writer, audit_reader
```

After Stage J has produced some events:

```bash
just audit-psql -c "SELECT seq, actor, action, outcome FROM audit.events ORDER BY seq DESC LIMIT 5"
just audit-anchor                               # copy new events + head hash to the write-once bucket
just audit-verify                               # database chain + archive + agreement; exit 1 = problem
```

Schedule them like the guide's crontab ([`bootstrap/home/crontab`](../../bootstrap/home/crontab)):
`just audit-anchor` hourly, `just audit-verify` daily, `just cards lint --strict` weekly,
`just langfuse-retention` nightly (`crontab -e`, adjusting the path to your clone).

---

## Stage I · OpenBao, the secrets manager (Step 28)

> **IN PLAIN ENGLISH**
> SOPS (Stage B) holds the bootstrap secrets. OpenBao, an open-source Vault, hands out **short-lived
> database logins** to rag-api and the worker (each valid for an hour and renewed by an agent), and
> stores the other keys they need. It starts *sealed* (locked) after every restart; two of three key
> shares unlock it, and those shares live in your SOPS-encrypted `secrets/openbao-init.enc.json`.

Detail: [Step 28](../steps/step-28-vault-dynamic-secrets.md), [runbook](../runbooks/openbao.md),
[ADR-0028](../adr/0028-issue-database-credentials-dynamically-from-openbao.md).

```bash
just tools bao && bao version                   # pinned, checksum-verified OpenBao CLI into .tools/bin
just with-secrets docker compose -f infra/compose/compose.yaml up -d openbao
bao status                                      # Initialized false, Sealed true

just vault-init                                 # ONCE: unseal shares + root token straight into SOPS
git add secrets/openbao-init.enc.json           # encrypted; commit it
just vault-unseal                               # 2 of 3 shares, decrypted into a pipe
just vault-setup-first                          # engines, policies, DB connections and roles, AppRoles, your admin login
just vault-revoke-root                          # retire the root token
just vault-login                                # your day-to-day login (password: BAO_ADMIN_PASSWORD)
```

Store what rag-api's agent will write for rag-api and the worker. A KV write **replaces** the whole
secret, so always put every value:

```bash
just vault-put rag-api gateway_key=RAG_API_GATEWAY_KEY opa_token=OPA_API_TOKEN \
  valkey_url=RAG_API_VALKEY_URL s3_access_key=S3_INGEST_ACCESS_KEY s3_secret_key=S3_INGEST_SECRET_KEY \
  pii_hmac_key=RAG_PII_HMAC_KEY
```

> **NOTE · `opa_token=OPA_API_TOKEN`**
> The step write-ups print `opa_token=RAG_API_OPA_TOKEN`. `vault-put` reads each value from the
> environment variable you name, and the generated secrets file holds the OPA token as
> `OPA_API_TOKEN` (the same value Compose already gives rag-api as `rag_api_opa_token`). Either name
> works if it exists in your SOPS file; `OPA_API_TOKEN` exists without editing anything.

**Check Stage I:**

```bash
just vault-status                               # Sealed false, the audit device listed
just vault-creds rag-readonly                   # a 1-hour read-only login in .bao/rag-readonly.json
```

---

## Stage J · rag-api and the ingestion worker (Steps 17, 31–33)

`just vault-agent-start` gives rag-api's OpenBao Agent a fresh single-use secret ID, starts it, waits
until it has written the credential files, then starts rag-api. `just api-up` builds the image from
the repository.

```bash
just api-up                     # builds rag-platform/rag-api:dev (rag-api will wait for its agent)
just vault-agent-start          # role id + wrapped secret id -> agent -> /run/bao files -> rag-api
just with-secrets docker compose -f infra/compose/compose.yaml up -d ingestion-worker
just up                         # from now on: the whole stack, in one command
just ps                         # everything healthy (or "running" for images without a healthcheck)
```

**Check Stage J:**

```bash
curl -s http://127.0.0.1:8000/healthz                         # {"status":"ok"}
curl -si http://127.0.0.1:8000/v1/me | head -5                # 401 + WWW-Authenticate: Bearer realm="rag-api"
docker compose -f infra/compose/compose.yaml exec rag-api id  # uid=10001(app): not root
just api-demo     # sign in as alice in a private window: person, machine, no token, forged token,
                  # then an answer, a follow-up, a streamed answer and a rating
```

---

## Stage K · Ingest the sample corpus and ask questions (Steps 31–35)

### First, with nothing running (the `offline` profile)

The `offline` profile uses in-memory stores, a hashing embedder and an extractive "generator", so it
runs anywhere, including CI. It is the fastest way to see the pipeline:

```bash
uv run rag components                                          # every switchable part (docs/catalogue.md)
uv run rag config show --profile local                         # what a profile resolves to
uv run rag ingest --profile offline --group hr examples/corpus/*
uv run rag search "How many days of annual leave do I get?" --profile offline --group all-staff \
  --ingest examples/corpus/handbook/*.md                       # every hit with dense, sparse, fusion, rerank scores
uv run rag ask "How many days of annual leave do I get?" "And for part-timers?" \
  --profile offline --group all-staff --corpus examples/eval/handbook.yaml      # cited answers, one conversation
```

### Then, on the platform (the `local` profile)

The `local` profile ([`rag.yaml`](../../rag.yaml)) names container hostnames (`litellm`, `rag-db`,
`valkey`) and the files OpenBao's agent writes under `/run/bao`, so it runs **inside** the containers.
Upload the documents to the object store, then queue them for the workers:

```bash
just s3 s3 cp examples/corpus/handbook s3://rag-raw-docs/handbook/ --recursive
docker compose -f infra/compose/compose.yaml exec ingestion-worker \
  rag enqueue --profile local --group all-staff \
  s3://rag-raw-docs/handbook/annual-leave.md s3://rag-raw-docs/handbook/remote-work.md   # … one URI per document
docker compose -f infra/compose/compose.yaml logs -f ingestion-worker                     # "indexed"; Ctrl+C
```

Give restricted documents their own access when you enqueue them, as the evaluation file does for
`exec-compensation.md` (`--group executives --classification restricted`). A second enqueue of an
unchanged document says `unchanged`: ingestion replaces rather than appends
([ADR-0031](../adr/0031-ingest-through-a-replace-not-append-pipeline.md)).

Ask through the API as a signed-in person: `just api-demo` signs you in (device flow) and calls
`POST /v1/answer` (`{"question", "session_id"?, "stream"?}`), streams an answer and sends
`POST /v1/feedback` (`{"answer_id", "rating", "reason"?}`). Sign in as **alice** and then **carol**: only
carol (executives) can ever see the executive pay document.

**Check Stage K:**

- the worker logs show `indexed` for each document;
- an answer cites numbered sources, and a question the handbook can't answer gets "I don't know"
  rather than a guess ([ADR-0033](../adr/0033-answer-with-checked-citations-and-abstention.md));
- Grafana shows the searches and answers; Tempo has one trace per request (rewrite → retrieval →
  rerank → generation); Langfuse shows the LLM call with personal data masked;
- `just audit-psql -c "SELECT action, outcome FROM audit.events ORDER BY seq DESC LIMIT 5"` lists
  them, with ids and counts only, never the question text.

Try other techniques without editing any file, one run at a time (the `RAG__SLOT__SETTING` override):

```bash
RAG__RERANKER__USE=none uv run rag search "VPN keeps dropping" --profile offline --group all-staff --ingest examples/corpus/handbook/*.md
RAG__PIPELINE__USE=adaptive uv run rag ask "hi" "How do I report a security incident?" --profile offline --group all-staff --corpus examples/eval/handbook.yaml
```

Every switch is explained in the [RAG handbook](../concepts/rag-handbook.md).

---

## Stage L · Evaluations, guards and CI locally (Steps 24–27, 32–38)

The same recipes run on your Mac and in GitHub Actions ([Step 27](../steps/step-27-ci-pipeline-and-supply-chain.md)).

```bash
just tools                 # every pinned tool from ci/tools.yaml into .tools/bin (on PATH via .envrc)
just ci                    # = ci-static, ci-test, ci-config, policy-check, ci-supply-chain
just audit-test            # ALL tests, incl. the audit-DB and OpenBao tests, on a throwaway Postgres (:55432)
just image-scan            # build the rag-api image, Trivy scan, CycloneDX SBOM
```

The offline quality gates inside `ci-config`, runnable on their own:

| Recipe | Gate |
|---|---|
| `just search-eval` | recall ≥ 0.9, MRR ≥ 0.8 on `examples/eval/handbook.yaml`, and **no leak** of a forbidden document |
| `just guard-eval` | ≥ 95% of attacks caught, ≤ 5% of ordinary questions stopped (`examples/eval/guards.yaml`) |
| `just answer-eval` | context recall ≥ 0.95 and correct abstention with the `standard` architecture |
| `just rag-config-check` | every profile validates; `production` passes readiness |
| `just doctor` | the platform meets its own [standards](../standards/rag-standards.md) |
| `just prompts lint` · `just cards lint` · `just compliance-check` | prompts, cards and the risk register are consistent |

Live evaluations against the real models (Step 26; this is what `.github/workflows/evals.yml` runs on
a self-hosted Mac runner):

```bash
just evals release retrieval-golden && just evals release rag-answer-golden   # pin dataset versions (once)
just evals run retrieval                                  # as alice, bob, carol, zoe, through the real policy
just evals run answer --prompt rag-answer --label staging --judge
just evals gate evals/runs/<run>                          # thresholds + no regression vs baseline
just evals baseline evals/runs/<run>                      # accept a run as the reference; commit it
uv run rag eval-search examples/eval/handbook.yaml --profile local --no-ingest       # inside the stack's network
```

`evals/baselines/` is empty in this repository: a baseline is a real accepted run against your models,
so produce it here with `just evals baseline`. More on the whole testing strategy:
[quality-and-operations.md](quality-and-operations.md#1-evaluation-and-testing).

---

## Stage M · Local Kubernetes with OrbStack and Argo CD (Step 29)

> **IN PLAIN ENGLISH**
> rag-api can also run on a small Kubernetes cluster inside OrbStack, deployed by Argo CD from git:
> you change a line in git (the image digest), Argo CD notices and makes the cluster match. The stateful
> services stay in Compose; the cluster reaches them under their usual names.

Detail: [Step 29](../steps/step-29-kubernetes-gitops-argo-cd.md),
[runbook](../runbooks/kubernetes.md), [ADR-0029](../adr/0029-run-rag-api-on-kubernetes-deployed-by-argo-cd-from-git.md).

**Before you start, fill in the placeholders:**

- your GitHub owner (lower case) instead of `owner` in `deploy/cluster/policy-images.yaml`,
  `deploy/envs/*/kustomization.yaml`, `deploy/argocd/**`, and in the `repo_ssh` variable of the `justfile`;
- the image digests marked `sha256:<digest>` in `deploy/argocd/install/kustomization.yaml` (Argo CD
  v3.5.5) and `deploy/base/rag-api/kustomization.yaml` (OpenBao 2.7.1 from `quay.io/openbao/openbao`):
  `docker buildx imagetools inspect quay.io/argoproj/argocd:v3.5.5 | head -5`;
- a published rag-api image: CI's `release.yml` on `main` pushes a signed image and prints its digest
  ([Step 27](../steps/step-27-ci-pipeline-and-supply-chain.md)).

```bash
just k8s-up                     # OrbStack → Settings → Kubernetes → Enable, the first time
just k8s-netpol-check           # does this cluster ENFORCE NetworkPolicies? (tells you either way)
just k8s-check                  # every overlay renders; the Kubernetes tests against a real API server
just k8s-render envs/local      # exactly what Argo CD will apply
just vault-login && just vault-k8s-trust        # let pods log in to OpenBao with their service account

# a read-only deploy key and a read-only package token, added to SOPS
ssh-keygen -t ed25519 -N "" -f /tmp/argocd-deploy -C argocd   # add /tmp/argocd-deploy.pub as a read-only deploy key on GitHub
just secrets-edit               # add ARGOCD_DEPLOY_KEY (the private key), GHCR_USER, GHCR_READ_TOKEN; then delete /tmp/argocd-deploy*

just k8s-bootstrap              # Argo CD, its repository key, the projects, the root app
just k8s-pull-secret            # lets the cluster pull your private images
just k8s-deps-check             # pods can reach rag-db, litellm, opa, openbao, keycloak, otel-collector
just promote local sha256:<release digest>      # verify signature + provenance, one-line PR; merge = deploy
just k8s-status                 # Synced / Healthy
just argocd-ui                  # https://localhost:8443, user admin (password copied to the clipboard)
```

Roll back with `git revert <promotion commit>` through a pull request, never the Argo CD button
([runbook](../runbooks/kubernetes.md)).

---

## Daily use after a restart

OpenBao forgets its unlock key on every restart, and the agent's single-use secret ID is gone, so:

```bash
just health                     # model servers (launchd restarts them with the Mac)
just up                         # the stack
just vault-up                   # = vault-unseal + vault-agent-start
just ps
```

| You changed… | Run |
|---|---|
| rag-api or rag-core code | `just api-up` |
| A secret value | `just secrets-edit`, then `just up` (and `just vault-put …` + `just vault-agent-start` if it lives in OpenBao) |
| Prometheus rules or config | `just prom-reload` |
| `rag.yaml` | `just sync-profiles`, `just rag-config-check`, then `just api-up` |
| A prompt | `just prompts new <name>` → edit → `just prompts lock` → `just prompts promote <name> <v> staging` |
| A policy | `just policy-check` (OPA reloads the files by itself) |

---

## Stopping and resetting

| Goal | Command | What survives |
|---|---|---|
| Stop the containers | `just down` | All data (named volumes) |
| Stop the model servers | `just models-down` · `just search-models-down` | Model files |
| Wipe one service's data (dev only), e.g. re-import the Keycloak realm | `just down && docker volume rm rag-platform_keycloak-db-data && just up` | Everything else |
| Wipe **all** container data | `docker compose -f infra/compose/compose.yaml down -v` | Model files, git, your SOPS files |
| Reset local Kubernetes | OrbStack → Reset Kubernetes, then [the runbook's four steps](../runbooks/kubernetes.md#the-whole-cluster-was-reset-orbstack--reset-kubernetes) | Compose services |

> **WATCH OUT · WIPING OPENBAO'S VOLUME**
> `down -v` deletes `openbao-data`. The old `secrets/openbao-init.enc.json` then belongs to a server
> that no longer exists: move it aside, and start again from `just vault-init` (Stage I). Never delete
> OpenBao's volume on a machine whose secrets you still need.

Back up before experiments: `just db-backup` (a dump plus a receipt in `backups/`) and prove it restores
with `just db-restore-test backups/<file>.dump` ([Step 36](../steps/step-36-lifecycle-threat-model-compliance.md)).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `just` / `uv` / `sops`: command not found | Homebrew not on PATH | Add `bootstrap/home/.zprofile`'s line to `~/.zprofile`; open a new terminal |
| `sops`: "no identity matched" / "failed to get the data key" | Wrong or missing age key; `.sops.yaml` still has the placeholder | `echo $SOPS_AGE_KEY_FILE` (run `direnv allow`); put your public key in `.sops.yaml` |
| `hf download` 401 | No `HF_TOKEN` | Store it in the Keychain (Stage B step 5), `direnv allow` |
| `just health`: a model DOWN | launchd agent not running or out of memory | `just models-logs`; `just models-up`; check memory with Activity Monitor |
| Compose: `secret … environment variable … not set` | A value not yet in SOPS (gateway keys, GHCR) | Add it with `just secrets-edit` (see the table in Stage B) |
| A container restarts over and over | Its dependency isn't healthy, or memory | `just logs <service>`; `docker stats --no-stream`; raise the OrbStack cap |
| OpenSearch exits at start | `vm.max_map_count` too low | See the Stage D note |
| rag-api never starts ("waiting for rag-api-agent") | OpenBao sealed or the agent has no secret ID | `just vault-up`; `just logs rag-api-agent` ([runbook](../runbooks/openbao.md)) |
| Agent log: `permission denied` / missing key | A value missing from `secret/rag-api` (e.g. `pii_hmac_key`) | Re-run the full `just vault-put rag-api …` from Stage I, then `just vault-agent-start` |
| `password authentication failed for user "v-approle-…"` | The agent restarted and lost its secret ID | `just vault-agent-start` |
| API returns 401 for a valid sign-in | Issuer mismatch: token from `127.0.0.1` vs `localhost` | Always use `http://localhost:8180` for Keycloak (that's the issuer) ([runbook](../runbooks/keycloak-login-failures.md)) |
| API returns 503 | OPA, Keycloak keys or the audit database unreachable (rag-api fails closed) | `just ps`; [rag-search-errors](../runbooks/rag-search-errors.md), [audit-log](../runbooks/audit-log.md) |
| Answers are always "I don't know" | Nothing ingested for your groups, or the wrong group at enqueue | Check the worker logs; re-enqueue with the right `--group`; [answer-quality](../runbooks/answer-quality.md) |
| Prometheus target DOWN / 401 | Service down or token wrong | [target-down](../runbooks/target-down.md) |
| Collector dropping data | Memory limit or a backend down | [otel-collector-losing-data](../runbooks/otel-collector-losing-data.md) |
| `just audit-verify` exits 1 | The chain or the archive disagree | Treat as an incident: [audit-log runbook](../runbooks/audit-log.md) |
| Kubernetes pods `Init:0/1` | Pods can't log in to OpenBao | `just vault-k8s-trust`; [kubernetes runbook](../runbooks/kubernetes.md) |
| `ImagePullBackOff` | Wrong digest or expired pull token | `just k8s-pull-secret` with a fresh read-only token |
| `tests/test_backup.py` fails | `pg_dump` older than the server (17) | Use Homebrew's `libpq` tools (on PATH via `/opt/homebrew/opt/libpq/bin`) |
| A secret was pasted somewhere public | | [secret-leak runbook](../runbooks/secret-leak.md), now |

---

## Linux and other machines

The platform's *design* is portable; the *workstation scripts* are macOS-specific. What changes:

| Piece | On the Mac | On Linux (or a machine without Apple Silicon) |
|---|---|---|
| Tools | Homebrew + `bootstrap/Brewfile` | Your distribution's packages (or Homebrew on Linux for the CLI tools; the `orbstack` cask doesn't exist) |
| Containers | OrbStack | Docker Engine with Compose; `infra/compose/compose.yaml` runs unchanged (Linux is its native home) |
| Chat models | mlx-lm (needs Apple's Metal GPU) | **No MLX.** The alternatives named in [ADR-0007](../adr/0007-serve-local-models-natively-with-mlx-lm-behind-localhost.md) and the [cloud mapping](../architecture/cloud-mapping.md): Ollama or the llama.cpp server (GGUF models, CPU or GPU), or vLLM / TGI on an NVIDIA GPU |
| Embeddings and reranking | TEI's Metal build | TEI's CPU or CUDA build (or its container); llama.cpp's server also embeds and reranks ([ADR-0008](../adr/0008-serve-embeddings-and-reranking-with-tei-natively-behind-an-api-key.md)) |
| Wiring the models in | `api_base: http://host.docker.internal:808x` in the LiteLLM config | Point the same four role names at your servers in [`infra/config/litellm/config.yaml`](../../infra/config/litellm/config.yaml); applications don't change |
| Always-on services | launchd (`just models-up`, `search-models-up`) | systemd units of your own; the `models-*` / `search-models-*` / `models-logs` recipes are macOS-only |
| Personal tokens | macOS Keychain via `.envrc` | Your OS secret store, or `export HF_TOKEN` in an untracked shell profile |
| Local Kubernetes | OrbStack (`kube := "kubectl --context orbstack"`, `orb start k8s`) | kind, k3d or minikube ([ADR-0029](../adr/0029-run-rag-api-on-kubernetes-deployed-by-argo-cd-from-git.md) alternatives); change the `kube` variable and `k8s-up` |
| Clipboard | `pbcopy` in `just argocd-ui` | `xclip` / `wl-copy`, or print the password |

Everything that runs **offline** (`just sync`, `just test`, `just ci-static`, `just search-eval`,
`just guard-eval`, `just answer-eval`, `just doctor`, `uv run rag … --profile offline`) works on any
machine with uv: that's exactly how CI runs on Linux.

---

## Where next

- Take it beyond the laptop: [production-promotion.md](production-promotion.md)
- How the pieces fit: [architecture overview](../architecture/overview.md)
- Every RAG technique and how to switch it: [RAG handbook](../concepts/rag-handbook.md)
- Every file and command: [reference](../reference.md) · every term: [glossary](../glossary.md)
