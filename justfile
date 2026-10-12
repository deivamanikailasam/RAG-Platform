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

# Everything CI will run (Step 27 calls exactly this)
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

# Logical backup of the RAG database (custom format, compressed) into backups/ (gitignored)
db-backup:
    mkdir -p backups
    docker compose -f infra/compose/compose.yaml exec -T rag-db pg_dump -U postgres -d rag -Fc > backups/rag-$(date +%Y%m%d-%H%M%S).dump
    ls -lh backups | tail -3

# Restore the latest backup into a scratch database and count rows (proves the backup is usable)
db-restore-test:
    docker compose -f infra/compose/compose.yaml exec -T rag-db psql -U postgres -c "DROP DATABASE IF EXISTS rag_restore_test" -c "CREATE DATABASE rag_restore_test"
    cat "$(ls -t backups/rag-*.dump | head -1)" | docker compose -f infra/compose/compose.yaml exec -T rag-db pg_restore -U postgres -d rag_restore_test --no-owner
    docker compose -f infra/compose/compose.yaml exec -T rag-db psql -U postgres -d rag_restore_test -c "SELECT count(*) AS chunks FROM rag.chunks"
    docker compose -f infra/compose/compose.yaml exec -T rag-db psql -U postgres -c "DROP DATABASE rag_restore_test"

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
    docker run -d --rm --name audit-test-pg -p 127.0.0.1:55432:5432 \
      -e POSTGRES_HOST_AUTH_METHOD=trust pgvector/pgvector:0.8.7-pg17@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d >/dev/null
    trap 'docker stop audit-test-pg >/dev/null' EXIT
    until docker exec audit-test-pg pg_isready -h 127.0.0.1 -U postgres -q; do sleep 1; done
    AUDIT_TEST_ADMIN_DSN=postgres://postgres@127.0.0.1:55432/postgres uv run pytest

audit_reader_dsn := "postgres://audit_reader:$AUDIT_DB_READER_PASSWORD@127.0.0.1:5432/audit"

# Copy new audit events + head hash to the write-once bucket. Hourly.
audit-anchor:
    sops exec-env secrets/dev.enc.env 'AUDIT_DB_DSN="{{audit_reader_dsn}}" uv run python scripts/audit_chain.py anchor'

# Check database chain, archive, and that they agree. Daily, and on request. Exit 1 = problems.
audit-verify:
    sops exec-env secrets/dev.enc.env 'AUDIT_DB_DSN="{{audit_reader_dsn}}" uv run python scripts/audit_chain.py verify'
