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
