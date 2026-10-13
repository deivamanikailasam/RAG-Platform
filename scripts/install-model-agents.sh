#!/usr/bin/env bash
# Install launchd agents that keep both model servers running (start at login, restart on crash).
# Usage: QUALITY_MODEL=<repo> FAST_MODEL=<repo> scripts/install-model-agents.sh
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
uv_bin="$(command -v uv)"
logs="$HOME/Library/Logs/rag-platform"
mkdir -p "$logs" "$HOME/Library/LaunchAgents"

make_agent() {   # $1=name  $2=model  $3=port  $4=extra chat-template args (JSON)
  local label="com.rag-platform.$1"
  local plist="$HOME/Library/LaunchAgents/${label}.plist"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key><array>
    <string>${uv_bin}</string><string>run</string>
    <string>--project</string><string>${repo}/infra/model-serving</string>
    <string>mlx_lm.server</string>
    <string>--model</string><string>$2</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>$3</string>
    <string>--max-tokens</string><string>4096</string>
    <string>--allowed-origins</string><string>http://localhost</string>
    <string>--chat-template-args</string><string>$4</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>HF_HUB_OFFLINE</key><string>1</string>
  </dict>
  <key>WorkingDirectory</key><string>${repo}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>${logs}/$1.log</string>
  <key>StandardErrorPath</key><string>${logs}/$1.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true   # unload an old version if present
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "loaded ${label} on 127.0.0.1:$3  (logs: ${logs}/$1.log)"
}

make_agent qwen-quality "${QUALITY_MODEL:?set QUALITY_MODEL}" 8081 '{}'
make_agent qwen-fast    "${FAST_MODEL:?set FAST_MODEL}"       8082 '{"enable_thinking": false}'
