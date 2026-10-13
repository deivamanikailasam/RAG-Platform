#!/usr/bin/env bash
# Step 3: cap the OrbStack VM and switch on Docker log rotation, then check the result.
#
# This is the command-line version of parts 2 and 3 of the Step 3 chapter:
#   2) cap the VM's resources: 24 GB memory (24 x 1024 = 24576 MiB) and 8 CPUs, because the Mac's
#      unified memory is shared with the model servers
#   3) log rotation in the Docker engine: json-file driver, at most 3 files of 10 MB per container
#
# You can do the same in the OrbStack app (Settings -> System, Settings -> Docker); this script exists
# so a new Mac can be set up the same way every time.
#
# Usage (on macOS, after `brew bundle --file=bootstrap/Brewfile` and the first `open -a OrbStack`):
#   bash bootstrap/orbstack-setup.sh
#   VM_MEMORY_MIB=32768 bash bootstrap/orbstack-setup.sh     # raise to 32 GB if `docker stats` shows pressure
#   VM_CPUS=8 bash bootstrap/orbstack-setup.sh
#   CHECK_ONLY=1 bash bootstrap/orbstack-setup.sh            # only print the current state, change nothing
#
# Key names can change between OrbStack versions: the script prints `orb config show` first so you can
# confirm `memory_mib` and `cpu` exist on your version.

set -euo pipefail

VM_MEMORY_MIB="${VM_MEMORY_MIB:-24576}"   # 24 GB to start; up to 32768 (32 GB) later
VM_CPUS="${VM_CPUS:-8}"                   # leave the remaining performance cores to the model servers
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_CONFIG_SRC="$REPO_ROOT/bootstrap/home/.orbstack/config/docker.json"
ENGINE_CONFIG_DST="${ORBSTACK_DOCKER_CONFIG:-$HOME/.orbstack/config/docker.json}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

command -v orb >/dev/null 2>&1 || fail "the 'orb' command is missing. Install OrbStack: brew bundle --file=bootstrap/Brewfile, then: open -a OrbStack"
command -v docker >/dev/null 2>&1 || fail "the 'docker' command is missing. Launch OrbStack once (open -a OrbStack) so it installs the Docker CLI."

say "Current OrbStack settings (confirm the key names memory_mib and cpu)"
orb config show

if [[ "${CHECK_ONLY:-0}" != "1" ]]; then
  # ---- 2 · Cap the VM's resources ----
  say "Cap the VM: memory_mib=$VM_MEMORY_MIB, cpu=$VM_CPUS"
  orb config set memory_mib "$VM_MEMORY_MIB"
  orb config set cpu "$VM_CPUS"

  # ---- 3 · Log rotation in the Docker engine ----
  # OrbStack keeps its Docker engine config (the equivalent of Docker's daemon.json) here. We merge our
  # log settings into whatever is already there, so other engine settings you set in the app survive.
  say "Switch on log rotation in $ENGINE_CONFIG_DST"
  mkdir -p "$(dirname "$ENGINE_CONFIG_DST")"
  if [[ -s "$ENGINE_CONFIG_DST" ]]; then
    cp "$ENGINE_CONFIG_DST" "$ENGINE_CONFIG_DST.bak"
    jq -s '.[0] * .[1]' "$ENGINE_CONFIG_DST.bak" "$ENGINE_CONFIG_SRC" > "$ENGINE_CONFIG_DST"
    echo "Merged (previous version saved as $ENGINE_CONFIG_DST.bak)"
  else
    cp "$ENGINE_CONFIG_SRC" "$ENGINE_CONFIG_DST"
  fi
  cat "$ENGINE_CONFIG_DST"

  say "Restart OrbStack so the new limits and engine config take effect"
  orb stop
  orb start
fi

# ---- Checks ----
say "docker version (both Client and Server sections should appear)"
docker version

say "docker compose version (Compose v2 is 'docker compose', with a space)"
docker compose version

say "docker context ls (the context marked * should be orbstack)"
docker context ls
current_context="$(docker context show)"
[[ "$current_context" == "orbstack" ]] || echo "WARNING: the current docker context is '$current_context', not 'orbstack'. Two runtimes installed? Run: docker context use orbstack" >&2

say "Logging driver (expect: json-file)"
driver="$(docker info --format '{{.LoggingDriver}}')"
echo "$driver"
[[ "$driver" == "json-file" ]] || fail "logging driver is '$driver', expected json-file. Check OrbStack Settings -> Docker."

say "VM resources as the Docker engine sees them"
docker info --format 'CPUs: {{.NCPU}}  Memory: {{.MemTotal}} bytes'

say "Done. Next: bash bootstrap/labs/container-lab.sh"
