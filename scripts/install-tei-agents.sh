#!/usr/bin/env bash
# launchd agents for the embedding and reranker servers (start at login, restart on crash).
# Usage: EMBED_DIR=<snapshot dir> RERANK_DIR=<snapshot dir> scripts/install-tei-agents.sh
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
logs="$HOME/Library/Logs/rag-platform"
mkdir -p "$logs" "$HOME/Library/LaunchAgents"

make_agent() {   # $1=name  $2=model-dir  $3=port  $4=metrics-port  $5=served-name
  local label="com.rag-platform.$1"
  local plist="$HOME/Library/LaunchAgents/${label}.plist"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>${repo}/scripts/run-tei.sh</string>
    <string>$2</string><string>$3</string><string>$4</string><string>$5</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>SOPS_AGE_KEY_FILE</key><string>${HOME}/.config/sops/age/keys.txt</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>${logs}/$1.log</string>
  <key>StandardErrorPath</key><string>${logs}/$1.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true   # unload an old version if present
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "loaded ${label} on 127.0.0.1:$3 (metrics :$4, logs ${logs}/$1.log)"
}

make_agent embedder "${EMBED_DIR:?}" 8083 9083 qwen3-embedding-0.6b
make_agent reranker "${RERANK_DIR:?}" 8084 9084 bge-reranker-v2-m3
