#!/usr/bin/env bash
# Print the local snapshot folder of a downloaded Hugging Face model.
# Usage: model-path.sh <org/name> [revision-sha]
set -euo pipefail
repo="$1"; rev="${2:-}"
base="${HF_HOME:-$HOME/.cache/huggingface}/hub/models--${repo//\//--}/snapshots"
# "|| true": if the model was never downloaded, ls fails; with pipefail that would end the script
# silently, so let it fall through to the clear "not downloaded" message instead.
if [ -n "$rev" ]; then dir="$base/$rev"; else dir="$(ls -d "$base"/*/ 2>/dev/null | head -1 || true)"; fi
[ -n "$dir" ] && [ -d "$dir" ] || { echo "not downloaded: $repo ${rev}" >&2; exit 1; }
echo "${dir%/}"
