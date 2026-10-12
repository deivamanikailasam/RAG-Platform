#!/usr/bin/env bash
# Step 3 lab: learn the container behaviour the platform depends on.
#
# This script walks through parts A-F of the Step 3 lab so you can replay it any time:
#   A) containers are native arm64 (aarch64); check an image's platforms before adopting it
#   B) container -> host networking: a container reaches a "model server" on the Mac via
#      host.docker.internal (the path LiteLLM will use to reach mlx-lm)
#   C) host -> container: publish ports on 127.0.0.1 only (compare *:8088 with 127.0.0.1:8089)
#   D) storage: a named volume survives the container being deleted
#   E) per-container resource limits (--memory 256m --cpus 0.5)
#   F) housekeeping: docker system df, docker image prune
#
# Doing the steps by hand (see docs/steps/step-03-container-runtime.md) teaches more; this script is the
# "answer key" and a quick way to check that the container runtime works on a new machine.
#
# Usage:
#   bash bootstrap/labs/container-lab.sh
#   SKIP_PLATFORM_INSPECT=1 bash bootstrap/labs/container-lab.sh   # skip the registry lookup in part A
#   FAKE_MODEL_BIND=0.0.0.0 bash bootstrap/labs/container-lab.sh   # runtimes that can't forward to 127.0.0.1
#                                                                  # (Colima, plain Docker on Linux); this
#                                                                  # exposes the fake server to your network
#
# Everything the lab creates (containers web-open, web-local, capped; volume lab-data; /tmp/fake-model)
# is removed at the end, even if a part fails.

set -euo pipefail

FAKE_MODEL_PORT="${FAKE_MODEL_PORT:-8099}"
FAKE_MODEL_BIND="${FAKE_MODEL_BIND:-127.0.0.1}"
FAKE_MODEL_DIR="${FAKE_MODEL_DIR:-/tmp/fake-model}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

# Pinned image tags (never :latest, see "Common mistakes"); override if a tag disappears.
ALPINE_IMAGE="${ALPINE_IMAGE:-alpine:3.22}"
CURL_IMAGE="${CURL_IMAGE:-curlimages/curl:8.16.0}"
NGINX_IMAGE="${NGINX_IMAGE:-nginx:1.29-alpine}"
INSPECT_IMAGE="${INSPECT_IMAGE:-postgres:17}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

FAKE_SERVER_PID=""
cleanup() {
  [[ -n "$FAKE_SERVER_PID" ]] && kill "$FAKE_SERVER_PID" 2>/dev/null || true
  docker rm -f web-open web-local capped >/dev/null 2>&1 || true
  docker volume rm lab-data >/dev/null 2>&1 || true
  rm -rf "$FAKE_MODEL_DIR"
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || fail "docker is not installed. Install OrbStack (bootstrap/Brewfile) and launch it once."
docker info >/dev/null 2>&1 || fail "the Docker engine is not running. Start it: open -a OrbStack"

say "Docker context and logging driver (expect orbstack and json-file)"
docker context show || true
docker info --format 'Logging driver: {{.LoggingDriver}}'

# ---- A) Check containers are native arm64 ----
say "A) docker run --rm $ALPINE_IMAGE uname -m"
arch="$(docker run --rm "$ALPINE_IMAGE" uname -m)"
echo "$arch"
case "$arch" in
  aarch64|arm64) echo "OK: native arm64, no emulation." ;;
  x86_64)
    if [[ "$(uname -s)" == "Darwin" ]]; then
      echo "WARNING: x86_64 on a Mac means the container runs under emulation (Rosetta)." >&2
    else
      echo "Note: x86_64 is native on an Intel/AMD Linux machine; on an Apple Silicon Mac expect aarch64."
    fi ;;
  *) echo "Unexpected architecture: $arch" >&2 ;;
esac

if [[ "${SKIP_PLATFORM_INSPECT:-0}" != "1" ]]; then
  say "A) Which platforms does $INSPECT_IMAGE support? (look for linux/arm64)"
  docker buildx imagetools inspect "$INSPECT_IMAGE" | grep -i platform \
    || echo "WARNING: could not inspect $INSPECT_IMAGE (no buildx plugin or no registry access)." >&2
fi

# ---- B) Container -> host networking ----
say "B) Start a stand-in model server on the host: $FAKE_MODEL_BIND:$FAKE_MODEL_PORT"
mkdir -p "$FAKE_MODEL_DIR" && echo '{"ok":true}' > "$FAKE_MODEL_DIR/health"
if command -v uv >/dev/null 2>&1; then
  uv run --no-project --python "$PYTHON_VERSION" python -m http.server "$FAKE_MODEL_PORT" \
    --bind "$FAKE_MODEL_BIND" --directory "$FAKE_MODEL_DIR" >/dev/null 2>&1 &
else
  python3 -m http.server "$FAKE_MODEL_PORT" --bind "$FAKE_MODEL_BIND" --directory "$FAKE_MODEL_DIR" >/dev/null 2>&1 &
fi
FAKE_SERVER_PID=$!
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$FAKE_MODEL_PORT/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$FAKE_MODEL_PORT/health" >/dev/null || fail "the fake model server did not start"

say "B) Call it from inside a container via host.docker.internal"
# --add-host isn't needed on OrbStack or Docker Desktop, but it makes the same command work on Colima and
# Linux CI. Compose services that call a model get the equivalent extra_hosts line.
reply="$(docker run --rm --add-host=host.docker.internal:host-gateway \
  "$CURL_IMAGE" -s --max-time 10 "http://host.docker.internal:$FAKE_MODEL_PORT/health" || true)"
echo "$reply"
if [[ "$reply" == '{"ok":true}' ]]; then
  echo "OK: the container reached the host's $FAKE_MODEL_BIND:$FAKE_MODEL_PORT through host.docker.internal."
else
  echo "WARNING: no reply. On runtimes other than OrbStack/Docker Desktop, a host server bound to 127.0.0.1 is" >&2
  echo "         not reachable from containers; re-run with FAKE_MODEL_BIND=0.0.0.0 (this exposes it to your network)." >&2
fi

say "B) Inside a container, localhost is the container itself (this call is expected to FAIL)"
if docker run --rm "$CURL_IMAGE" -s --max-time 3 "http://localhost:$FAKE_MODEL_PORT/health"; then
  echo "Unexpected: localhost answered inside the container (host networking?)."
else
  echo "OK: localhost inside the container is not your Mac. Use host.docker.internal."
fi
kill "$FAKE_SERVER_PID" 2>/dev/null || true
FAKE_SERVER_PID=""

# ---- C) Host -> container: publish ports to localhost only ----
say "C) Publish the same nginx two ways: all interfaces (8088) vs localhost only (8089)"
docker run -d --name web-open                -p 8088:80 "$NGINX_IMAGE" >/dev/null   # listens on ALL interfaces
docker run -d --name web-local -p 127.0.0.1:8089:80 "$NGINX_IMAGE" >/dev/null   # listens on localhost only
sleep 1
say "C) Listening doors (expect *:8088 or 0.0.0.0:8088, and 127.0.0.1:8089)"
if command -v lsof >/dev/null 2>&1; then
  lsof -nP -iTCP -sTCP:LISTEN | grep -E '8088|8089' || true
elif command -v ss >/dev/null 2>&1; then
  ss -ltn | grep -E '8088|8089' || true    # Linux without lsof
fi
docker port web-open
docker port web-local
docker port web-local | grep -q '^80/tcp -> 127.0.0.1:8089$' || fail "web-local is not bound to 127.0.0.1 only"
echo "Platform rule from now on: every published port is bound to 127.0.0.1."
docker rm -f web-open web-local >/dev/null

# ---- D) Storage: named volumes ----
say "D) Write to a named volume from one container, read it from another"
docker volume create lab-data >/dev/null
docker run --rm -v lab-data:/data "$ALPINE_IMAGE" sh -c 'echo "persisted at $(date)" > /data/note.txt'
note="$(docker run --rm -v lab-data:/data "$ALPINE_IMAGE" cat /data/note.txt)"   # survives the container being deleted
echo "$note"
[[ "$note" == persisted\ at* ]] || fail "the note did not survive in the named volume"
docker volume rm lab-data >/dev/null

# ---- E) Per-container resource limits ----
say "E) Run nginx capped at 256 MiB memory and half a CPU"
docker run -d --name capped --memory 256m --cpus 0.5 "$NGINX_IMAGE" >/dev/null
docker stats --no-stream capped                     # MEM USAGE / LIMIT shows the 256MiB cap
limit="$(docker inspect --format '{{.HostConfig.Memory}}' capped)"
[[ "$limit" == "268435456" ]] || fail "expected a 256 MiB (268435456 bytes) memory limit, got $limit"
docker rm -f capped >/dev/null

# ---- F) Housekeeping ----
say "F) docker system df: space used by images, containers, volumes, build cache"
docker system df
say "F) docker image prune: remove dangling (unused, untagged) images"
docker image prune -f
# docker system prune -a --volumes   # nuclear option: deletes ALL volumes too. Never run it once real data exists.

say "Done. Record your decisions in bootstrap/NOTES-step3.md."
