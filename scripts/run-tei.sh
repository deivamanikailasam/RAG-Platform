#!/usr/bin/env bash
# Start one TEI server, with its API key from the encrypted secrets.
# The key travels as an environment variable, never as a command-line argument (visible to `ps`).
# Usage: run-tei.sh <model-dir> <port> <metrics-port> <served-name>
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
export SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
exec sops exec-env secrets/dev.enc.env "API_KEY=\"\$TEI_API_KEY\" exec text-embeddings-router \
  --model-id '$1' --hostname 127.0.0.1 --port '$2' --prometheus-port '$3' \
  --served-model-name '$4' --json-output"
