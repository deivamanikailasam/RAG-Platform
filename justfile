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
    uv run pytest

# Policies: formatted, compiled strictly, linted, tested with >= 90% coverage (Step 18)
policy-check:
    opa fmt --list --fail policies
    opa check --strict policies
    regal lint policies
    opa test policies --coverage --threshold 90 > /dev/null
    opa test policies

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
