# Model serving (Step 7): which models to serve, and the shared safe server command
quality_model := "mlx-community/Qwen3.8-27B-8bit"
fast_model    := "lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit"
serve         := "HF_HUB_OFFLINE=1 uv run --project infra/model-serving mlx_lm.server --host 127.0.0.1 --allowed-origins http://localhost"

# Embedding and reranking (Step 8): served by TEI from pinned local snapshot folders
embed_model   := "Qwen/Qwen3-Embedding-0.6B"
rerank_model  := "BAAI/bge-reranker-v2-m3"

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
    uv run pytest

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
