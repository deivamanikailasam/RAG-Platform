# Reference: files and commands

Everything the 38 steps create, in one place, so you can rebuild the setup without flipping back
through the chapters. This is Appendix A of the build guide, adjusted to this repository.

**How paths map to this repository**

- The guide's project folder `~/dev/rag-platform/` **is** the repository root. `~/dev/rag-platform/justfile`
  is [`justfile`](../justfile), and so on.
- Files the guide puts in your home folder (`~/.zprofile`, `~/.gitconfig`, `~/.ssh/config`,
  `~/.config/uv/uv.toml`, launchd agents, the crontab) are kept as **reference copies** under
  [`bootstrap/home/`](../bootstrap/home/), mirroring the path. Copy them to `~` during workstation set-up.
- Per-machine secrets are **never committed**: your age private key, SSH keys, the encrypted
  `secrets/dev.enc.env` and `secrets/openbao-init.enc.json`. The repository has the instructions and
  placeholder files instead ([`.env.example`](../.env.example), [`secrets/README.md`](../secrets/README.md),
  `bootstrap/home/.ssh/allowed_signers.example`); `just secrets-init` and `just vault-init` create the
  encrypted files on your machine.
- Step write-ups are in [`docs/steps/`](steps/README.md); terms are in the [glossary](glossary.md); every
  switchable component is in the [catalogue](catalogue.md) (Appendix C).

Contents: [Brewfile](#the-complete-brewfile-steps-138) ·
[Configuration and settings](#configuration-files-and-settings) ·
[Repository files](#repository-files) · [Command cheat sheet](#command-cheat-sheet)

---

## The complete Brewfile (Steps 1–38)

File: [`bootstrap/Brewfile`](../bootstrap/Brewfile). `just bootstrap` (= `brew bundle --file=bootstrap/Brewfile`)
installs whatever is missing.

```ruby
# ---- Core CLI (Step 1) ----
brew "git"                  # newer than Apple's bundled git
brew "gh"                   # GitHub CLI: repos, PRs, Actions from the terminal
brew "jq"                   # query/transform JSON (API responses, traces, configs)
brew "yq"                   # same for YAML (Compose, Kubernetes, Helm files)
brew "just"                 # task runner: one-word commands like `just up`, `just test`
brew "direnv"               # loads per-project environment variables when you cd in
brew "wget"                 # downloading models and datasets
brew "tree"                 # inspect folder structures

# ---- Python toolchain (Step 2) ----
brew "uv"                   # Python versions, venvs, dependency locking, tool installs; replaces pip/pyenv/pipx/pip-tools

# ---- Containers (Step 3) ----
cask "orbstack"             # Linux VM + Docker engine + CLI + Compose + single-node Kubernetes (used in Step 29)
brew "dive"                 # inspect image layers: find bloat and accidentally baked-in secrets

# ---- Secrets (Step 6) ----
brew "age"                  # modern file encryption; makes the key pair SOPS uses
brew "sops"                 # encrypts values inside .env / YAML / JSON files, keeps names readable

# ---- Embeddings & reranking (Step 8) ----
brew "text-embeddings-inference"  # Hugging Face TEI: fast embedding/reranking server, native Metal build on Apple Silicon

# ---- Database migrations (Step 11) ----
brew "dbmate"               # simple, language-agnostic SQL migrations (up/down), single binary

# ---- Object storage tools (Step 14) ----
brew "awscli"               # AWS CLI v2: speaks S3 to any compatible store via --endpoint-url

# ---- Policy as code (Step 18) ----
brew "opa"                  # Open Policy Agent: evaluate and test Rego policies
brew "regal"                # Rego linter and language server (editor support)

# ---- Audit log tests (Step 23) ----
brew "libpq"                # psql and pg_isready without a full Postgres server (keg-only: /opt/homebrew/opt/libpq/bin)

# ---- Secrets manager (Step 28) ----
# OpenBao's `bao` (server, agent, CLI) comes from `just tools bao`: pinned and checksum-verified

# ---- Kubernetes and GitOps (Step 29) ----
brew "kubectl"              # the Kubernetes CLI; includes kustomize (`kubectl kustomize`)
brew "argocd"               # Argo CD CLI (optional: the web UI does the same)
# Tests and CI use pinned kubectl / kube-apiserver / etcd from `just tools` (Kubernetes 1.36.2)
```

---

## Configuration files and settings

Where each setting lives, what it holds, and the step that introduces it. "Secret" names are keys in the
SOPS-encrypted `secrets/dev.enc.env` (names listed in [`.env.example`](../.env.example)); containers read
them as files under `/run/secrets/`.

### Workstation (Steps 1–7)

| Where | What it contains | Step | In this repo |
|---|---|---:|---|
| `~/.zprofile` | `eval "$(/opt/homebrew/bin/brew shellenv)"`: puts Homebrew first on your PATH | 1 | [`bootstrap/home/.zprofile`](../bootstrap/home/.zprofile) |
| `~/.zshrc` | `eval "$(direnv hook zsh)"`: switches on direnv | 1 | [`bootstrap/home/.zshrc`](../bootstrap/home/.zshrc) |
| `~/.config/uv/uv.toml` | `python-preference = "only-managed"` and `python-downloads = "manual"` | 2 | [`bootstrap/home/.config/uv/uv.toml`](../bootstrap/home/.config/uv/uv.toml) |
| OrbStack → Settings → System | Memory 24 GB, CPU 8 | 3 | [`bootstrap/orbstack-setup.sh`](../bootstrap/orbstack-setup.sh) |
| OrbStack → Settings → Docker | Log rotation: `json-file`, `max-size 10m`, `max-file 3` | 3 | [`bootstrap/home/.orbstack/config/docker.json`](../bootstrap/home/.orbstack/config/docker.json) |
| `bootstrap/NOTES-step3.md` | Step 3 decisions; superseded by ADR-0004 in Step 4 | 3 | [`bootstrap/NOTES-step3.md`](../bootstrap/NOTES-step3.md) |
| `~/.gitconfig` | Name, email, `init.defaultBranch=main`, `pull.ff=only`, `fetch.prune=true`, `core.autocrlf=input`, SSH commit + tag signing | 4 | [`bootstrap/home/.gitconfig`](../bootstrap/home/.gitconfig) |
| `~/.ssh/id_ed25519` (+ `.pub`) | Your SSH key: GitHub login and commit signing. Never share the file without `.pub`. | 4 | not committed (made by [`bootstrap/git-setup.sh`](../bootstrap/git-setup.sh)) |
| `~/.ssh/config` | Use the key for github.com and keep the passphrase in Keychain | 4 | [`bootstrap/home/.ssh/config`](../bootstrap/home/.ssh/config) |
| `~/.ssh/allowed_signers` | Which keys git trusts when verifying signatures locally | 4 | `bootstrap/home/.ssh/allowed_signers.example` |
| Ports `127.0.0.1:8081` / `:8082` | `qwen-quality` (Qwen3.8-27B-8bit) / `qwen-fast` (Qwen3.6-35B-A3B-4bit) | 7 | [`infra/model-serving/models.yaml`](../infra/model-serving/models.yaml) |
| `sysctl iogpu.wired_limit_mb` | GPU working-set limit (0 = macOS default); only raise if measured need | 7 | documented in [step 7](steps/README.md) |

The two small home-folder files, exactly as the guide gives them:

```toml
# ~/.config/uv/uv.toml
python-preference = "only-managed"
python-downloads = "manual"
```

```json
// OrbStack · Settings → Docker (engine config)
{
    "log-driver": "json-file",
    "log-opts": { "max-size": "10m", "max-file": "3" }
}
```

### Models and gateway (Steps 8–10)

| Where | What it contains | Step |
|---|---|---:|
| Ports `127.0.0.1:8083` / `:8084` (metrics 9083 / 9084) | `embedder` (Qwen3-Embedding-0.6B) / `reranker` (bge-reranker-v2-m3), API key required | 8 |
| `TEI_API_KEY` in `secrets/dev.enc.env` | Bearer token for both TEI servers | 8 |
| Port `127.0.0.1:4000` | LiteLLM gateway: `qwen-quality`, `qwen-fast`, `embedder`, `reranker` | 9 |
| `LLM_GATEWAY_URL` / `LLM_GATEWAY_KEY` | The only model settings applications use (`http://litellm:4000` from containers) | 9 |
| `LITELLM_DB_PASSWORD`, `LITELLM_SALT_KEY` (never rotate casually) | Gateway database password and credential-encryption salt | 10 |
| `RAG_API_GATEWAY_KEY`, `INGESTION_GATEWAY_KEY`, `EVAL_GATEWAY_KEY` | Per-app virtual keys (encrypted secrets) | 10 |
| `http://127.0.0.1:4000/ui` | LiteLLM admin UI (localhost only, admin use) | 10 |

### Data stores (Steps 11–15)

| Where | What it contains | Step |
|---|---|---:|
| Port `127.0.0.1:5432` · database `rag` · schema `rag` | RAG system of record (from containers: `rag-db:5432`) | 11 |
| `RAG_DB_MIGRATOR_PASSWORD`, `RAG_DB_APP_PASSWORD`, `RAG_DB_READONLY_PASSWORD` | Role passwords (the superuser uses `POSTGRES_PASSWORD`) | 11 |
| Ports `127.0.0.1:6333` (REST + `/dashboard`) · `:6334` (gRPC) | Qdrant; alias `rag_chunks` for apps (from containers: `qdrant:6333`) | 12 |
| `QDRANT_API_KEY`, `QDRANT_READ_ONLY_API_KEY` | Qdrant admin / read-only keys (the admin key also signs JWTs) | 12 |
| Port `127.0.0.1:9200` (HTTPS, self-signed in dev) | OpenSearch; alias `rag-chunks`; pipeline `rag-hybrid` (from containers: `opensearch:9200`) | 13 |
| `OPENSEARCH_ADMIN_PASSWORD`, `OPENSEARCH_SEARCH_PASSWORD`, `OPENSEARCH_INDEXER_PASSWORD` | Admin / read-only / writer users | 13 |
| Port `127.0.0.1:8333` (S3, path-style, region `us-east-1`) | Object store (from containers: `http://object-store:8333`) | 14 |
| `S3_ADMIN_*`, `S3_INGEST_*`, `S3_READER_*` (`_ACCESS_KEY` / `_SECRET_KEY`) | Object store identities (replace Step 6's `MINIO_*`) | 14 |
| Port `127.0.0.1:6379` · `maxmemory 512mb` · `volatile-lru` | Valkey cache / queues / locks (from containers: `valkey:6379`) | 15 |
| `VALKEY_ADMIN_PASSWORD`, `VALKEY_LITELLM_PASSWORD`, `VALKEY_APP_PASSWORD` | Valkey ACL users `admin` / `litellm` / `rag_app` (replace Step 6's `REDIS_PASSWORD`) | 15 |
| `REDIS_URL` (litellm container only) · `cache: true`, `ttl: 600` | Gateway response cache in Valkey, namespace `litellm.cache` | 15 |

### Identity and policy (Steps 16–18)

| Where | What it contains | Step |
|---|---|---:|
| Port `127.0.0.1:8180` · issuer `http://localhost:8180/realms/rag` | Keycloak (admin console `/admin/`; from containers `http://keycloak:8080`); health/metrics on 9000, not published | 16 |
| `KEYCLOAK_ADMIN_PASSWORD` (temporary admin, first start only), `KEYCLOAK_DB_PASSWORD` | Keycloak bootstrap admin / its database | 16 |
| `KEYCLOAK_PROVISIONER_SECRET`, `KEYCLOAK_INGESTION_SECRET` | Client secrets for the `rag-provisioner` and `ingestion-worker` service accounts | 16 |
| Realm `rag` lifetimes | Access token 5 min · session idle 30 min / max 10 h · one-time refresh tokens · lockout after 5 failures | 16 |
| Port `127.0.0.1:8000` | rag-api (`/healthz` public; `/v1/me`, `/v1/search`, `/v1/admin/ping` need a token) | 17 |
| `RAG_API_OIDC_ISSUER = http://localhost:8180/realms/rag` · `RAG_API_OIDC_JWKS_URL = http://keycloak:8080/…/certs` | Issuer text to match vs where to fetch keys (two different settings) | 17 |
| `/run/secrets/rag_api_gateway_key`, `/run/secrets/rag_api_db_password` | rag-api secrets, read directly by pydantic-settings (from `RAG_API_GATEWAY_KEY`, `RAG_DB_APP_PASSWORD`) | 17 |
| Port `127.0.0.1:8181` · `OPA_API_TOKEN` | OPA (from containers `http://opa:8181`); token required for decisions, uploads refused | 18 |
| `RAG_API_OPA_URL`, `/run/secrets/rag_api_opa_token` | How rag-api reaches and authenticates to OPA | 18 |

### Observability (Steps 19–22)

| Where | What it contains | Step |
|---|---|---:|
| Ports `127.0.0.1:4317` (OTLP gRPC) · `:4318` (OTLP HTTP) · `:13133` (health) | OpenTelemetry Collector (from containers `otel-collector:4317/4318`) | 19 |
| `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_TRACES_SAMPLER(_ARG)` | Standard telemetry settings for every service (`OTEL_SDK_DISABLED=true` turns it off) | 19 |
| LiteLLM `OTEL_EXPORTER=otlp_http`, `OTEL_ENDPOINT=http://otel-collector:4318`; `callback_settings.otel.message_logging: false` | Gateway traces without prompt or answer content | 19 |
| Keycloak `KC_TRACING_ENABLED`, `KC_TRACING_ENDPOINT`; OPA `--set=distributed_tracing.*` | Identity and policy spans join the same traces | 19 |
| `http://localhost:9090` (Prometheus) · `:9093` (Alertmanager) · `:3000` (Grafana, user `admin`) | Monitoring UIs; Prometheus and Alertmanager have no login, so localhost only | 20 |
| `OPA_METRICS_TOKEN`, `RAG_DB_METRICS_PASSWORD` (+ `GRAFANA_ADMIN_PASSWORD`, `QDRANT_READ_ONLY_API_KEY`) | Least-privilege credentials for scraping and Grafana | 20 |
| Retention `15d` / `5GB`; scrape and rule interval `15s`; `OTEL_METRIC_EXPORT_INTERVAL` (ms) | Prometheus storage limits and timing | 20 |
| Search SLO: 99% success over 28 days, p95 < 2 s | Burn-rate alerts: 14.4× (1h + 5m) critical, 6× (6h + 30m) warning | 20 |
| `http://localhost:3200` (Tempo API) · `:3100` (Loki API) | Trace and log stores (from containers `tempo:3200`, `loki:3100`; Tempo OTLP `tempo:4317` internal only) | 21 |
| Port `127.0.0.1:24224` (Collector `fluent_forward`) | Where the Docker engine sends every container's output | 21 |
| `x-logging: &to-collector` (fluentd driver, `fluentd-async`, labels `com.docker.compose.service`) | Shared logging block for every service except the Collector | 21 |
| Tempo `block_retention: 168h`; Loki `retention_period: 168h` + `retention_enabled` | 7 days of traces and logs | 21 |
| Prometheus `--web.enable-remote-write-receiver`, `--enable-feature=exemplar-storage` | Tempo's generated metrics and exemplars | 21 |
| `http://localhost:3002` (Langfuse, `admin@example.com`) | LLM traces UI; from containers `http://langfuse-web:3000`; sign-up disabled | 22 |
| `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`, `LANGFUSE_ENCRYPTION_KEY` (never rotate casually) | Langfuse session signing, key hashing, credential encryption | 22 |
| `LANGFUSE_DB_PASSWORD`, `LANGFUSE_CLICKHOUSE_PASSWORD`, `LANGFUSE_VALKEY_PASSWORD`, `S3_LANGFUSE_*`, `LANGFUSE_ADMIN_PASSWORD` | Langfuse's own stores and first admin | 22 |
| `LANGFUSE_PUBLIC_KEY` (`pk-lf-…`), `LANGFUSE_SECRET_KEY` (`sk-lf-…`) | Project keys; rag-api reads the secret from `/run/secrets/rag_api_langfuse_secret_key` | 22 |
| `RAG_API_LANGFUSE_BASE_URL`, `RAG_API_LANGFUSE_CAPTURE_QUESTION`; `LANGFUSE_RETENTION_DAYS` (30) | Switch LLM tracing on, question capture, retention window | 22 |

### Audit and governance (Steps 23–25)

| Where | What it contains | Step |
|---|---|---:|
| Database `audit` · schema `audit` on rag-db (`127.0.0.1:5432`) | Tamper-evident audit log; roles `audit_migrator` (owner), `audit_writer` (append only), `audit_reader` (read + verify) | 23 |
| `AUDIT_DB_MIGRATOR_PASSWORD`, `AUDIT_DB_WRITER_PASSWORD`, `AUDIT_DB_READER_PASSWORD` | Audit role passwords; rag-api reads the writer's from `/run/secrets/rag_api_audit_db_password` | 23 |
| `RAG_API_AUDIT_DB_HOST` (`rag-db`), `RAG_API_AUDIT_DB_PORT` (5432) | Where rag-api writes audit events (fails closed with 503 if it can't) | 23 |
| `S3_AUDIT_ANCHOR_*`, `S3_AUDIT_READER_*` (`_ACCESS_KEY` / `_SECRET_KEY`) | Write / read-only identities for `rag-audit-archive` (`audit/segments/`, `audit/manifests/`) | 23 |
| crontab: `just audit-anchor` hourly (`5 * * * *`), `just audit-verify` daily (`30 4 * * *`) | Anchor the chain in write-once storage; check database vs archive ([`bootstrap/home/crontab`](../bootstrap/home/crontab)) | 23 |
| `RAG_API_PROMPT_LABEL` (`production`; staging stacks: `staging`), `RAG_API_PROMPTS_DIR` (`/app/prompts`) | Which prompt versions this rag-api runs; where the baked-in registry lives | 24 |
| [`prompts/labels.yaml`](../prompts/labels.yaml) · [`prompts/prompts.lock.json`](../prompts/prompts.lock.json) | Version per environment · SHA-256 of every released version (entries only ever added) | 24 |
| [`cards/policy.yaml`](../cards/policy.yaml) | Allowed model licences (SPDX ids); licence re-check every 365 days | 25 |
| crontab: `just cards lint --strict` weekly (`0 8 * * 1`) | Overdue reviews and licence re-checks fail, and reach the owners | 25 |

### Quality and delivery (Steps 26–29)

| Where | What it contains | Step |
|---|---|---:|
| [`evals/gates.yaml`](../evals/gates.yaml) · `evals/baselines/*.json` | Quality gates (thresholds, regression tolerance 0.02) · last accepted run per suite | 26 |
| `EVAL_GATEWAY_KEY` (Step 10), `RAG_DB_READONLY_PASSWORD`, `OPA_API_TOKEN` | What `just evals` uses: its own gateway budget, the read-only DB role, the policy | 26 |
| `RAG_API_DB_USER` (default `rag_app`) | Database role for search; the harness uses `rag_readonly` | 26 |
| [`ci/tools.yaml`](../ci/tools.yaml) · `.tools/bin` (on PATH via `.envrc`) | Pinned, SHA-256-verified tool binaries for CI and your Mac | 27 |
| [`ci/licence-policy.yaml`](../ci/licence-policy.yaml) | Allowed / review-required / denied dependency licences, verified exceptions | 27 |
| GitHub ruleset on `main` | 3 required checks, Code Owner review, signed commits, linear history, no force push | 27 |
| GitHub environment `evals` · runner label `rag-models` | Approval before evaluations run on your Mac (self-hosted runner) | 27 |
| `ghcr.io/<owner>/<repo>/rag-api@sha256:…` | Published images: signed (keyless), with provenance and SBOM attestations | 27 |
| Port `127.0.0.1:8200` · `BAO_ADDR=http://127.0.0.1:8200` | OpenBao API and CLI (from containers `http://openbao:8200`); metrics at `/v1/sys/metrics` | 28 |
| `secrets/openbao-init.enc.json` (SOPS) | 3 unseal key shares (any 2 unseal) and the initial root token (revoked after setup); created by `just vault-init`, never committed here | 28 |
| `VAULT_ADMIN_PG_PASSWORD`, `BAO_ADMIN_PASSWORD` in `secrets/dev.enc.env` | Bootstrap password for `vault_admin_rag` / `vault_admin_audit` (rotated by OpenBao) · your admin login | 28 |
| `BAO_PG_HOST` (`rag-db`), `BAO_PG_PORT` (5432), `BAO_APPROLE_CIDRS` (`172.16.0.0/12,127.0.0.1/32`) | What `vault_setup.py` writes into connections and AppRole address limits | 28 |
| Database roles `rag-api` (1 h / 24 h), `rag-readonly` (1 h / 8 h), `audit-writer` (1 h / 24 h) | Dynamic Postgres users `v-…`, members of `rag_app` / `rag_readonly` / `audit_writer`, `VALID UNTIL` the lease | 28 |
| AppRoles `rag-api`, `rag-evals` · userpass `admin` | Machine logins (token 1 h, max 24 h / 4 h; secret ID 30 days, CIDR-bound) · your login (1 h, max 8 h) | 28 |
| `RAG_API_DB_CREDENTIALS_FILE`, `RAG_API_AUDIT_DB_CREDENTIALS_FILE` (`/run/bao/*.json`) | rag-api reads the agent's current logins per connection (static `*_PASSWORD` = rollback) | 28 |
| `RAG_DB_READONLY_CREDENTIALS_FILE` (`.bao/rag-readonly.json`) | The evaluation harness's short-lived read-only login | 28 |
| OrbStack → Settings → Kubernetes (enable) · context `orbstack` (server 1.33+) | Single-node cluster; Services and pod IPs reachable from the Mac | 29 |
| Namespace `rag`: Pod Security `restricted` (v1.36), label `rag-platform/policy: enforced` | Where rag-api runs; our admission policies apply | 29 |
| ResourceQuota `rag-quota` (4 CPU / 4 Gi requests, 6 Gi memory limits, 20 pods) · LimitRange defaults 50m/64Mi, limit 256Mi | Keeps the cluster from starving the models | 29 |
| `owner` in `policy-images.yaml`, `envs/*/kustomization.yaml`, `deploy/argocd/**` | Your GitHub owner (lower case): allowed image registry and the repository Argo CD reads | 29 |
| `GHCR_USER`, `GHCR_READ_TOKEN`, `ARGOCD_DEPLOY_KEY` in `secrets/dev.enc.env` | Read-only image pulls (fine-grained token) · Argo CD's read-only deploy key | 29 |
| Argo CD: namespace `argocd`, UI `https://localhost:8443` (`just argocd-ui`), reconcile every 180 s | GitOps controller; projects `platform` and `rag` | 29 |
| OpenBao `auth/kubernetes-jwt` · role `rag-api` (subject `system:serviceaccount:rag:rag-api`, audience `openbao`) | Pods log in with their projected token (10 min), verified with the cluster's public key | 29 |

### RAG core, production and reuse (Steps 30–38)

| Where | What it contains | Step |
|---|---|---:|
| [`rag.yaml`](../rag.yaml) (repo root) · `RAG_PROFILE`, `RAG_CONFIG` | Component choices per profile: `offline` (no services), `local` (pgvector, Postgres FTS, gateway, Valkey), `local-engines` (Qdrant + OpenSearch) | 30, 31 |
| `RAG__<SLOT>__<SETTING>` env vars (e.g. `RAG__CHUNKER__MAX_TOKENS=300`, `RAG__EMBEDDER__USE=hashing`) | Override one setting for one run; `none` switches an optional slot off | 30 |
| OpenBao `kv/rag-api`: `pii_hmac_key`, `valkey_url`, `s3_access_key`, `s3_secret_key` → `/run/bao/…` | Keys the ingestion pipeline reads from files written by the agent, never from config | 31 |
| `RAG_API_SEARCH_BACKEND` (`legacy` · `core`), `RAG_API_RAG_PROFILE`, `RAG_API_RAG_CONFIG` | Which engine answers `/v1/search`; `core` = rag-core's pipeline with that profile | 32 |
| `api_key_file: /run/bao/rag_api_gateway_key` (gateway llm, embedder, reranker) · `key_file: /run/bao/pii_hmac_key` (PII) | Keys read from OpenBao Agent's files on every use | 32 |
| `query_prompt: query-instruction`, `prompts_dir`, `prompt_label` (gateway embedder) | The registered query instruction (Step 24) instead of a constant | 32 |
| `rag.yaml` slots `answer_llm`, `pipeline`, `context_builder`, `generator`, `memory`, `cache` | The answer model, answer settings (`uncited`, `search_k`), context budget and order, generator and prompt label, memory and cache backends | 33 |
| `RAG__GENERATOR__PROMPT_LABEL=staging`, `RAG__CACHE__USE=none`, `RAG__GENERATOR__USE=extractive` | Switch the prompt label, turn the cache off, or answer without a model, for one run | 33 |
| `rag.yaml` slot `guards` (list, run in order per stage) · `pipeline.stream: live \| checked` · `pipeline.blocked_text` | Which guards run with which actions; whether unchecked text may be streamed; the message a blocked person sees | 34 |
| `rag.yaml` slot `pipeline: {use: standard \| naive \| corrective \| self-reflective \| adaptive \| agentic \| graph \| sql, …}` · `graph_store` · enricher `graph-entities` | The RAG architecture and its settings; the graph store and entity extraction for GraphRAG | 35 |
| [`examples/retention.yaml`](../examples/retention.yaml) (`rules`: `match`, `keep_days`, `reason`; `default_keep_days`; `legal_holds`: `match`, `matter`, `until`) | Retention rules for `rag retention`; legal holds (Step 37) win over every rule | 36, 37 |
| `rag.tenant` (Postgres setting, set per transaction) · migration `20261014000000_lifecycle_and_tenants.sql` | Row-level security on documents and chunks; `*` only for writes and maintenance | 36 |
| [`docs/compliance/risk-register.yaml`](compliance/risk-register.yaml) (`threats`, `controls`, `evidence`, `frameworks`) | The risk register as code, checked in CI | 36 |
| `rag.yaml` profile `production` (extends `local`: `uncited: abstain`, `stream: checked`, the full guard list) | What staging and prod run; `rag config readiness` must pass | 37 |
| [`deploy/envs/promotion.yaml`](../deploy/envs/promotion.yaml) (`order`, per environment: `evidence`, `max_evidence_age_days`, `from`, `soak_hours`, `alerts_clear`, `freeze`) | Promotion gates | 37 |
| `RAG_API_RELEASE` (from the pod label `rollouts-pod-template-hash`), `RAG_ENVIRONMENT` | The release on every metric (`service.version`) and audit record; the environment name | 37 |
| AnalysisTemplate args `prometheus`, `on-insufficient` (`fail` / `pass`) | Where the canary checks query; what "not enough answers" means | 37 |
| CNPG `Cluster`: `instances`, `postgresql.synchronous` (`method`, `number`, `dataDurability`), `affinity`, `plugins`; `ObjectStore.retentionPolicy` | Database HA and the recovery window | 37 |
| `rag.yaml` `include: {platform: "rag-core:platform.yaml"}`; `extends: platform/<profile>` | Use the platform's packaged profiles; write only what differs | 38 |
| `RAG_PLUGINS=module.a,module.b` | Import a project's components without installing it (containers) | 38 |
| `[project.entry-points."rag_core.components"]` in a project's `pyproject.toml` | Register a project's components when installed | 38 |
| [`templates/rag-project/copier.yml`](../templates/rag-project/copier.yml) questions | `project_name`, `slug`, `owner`, `purpose`, `architecture`, `search_engine`, `highest_classification`, `personal_data`, `retention_days`, `platform_version` | 38 |

---

## Repository files

Every file or folder the steps add, with its purpose. Paths are relative to the repository root.

### Repository and code quality (Steps 4–5)

| File | Purpose | Step |
|---|---|---:|
| [`pyproject.toml`](../pyproject.toml) | Workspace root: Python `>=3.12,<3.13`, `package = false`, members `libs/*` (later `services/*`) | 4 |
| [`.python-version`](../.python-version) | `3.12`: one interpreter version for the whole repo | 4 |
| [`uv.lock`](../uv.lock) | The exact receipt for every workspace member | 4 |
| [`justfile`](../justfile) | The command menu; first recipes `bootstrap`, `sync`, `lock`, `check`, `adr` | 4 |
| [`.gitignore`](../.gitignore) | Keeps `.venv`, caches, `.env` secrets, data and model files out of git | 4 |
| [`.gitattributes`](../.gitattributes) | LF line endings; binary file types; lockfile marked as generated | 4 |
| [`.editorconfig`](../.editorconfig) | UTF-8, LF, 4-space indent (2 for YAML/JSON/TOML/Markdown) | 4 |
| [`.github/pull_request_template.md`](../.github/pull_request_template.md) | What/why, testing, checklist for every PR | 4 |
| [`.github/CODEOWNERS`](../.github/CODEOWNERS) | Who must review which folders (incl. `/prompts/` from Step 24) | 4 |
| [`docs/adr/0000-template.md`](adr/0000-template.md) | ADR template | 4 |
| `docs/adr/0001…0004-*.md` | Record ADRs · Homebrew/Brewfile · Python 3.12 + uv · native models, containerised services | 4 |
| [`docs/adr/README.md`](adr/README.md) | ADR index | 4 |
| [`libs/rag-common/`](../libs/rag-common/) | First shared library (src layout) | 4 |
| [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) | Hooks: file hygiene, private-key and gitleaks scans, no commits to main, Conventional Commits, ruff, mypy, `uv.lock` check, pytest on push | 5 |
| `pyproject.toml` `[tool.ruff]` `[tool.mypy]` `[tool.pytest.ini_options]` | Lint rule families, formatter style, strict typing, test settings | 5 |
| `pyproject.toml` `[dependency-groups] dev` | ruff, mypy, pytest, pre-commit, locked in `uv.lock` | 5 |
| [`libs/rag-common/tests/test_hello.py`](../libs/rag-common/tests/test_hello.py) | First unit test | 5 |
| [`.vscode/extensions.json`](../.vscode/extensions.json) | Recommended editor extensions: Ruff, Python, mypy, EditorConfig | 5 |
| `docs/adr/0005-…quality-gates….md` | ADR-0005: automated code quality gates | 5 |

### Secrets (Step 6)

| File | Purpose | Step |
|---|---|---:|
| `~/.config/sops/age/keys.txt` | Your age private key (chmod 600, backed up, **never committed**) | 6 |
| [`.sops.yaml`](../.sops.yaml) | Which age public keys can decrypt files in `secrets/` | 6 |
| `secrets/dev.enc.env` | All platform dev secrets, SOPS-encrypted, committed. Created on your machine by `just secrets-init`; see [`secrets/README.md`](../secrets/README.md) | 6 |
| [`scripts/new-dev-secrets.sh`](../scripts/new-dev-secrets.sh) | Generates random secrets and encrypts them immediately | 6 |
| [`scripts/check-sops-encrypted.sh`](../scripts/check-sops-encrypted.sh) + `secrets-encrypted` hook | Blocks unencrypted files in `secrets/` | 6 |
| [`.gitleaks.toml`](../.gitleaks.toml) | Default gitleaks rules, with SOPS ciphertext allow-listed | 6 |
| [`infra/compose/secrets-demo.yaml`](../infra/compose/secrets-demo.yaml) | Pattern for delivering secrets as `/run/secrets/*` files | 6 |
| [`libs/rag-common/src/rag_common/settings.py`](../libs/rag-common/src/rag_common/settings.py) | pydantic-settings `Settings` with `SecretStr`, reading `/run/secrets` | 6 |
| [`.envrc`](../.envrc) | Committed, no values: venv, `SOPS_AGE_KEY_FILE`, `HF_TOKEN` from Keychain | 6 |
| [`.env.example`](../.env.example) | Names of every expected setting, with placeholders only | 6 |
| [`docs/runbooks/secret-leak.md`](runbooks/secret-leak.md) | What to do if a secret leaks | 6 |
| `docs/adr/0006-…sops-and-age….md` | ADR-0006: secrets management decision | 6 |

### Model serving and gateway (Steps 7–10)

| File | Purpose | Step |
|---|---|---:|
| [`infra/model-serving/pyproject.toml`](../infra/model-serving/pyproject.toml) + `uv.lock` | Isolated, locked mlx-lm + Hugging Face CLI for native model serving | 7 |
| [`infra/model-serving/models.yaml`](../infra/model-serving/models.yaml) | Model inventory: repo, revision SHA, size, licence, port, role, approval | 7 |
| [`scripts/bench_models.py`](../scripts/bench_models.py) | Measures TTFT and ~tokens/s for both servers | 7 |
| [`scripts/install-model-agents.sh`](../scripts/install-model-agents.sh) | Creates launchd agents for both servers | 7 |
| `~/Library/LaunchAgents/com.rag-platform.qwen-*.plist` | The launchd service definitions (reference copies in [`bootstrap/home/Library/LaunchAgents/`](../bootstrap/home/Library/LaunchAgents/)) | 7 |
| `~/Library/Logs/rag-platform/qwen-*.log` | Model server logs (on your Mac only) | 7 |
| [`docs/benchmarks/models.md`](benchmarks/models.md) | Measured TTFT, tok/s and peak memory | 7 |
| `docs/adr/0007-serve-local-models….md` | ADR-0007: native mlx-lm serving on localhost | 7 |
| `models.yaml` entries `embedder` / `reranker` | Pinned SHAs plus the embedding contract (dims, normalise, pooling, query instruction, chunk limit) | 8 |
| [`scripts/model-path.sh`](../scripts/model-path.sh) | Prints a model's local snapshot folder (pins the exact revision) | 8 |
| [`scripts/run-tei.sh`](../scripts/run-tei.sh) | Starts TEI with `TEI_API_KEY` decrypted in memory, bound to 127.0.0.1 | 8 |
| [`scripts/install-tei-agents.sh`](../scripts/install-tei-agents.sh) | launchd agents for embedder and reranker | 8 |
| [`scripts/embed_demo.py`](../scripts/embed_demo.py) | Instruction vs no instruction, Matryoshka truncation, reranking demo | 8 |
| [`scripts/bench_embeddings.py`](../scripts/bench_embeddings.py) | Embedding chunks/s and rerank latency | 8 |
| `docs/adr/0008-serve-embeddings….md` | ADR-0008: TEI for embeddings and reranking | 8 |
| [`infra/config/litellm/config.yaml`](../infra/config/litellm/config.yaml) | Gateway routing: role names → backends, retries, timeouts, master key from env | 9 |
| [`infra/compose/compose.yaml`](../infra/compose/compose.yaml) | The container stack; first service `litellm` (digest pin, localhost port, secrets, limits, healthcheck) | 9 |
| [`scripts/gateway_smoke.py`](../scripts/gateway_smoke.py) | End-to-end and security checks through the gateway with the OpenAI SDK | 9 |
| `docs/adr/0009-route-all-model-access….md` | ADR-0009: all model access via LiteLLM | 9 |
| `compose.yaml` service `litellm-db` | Private Postgres 17 for gateway state; no published port; named volume `litellm-db-data` | 10 |
| `config.yaml` additions | Shadow prices, retries, cooldown, chat fallbacks, `store_model_in_db: false` | 10 |
| [`docs/finops/shadow-pricing.md`](finops/shadow-pricing.md) | How notional prices are derived from benchmarks | 10 |
| [`docs/security/gateway-access-policy.md`](security/gateway-access-policy.md) | Teams, keys, allowed models, limits, owners, review rules | 10 |
| [`scripts/gateway_admin.py`](../scripts/gateway_admin.py) | Create teams/keys, show key info, block keys | 10 |
| [`scripts/gateway_limits_test.py`](../scripts/gateway_limits_test.py) | Proves allow-list, rate-limit and budget enforcement | 10 |
| `docs/adr/0010-govern-model-access….md` | ADR-0010: keys, budgets, shadow prices, fallbacks | 10 |

### Data stores (Steps 11–15)

| File | Purpose | Step |
|---|---|---:|
| `compose.yaml` service `rag-db` | pgvector/Postgres 17, tuned, `pg_stat_statements`, `127.0.0.1:5432`, volume `rag-db-data` | 11 |
| [`infra/config/rag-db/init/01-roles.sh`](../infra/config/rag-db/init/01-roles.sh) | One-time bootstrap: extensions, `rag` schema, roles and default privileges | 11 |
| [`infra/db/rag/migrations/*.sql`](../infra/db/rag/migrations/) | dbmate migrations; first: collections, documents, chunks, HNSW, GIN indexes | 11 |
| [`scripts/pg_demo.py`](../scripts/pg_demo.py) | Loads documents via the gateway; permission-aware semantic search | 11 |
| `backups/` (git-ignored) | `pg_dump` backups of the RAG database | 11 |
| `docs/adr/0011-use-postgres-with-pgvector….md` | ADR-0011: Postgres + pgvector as system of record | 11 |
| `compose.yaml` service `qdrant` | Qdrant v1.19.x, keys from secrets, JWT RBAC, telemetry off, `127.0.0.1:6333/6334`, volumes `qdrant-data`, `qdrant-snapshots` | 12 |
| [`scripts/qdrant_setup.py`](../scripts/qdrant_setup.py) | Creates `rag_chunks_qwen3e06b_v1` (float16, int8 quantization, payload indexes) and alias `rag_chunks` | 12 |
| [`scripts/qdrant_sync.py`](../scripts/qdrant_sync.py) | Mirrors live chunks from Postgres (read-only role) and runs filtered search | 12 |
| [`scripts/qdrant_token.py`](../scripts/qdrant_token.py) | Mints a read-only, collection-scoped, expiring JWT and proves it can't write | 12 |
| `docs/adr/0012-use-qdrant-as-a-derived….md` | ADR-0012: Qdrant as derived vector index | 12 |
| `compose.yaml` service `opensearch` | OpenSearch 3.x single node, TLS + security plugin, 2 GB heap, `127.0.0.1:9200`, volume `opensearch-data` | 13 |
| [`scripts/os_setup.py`](../scripts/os_setup.py) | Users/roles, index `rag-chunks-v1` (analyzers, synonyms, k-NN) + alias, pipeline `rag-hybrid` | 13 |
| [`scripts/os_demo.py`](../scripts/os_demo.py) | Adds docs to Postgres, syncs to OpenSearch, compares BM25 / vector / hybrid, explain | 13 |
| `docs/adr/0013-use-opensearch-for-keyword….md` | ADR-0013: OpenSearch for keyword and hybrid search | 13 |
| `compose.yaml` service `object-store` | SeaweedFS 4.x `weed mini`, identities built in tmpfs from secrets, `127.0.0.1:8333`, volume `object-store-data` | 14 |
| [`scripts/s3_setup.py`](../scripts/s3_setup.py) | Buckets: `rag-raw-docs` (versioned, 90-day old-version expiry), `rag-audit-archive` (object lock), `rag-tmp` (1-day expiry) | 14 |
| [`scripts/s3_demo.py`](../scripts/s3_demo.py) | Proves versioning, least privilege, presigned URLs, object lock; records lineage in Postgres | 14 |
| [`docs/data/object-storage.md`](data/object-storage.md) | Bucket purposes, rules and access | 14 |
| `docs/adr/0014-use-seaweedfs….md` | ADR-0014: SeaweedFS instead of unmaintained MinIO | 14 |
| `compose.yaml` service `valkey` | Valkey 9.1.x (alpine, pinned), ACL file built in tmpfs from secrets, `127.0.0.1:6379`, volume `valkey-data` | 15 |
| [`infra/config/valkey/valkey.conf`](../infra/config/valkey/valkey.conf) | Memory limit + eviction policy, AOF `everysec` + RDB snapshots, slowlog | 15 |
| [`scripts/kv_queue_demo.py`](../scripts/kv_queue_demo.py) | Proves ACLs, a Streams job queue with retries + dead-letter, and a safe lock | 15 |
| `docs/adr/0015-use-valkey….md` | ADR-0015: Valkey for cache, queues and locks | 15 |

### Identity and policy (Steps 16–18)

| File | Purpose | Step |
|---|---|---:|
| `compose.yaml` services `keycloak`, `keycloak-db` | Keycloak 26.8.x production mode, realm import, JSON logs, `127.0.0.1:8180`; Postgres 17, volume `keycloak-db-data` | 16 |
| [`infra/config/keycloak/realm-rag.json`](../infra/config/keycloak/realm-rag.json) | Realm as code: policies, roles, groups, clients, mappers, service accounts; secrets as `${…}` placeholders | 16 |
| [`scripts/kc_users.py`](../scripts/kc_users.py) | Creates demo users and group memberships via the least-privilege provisioner | 16 |
| [`scripts/kc_whoami.py`](../scripts/kc_whoami.py) | Device-flow sign-in, client-credentials sign-in, token claims, logout | 16 |
| [`docs/adr/0016-use-keycloak-for-identity.md`](adr/0016-use-keycloak-for-identity.md) | ADR-0016: Keycloak for identity | 16 |
| [`libs/rag-common/src/rag_common/auth.py`](../libs/rag-common/src/rag_common/auth.py) | Shared token verifier: RS256 only, JWKS cache, issuer/audience/expiry/type/client checks → `Principal` | 17 |
| [`services/rag-api/`](../services/rag-api/) | First service: FastAPI app (`main.py`, `settings.py`, `search.py`), auth tests, multi-stage Dockerfile | 17 |
| `compose.yaml` service `rag-api` | Built from the repo, `127.0.0.1:8000`, non-root, read-only, `cap_drop: ALL`, file secrets | 17 |
| [`scripts/api_demo.py`](../scripts/api_demo.py) | Calls the API as person, machine, no token and forged token (from Step 33 also asks, streams and rates) | 17 |
| `docs/adr/0017-validate-jwts-locally….md` | ADR-0017: local JWT validation in every service | 17 |
| [`policies/rag/authz/`](../policies/rag/authz/) `authz.rego` · `data.json` · `authz_test.rego` | Authorisation policy (actions, clearance, caps, search filter, post-check), its mappings and tests | 18 |
| [`policies/system/authz/authz.rego`](../policies/system/authz/authz.rego) (+ test) | Protects OPA's own API: token required, decisions only, no uploads | 18 |
| [`.regal/config.yaml`](../.regal/config.yaml) | Regal lint settings (`data.json` references are expected) | 18 |
| `compose.yaml` service `opa` | OPA 1.21.x static image, read-only policies, `--watch`, JSON decision logs, non-root, `127.0.0.1:8181` | 18 |
| [`services/rag-api/src/rag_api/policy.py`](../services/rag-api/src/rag_api/policy.py) | OPA client: `decide()` and `readable()`, fail closed | 18 |
| `services/rag-api/tests/conftest.py`, `test_policy.py`, `test_opa_live.py` | Shared fakes, wiring tests, real-OPA tests | 18 |
| [`docs/adr/0018-use-opa-as-the-policy-decision-point.md`](adr/0018-use-opa-as-the-policy-decision-point.md) | ADR-0018: OPA as the policy decision point | 18 |

### Observability (Steps 19–22)

| File | Purpose | Step |
|---|---|---:|
| [`infra/config/otel-collector/config.yaml`](../infra/config/otel-collector/config.yaml) | Collector pipelines: OTLP in; memory_limiter, scrub, redaction, resource, batch; debug out (Step 21 adds `fluent_forward`, `groupbyattrs`, log-body masking; exporters `otlp_grpc/tempo`, `otlp_http/loki`) | 19, 21 |
| `compose.yaml` service `otel-collector` | Collector contrib 0.162.x, read-only, `127.0.0.1:4317/4318/13133` | 19 |
| [`libs/rag-common/src/rag_common/telemetry.py`](../libs/rag-common/src/rag_common/telemetry.py) | `setup_telemetry()` (traces, metrics, flush on shutdown) and JSON logs with trace ids | 19 |
| `services/rag-api/tests/test_telemetry.py` | One trace per search, attributes, metrics, no token or question text | 19 |
| [`docs/adr/0019-use-opentelemetry-and-a-central-collector.md`](adr/0019-use-opentelemetry-and-a-central-collector.md) | ADR-0019: OpenTelemetry and a central Collector | 19 |
| [`infra/config/prometheus/prometheus.yml`](../infra/config/prometheus/prometheus.yml) | OTLP receiver settings, rule files, Alertmanager, scrape jobs with secret-file credentials | 20 |
| `infra/config/prometheus/rules/{slo-rag-search,security,platform}.yml` | Recording rules and alerts: SLO burn rates, latency, policy mismatch, login failures, target down, telemetry loss | 20 |
| [`infra/config/prometheus/tests/rules_test.yml`](../infra/config/prometheus/tests/rules_test.yml) | promtool unit-test groups for the alerts (test 8 for the audit alert from Step 23) | 20 |
| [`infra/config/alertmanager/alertmanager.yml`](../infra/config/alertmanager/alertmanager.yml) | Grouping, severity routing, inhibition, receivers | 20 |
| `infra/config/grafana/provisioning/…`, `dashboards/rag-overview.json` | Data sources and dashboards loaded at start-up (Step 21 adds Tempo and Loki with exemplar, trace-to-logs, trace-to-metrics and log-to-trace links) | 20, 21 |
| [`scripts/build_dashboards.py`](../scripts/build_dashboards.py) | Dashboards as code: generates the Grafana JSON; `--check` detects drift | 20 |
| [`docs/runbooks/*.md`](runbooks/) | What to do when each alert fires | 20 |
| `compose.yaml` services `prometheus`, `alertmanager`, `grafana`, `postgres-exporter` | Monitoring stack, pinned, localhost-only | 20 |
| [`docs/adr/0020-use-prometheus-alertmanager-and-grafana.md`](adr/0020-use-prometheus-alertmanager-and-grafana.md) | ADR-0020: Prometheus, Alertmanager, Grafana, SLO alerting | 20 |
| [`infra/config/tempo/tempo.yaml`](../infra/config/tempo/tempo.yaml) | Tempo 3 single-process: OTLP in, local storage, retention, metrics generator | 21 |
| [`infra/config/loki/loki.yaml`](../infra/config/loki/loki.yaml) | Loki single-process: tsdb v13, retention with compactor, structured metadata | 21 |
| `compose.yaml` services `tempo`, `loki` | Pinned, localhost-only APIs, volumes `tempo-data`, `loki-data` | 21 |
| [`docs/adr/0021-use-tempo-and-loki-for-traces-and-logs.md`](adr/0021-use-tempo-and-loki-for-traces-and-logs.md) | ADR-0021: Tempo and Loki | 21 |
| `compose.yaml` services `langfuse-web`, `langfuse-worker`, `langfuse-db`, `langfuse-clickhouse`, `langfuse-valkey` | Self-hosted Langfuse 4.27 with dedicated stores | 22 |
| SeaweedFS identity `langfuse`, bucket `langfuse` (30-day rule on `events/`) | Langfuse event and media storage | 22 |
| [`services/rag-api/src/rag_api/llmtrace.py`](../services/rag-api/src/rag_api/llmtrace.py) | Langfuse on a private tracer provider: masking, withheld titles, shared trace id | 22 |
| `services/rag-api/tests/test_llmtrace.py`, `tests/test_langfuse_retention.py` | Langfuse integration and retention tests | 22 |
| [`scripts/langfuse_retention.py`](../scripts/langfuse_retention.py) | Deletes traces older than N days (self-hosted retention is Enterprise-only) | 22 |
| [`docs/adr/0022-use-self-hosted-langfuse-for-llm-traces.md`](adr/0022-use-self-hosted-langfuse-for-llm-traces.md) | ADR-0022: self-hosted Langfuse | 22 |

### Audit and governance (Steps 23–25)

| File | Purpose | Step |
|---|---|---:|
| [`infra/config/rag-db/init/02-audit.sh`](../infra/config/rag-db/init/02-audit.sh) | One-time bootstrap: audit database, three roles, no default EXECUTE | 23 |
| [`infra/db/audit/migrations/20261012090000_create_audit_log.sql`](../infra/db/audit/migrations/20261012090000_create_audit_log.sql) | `audit.events`, `event_body()`, `append()` (hash chain), `verify()`, append-only trigger, grants | 23 |
| [`services/rag-api/src/rag_api/audit.py`](../services/rag-api/src/rag_api/audit.py) | `AuditEvent`, `AuditLog`, `PgAuditLog` (checked pool, fail fast) | 23 |
| `services/rag-api/tests/test_audit.py` | What is and isn't recorded; fail closed | 23 |
| `tests/conftest.py`, `tests/test_audit_db.py` | Real-Postgres tests: roles, trigger, chain, attacks, concurrency, restart | 23 |
| [`scripts/audit_chain.py`](../scripts/audit_chain.py), `tests/test_audit_chain.py` | Anchor and verify against the object-locked bucket; tests with moto | 23 |
| [`docs/runbooks/audit-log.md`](runbooks/audit-log.md) | Audit write failures and failed verifications (treat as incident) | 23 |
| Alert `RagAuditWriteFailing` in `prometheus/rules/security.yml` (+ promtool test 8) | Pages when audit events can't be stored | 23 |
| [`docs/adr/0023-use-a-hash-chained-audit-log-anchored-in-write-once-storage.md`](adr/0023-use-a-hash-chained-audit-log-anchored-in-write-once-storage.md) | ADR-0023: hash-chained audit log anchored in write-once storage | 23 |
| [`libs/rag-common/src/rag_common/prompts.py`](../libs/rag-common/src/rag_common/prompts.py) | Prompt registry: format rules, safe single-pass rendering, lock and label checks | 24 |
| [`prompts/query-instruction/v1.yaml`](../prompts/query-instruction/v1.yaml) | The embedding query instruction, moved out of `search.py` unchanged | 24 |
| `prompts/rag-answer/v1.yaml`, `v2.yaml` | The answer prompt used by `/v1/answer` in Step 33 (v2 adds citations) | 24 |
| [`scripts/prompts.py`](../scripts/prompts.py) | `just prompts list / lint / new / lock / promote / render / diff` | 24 |
| `libs/rag-common/tests/test_prompts.py`, `tests/test_prompts_cli.py`, `services/rag-api/tests/test_prompts_api.py` | Registry rules, workflow and rag-api integration tests | 24 |
| `.pre-commit-config.yaml` hooks `prompts-lint`, `prompts-check-main`; `.github/CODEOWNERS` `/prompts/` | Prompt checks on commit and push; owners review prompt changes | 24 |
| Grafana "Active prompt versions" table + "Prompt version changes" annotation; metric `rag_prompt_info` | What runs where, and when it changed | 24 |
| [`docs/adr/0024-manage-prompts-as-versioned-files-in-a-registry.md`](adr/0024-manage-prompts-as-versioned-files-in-a-registry.md) | ADR-0024: prompts as versioned files in a registry | 24 |
| `cards/models/{qwen-quality,qwen-fast,embedder,reranker}.yaml` | Model cards: use, out of scope, limits, risks, licence (verified date), fallback rule | 25 |
| `cards/datasets/{company-documents,company-chunks,llm-traces,audit-log,rag-answer-golden}.yaml` | Dataset cards: provenance, locations, personal data + legal basis, retention, deletion | 25 |
| [`cards/systems/rag-api.yaml`](../cards/systems/rag-api.yaml) | System card: purpose, users, oversight, EU AI Act risk assessment | 25 |
| [`libs/rag-common/src/rag_common/cards.py`](../libs/rag-common/src/rag_common/cards.py) | Card schemas, rules, lineage graph, impact analysis, Markdown pages | 25 |
| [`scripts/cards.py`](../scripts/cards.py) | `just cards lint / docs / impact / lineage` | 25 |
| [`docs/cards/*.md`](cards/) (generated) | Readable cards and a Mermaid lineage diagram; never edited by hand | 25 |
| `libs/rag-common/tests/test_cards.py`, `tests/test_cards_cli.py` | Rule-by-rule and command-line tests | 25 |
| [`docs/adr/0025-document-models-datasets-and-systems-as-checked-cards-with-lineage.md`](adr/0025-document-models-datasets-and-systems-as-checked-cards-with-lineage.md) | ADR-0025: checked cards with lineage | 25 |

### Quality and delivery (Steps 26–29)

| File | Purpose | Step |
|---|---|---:|
| [`libs/rag-evals/`](../libs/rag-evals/) (`datasets`, `metrics`, `targets`, `judge`, `runner`, `gates`, `record`) | The evaluation harness package | 26 |
| `evals/datasets/retrieval-golden/`, `evals/datasets/rag-answer-golden/` | Golden datasets: `v1.jsonl` + `dataset.yaml` with pinned SHA-256 | 26 |
| [`prompts/eval-judge/v1.yaml`](../prompts/eval-judge/v1.yaml) | The LLM judge's prompt: correct / faithful, strict JSON | 26 |
| [`cards/datasets/retrieval-golden.yaml`](../cards/datasets/retrieval-golden.yaml) | Card for the retrieval dataset; `rag-answer-golden` now approved | 26 |
| [`scripts/evals.py`](../scripts/evals.py) | `just evals run / gate / compare / baseline / record / release` | 26 |
| `libs/rag-evals/tests/*`, `services/rag-api/tests/test_eval_consistency.py`, `tests/test_evals_cli.py` | Metrics by hand, real-policy test, harness = endpoint, workflow | 26 |
| `evals/runs/` (git-ignored) | Every run: `results.jsonl` + `summary.json` with provenance | 26 |
| [`docs/adr/0026-evaluate-retrieval-and-prompts-offline-with-versioned-datasets-and-gates.md`](adr/0026-evaluate-retrieval-and-prompts-offline-with-versioned-datasets-and-gates.md) | ADR-0026: offline evaluation with versioned datasets and gates | 26 |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Pull requests and main: checks, supply-chain, image (build, Trivy, SBOM) | 27 |
| [`.github/workflows/release.yml`](../.github/workflows/release.yml) | Main: push by digest, cosign keyless signature, provenance + SBOM attestations | 27 |
| [`.github/workflows/evals.yml`](../.github/workflows/evals.yml) | Evaluations on the self-hosted Mac; same-repo PRs only; approval required | 27 |
| `.github/dependabot.yml`, `.github/actionlint.yaml` | Weekly pin updates (actions, uv, Docker); custom runner label | 27 |
| [`scripts/ci_tools.py`](../scripts/ci_tools.py), [`scripts/licences.py`](../scripts/licences.py) | Checksum-verified tool installer; dependency licence check | 27 |
| [`services/rag-api/Dockerfile`](../services/rag-api/Dockerfile) (fixed) | Copies every workspace member's manifest and the prompt registry | 27 |
| `tests/test_ci_policy.py`, `tests/test_ci_tools.py`, `tests/test_licences.py` | Pipeline rules, installer and licence tests | 27 |
| [`docs/adr/0027-run-ci-with-pinned-tools-and-publish-signed-attested-images.md`](adr/0027-run-ci-with-pinned-tools-and-publish-signed-attested-images.md) | ADR-0027: CI with pinned tools; signed, attested images | 27 |
| [`infra/config/openbao/server.hcl`](../infra/config/openbao/server.hcl) | OpenBao server: raft storage, listener, telemetry, file audit device | 28 |
| `infra/config/openbao/policies/*.hcl` | `rag-api`, `rag-evals`, `developer`, `platform-admin` policies (`rag-ingest` from Step 37) | 28 |
| [`infra/config/openbao/agent-rag-api.hcl`](../infra/config/openbao/agent-rag-api.hcl) | Agent: AppRole auto-auth with wrapped secret ID, templates into `/openbao/out` | 28 |
| `infra/config/rag-db/init/03-openbao.sh`, `infra/config/rag-db/vault-cutover.sql` | OpenBao's database logins; switch shared roles to NOLOGIN | 28 |
| `compose.yaml` services `openbao`, `rag-api-agent`; volumes `openbao-data`, `openbao-logs`, `rag-api-bao` (tmpfs) | Secrets manager and rag-api's agent sidecar | 28 |
| [`scripts/vault_setup.py`](../scripts/vault_setup.py) | Desired state applied idempotently: engines, policies, DB connections and roles, AppRoles, admin login; put, creds, unseal | 28 |
| [`libs/rag-common/src/rag_common/secrets.py`](../libs/rag-common/src/rag_common/secrets.py) | `CredentialsFile` (re-read on change), `StaticCredentials` | 28 |
| [`docs/runbooks/openbao.md`](runbooks/openbao.md) · alerts `OpenBaoSealed`, `OpenBaoAuditFailing` | Sealed, audit failing, agent and leak procedures, break-glass | 28 |
| `tests/test_vault.py`, `libs/rag-common/tests/test_secrets.py`, `services/rag-api/tests/test_settings.py` | Live OpenBao + Postgres tests; credentials and settings tests | 28 |
| [`docs/adr/0028-issue-database-credentials-dynamically-from-openbao.md`](adr/0028-issue-database-credentials-dynamically-from-openbao.md) | ADR-0028: dynamic database credentials from OpenBao | 28 |
| [`deploy/cluster/`](../deploy/cluster/) | Namespace `rag` (Pod Security), quota and limits, admission policies `rag-images-pinned`, `rag-workloads-hardened` | 29 |
| [`deploy/base/rag-api/`](../deploy/base/rag-api/) | ServiceAccount, Deployment (2 replicas, OpenBao Agent native sidecar), Service, PDB, NetworkPolicies, agent config | 29 |
| [`deploy/components/external-deps/`](../deploy/components/external-deps/) | ExternalName services: Compose services under their usual names | 29 |
| [`deploy/envs/local/`](../deploy/envs/local/) | The local overlay: namespace, image digest (set by `just promote`), patches | 29 |
| [`deploy/argocd/install/`](../deploy/argocd/install/) (+ `upstream/install.yaml`, vendored v3.5.5) | Argo CD and its settings (`argocd-cm`, `argocd-rbac-cm`, `argocd-cmd-params-cm`) | 29 |
| `deploy/argocd/apps/`, `deploy/argocd/root.yaml` | AppProjects and Applications (app of apps); the one file applied by hand | 29 |
| [`scripts/promote.py`](../scripts/promote.py), [`scripts/k8s_secrets.py`](../scripts/k8s_secrets.py) | One-line digest promotion; the pull and repository Secrets from SOPS env vars | 29 |
| [`.trivyignore.yaml`](../.trivyignore.yaml) | Accepted Kubernetes scan findings, each with a reason and an expiry | 29 |
| `tests/kube.py`, `tests/test_k8s.py`, `tests/test_promote.py`, `tests/test_k8s_secrets.py` | A real kube-apiserver for tests; manifest, policy, Argo CD, promotion and Secret tests | 29 |
| [`docs/runbooks/kubernetes.md`](runbooks/kubernetes.md) | Rollback, OutOfSync/Degraded, sidecar login, pull errors, cluster reset | 29 |
| [`docs/adr/0029-run-rag-api-on-kubernetes-deployed-by-argo-cd-from-git.md`](adr/0029-run-rag-api-on-kubernetes-deployed-by-argo-cd-from-git.md) | ADR-0029: Kubernetes + Argo CD GitOps | 29 |

### RAG core (Steps 30–35)

`rag_core/…` below means [`libs/rag-core/src/rag_core/`](../libs/rag-core/src/rag_core/).

| File | Purpose | Step |
|---|---|---:|
| `libs/rag-core/` (`rag_core/types.py`, `contracts.py`, `registry.py`, `config.py`, `cli.py`) | The RAG core: data types, contracts, component registry and Container, profile loader, `rag` command | 30 |
| `rag_core/testing/conformance.py` | Shared tests every embedder and store must pass, including the access-leak checks | 30 |
| `rag_core/components/basics.py` | Token counters, gateway and scripted LLMs, hashing embedder, in-memory vector store and BM25 index | 30 |
| `docs/adr/0030-…` | ADR-0030: a shared core of switchable components | 30 |
| `rag_core/components/parsing.py`, `cleaning.py` | Parsers (text, Markdown, HTML, CSV, PDF, DOCX; Docling and Tika as options), normalisers, PII redaction | 31 |
| `rag_core/components/chunking.py`, `enrichment.py` | Six chunkers; context-header, LLM-context and question enrichers; gateway and cached embedders | 31 |
| `rag_core/components/pgstore.py`, `qdrant.py`, `opensearch.py`, `queues.py` | pgvector, Postgres full-text, Qdrant, OpenSearch BM25 and k-NN stores; manifests and job queues | 31 |
| `rag_core/ingest.py` | `IngestionPipeline`, `Worker`, `load_source` (`file://` and `s3://`) | 31 |
| [`infra/db/rag/migrations/20261013000000_rag_core.sql`](../infra/db/rag/migrations/20261013000000_rag_core.sql) | Tenant, chunk keys, embed text, parent links, nullable embeddings, `rag.ingest_manifest` | 31 |
| [`examples/corpus/`](../examples/corpus/) | Six sample sources (Markdown, HTML, PDF, DOCX, CSV and a broken PDF) for tests and demos | 31 |
| [`libs/rag-core/tests/`](../libs/rag-core/tests/) | Registry, parsing, cleaning, chunking, enrichment, store (live pgvector and Qdrant) and pipeline tests | 30–31 |
| `compose.yaml` service `ingestion-worker` | Runs `rag worker --forever` with the `local` profile | 31 |
| `docs/adr/0031-…` | ADR-0031: one replace-not-append ingestion pipeline, redacting before storing | 31 |
| `rag_core/components/retrieval.py` | Query transformers, dense/keyword/hybrid retrievers, RRF/weighted/DBSF fusion, five rerankers, seven post-processors | 32 |
| `rag_core/search.py`, `evaluate.py` | `SearchPipeline` (traced, access re-check) · search evaluation: recall@k, MRR, nDCG@k, leaks, latency | 32 |
| `examples/corpus/handbook/` (17 policies), [`examples/eval/handbook.yaml`](../examples/eval/handbook.yaml) (25 questions, 11 variants) | Sample corpus and labelled search evaluation | 32 |
| `libs/rag-core/tests/test_retrieval.py`, `services/rag-api/tests/test_core_search.py` | Search tests; rag-api on rag-core with OPA and audit | 32 |
| [`services/rag-api/src/rag_api/search.py`](../services/rag-api/src/rag_api/search.py) · `CoreSearch` | `/v1/search` answered by rag-core | 32 |
| [`docs/adr/0032-search-through-a-switchable-hybrid-pipeline.md`](adr/0032-search-through-a-switchable-hybrid-pipeline.md) | ADR-0032: hybrid retrieval, fusion and reranking in one switchable pipeline | 32 |
| `rag_core/components/generation.py`, `conversation.py` | Context builder, citation check, LLM and extractive generators, `AnswerParams`; memory and caches | 33 |
| `rag_core/answer.py` | `AnswerPipeline` (answer and stream), guard hook, `answer_dict` | 33 |
| `libs/rag-core/tests/test_answer.py`, `services/rag-api/tests/test_answer_api.py` | Answer tests; `/v1/answer` and `/v1/feedback` with OPA and audit | 33 |
| [`docs/adr/0033-answer-with-checked-citations-and-abstention.md`](adr/0033-answer-with-checked-citations-and-abstention.md) | ADR-0033: numbered sources, checked citations, abstention | 33 |
| `rag_core/components/guards.py` | Ten guards (size, injection, pii, topics, context-injection, groundedness, secrets, toxicity, llm-judge, webhook) and `Verdict` | 34 |
| [`examples/eval/guards.yaml`](../examples/eval/guards.yaml), `libs/rag-core/tests/test_guards.py` | Attack and ordinary cases with known gaps; guard tests | 34 |
| [`docs/adr/0034-layered-guardrails-measured-in-ci.md`](adr/0034-layered-guardrails-measured-in-ci.md) | ADR-0034: layered guardrails at three stages, measured in CI | 34 |
| `rag_core/components/architectures.py` | Eight architectures, the memory graph store and entity extractor, SQL RAG with an authorizer | 35 |
| `examples/tables/expense_limits.csv`, `salary_bands.csv` | Sample tables for SQL RAG (one internal, one confidential) | 35 |
| `libs/rag-core/tests/test_architectures.py` | Architecture tests | 35 |
| [`docs/adr/0035-rag-architectures-as-switchable-pipelines.md`](adr/0035-rag-architectures-as-switchable-pipelines.md) | ADR-0035: architectures as switchable pipelines sharing every control | 35 |

### Production and reuse (Steps 36–38)

| File | Purpose | Step |
|---|---|---:|
| `rag_core/lifecycle.py` | Retention, erasure (source and subject), access changes, re-index; dry-run reports | 36 |
| [`infra/db/rag/migrations/20261014000000_lifecycle_and_tenants.sql`](../infra/db/rag/migrations/20261014000000_lifecycle_and_tenants.sql) | Manifest access/metadata columns and tenant RLS policies | 36 |
| [`scripts/backup.py`](../scripts/backup.py) | Backups with receipts and restore drills | 36 |
| [`scripts/compliance.py`](../scripts/compliance.py), [`docs/compliance/risk-register.yaml`](compliance/risk-register.yaml) | Risk register checks and generated docs | 36 |
| [`docs/security/threat-model.md`](security/threat-model.md), [`docs/compliance/controls.md`](compliance/controls.md) | Generated threat model and control/framework matrix | 36 |
| [`docs/architecture/workspace.dsl`](architecture/workspace.dsl) | C4 architecture model as code | 36 |
| [`examples/lifecycle_demo.py`](../examples/lifecycle_demo.py) | Walk-through of every lifecycle action | 36 |
| `libs/rag-core/tests/test_lifecycle.py`, `tests/test_backup.py`, `tests/test_compliance.py` | Lifecycle, backup and register tests | 36 |
| [`docs/adr/0036-lifecycle-tenant-isolation-and-a-risk-register-as-code.md`](adr/0036-lifecycle-tenant-isolation-and-a-risk-register-as-code.md) | ADR-0036: lifecycle operations, tenant RLS, restore drills, risk register as code | 36 |
| `deploy/envs/staging/`, `deploy/envs/prod/`, `deploy/envs/promotion.yaml` | Staging and prod overlays; promotion rules | 37 |
| [`deploy/components/production/`](../deploy/components/production/) (`rollout.yaml`, `analysis-template.yaml`, `hpa.yaml`, patches, `kustomize-config.yaml`) | What makes an environment production-shaped: canary, analysis, autoscaling, spreading | 37 |
| [`deploy/components/managed-deps/`](../deploy/components/managed-deps/) | Service aliases to real dependencies in staging/prod | 37 |
| [`deploy/base/rag-ingest/`](../deploy/base/rag-ingest/) (worker, CronJobs, own identity, `retention.yaml`) | Ingestion worker and scheduled lifecycle jobs | 37 |
| `deploy/argo-rollouts/install/`, `deploy/cnpg/install/` | Vendored, hash-checked Argo Rollouts, CloudNativePG and Barman Cloud plugin | 37 |
| [`deploy/data/`](../deploy/data/) (`base`, `envs`, `drills`) | HA Postgres with backups and PITR; the DR drill cluster | 37 |
| `deploy/argocd/common/`, `deploy/argocd/operators/`, `deploy/argocd/envs/{staging,prod}/` | Argo CD per environment; the data project | 37 |
| [`infra/config/openbao/policies/rag-ingest.hcl`](../infra/config/openbao/policies/rag-ingest.hcl) | The worker's OpenBao policy | 37 |
| `infra/config/prometheus/rules/rag-answers.yml`, `infra/config/prometheus/tests/rag_answers_test.yml` | Answer-quality alerts and their unit tests | 37 |
| `rag_core/online.py`, `rag_core/readiness.py` | Online evaluation; production readiness | 37 |
| [`scripts/gates.py`](../scripts/gates.py), [`scripts/dr_drill.py`](../scripts/dr_drill.py) | Promotion gates and evidence; DR drill | 37 |
| [`examples/online_demo.py`](../examples/online_demo.py) | Online evaluation end to end, without a cluster | 37 |
| `docs/runbooks/answer-quality.md`, `canary.md`, `disaster-recovery.md`; [`docs/architecture/cloud-mapping.md`](architecture/cloud-mapping.md) | Runbooks; managed-service equivalents | 37 |
| `tests/test_environments.py`, `tests/test_gates.py`, `libs/rag-core/tests/test_online.py`, `test_readiness.py` | Step 37 tests | 37 |
| [`docs/adr/0037-production-environments-canaries-and-recovery.md`](adr/0037-production-environments-canaries-and-recovery.md) | ADR-0037: gated promotion, canaries, HA Postgres, online evaluation | 37 |
| `rag_core/sdk.py`, `rag_core/doctor.py`, `rag_core/profiles/platform.yaml` | SDK, standards check, packaged profiles | 38 |
| [`templates/rag-project/`](../templates/rag-project/) | The Copier project template | 38 |
| [`docs/standards/rag-standards.md`](standards/rag-standards.md) | Standards with ids: MUST / SHOULD / reviewed | 38 |
| [`docs/catalogue.md`](catalogue.md), [`scripts/catalogue.py`](../scripts/catalogue.py) | Every switchable component, generated (Appendix C) | 38 |
| [`libs/rag-core/CHANGELOG.md`](../libs/rag-core/CHANGELOG.md) | rag-core versions; 1.0.0 = stable public API | 38 |
| `libs/rag-core/tests/test_sdk.py`, `test_doctor.py`, `tests/test_template.py` | Step 38 tests | 38 |
| [`docs/adr/0038-a-reuse-kit-for-rag-projects.md`](adr/0038-a-reuse-kit-for-rag-projects.md) | ADR-0038: versioned core, packaged profiles, standards as code, template | 38 |
| [`docs/adr/`](adr/README.md) | All decision records, ADR-0001 to ADR-0038 | 4–38 |

---

## Command cheat sheet

Run from the repository root. `just` with no arguments lists every recipe.

### Homebrew (Step 1)

| Command | What it does |
|---|---|
| `brew bundle --file=bootstrap/Brewfile` | Install everything on the list that's missing (`just bootstrap`) |
| `brew bundle check --file=bootstrap/Brewfile` | Confirm everything on the list is installed |
| `brew doctor` | Diagnose common Homebrew problems |
| `brew analytics off` | Stop sending usage statistics |
| `brew upgrade <name>` | Upgrade one tool, on purpose |
| `which <tool>` | Show which copy of a tool your shell will run |

### uv (Step 2)

| Command | What it does |
|---|---|
| `uv python install 3.12` | Install a managed Python interpreter |
| `uv python list --only-installed` | List installed interpreters |
| `uv init <name> --python 3.12` | Create a new project |
| `uv add <pkg>` / `uv add --dev <pkg>` | Add a dependency (edit + lock + sync) / a dev-only dependency |
| `uv lock` | Update the lockfile from `pyproject.toml` |
| `uv sync` | Make `.venv` match the lockfile |
| `uv sync --locked` | Fail if the lockfile is out of date (the CI check) |
| `uv run <cmd>` | Sync, then run a command inside the project environment |
| `uv tree` | Show the full dependency tree |
| `uv lock --upgrade-package <pkg>` | Upgrade one package deliberately |
| `uvx <tool>` / `uv tool install <tool>` | Run a tool once in isolation / install a tool globally |

### Docker and OrbStack (Step 3)

| Command | What it does |
|---|---|
| `docker version` / `docker context ls` | Check the CLI and engine, and which runtime you're talking to |
| `orb config show` / `orb config set memory_mib 24576` | View / set OrbStack VM limits |
| `docker run --rm alpine uname -m` | Check that containers are native arm64 (`aarch64`) |
| `docker buildx imagetools inspect <image>` | Show which platforms an image supports |
| `docker run -p 127.0.0.1:<host>:<container> …` | Publish a port to localhost only |
| `--add-host=host.docker.internal:host-gateway` | Let a container reach the Mac on any runtime |
| `docker volume create <name>` / `-v <name>:/path` | Create and use a named volume |
| `docker run --memory 256m --cpus 0.5 …` | Cap one container's resources |
| `docker stats --no-stream` | Show live resource use |
| `lsof -nP -iTCP -sTCP:LISTEN` | List every listening port on the Mac |
| `docker system df` / `docker image prune` | Show disk use / remove unused images |

### Git, GitHub and the repo (Step 4)

| Command | What it does |
|---|---|
| `git status` | Show what's changed and what's staged. Read it before every commit. |
| `git add <files>` / `git commit -m "type(scope): message"` | Stage changes / save a signed Conventional Commit |
| `git log --oneline` / `git log --show-signature -1` | Short history / verify the latest commit's signature |
| `git switch -c <branch>` / `git switch main` | Create and move to a branch / return to main |
| `git push -u origin <branch>` / `git pull` | Send a branch to GitHub / fetch and fast-forward |
| `gh auth login` / `gh ssh-key add … --type signing` | Log in to GitHub / upload a signing key |
| `gh repo create rag-platform --private --source=. --push` | Create the private remote and push |
| `gh pr create --fill` / `gh pr merge --squash --delete-branch` | Open a PR / squash-merge it and delete the branch |
| `just` / `just check` / `just sync` | List recipes / verify tools and lockfile / install all workspace packages |
| `just adr "Title"` | Create the next numbered ADR from the template |
| `uv init --lib libs/<name>` | Add a new shared library to the workspace |
| `uv run --package <member> <cmd>` | Run a command in the context of one workspace member |

### Code quality (Step 5)

| Command | What it does |
|---|---|
| `uv add --dev <tool>` | Add a development-only tool, locked in `uv.lock` |
| `uv run ruff check --fix .` / `just lint` | Lint and auto-fix safe issues |
| `uv run ruff format .` / `just fmt` | Format all code |
| `uv run mypy` / `just typecheck` | Strict type check of the configured files |
| `uv run pytest` / `just test` | Run the tests |
| `uv run pre-commit install` (`just install-hooks`) | Install the pre-commit, commit-msg and pre-push hooks (once per clone) |
| `uv run pre-commit run --all-files` / `just hooks` | Run every hook on every file |
| `uv run pre-commit autoupdate --freeze` | Update hook versions, pinned to commit SHAs |
| `SKIP=<hook-id> git commit …` | Skip one hook for one commit |
| `git commit --no-verify` | Skip all local hooks (CI still checks) |
| `just check` | Everything CI will run: Brewfile, locked sync, all hooks, tests |

### Secrets (Step 6)

| Command | What it does |
|---|---|
| `age-keygen -o ~/.config/sops/age/keys.txt` | Create your age key pair (prints the public key) |
| `age-keygen -y ~/.config/sops/age/keys.txt` | Show your public key again |
| `just secrets-init` | Generate and encrypt `secrets/dev.enc.env` (first time) |
| `just secrets-keys` | List secret names, never values |
| `just secrets-edit` / `sops secrets/dev.enc.env` | Edit secrets; decrypted only inside the editor |
| `just with-secrets <cmd>` / `sops exec-env secrets/dev.enc.env '<cmd>'` | Run one command with secrets in its environment |
| `sops --encrypt --in-place <file>` | Encrypt a file in place using `.sops.yaml` rules |
| `sops updatekeys <file>` | Apply recipient changes from `.sops.yaml` |
| `sops --rotate --in-place <file>` | Replace the internal data key |
| `security add-generic-password -a "$USER" -s <name> -w` | Store a personal token in the macOS Keychain |
| `security find-generic-password -s <name> -w` | Read a token from the Keychain |
| `direnv allow` | Approve the project's `.envrc` after changes |

### Model serving (Step 7)

| Command | What it does |
|---|---|
| `just models-download` | Download both models into the Hugging Face cache |
| `just serve-quality` / `just serve-fast` | Run a model server in the foreground |
| `just models-up` / `just models-down` | Install and start / stop the launchd services |
| `just models-health` | Check both `/health` endpoints |
| `just models-logs` | Follow the server logs |
| `just bench` / `just bench --long` | Measure TTFT and tok/s (short / ~8k-token prompt) |
| `curl -s http://127.0.0.1:8081/v1/models` | List models a server can see |
| `mlx_lm.generate --model <repo> --prompt "…"` | One-off generation; prints tok/s and peak memory |
| `ls ~/.cache/huggingface/hub/models--<org>--<name>/snapshots/` | Show the exact downloaded revision SHA |
| `sysctl iogpu.wired_limit_mb` | Show the GPU memory limit setting |
| `launchctl bootstrap gui/$(id -u) <plist>` / `launchctl bootout gui/$(id -u)/<label>` | Load / unload a launchd agent |

### Embeddings and reranking (Step 8)

| Command | What it does |
|---|---|
| `just serve-embed` / `just serve-rerank` | Run a TEI server in the foreground |
| `just search-models-up` / `just search-models-down` | Start / stop the always-on embedder and reranker |
| `just health` | Health of all four model servers |
| `just with-secrets uv run scripts/embed_demo.py` (`just embed-demo`) | Embeddings, instructions, Matryoshka and reranking demo |
| `just with-secrets uv run scripts/bench_embeddings.py` (`just bench-embed`) | Measure chunks/s and rerank latency |
| `POST :8083/embed {"inputs": [...]}` | Get normalised embeddings (Bearer token required) |
| `POST :8083/v1/embeddings` | OpenAI-compatible embeddings |
| `POST :8084/rerank {"query": "...", "texts": [...]}` | Relevance scores for each text |
| `text-embeddings-router --help` | All TEI options for your version |

### Gateway and Compose (Step 9)

| Command | What it does |
|---|---|
| `just up` / `just down` | Start (with secrets in memory) / stop the container stack |
| `just ps` / `just logs [service]` | Container status and health / follow logs |
| `just gateway-health` | Liveness and readiness of the gateway |
| `just with-secrets uv run --with openai scripts/gateway_smoke.py` (`just gateway-smoke`) | Full smoke and security test through the gateway |
| `docker buildx imagetools inspect <image:tag>` | Show an image's digest and platforms (for pinning) |
| `docker inspect <container> --format '{{json .Config.Env}}'` | Check no secrets leaked into the environment |
| `curl http://127.0.0.1:4000/v1/models -H "Authorization: Bearer $KEY"` | Models the gateway allows |

### Gateway governance (Step 10)

| Command | What it does |
|---|---|
| `just gateway-admin team <alias> --budget <usd> --models …` | Create a team with a budget |
| `just gateway-admin key <alias> --team-id <id> --models … --rpm N --parallel N` | Issue a scoped virtual key (shown once) |
| `just with-secrets 'uv run scripts/gateway_admin.py info "$KEY"'` | Show a key's spend, limits, expiry |
| `just gateway-admin block <key>` | Block a key immediately |
| `just gateway-test` | Prove allow-list, rate-limit and budget enforcement |
| `launchctl bootout gui/$(id -u)/com.rag-platform.qwen-fast` | Fallback drill: stop the fast model (restore with `just models-up`) |
| `docker compose -f infra/compose/compose.yaml exec litellm-db psql -U litellm` | Inspect the gateway DB without exposing its port |

### Postgres + pgvector (Step 11)

| Command | What it does |
|---|---|
| `just db-psql` | Superuser SQL shell inside the container |
| `just db-migrate new <name>` / `up` / `status` / `rollback` | Create, apply, inspect, undo migrations (as `rag_migrator`) |
| `just db-backup` / `just db-restore-test <dump>` | Logical backup / prove a backup restores (receipts and drills from Step 36) |
| `\du` · `\dx` · `\dt rag.*` (in psql) | List roles · extensions · tables |
| `EXPLAIN (ANALYZE) <query>` | Show how a query runs (index or not) |
| `SET hnsw.ef_search = 100;` | More search effort per query (recall up, speed down) |
| `SET hnsw.iterative_scan = relaxed_order;` | Keep scanning when filters remove results |
| `SELECT … FROM pg_stat_statements …` | Slowest / most frequent queries |

### Qdrant (Step 12)

| Command | What it does |
|---|---|
| `just qdrant-health` | List collections with the admin key |
| `just with-secrets uv run --with qdrant-client scripts/qdrant_setup.py` | Create collection, payload indexes and alias |
| `just with-secrets uv run --with qdrant-client --with "psycopg[binary]" --with pgvector --with openai scripts/qdrant_sync.py` | Sync from Postgres and run permission-aware search |
| `just with-secrets uv run --with qdrant-client --with pyjwt scripts/qdrant_token.py` | Mint and test a read-only token |
| `just qdrant-snapshot` | Snapshot the live collection |
| `open http://127.0.0.1:6333/dashboard` | Web dashboard (log in with the admin key) |
| `curl -H "api-key: $KEY" http://127.0.0.1:6333/collections` | REST call with a key header |

### OpenSearch (Step 13)

| Command | What it does |
|---|---|
| `just os-health` | Cluster health (admin) |
| `just os-count` | Documents in `rag-chunks` (read-only user) |
| `just with-secrets uv run --with opensearch-py scripts/os_setup.py` | Users, index, alias, hybrid pipeline |
| `just with-secrets uv run --with opensearch-py --with "psycopg[binary]" --with pgvector --with openai scripts/os_demo.py` | Sync from Postgres and compare search styles |
| `curl -sk -u "<user>:$PASSWORD" https://127.0.0.1:9200/<index>/_search` | Raw search as a user (`-k`: dev self-signed certs only) |
| `POST /<index>/_search?search_pipeline=rag-hybrid` | Hybrid query with score normalisation |
| `"explain": true` in a search body | Show how each score was computed |
| `docker run --rm --privileged alpine sysctl -w vm.max_map_count=262144` | Fix the VM limit if OpenSearch complains |

### Object storage (Step 14)

| Command | What it does |
|---|---|
| `just s3 s3 ls` / `just s3 s3 ls s3://rag-raw-docs --recursive` | List buckets / objects (admin) |
| `just s3 s3api list-object-versions --bucket rag-raw-docs` | Show every version of every object |
| `just with-secrets uv run --with boto3 scripts/s3_setup.py` | Create buckets and rules |
| `just with-secrets uv run --with boto3 --with "psycopg[binary]" scripts/s3_demo.py` | Prove the rules and record lineage |
| `boto3 … generate_presigned_url("get_object", ExpiresIn=300, …)` | Temporary link to one object version |

### Valkey (Step 15)

| Command | What it does |
|---|---|
| `just kv-cli ping` | Health check as admin (expect `PONG`) |
| `just kv-cli acl list` / `just kv-cli acl whoami` | Show users and their rules / who you are |
| `just kv-cli info memory` | Memory used, limit and eviction policy |
| `just kv-cli --scan --pattern 'rag:*'` | List keys safely (never `KEYS *` in production) |
| `just kv-cli ttl <key>` | Seconds until a key expires (`-1` = never, `-2` = gone) |
| `just kv-cli xinfo groups rag:ingest:jobs` | Consumer groups, pending and lag on the job stream |
| `just kv-cli xpending rag:ingest:jobs rag:ingest:workers` | Jobs claimed but not yet acknowledged |
| `just kv-cli slowlog get 10` | The ten slowest recent commands |
| `just with-secrets uv run --with redis scripts/kv_queue_demo.py` | Run the ACL / queue / lock demo |

### Keycloak (Step 16)

| Command | What it does |
|---|---|
| `open http://localhost:8180/admin/` | Admin console (sign in to `master` as your personal admin) |
| `curl -s http://localhost:8180/realms/rag/.well-known/openid-configuration` | Discovery document: issuer, endpoints, JWKS address (pipe into `jq`) |
| `curl -s http://localhost:8180/realms/rag/protocol/openid-connect/certs` | Public signing keys (JWKS) |
| `just kc-users` | Create demo users and memberships (safe to re-run) |
| `just kc-whoami` | Sign in via device flow + client credentials and print token claims |
| `docker compose -f infra/compose/compose.yaml logs keycloak` | Start-up, import and error logs (JSON) |
| `just down && docker volume rm rag-platform_keycloak-db-data && just up` | Dev only: wipe and re-import the realm |

### rag-api and token checks (Step 17)

| Command | What it does |
|---|---|
| `just check` | ruff + mypy (strict) + pytest, including the auth tests |
| `uv run pytest services/rag-api -q` | Run only the API tests |
| `just api-up` | Rebuild the image and restart rag-api after code changes |
| `curl -si http://127.0.0.1:8000/v1/me` | Expect 401 with `WWW-Authenticate: Bearer realm="rag-api"` |
| `just api-demo` | Person / machine / no token / forged token, end to end |
| `docker compose -f infra/compose/compose.yaml logs rag-api` | See why tokens were rejected (reasons only, never tokens) |

### Policy engine (Step 18)

| Command | What it does |
|---|---|
| `just policy-check` | `opa fmt`, `opa check --strict`, `regal lint`, `opa test` with ≥ 90% coverage |
| `opa test policies -v` | Run every policy test, showing each name |
| `opa test policies --coverage --format=json` | Find policy lines no test touches |
| `opa eval -d policies -i input.json "data.rag.authz.decision"` | Evaluate a decision locally from a file, no server needed |
| `curl -H "Authorization: Bearer $T" -X POST localhost:8181/v1/data/rag/authz/decision -d '{"input":…}'` | Ask the running OPA for a decision |
| `docker compose -f infra/compose/compose.yaml logs opa` | Decision logs (JSON) with input, result and `decision_id` |

### OpenTelemetry (Step 19)

| Command | What it does |
|---|---|
| `curl -s localhost:13133/` | Collector health (`"status":"Server available"`) |
| `docker run --rm -v "$PWD/infra/config/otel-collector:/cfg:ro" otel/opentelemetry-collector-contrib:0.162.0 validate --config=/cfg/config.yaml` | Validate the Collector config before restarting |
| `docker compose -f infra/compose/compose.yaml logs otel-collector` | What the Collector received (set `verbosity: detailed` for every attribute) |
| `docker compose -f infra/compose/compose.yaml logs rag-api` | JSON logs; pipe into `jq '{level, msg, trace_id}'` |
| `OTEL_SDK_DISABLED=true` | Switch telemetry off for one run (e.g. a benchmark baseline) |
| `uv run pytest services/rag-api/tests/test_telemetry.py -q` | Run only the telemetry tests |

### Prometheus, Alertmanager and Grafana (Step 20)

| Command | What it does |
|---|---|
| `just alerts-test` | Check rules, run alert unit tests, check Alertmanager config (pinned promtool from Step 37) |
| `just dashboards` / `just dashboards-check` | Regenerate dashboard JSON / fail if it's out of date |
| `just prom-reload` | Reload Prometheus config and rules without a restart (SIGHUP) |
| `open http://localhost:9090/targets` | Is every target UP? (401 = wrong token) |
| `open http://localhost:9090/alerts` | Rules and their state: inactive, pending, firing |
| `open http://localhost:9093` | Alertmanager: firing alerts, create a silence for maintenance |
| PromQL `rag:search_errors:ratio_rate1h` | Share of failed searches, last hour (recording rule) |
| PromQL `histogram_quantile(0.95, sum by (le) (rate(rag_search_duration_seconds_bucket[5m])))` | p95 search latency |

### Tempo and Loki (Step 21)

| Command | What it does |
|---|---|
| `curl -s localhost:3200/ready` / `curl -s localhost:3100/ready` | Is Tempo / Loki ready? |
| `curl -s localhost:3200/api/v2/traces/<trace_id>` | Fetch one trace as JSON |
| `curl -s localhost:3100/loki/api/v1/label/service_name/values` | Which services have logs |
| LogQL `{service_name="rag-api"} \|= "<trace_id>"` | One request's log lines |
| LogQL `{service_name="rag-api"} \| json \| level="ERROR"` | Parse JSON logs and filter by field |
| TraceQL `{resource.service.name="rag-api" && duration > 1s}` | Slow rag-api traces |
| PromQL `sum by (client, server) (rate(traces_service_graph_request_total[5m]))` | Who calls whom, per second |

### Langfuse (Step 22)

| Command | What it does |
|---|---|
| `open http://localhost:3002` | Langfuse UI (Tracing → Traces; filter by user, tags, time) |
| `just langfuse-retention --dry-run` | How many traces are older than the retention window |
| `just langfuse-retention` | Delete them (scheduled nightly: [`bootstrap/home/crontab`](../bootstrap/home/crontab)) |
| `just s3 s3api get-bucket-lifecycle-configuration --bucket langfuse` | Check the 30-day rule on raw events |
| `docker stats --no-stream` | Check memory headroom (ClickHouse is the heaviest) |
| `uv run pytest services/rag-api/tests/test_llmtrace.py -q` | Masking, withholding, isolation and trace-id tests |

### Audit log (Step 23)

| Command | What it does |
|---|---|
| `just audit-bootstrap` | One-time: create the audit database and roles on an existing rag-db volume |
| `just audit-migrate up` / `status` | Apply / list audit migrations (as `audit_migrator`); rollback is refused by design |
| `just audit-psql` | Superuser SQL shell on `audit` (break-glass) |
| `SELECT * FROM audit.verify();` | Check the chain in the database: ok, rows checked, first bad row, problem |
| `just audit-anchor` | Copy new events + head hash to `rag-audit-archive` (refuses if history was rewritten) |
| `just audit-verify` | Database chain, archive and their agreement; exit 1 with a list of problems |
| `just audit-test` | Full test suite including the audit database and OpenBao tests, on a throwaway Postgres (port 55432, password `test-admin` since Step 28) |

### Prompt registry (Step 24)

| Command | What it does |
|---|---|
| `just prompts list` | Every prompt, its versions and labels |
| `just prompts lint` | Validate format, rules, lock and labels (pre-commit runs it) |
| `just prompts new <name>` | Start the next version as a copy of the latest |
| `just prompts lock` | Release new versions (record their SHA-256); refuses if a released file was edited |
| `just prompts promote <name> <version> <label>` | Point a label (staging, production) at a version; roll back the same way |
| `just prompts render <name> [--label L / --version N] --var k=v …` | Show exactly what the model would receive |
| `just prompts diff <name> <a> <b>` | What changed between two versions |
| `just prompts-check-main` | Released versions on main are unchanged here (before push; CI in Step 27) |

### Cards and lineage (Step 25)

| Command | What it does |
|---|---|
| `just cards lint` | All rules and cross-checks; errors fail (pre-commit runs it) |
| `just cards lint --strict` | Warnings fail too: overdue reviews, licence re-checks (weekly) |
| `just cards docs` / `--check` | Regenerate `docs/cards/` / fail if a page is stale |
| `just cards impact model:embedder` | Everything downstream, with owners: what to re-check before a change |
| `just cards lineage dataset:llm-traces` | Everything upstream: what it was built from |

### Evaluation harness (Step 26)

| Command | What it does |
|---|---|
| `just evals release <dataset>` | Pin a new dataset version (SHA-256) in its `dataset.yaml` |
| `just evals run retrieval` | Every retrieval case as its persona, through the real policy: recall@5, MRR, nDCG, leaks |
| `just evals run answer --prompt rag-answer --label staging [--judge]` | Every answer case with a prompt version: pass rate, refusals, citations, injections |
| `just evals compare <run-a> <run-b>` | Metrics side by side, and the cases that changed |
| `just evals gate <run>` | Thresholds + the prompt's `min_score` + no regression vs baseline; exit 1 on failure |
| `just evals baseline <run>` | Make a run the new reference (commit it, with the reason) |
| `just evals record <run> --card model:<id>` | Write the results into the model card (then `just cards docs`) |

### CI and supply chain (Step 27)

| Command | What it does |
|---|---|
| `just tools [names]` | Install pinned tools into `.tools/bin`, refusing any whose SHA-256 differs |
| `just ci` | Everything a pull request must pass, locally (static, tests, config, policy, supply chain) |
| `just ci-supply-chain` | gitleaks (history), actionlint, zizmor, pip-audit on `uv.lock`, licences, Trivy on the Dockerfile |
| `just image-scan` | Build the image and scan it like CI: Trivy + a CycloneDX SBOM |
| `just image-verify sha256:…` | Check a published image's keyless signature and attestations before deploying |
| `gh pr checks --watch` · `gh run list --workflow release.yml` | Follow a pull request's checks · find the latest release run |

### Vault / OpenBao (Step 28)

| Command | What it does |
|---|---|
| `just vault-init` | Once: initialise; key shares and root token go straight into `secrets/openbao-init.enc.json` |
| `just vault-unseal` · `just vault-up` | Unseal after a restart (keys piped from SOPS) · unseal and restart the agent |
| `just vault-setup-first` · `just vault-revoke-root` | First configuration with the root token · then retire it |
| `just vault-login` · `just vault-setup` | Your admin login (1 h) · apply the policy files and script again (idempotent) |
| `just vault-put rag-api key=ENV_VAR …` | Store secret values taken from your SOPS environment (never typed on the command line) |
| `just vault-creds rag-readonly` | A 1-hour read-only database login in `.bao/rag-readonly.json` (0600) |
| `just vault-agent-start` | Fresh role ID + wrapped single-use secret ID for rag-api's agent; (re)start it |
| `just vault-status` · `just vault-check` | Seal state, audit devices, leases · policies in canonical format (CI) |
| `just vault-db-bootstrap` · `just vault-cutover` / `vault-cutover-undo` | Create OpenBao's DB logins on an existing volume · shared roles NOLOGIN / back to LOGIN |
| `bao lease revoke <lease_id>` · `bao lease revoke -prefix database/creds/rag-api` | End one login now (sessions ended, user dropped) · all of a role's logins |
| `bao write sys/audit-hash/file input=<value>` | The HMAC of a value, to search the audit log for it |
| `bao operator seal` · `bao operator generate-root` | Seal on purpose (test the alert) · break-glass root token from 2 key shares |

### Kubernetes and GitOps (Step 29)

| Command | What it does |
|---|---|
| `just k8s-up` | Start OrbStack's Kubernetes and show the node |
| `just k8s-render [path]` · `just k8s-diff [path]` | What a kustomization renders · what would change in the cluster (read-only) |
| `just k8s-check` · `just k8s-scan` | Render everything and run the Kubernetes tests (real API server) · Trivy on the rendered manifests |
| `just k8s-bootstrap` | Once per cluster: Argo CD, repository key, projects, root app |
| `just k8s-pull-secret` · `just k8s-repo-secret` | The two Kubernetes Secrets, built from SOPS env vars |
| `just vault-k8s-trust` | Let OpenBao trust this cluster's service account tokens (after every cluster reset) |
| `just k8s-status` · `just argocd-ui` | Applications' sync/health and the rag pods · Argo CD UI on https://localhost:8443 |
| `just k8s-deps-check` · `just k8s-netpol-check` | Can pods reach Compose? · Are NetworkPolicies enforced? |
| `just promote <env> sha256:…` | Verify the image, change its digest in one line, open a pull request (merge = deploy) |
| `git revert <promotion commit>` | Roll back (through a pull request) |
| `just argocd-vendor v3.x.y` | Upgrade Argo CD: fetch the release manifest, record its SHA-256 |
| `kubectl --context orbstack -n rag logs deploy/rag-api -c openbao-agent` | Why a pod is stuck in Init (OpenBao login) |

### RAG core, production and reuse (Steps 30–38)

| Command | What it does |
|---|---|
| `uv run rag components [--kind embedder] [--json]` | Every registered component with its status (live, mocked, reference) and what it needs installed |
| `uv run rag config check --profile offline` | Build every slot of a profile (needs its services) |
| `uv run rag config validate --profile local` | Check names and settings without connecting to anything (CI-safe) |
| `uv run rag config show --profile local` | The fully resolved profile, after `extends` and environment overrides |
| `uv run rag ingest --profile offline --group hr examples/corpus/*` | Ingest files now, in this process; `--force` ignores the manifest |
| `uv run rag enqueue --profile local file:///… s3://…` · `--delete` | Queue ingestion (or deletion) jobs for the workers |
| `uv run rag worker --profile local [--forever]` | Process queued jobs: retries, then the dead-letter stream |
| `uv run rag delete --profile local <uri>` | Remove a source from every store and the manifest |
| `uv run pytest -q libs/rag-core` | rag-core tests (live store tests need `RAG_TEST_PGVECTOR_DSN` and the Qdrant binary from `just tools`) |
| `uv run rag search "question" --profile offline --group all-staff [--ingest files…] [--json]` | Search as someone; every hit with its dense, sparse, fusion and rerank scores (Step 32) |
| `uv run rag eval-search examples/eval/handbook.yaml --profile offline [--variant …] [--no-ingest] [--fail-under recall=0.9]` | Compare search variants on labelled questions; exit 1 on a gate failure or any leak |
| `just rag-config-check` · `just search-eval` | CI: every profile validates (and `production` is ready) · the shipped search settings pass the quality and leak gate |
| `RAG__RETRIEVER__USE=keyword` · `RAG__RERANKER__USE=none` · `RAG__QUERY_TRANSFORMER__USE=multi-query` · `RAG__FUSION__USE=weighted` | Switch one search stage for one run |
| `uv run rag ask "question" ["follow-up" …] --profile offline --group all-staff --corpus examples/eval/handbook.yaml [--stream] [--no-memory] [--json]` | Cited answers in one conversation; trace with cache, model, prompt and timings (Step 33) |
| `POST /v1/answer {"question", "session_id"?, "stream"?}` · `POST /v1/feedback {"answer_id", "rating", "reason"?}` | rag-api: an answer (JSON or server-sent events) · a rating tied to that answer |
| `just api-demo` | Now also asks, follows up, streams and rates (Step 33) |
| `uv run rag eval-guards examples/eval/guards.yaml --profile offline [--min-catch-rate 0.95] [--max-false-positive-rate 0.05]` | Catch rate, false positive rate, wrong cases and known gaps (Step 34) |
| `just guard-eval` | CI: the guardrail gate |
| `uv run rag components --kind guard` | The ten guards and their settings |
| `uv run rag eval-answers examples/eval/handbook.yaml --profile offline [--variant standard] [--fail-under context_recall=0.95]` | Compare architectures: context recall, answered, cited, abstentions, groundedness, leaks, latency (Step 35) |
| `just answer-eval` | CI: the default architecture's gate |
| `RAG__PIPELINE__USE=adaptive` · `RAG__PIPELINE__USE=graph RAG__GRAPH_STORE__USE=memory RAG__ENRICHERS='[context-header, graph-entities]'` | Try an architecture for one run |
| `uv run rag retention --rules examples/retention.yaml --profile local [--apply]` | Report (or remove) documents past their retention rule (Step 36) |
| `uv run rag erase-source <uri> --profile local [--apply]` | Remove a document everywhere, including every stored object version |
| `uv run rag erase-subject --subject <sub> [--identifier <email>] --profile local [--apply]` | Remove a person's conversations and cached answers; list documents mentioning them |
| `uv run rag reacl <uri> --group hr --classification confidential --profile local` | Change a document's access in every store at once |
| `uv run rag reindex --profile local --to local-v2 [--apply]` | Blue/green re-index into a new collection |
| `just db-backup` · `just db-restore-test <dump>` | Backup with receipt · restore drill into a throwaway database |
| `just compliance-check` · `just compliance-docs` | Validate the risk register · regenerate the threat model and control matrix |
| `uv run rag config readiness --profile production` | Fit for production? Errors fail (Step 37) |
| `uv run rag online-eval --events audit.jsonl \| --dsn-file F [--candidate A --baseline B] [--queue review.jsonl] [--json verdict.json] [--on-insufficient wait\|pass\|fail]` | Answer quality per release; exit 0 pass, 1 fail, 3 wait (`just online-eval`) |
| `uv run rag erase-source <uri> --rules retention.yaml [--override-hold "reason"] [--apply]` | Erasure that respects legal holds |
| `just gates <env> sha256:… [evidence] [alertmanager]` · `just gates-record <check> sha256:… pass "summary"` | Check the promotion gates · record evidence (CI) |
| `just promote <env> sha256:… ["INC-123: reason"]` | Gates, then the digest pull request; a reason = break glass |
| `just dr-drill "2026-10-13 08:59:00+00"` | Restore into a new cluster at that second, compare, delete |
| `just vendor argo-rollouts\|cnpg\|barman-cloud <version>` | Upgrade a vendored operator, recording its hash |
| `just tools promtool` · `just alerts-test` | Pinned promtool · alert rules and their unit tests |
| `kubectl argo rollouts get rollout rag-api -n rag --watch` · `… abort` · `… promote --full` | Watch, stop or (break glass) finish a canary |
| `kubectl cnpg status rag-db -n rag-data` | Database cluster health, replication, backups (cnpg plugin) |
| `just new-project ../my-project` (`uvx copier copy --trust templates/rag-project …`) | A new RAG project from the template (Step 38) |
| `uvx copier update` (in a project) | Bring template improvements into an existing project |
| `uv run rag doctor [path] [--json]` · `just doctor` | Check a project against the standards |
| `just catalogue [--check]` | Regenerate (or check) the component catalogue |
| `just sync-profiles` | Copy `rag.yaml` into rag-core's packaged profiles after editing it |
| `python -c "from rag_core.sdk import RagApp; …"` | Use the engine from any script or notebook |

### Recipes not in the guide's cheat sheet

These exist in the `justfile` (added by the steps) but Appendix A doesn't list them separately:
`default`, `install-hooks`, `embed-demo`, `bench-embed`, `gateway-smoke`, `search-models-download`,
`licences`, `ci-static`, `ci-test`, `ci-config`, `vault-secret-id`, `online-eval`.
