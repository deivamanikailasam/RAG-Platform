#!/usr/bin/env bash
# Step 2 lab: learn the uv workflow on a throwaway project.
#
# This script walks through parts A-E of the Step 2 lab so you can replay it any time:
#   A) add dependencies and look at what changed (pyproject.toml vs uv.lock, uv tree)
#   B) the environment is disposable; the lockfile is the source of truth (rm -rf .venv; uv sync)
#   C) watch `uv sync --locked` catch "drift", then fix it with `uv lock`
#   D) upgrade one package on purpose (uv lock --upgrade-package httpx)
#   E) run a tool without adding it to the project (uvx, uv tool install)
#
# Doing the steps by hand (see docs/steps/step-02-python-uv.md) teaches more; this script is the
# "answer key" and a quick way to check that uv works on a new machine.
#
# Usage:
#   bash bootstrap/labs/uv-lab.sh            # builds the lab in ~/dev/sandbox/uv-lab
#   SANDBOX_DIR=/tmp/sandbox bash bootstrap/labs/uv-lab.sh
#   SKIP_TOOL_INSTALL=1 bash bootstrap/labs/uv-lab.sh   # skip the global `uv tool install ruff`
#   KEEP_LAB=1 bash bootstrap/labs/uv-lab.sh # keep the lab folder afterwards (default: delete it)
#
# The lab is throwaway: the real repository starts in Step 4.

set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
SANDBOX_DIR="${SANDBOX_DIR:-$HOME/dev/sandbox}"
LAB_NAME="uv-lab"
LAB_DIR="$SANDBOX_DIR/$LAB_NAME"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

command -v uv >/dev/null 2>&1 || {
  echo "uv is not installed. Add it to bootstrap/Brewfile and run: brew bundle --file=bootstrap/Brewfile" >&2
  exit 1
}

say "uv version"
uv --version

# Part 2 of the chapter: install a managed interpreter (a no-op if it is already installed).
# With python-downloads = "manual" in ~/.config/uv/uv.toml, this is the only way one gets downloaded.
say "Install the uv-managed Python $PYTHON_VERSION interpreter"
uv python install "$PYTHON_VERSION"
uv python list --only-installed

say "Check the interpreter architecture (on an Apple Silicon Mac this must print arm64)"
arch_line="$(uv run --no-project --python "$PYTHON_VERSION" python -c \
  "import platform, sys; print(platform.machine(), sys.version)")"
echo "$arch_line"
if [[ "$(uname -s)" == "Darwin" && "$arch_line" != arm64* ]]; then
  echo "WARNING: this Python is not native arm64 (Rosetta?). MLX will not run under Rosetta emulation." >&2
fi

if [[ -e "$LAB_DIR" ]]; then
  say "Removing the previous lab at $LAB_DIR"
  rm -rf "$LAB_DIR"
fi

say "Create the throwaway project: uv init $LAB_NAME --python $PYTHON_VERSION"
mkdir -p "$SANDBOX_DIR"
cd "$SANDBOX_DIR"
uv init "$LAB_NAME" --python "$PYTHON_VERSION"
cd "$LAB_DIR"
ls -a

# ---- A) Add dependencies and look at what changed ----
say "A) uv add httpx pydantic  (runtime dependencies)"
uv add httpx pydantic
say "A) uv add --dev pytest  (development-only dependency, goes in a dependency group)"
uv add --dev pytest
say "A) pyproject.toml: the shopping list (ranges you will accept)"
cat pyproject.toml
say "A) uv.lock: the receipt (exact version, source and sha256 hashes)"
grep -A3 'name = "httpx"' uv.lock
say "A) uv tree: the full dependency tree, including transitive dependencies"
uv tree

# ---- B) The environment is disposable; the lockfile is the source of truth ----
say "B) Throw the pantry away (rm -rf .venv) and rebuild it from uv.lock"
rm -rf .venv
time uv sync
uv run python -c "import httpx, pydantic; print(httpx.__version__, pydantic.__version__)"

# ---- C) Watch CI catch "drift" ----
say "C) Simulate drift: add \"rich\" to the dependencies by hand, without running uv lock"
# Insert "rich" as the first entry of the [project] dependencies list (same as editing by hand).
awk '{ print } /^dependencies = \[/ && !done { print "    \"rich\","; done = 1 }' pyproject.toml > pyproject.toml.new
mv pyproject.toml.new pyproject.toml
grep -A5 '^dependencies = \[' pyproject.toml

say "C) uv sync --locked must now FAIL (the list and the receipt no longer match)"
if uv sync --locked; then
  echo "ERROR: expected 'uv sync --locked' to fail on drift, but it passed." >&2
  exit 1
else
  echo "OK: uv sync --locked refused to run. This is the check CI enforces in Step 27."
fi

say "C) Fix it the proper way: uv lock && uv sync --locked"
uv lock && uv sync --locked
echo "OK: lockfile updated, uv sync --locked passes."

# ---- D) Upgrade on purpose ----
say "D) Move ONE package: uv lock --upgrade-package httpx (review the change, then commit)"
uv lock --upgrade-package httpx
# uv lock --upgrade   # moves EVERYTHING; do this rarely and deliberately

# ---- E) Run a tool without adding it to the project ----
say "E) uvx ruff --version  (one-off run in a temporary, isolated environment)"
uvx ruff --version
if [[ "${SKIP_TOOL_INSTALL:-0}" != "1" ]]; then
  say "E) uv tool install ruff  (standalone CLI tool, isolated from your projects)"
  uv tool install ruff
fi

if [[ "${KEEP_LAB:-0}" == "1" ]]; then
  say "Done. The lab is kept at $LAB_DIR"
else
  say "Done. Deleting the lab ($LAB_DIR); the real repository starts in Step 4."
  rm -rf "$LAB_DIR"
fi
