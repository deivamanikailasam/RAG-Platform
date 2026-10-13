#!/usr/bin/env bash
# Fail if any file passed in (from secrets/) is not SOPS-encrypted.
set -euo pipefail
status=0
for f in "$@"; do
  case "$f" in *.md|*/.gitkeep) continue ;; esac
  if ! grep -qE '^sops_mac=|^[[:space:]]*mac: ENC\[|"mac": "ENC\[' "$f"; then
    echo "NOT ENCRYPTED: $f   ->   run: sops --encrypt --in-place $f"
    status=1
  fi
done
exit $status
