# Model serving (Step 7): which models to serve, and the shared safe server command
quality_model := "mlx-community/Qwen3.8-27B-8bit"
fast_model    := "lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit"
serve         := "HF_HUB_OFFLINE=1 uv run --project infra/model-serving mlx_lm.server --host 127.0.0.1 --allowed-origins http://localhost"

# Embedding and reranking (Step 8): served by TEI from pinned local snapshot folders
embed_model   := "Qwen/Qwen3-Embedding-0.6B"
rerank_model  := "BAAI/bge-reranker-v2-m3"

# Container stack (Step 9): one Compose file for every platform service
compose       := "docker compose -f infra/compose/compose.yaml"

# The RAG database (Step 11): migrations connect as rag_migrator, never as the superuser.
# search_path lists "public" too, because the pgvector types (halfvec, vector) live there.
rag_db_url    := "postgres://rag_migrator:$RAG_DB_MIGRATOR_PASSWORD@127.0.0.1:5432/rag?sslmode=disable&search_path=rag,public"

# Object storage (Step 14): SeaweedFS S3 API, localhost only, path-style
s3_endpoint   := "http://127.0.0.1:8333"

# Monitoring (Step 20): the same Prometheus / Alertmanager versions as Compose, for promtool and amtool
prom_image := "prom/prometheus:v3.13.4"
am_image := "prom/alertmanager:v0.34.1"

# List available recipes (runs when you type just "just")
default:
    @just --list

# Install system tools from the Brewfile
bootstrap:
    brew bundle --file=bootstrap/Brewfile

# Install Python packages for every workspace member
sync:
    uv sync --all-packages

# Re-resolve the lockfile after editing a pyproject.toml
lock:
    uv lock

# Install the git hooks (pre-commit, commit-msg, pre-push); run once after cloning
install-hooks:
    uv run pre-commit install

# Format all code
fmt:
    uv run ruff format .

# Lint (and auto-fix what's safe)
lint:
    uv run ruff check --fix .

# Strict type check
typecheck:
    uv run mypy

# Run the tests
test:
    uv run pytest

# Run every pre-commit hook on every file
hooks:
    uv run pre-commit run --all-files

# Every local gate in one go (needs Homebrew); CI runs the `ci-*` recipes below (Step 27)
check:
    brew bundle check --file=bootstrap/Brewfile
    uv sync --locked --all-packages
    uv run pre-commit run --all-files
    just policy-check
    just alerts-test
    just dashboards-check
    uv run pytest

# Policies: formatted, compiled strictly, linted, tested with >= 90% coverage (Step 18)
policy-check:
    opa fmt --list --fail policies
    opa check --strict policies
    regal lint policies
    opa test policies --coverage --threshold 90 > /dev/null
    opa test policies

# Validate Prometheus config + rules and run the alert unit tests (same versions as production)
alerts-test:
    docker run --rm -v "$PWD/infra/config/prometheus:/p:ro" -w /p --entrypoint promtool {{prom_image}} check rules rules/slo-rag-search.yml rules/security.yml rules/platform.yml
    docker run --rm -v "$PWD/infra/config/prometheus:/p:ro" -w /p --entrypoint promtool {{prom_image}} test rules tests/rules_test.yml
    docker run --rm -v "$PWD/infra/config/alertmanager:/a:ro" --entrypoint amtool {{am_image}} check-config /a/alertmanager.yml

# Regenerate dashboards from scripts/build_dashboards.py / check they're up to date
dashboards:
    uv run python scripts/build_dashboards.py
dashboards-check:
    uv run python scripts/build_dashboards.py --check

# Reload Prometheus after editing its config or rules (no restart, no lost data)
prom-reload:
    docker compose -f infra/compose/compose.yaml kill -s HUP prometheus

# Create the next numbered ADR from the template:   just adr "Use Qdrant for vectors"
adr title:
    #!/usr/bin/env bash
    set -euo pipefail
    last=$(ls docs/adr | grep -E '^[0-9]{4}-' | sed 's/-.*//' | sort -n | tail -1)
    next=$(printf "%04d" $((10#$last + 1)))
    slug=$(echo "{{title}}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//; s/-$//')
    file="docs/adr/${next}-${slug}.md"
    sed -e "s/NNNN/${next}/" -e "s/TITLE/{{title}}/" -e "s/YYYY-MM-DD/$(date +%F)/" docs/adr/0000-template.md > "$file"
    echo "created $file"

# Create the encrypted dev secrets file (first time only)
secrets-init:
    scripts/new-dev-secrets.sh

# List secret NAMES (never values)
secrets-keys:
    sops --decrypt secrets/dev.enc.env | cut -d= -f1 | grep -v '^#' | grep .

# Edit secrets safely (decrypted only inside the editor)
secrets-edit:
    sops secrets/dev.enc.env

# Run any command with the dev secrets available:   just with-secrets docker compose up -d
with-secrets +cmd:
    sops exec-env secrets/dev.enc.env "{{cmd}}"

# Download both models (needs network + HF token)
models-download:
    uv run --project infra/model-serving hf download {{quality_model}}
    uv run --project infra/model-serving hf download {{fast_model}}

# Run a model server in the foreground (Ctrl+C to stop)
serve-quality:
    {{serve}} --model {{quality_model}} --port 8081 --max-tokens 4096

serve-fast:
    {{serve}} --model {{fast_model}} --port 8082 --max-tokens 2048 --chat-template-args '{"enable_thinking": false}'

# Install / remove the always-on launchd services
models-up:
    QUALITY_MODEL={{quality_model}} FAST_MODEL={{fast_model}} scripts/install-model-agents.sh

models-down:
    -launchctl bootout gui/$(id -u)/com.rag-platform.qwen-quality
    -launchctl bootout gui/$(id -u)/com.rag-platform.qwen-fast

# Are both model servers healthy?
models-health:
    @curl -sf http://127.0.0.1:8081/health && echo "  quality :8081 ok" || echo "  quality :8081 DOWN"
    @curl -sf http://127.0.0.1:8082/health && echo "  fast    :8082 ok" || echo "  fast    :8082 DOWN"

# Follow the model server logs
models-logs:
    tail -f ~/Library/Logs/rag-platform/qwen-*.log

# Measure TTFT and tokens/s
bench *args:
    uv run scripts/bench_models.py {{args}}

# Download the embedding and reranker models (needs network + HF token)
search-models-download:
    uv run --project infra/model-serving hf download {{embed_model}}
    uv run --project infra/model-serving hf download {{rerank_model}}

# Run the embedding / reranker servers in the foreground
serve-embed:
    scripts/run-tei.sh "$(scripts/model-path.sh {{embed_model}})" 8083 9083 qwen3-embedding-0.6b

serve-rerank:
    scripts/run-tei.sh "$(scripts/model-path.sh {{rerank_model}})" 8084 9084 bge-reranker-v2-m3

# Always-on embedding + reranker services
search-models-up:
    EMBED_DIR="$(scripts/model-path.sh {{embed_model}})" RERANK_DIR="$(scripts/model-path.sh {{rerank_model}})" scripts/install-tei-agents.sh

search-models-down:
    -launchctl bootout gui/$(id -u)/com.rag-platform.embedder
    -launchctl bootout gui/$(id -u)/com.rag-platform.reranker

# Health of every model server (LLMs + embedder + reranker)
health: models-health
    @curl -sf -o /dev/null http://127.0.0.1:8083/health && echo "  embedder:8083 ok" || echo "  embedder:8083 DOWN"
    @curl -sf -o /dev/null http://127.0.0.1:8084/health && echo "  reranker:8084 ok" || echo "  reranker:8084 DOWN"

# Embeddings demo (instruction, Matryoshka, reranking) and benchmark; both need TEI_API_KEY
embed-demo:
    sops exec-env secrets/dev.enc.env "uv run scripts/embed_demo.py"

bench-embed:
    sops exec-env secrets/dev.enc.env "uv run scripts/bench_embeddings.py"

# Start / stop the container stack (secrets decrypted in memory)
up:
    sops exec-env secrets/dev.enc.env '{{compose}} up -d'
    {{compose}} ps

down:
    {{compose}} down

ps:
    {{compose}} ps

# Follow logs of one service:   just logs litellm
logs service="litellm":
    {{compose}} logs -f --tail 100 {{service}}

# Gateway checks
gateway-health:
    @curl -sf http://127.0.0.1:4000/health/liveliness > /dev/null && echo "  gateway :4000 alive" || echo "  gateway :4000 DOWN"
    @curl -sf http://127.0.0.1:4000/health/readiness | jq -c . || true

# End-to-end smoke test through the gateway (chat, streaming, embeddings, rerank, security checks)
gateway-smoke:
    sops exec-env secrets/dev.enc.env "uv run --with openai scripts/gateway_smoke.py"

# Gateway administration (master key, decrypted in memory)
gateway-admin *args:
    sops exec-env secrets/dev.enc.env 'uv run scripts/gateway_admin.py {{args}}'

# Prove the gateway's controls work (creates and blocks throwaway keys)
gateway-test:
    sops exec-env secrets/dev.enc.env 'uv run scripts/gateway_limits_test.py'

# Database migrations:   just db-migrate new create_core_tables | up | status | rollback
db-migrate *args="status":
    sops exec-env secrets/dev.enc.env 'DATABASE_URL="{{rag_db_url}}" dbmate --migrations-dir infra/db/rag/migrations --no-dump-schema {{args}}'

# Admin SQL shell (superuser, inside the container: no password on your Mac)
db-psql:
    docker compose -f infra/compose/compose.yaml exec rag-db psql -U postgres -d rag

# Backups (Step 36): a dump plus a receipt (checksum, row counts); a drill restores it and compares.
# They replace Step 11's first versions. The dump goes to backups/ (gitignored: it holds all your data).
db-backup out="backups/rag-$(date +%Y%m%d-%H%M).dump":
    sops exec-env secrets/dev.enc.env 'uv run python scripts/backup.py backup --dsn-env RAG_BACKUP_DSN --out {{out}}'

db-restore-test dump:
    sops exec-env secrets/dev.enc.env 'uv run python scripts/backup.py restore-test --dump {{dump}} --admin-dsn-env RAG_RESTORE_ADMIN_DSN'

# Qdrant checks (admin key from secrets)
qdrant-health:
    sops exec-env secrets/dev.enc.env 'curl -sf -H "api-key: $QDRANT_API_KEY" http://127.0.0.1:6333/collections | jq -c .'

# Create a Qdrant snapshot of the live collection (stored in the qdrant-snapshots volume)
qdrant-snapshot:
    sops exec-env secrets/dev.enc.env 'curl -sf -X POST -H "api-key: $QDRANT_API_KEY" http://127.0.0.1:6333/collections/rag_chunks_qwen3e06b_v1/snapshots | jq -c .result'

# OpenSearch: cluster health (admin) and index document counts
os-health:
    sops exec-env secrets/dev.enc.env 'curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" https://127.0.0.1:9200/_cluster/health | jq -c "{status, number_of_nodes, active_shards}"'

os-count:
    sops exec-env secrets/dev.enc.env 'curl -sk -u "rag_search:$OPENSEARCH_SEARCH_PASSWORD" https://127.0.0.1:9200/rag-chunks/_count | jq .count'

# AWS CLI against the local object store as ADMIN:   just s3 s3 ls   /   just s3 s3api list-buckets
# Keys are decrypted from SOPS into this one command only (never ~/.aws/credentials). Each argument is
# re-quoted, so JMESPath queries such as --query 'Versions[].{key:Key}' survive the inner shell.
[positional-arguments]
s3 *args:
    #!/usr/bin/env bash
    set -euo pipefail
    sops exec-env secrets/dev.enc.env "AWS_ACCESS_KEY_ID=\"\$S3_ADMIN_ACCESS_KEY\" AWS_SECRET_ACCESS_KEY=\"\$S3_ADMIN_SECRET_KEY\" AWS_REGION=us-east-1 aws --endpoint-url {{s3_endpoint}} $(printf '%q ' "$@")"

# Valkey CLI as admin (password via env var, never as an argument):   just kv-cli ping   /   just kv-cli acl list
kv-cli *args:
    sops exec-env secrets/dev.enc.env 'docker compose -f infra/compose/compose.yaml exec -e REDISCLI_AUTH="$VALKEY_ADMIN_PASSWORD" valkey valkey-cli --user admin {{args}}'

# Keycloak (Step 16): create demo users with the least-privilege provisioner (safe to re-run)
kc-users:
    just with-secrets uv run --with httpx scripts/kc_users.py

# Keycloak: sign in (device flow) and as a machine (client credentials), look inside the tokens, sign out
kc-whoami:
    just with-secrets uv run --with httpx scripts/kc_whoami.py

# Rebuild and restart the API after code changes (Step 17)
api-up:
    sops exec-env secrets/dev.enc.env 'docker compose -f infra/compose/compose.yaml up -d --build rag-api'

# Call the API as a person, a machine, with no token and with a forged token
api-demo:
    just with-secrets uv run --with httpx scripts/api_demo.py

# Delete Langfuse traces older than LANGFUSE_RETENTION_DAYS (default 30). Run nightly. (Step 22)
langfuse-retention *args:
    sops exec-env secrets/dev.enc.env 'LANGFUSE_BASE_URL=http://localhost:3002 uv run python scripts/langfuse_retention.py {{args}}'

# ---- Audit log (Step 23) ----
audit_db_url := "postgres://audit_migrator:$AUDIT_DB_MIGRATOR_PASSWORD@127.0.0.1:5432/audit?sslmode=disable"

# One-time: create the audit database and roles on an EXISTING rag-db volume
audit-bootstrap:
    docker compose -f infra/compose/compose.yaml exec -T rag-db bash < infra/config/rag-db/init/02-audit.sh

# Audit migrations:   just audit-migrate up | status
audit-migrate *args="status":
    sops exec-env secrets/dev.enc.env 'DATABASE_URL="{{audit_db_url}}" dbmate --migrations-dir infra/db/audit/migrations --migrations-table audit.schema_migrations --no-dump-schema {{args}}'

# Superuser SQL shell on the audit database (break-glass: inside the container only)
audit-psql *args:
    docker compose -f infra/compose/compose.yaml exec rag-db psql -U postgres -d audit {{args}}

# All tests, including the audit database tests, against a throwaway Postgres (deleted afterwards)
audit-test:
    #!/usr/bin/env bash
    set -euo pipefail
    export PATH="/opt/homebrew/opt/libpq/bin:$PATH"
    # Step 28: a real password (not "trust"), so tests can prove that old passwords STOP working
    docker run -d --rm --name audit-test-pg -p 127.0.0.1:55432:5432 \
      -e POSTGRES_PASSWORD=test-admin pgvector/pgvector:0.8.7-pg17@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d >/dev/null
    trap 'docker stop audit-test-pg >/dev/null' EXIT
    until docker exec audit-test-pg pg_isready -h 127.0.0.1 -U postgres -q; do sleep 1; done
    # Step 31: the same Postgres (it's the pgvector image) runs rag-core's store conformance tests
    AUDIT_TEST_ADMIN_DSN=postgres://postgres:test-admin@127.0.0.1:55432/postgres \
    RAG_TEST_PGVECTOR_DSN=postgres://postgres:test-admin@127.0.0.1:55432/postgres uv run pytest

audit_reader_dsn := "postgres://audit_reader:$AUDIT_DB_READER_PASSWORD@127.0.0.1:5432/audit"

# Copy new audit events + head hash to the write-once bucket. Hourly.
audit-anchor:
    sops exec-env secrets/dev.enc.env 'AUDIT_DB_DSN="{{audit_reader_dsn}}" uv run python scripts/audit_chain.py anchor'

# Check database chain, archive, and that they agree. Daily, and on request. Exit 1 = problems.
audit-verify:
    sops exec-env secrets/dev.enc.env 'AUDIT_DB_DSN="{{audit_reader_dsn}}" uv run python scripts/audit_chain.py verify'

# ---- Prompt registry (Step 24) ----
# just prompts list | lint | new <name> | lock | promote <name> <version> <label> | render … | diff …
[positional-arguments]
prompts *args:
    uv run python scripts/prompts.py "$@"

# Released prompt versions on main must be unchanged here (CI runs this; Step 27)
prompts-check-main:
    git fetch -q origin main
    git show origin/main:prompts/prompts.lock.json > .git/main-prompts.lock.json 2>/dev/null || : > .git/main-prompts.lock.json
    uv run python scripts/prompts.py lint --against .git/main-prompts.lock.json

# ---- Cards and lineage (Step 25) ----
# just cards lint [--strict] | docs [--check] | impact <kind:id> | lineage <kind:id>
[positional-arguments]
cards *args:
    uv run python scripts/cards.py "$@"

# ---- Evaluation harness (Step 26) ----
# just evals run retrieval | run answer --prompt rag-answer --label staging [--judge] | gate <run> | …
evals *args:
    sops exec-env secrets/dev.enc.env 'uv run python scripts/evals.py {{args}}'

# ---- CI (Step 27): the same recipes run on your Mac and in GitHub Actions ----

# Pinned tool binaries, checksum-verified, into .tools/bin (add it to PATH)
[positional-arguments]
tools *names:
    uv run python scripts/ci_tools.py "$@"

# Everything a pull request must pass (the image job runs separately: it needs Docker)
ci: ci-static ci-test ci-config policy-check ci-supply-chain

# Lockfile, lint, format, types
ci-static:
    uv sync --locked --all-packages
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy

# All tests. In CI a Postgres service is running, so the audit database tests run too.
ci-test:
    uv run pytest -q

# Prompts, cards, dashboards, alert rules and OpenBao policies: the "configuration as code" checks
ci-config:
    just prompts lint
    just prompts-check-main
    just cards lint
    just cards docs --check
    just dashboards-check
    just alerts-test
    just vault-check
    just rag-config-check
    just search-eval
    just guard-eval
    just answer-eval

# rag.yaml: every profile names real components with valid settings (Step 30), no services needed
rag-config-check:
    for p in offline local local-engines; do uv run rag config validate --profile $p; done

# Search quality gate (Step 32): the shipped search settings must keep finding the handbook answers,
# and must never return a forbidden document. Offline: no models or stores needed.
search-eval *args:
    uv run rag eval-search examples/eval/handbook.yaml --profile offline --variant all-together --fail-under recall=0.9 --fail-under mrr=0.8 {{args}}

# Guardrail gate (Step 34): every listed attack caught, no ordinary question stopped
guard-eval:
    uv run rag eval-guards examples/eval/guards.yaml --profile offline --min-catch-rate 0.95 --max-false-positive-rate 0.05

# Architecture gate (Step 35): the default architecture puts the right documents in front of the
# model and says "I don't know" when it should, with no forbidden document cited
answer-eval *args:
    uv run rag eval-answers examples/eval/handbook.yaml --profile offline --variant standard --fail-under context_recall=0.95 --fail-under abstain_ok=1 {{args}}

# Secrets, workflows, dependencies, licences, Dockerfile, Kubernetes manifests
ci-supply-chain:
    gitleaks git --no-banner --redact .
    actionlint
    uvx zizmor==1.30.1 --min-severity medium .github/workflows    # online audits when GH_TOKEN is set (CI)
    uv export --quiet --frozen --all-packages --all-groups --no-emit-workspace --format requirements-txt -o .tools/requirements.txt
    uvx pip-audit==2.10.1 --disable-pip --requirement .tools/requirements.txt --progress-spinner off
    uv run python scripts/licences.py
    trivy config --exit-code 1 --severity HIGH,CRITICAL services/rag-api/Dockerfile
    just k8s-scan                                                   # Step 29: the Kubernetes manifests

# Licence of every installed dependency against ci/licence-policy.yaml (-v lists them all)
[positional-arguments]
licences *args:
    uv run python scripts/licences.py "$@"

# Build the image locally and scan it like CI does (needs Docker)
image-scan:
    docker build -f services/rag-api/Dockerfile -t rag-api:local .
    trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed rag-api:local
    syft scan rag-api:local -o cyclonedx-json=.tools/rag-api.cdx.json

# Check a published image's signature and provenance before deploying it (Step 29 automates this)
image-verify digest:
    cosign verify "ghcr.io/$(gh repo view --json nameWithOwner -q .nameWithOwner | tr '[:upper:]' '[:lower:]')/rag-api@{{digest}}" \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      --certificate-identity-regexp "^https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/.github/workflows/release.yml@refs/heads/main$" > /dev/null && echo "signature OK"
    gh attestation verify "oci://ghcr.io/$(gh repo view --json nameWithOwner -q .nameWithOwner | tr '[:upper:]' '[:lower:]')/rag-api@{{digest}}" --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)"

# ---- Vault: OpenBao (Step 28) ----
# (the `compose` variable is defined at the top of this file, Step 9)
export BAO_ADDR := env("BAO_ADDR", "http://127.0.0.1:8200")
bao_init_file := "secrets/openbao-init.enc.json"

# Once per new server: unseal keys + root token go STRAIGHT into a SOPS-encrypted file
vault-init:
    #!/usr/bin/env bash
    set -euo pipefail
    test ! -e {{bao_init_file}} || { echo "{{bao_init_file}} exists: already initialised"; exit 1; }
    bao operator init -key-shares=3 -key-threshold=2 -format=json \
      | sops encrypt --filename-override {{bao_init_file}} --input-type json --output-type json /dev/stdin \
      > {{bao_init_file}}.tmp
    mv {{bao_init_file}}.tmp {{bao_init_file}}
    echo "wrote {{bao_init_file}}: commit it. Next: just vault-unseal && just vault-setup-first"

# After every OpenBao restart: the keys are decrypted into a pipe, never onto disk or a command line
vault-unseal:
    sops decrypt {{bao_init_file}} | uv run python scripts/vault_setup.py unseal

# First configuration, with the root token (then: just vault-revoke-root)
vault-setup-first:
    #!/usr/bin/env bash
    set -euo pipefail
    export BAO_TOKEN="$(sops decrypt --extract '["root_token"]' {{bao_init_file}})"
    sops exec-env secrets/dev.enc.env 'uv run python scripts/vault_setup.py setup'

# Every later change: edit the files, run this with your admin login (just vault-login)
vault-setup:
    sops exec-env secrets/dev.enc.env 'uv run python scripts/vault_setup.py setup'

# Retire the root token. Break-glass if ever needed: bao operator generate-root (needs 2 key shares)
vault-revoke-root:
    #!/usr/bin/env bash
    set -euo pipefail
    BAO_TOKEN="$(sops decrypt --extract '["root_token"]' {{bao_init_file}})" bao token revoke -self
    echo "root token revoked (the copy in {{bao_init_file}} is now useless)"

# Your day-to-day login (platform-admin policy, 1 h, renewable to 8 h). Asks for the password.
vault-login:
    bao login -method=userpass username=admin

# Store a secret: just vault-put rag-api gateway_key=RAG_API_GATEWAY_KEY (values come from SOPS env vars)
vault-put path +pairs:
    sops exec-env secrets/dev.enc.env 'uv run python scripts/vault_setup.py put {{path}} {{pairs}}'

# Short-lived database login for you or a job, in .bao/<role>.json (0600)
vault-creds role:
    mkdir -p -m 700 .bao
    uv run python scripts/vault_setup.py creds {{role}} --out .bao/{{role}}.json

# Print a single-use, wrapped secret ID (valid 10 minutes) for an AppRole, e.g. for a job
vault-secret-id role:
    uv run python scripts/vault_setup.py secret-id {{role}}

# Hand rag-api's agent a fresh single-use secret ID and (re)start it. Needed after every agent restart.
vault-agent-start:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p -m 700 .bao/rag-api
    uv run python scripts/vault_setup.py role-id rag-api > .bao/rag-api/role_id
    uv run python scripts/vault_setup.py secret-id rag-api > .bao/rag-api/secret_id
    {{compose}} up -d --force-recreate --wait rag-api-agent
    {{compose}} up -d rag-api

# OpenBao policies in canonical format (part of ci-config)
vault-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    cp infra/config/openbao/policies/*.hcl "$tmp"/
    for f in "$tmp"/*.hcl; do bao policy fmt "$f" > /dev/null; done
    diff -ru infra/config/openbao/policies "$tmp" || { echo "fix with: bao policy fmt <file>"; exit 1; }

# After a restart of OpenBao (or your Mac): unseal, then give the agent a new secret ID
vault-up: vault-unseal vault-agent-start

vault-status:
    bao status || true
    bao audit list
    bao list sys/leases/lookup/database/creds/rag-api 2>/dev/null || echo "(no rag-api leases)"

# One-time on an EXISTING rag-db volume (a new volume runs 03-openbao.sh by itself)
vault-db-bootstrap:
    {{compose}} exec -T rag-db bash < infra/config/rag-db/init/03-openbao.sh

# After rag-api runs on OpenBao credentials: the shared roles stop logging in. Undo = roll back.
vault-cutover:
    {{compose}} exec -T rag-db psql -v ON_ERROR_STOP=1 -U postgres -d postgres < infra/config/rag-db/vault-cutover.sql

vault-cutover-undo:
    sed 's/NOLOGIN/LOGIN/' infra/config/rag-db/vault-cutover.sql | {{compose}} exec -T rag-db psql -v ON_ERROR_STOP=1 -U postgres -d postgres

# ---- Kubernetes and GitOps (Step 29) ----
kube := "kubectl --context orbstack"
repo_ssh := "git@github.com:owner/rag-platform.git"

# Start OrbStack's single-node cluster and show it's there
k8s-up:
    orb start k8s
    {{kube}} get nodes -o wide

# What a kustomization renders (exactly what Argo CD would apply)
k8s-render path="envs/local":
    kubectl kustomize deploy/{{path}}

# Render everything and test it against a real API server (part of CI)
k8s-check:
    for p in cluster base/rag-api envs/local argocd/install argocd/apps; do kubectl kustomize deploy/$p > /dev/null && echo "renders: $p"; done
    uv run pytest -q tests/test_k8s.py tests/test_promote.py tests/test_k8s_secrets.py

# What would change in the cluster if this were applied now (read-only)
k8s-diff path="envs/local":
    kubectl kustomize deploy/{{path}} | {{kube}} diff --server-side -f - || true

# Once per cluster: Argo CD, its repository key, then the root app. From here on, git drives.
k8s-bootstrap:
    kubectl kustomize deploy/argocd/install | {{kube}} apply --server-side --field-manager=argocd-controller -f -
    {{kube}} -n argocd rollout status deploy/argocd-server --timeout=5m
    just k8s-repo-secret
    {{kube}} apply --server-side --field-manager=argocd-controller -f deploy/argocd/apps/projects.yaml
    {{kube}} apply --server-side --field-manager=argocd-controller -f deploy/argocd/root.yaml
    @echo "Argo CD is syncing. Watch: just k8s-status        UI: just argocd-ui"

k8s-repo-secret:
    sops exec-env secrets/dev.enc.env 'uv run python scripts/k8s_secrets.py repo-secret {{repo_ssh}}' | {{kube}} apply -f -

k8s-pull-secret:
    sops exec-env secrets/dev.enc.env 'uv run python scripts/k8s_secrets.py pull-secret' | {{kube}} apply -f -

k8s-status:
    {{kube}} -n argocd get applications -o custom-columns=APP:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision
    {{kube}} -n rag get deploy,pods -o wide

# The Argo CD web UI on https://localhost:8443 (user admin; the first password is copied to your clipboard)
argocd-ui:
    {{kube}} -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d | pbcopy
    @echo "password copied; change it in the UI, then: {{kube}} -n argocd delete secret argocd-initial-admin-secret"
    {{kube}} -n argocd port-forward svc/argocd-server 8443:443

# Let rag-api pods log in to OpenBao with their service account (after every cluster reset)
vault-k8s-trust:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p -m 700 .bao
    {{kube}} get --raw /openid/v1/jwks > .bao/k8s-jwks.json
    issuer="$({{kube}} get --raw /.well-known/openid-configuration | jq -r .issuer)"
    uv run python scripts/vault_setup.py k8s-trust --jwks .bao/k8s-jwks.json --issuer "$issuer"

# Can pods reach the services in Compose? (DNS alias -> your Mac -> published port)
k8s-deps-check:
    {{kube}} -n default run deps-check --rm -i --restart=Never --image=busybox:1.37 -- sh -c \
      'for hp in rag-db:5432 litellm:4000 opa:8181 openbao:8200 keycloak:8180 otel-collector:4317; do \
         h=${hp%:*}; p=${hp#*:}; if nc -z -w 3 $h.rag.svc.cluster.local $p; then echo "ok   $hp"; else echo "FAIL $hp"; fi; done'

# Does the cluster ENFORCE NetworkPolicy? A pod that is denied all egress tries to resolve a name.
k8s-netpol-check:
    #!/usr/bin/env bash
    set -uo pipefail
    {{kube}} create namespace netpol-check >/dev/null
    trap '{{kube}} delete namespace netpol-check --wait=false >/dev/null' EXIT
    printf 'apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata: {name: deny-all, namespace: netpol-check}\nspec: {podSelector: {}, policyTypes: [Egress]}\n' | {{kube}} apply -f - >/dev/null
    if {{kube}} -n netpol-check run probe --rm -i --restart=Never --image=busybox:1.37 -- nslookup -timeout=3 kubernetes.default >/dev/null 2>&1; then
      echo "NOT ENFORCED: NetworkPolicies are stored but ignored by this cluster's network plugin"
    else
      echo "enforced: the denied pod could not even resolve a name"
    fi

# Promote a released image: verify it, change one line, open a pull request. Merging deploys it.
promote env digest:
    #!/usr/bin/env bash
    set -euo pipefail
    just image-verify {{digest}}
    git switch -c "promote/{{env}}-$(echo {{digest}} | cut -c8-19)"
    out="$(uv run python scripts/promote.py {{env}} {{digest}})"
    echo "$out"
    git commit -am "deploy({{env}}): rag-api {{digest}}" -m "$out" -m "Signature and provenance verified (just image-verify). Roll back: git revert this commit."
    git push -u origin HEAD
    gh pr create --fill

# Upgrade Argo CD: fetch the release manifest, record its hash, review the diff in the pull request
argocd-vendor version:
    #!/usr/bin/env bash
    set -euo pipefail
    curl -sSLf -o deploy/argocd/install/upstream/install.yaml \
      "https://raw.githubusercontent.com/argoproj/argo-cd/{{version}}/manifests/install.yaml"
    sha="$(shasum -a 256 deploy/argocd/install/upstream/install.yaml | cut -d' ' -f1)"
    sed -i.bak -E "s|# v[0-9.]+, sha256 [0-9a-f]{64}|# {{version}}, sha256 $sha|" deploy/argocd/install/kustomization.yaml && rm deploy/argocd/install/kustomization.yaml.bak
    echo "{{version}}: sha256 $sha. Update the image digests in deploy/argocd/install/kustomization.yaml too."

# Kubernetes misconfiguration scan of what Argo CD would apply (part of ci-supply-chain)
k8s-scan:
    #!/usr/bin/env bash
    set -euo pipefail
    out="$(mktemp -d)"; trap 'rm -rf "$out"' EXIT
    for p in cluster envs/local; do kubectl kustomize "deploy/$p" > "$out/$(echo $p | tr / -).yaml"; done
    trivy config --exit-code 1 --severity HIGH,CRITICAL,MEDIUM --ignorefile .trivyignore.yaml "$out"
