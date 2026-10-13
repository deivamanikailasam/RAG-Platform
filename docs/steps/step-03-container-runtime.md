# Step 3 · Container runtime: native models, containerised services

*Step 3 of 38 · Phase A · Workstation*

## At a glance

| | |
|---|---|
| **Goal** | Install a container runtime (OrbStack), cap how much memory it may use, switch on log rotation, and learn how containers handle networking, ports and storage. |
| **Time** | About 45–60 minutes, including the lab. |
| **You'll end up with** | Docker working on your Mac, safe resource limits, and the platform's most important architecture decision: AI models run directly on macOS; everything else runs in containers. |
| **New words** | Container, image, virtual machine (VM), runtime, Docker Compose, unified memory, port, interface, localhost, volume, bind mount, log rotation. |

## The big idea

> **ANALOGY · Apartments inside a building, inside your house**
> A container is like a self-contained apartment. It comes with its own furniture and appliances (the program plus
> everything it needs), so it never fights with the neighbours over which kettle to use.
> On a Mac there's a twist: macOS can't host these Linux "apartments" directly. So the container runtime first
> builds a small Linux building inside your Mac. That building is a **virtual machine (VM)**: a computer simulated
> inside your computer. All the apartments live in that building.
> The catch: the building has no access to your Mac's graphics chip (GPU), and the AI models need that chip.
> So the models stay in the main house (macOS), and everything else moves into the apartments.

## What we're doing

1. Install a container runtime so Linux containers run on your Mac. We'll use **OrbStack**.
2. Set resource limits so containers can't take memory your models need.
3. Switch on log rotation so container logs can't fill your disk.
4. Run a lab covering the networking, storage and security behaviour every later step relies on.
5. Make the most important architecture decision of Project 0: **models run natively on macOS; everything
   else runs in containers.**

## Why we're doing this

### Why containers at all?

The platform needs about 15 services: Postgres, Qdrant, OpenSearch, SeaweedFS (S3 storage), Redis, Keycloak,
OPA, Grafana, Loki, Tempo, Langfuse, LiteLLM and more. Installing all of them directly on macOS would cause four
problems:

| Problem without containers | How containers solve it |
|---|---|
| Each service needs its own version of Java, Node, Erlang and so on, and they clash | Each container carries its own dependencies |
| Your Mac would drift away from the Linux production environment | Containers run the same Linux images you'd run in production |
| You can't wipe and rebuild one service cleanly | `docker compose down -v` gives you a clean slate in seconds |
| You can't describe the whole stack in one reviewable file | From Step 11, a `compose.yaml` file is the stack definition |

> **IN PLAIN ENGLISH · Image vs container**
> An **image** is the blueprint: a frozen package containing a program and everything it needs. A **container** is
> a running copy built from that blueprint. You can start, stop, delete and recreate containers from the same
> image as often as you like.
> **Docker Compose** is a file listing many containers and how they connect, so one command (`docker compose up`)
> starts the whole stack.

### The constraint that shapes the whole architecture

macOS cannot run Linux containers directly. Every container runtime on a Mac runs a small Linux VM, and your
containers run inside it. That VM **cannot use Apple's Metal GPU**, and **MLX** (the software that runs your Qwen
models fast on Apple Silicon) needs Metal. So:

- **Model servers run natively on macOS**: mlx-lm (Step 7) and the embedder and reranker (Step 8). They get the
  full GPU and the full unified memory.
- **Everything else runs in containers**: databases, sign-in, monitoring and the gateway. None of them need a GPU.
- **Containers reach the models over HTTP** at a special address, `host.docker.internal`, which means "the Mac
  I'm running on".

The platform split (the guide's Figure 6):

```text
macOS HOST · M5 Max · 128 GB unified memory
┌──────────────────────────────────────┐        ┌───────────────────────────────────────────────────────┐
│ NATIVE (full GPU access)             │        │ LINUX VM (OrbStack · memory capped ~24 GB)            │
│                                      │        │                                                       │
│  mlx-lm · Qwen 27B          :8081 ◄──┼─ HTTP ─┼── LiteLLM gateway → host.docker.internal:8081         │
│  mlx-lm · Qwen 35B          :8082    │        │                                                       │
│  embedder / reranker        :8083    │        │  Postgres   Qdrant     OpenSearch   SeaweedFS         │
│                                      │        │  Redis      Keycloak   OPA          Grafana           │
│        Apple Metal GPU               │        │  Loki       Tempo      Langfuse     Prometheus        │
│        (MLX needs this)              │        │                    (no GPU inside the VM)             │
└──────────────────────────────────────┘        └───────────────────────────────────────────────────────┘
```

> **THIS IS A REAL PRODUCTION PATTERN**
> It isn't a workaround. In production, model serving usually runs on dedicated GPU machines, and applications
> call it over HTTP. Your Mac reproduces the same split on one machine, so the move to Kubernetes later is a
> translation rather than a redesign.

### Why resource limits matter more on your Mac

Apple Silicon has **unified memory**: the CPU and the GPU share the same 128 GB pool. Every gigabyte you give the
Linux VM is a gigabyte your models can't use.

> **ANALOGY · One water tank**
> One water tank supplies both the kitchen and the garden. If the garden hose runs without a limit, the kitchen tap
> runs dry. The VM memory cap is the limit on the garden hose.

A rough memory budget for the 128 GB (the guide's Figure 7; planning estimates, Step 7 measures the real numbers):

```text
0 GB                                                                                               128 GB
| Qwen 27B 8bit ~29 | Qwen 35B-A3B 4bit ~20 | Judge ~12 | KV cache ~15 | macOS & apps ~14 | Linux VM ~24 | spare ~11 |
  plus embedder + reranker ~3 GB
Models, the VM and macOS all draw from ONE shared pool. Every GB given to the VM is a GB your models can't use.
```

| Consumer | Rough size |
|---|---|
| Qwen3.8-27B-8bit weights | ~28–30 GB |
| Qwen3.6-35B-A3B-4bit weights | ~19–21 GB |
| Judge model (e.g. a 12–27B model at 4-bit) | ~8–16 GB |
| Embedder + reranker | ~2–4 GB |
| KV-cache headroom (working memory for long conversations) | ~10–20 GB |
| macOS, browser, IDE | ~12–16 GB |
| Linux VM for containers | ~24 GB to start, up to 32 GB |

Two practical consequences:

- The container VM gets a **hard memory cap**.
- Memory-hungry services such as OpenSearch get **their own limits** inside it.

macOS also caps how much memory the GPU may use by default. We'll look at that setting in Step 7.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Container runtime** | The software that downloads images and runs containers: OrbStack, Docker Desktop, Colima, Podman, and others. |
| **Docker engine / CLI** | The engine runs containers inside the VM; the `docker` command (CLI) is how you talk to it. |
| **Port** | A numbered "door" on a computer through which a program accepts network connections, e.g. 5432 for Postgres. |
| **Network interface** | A way your Mac connects to networks: Wi-Fi, Ethernet, and localhost (a private loop that only reaches the Mac itself). |
| **`127.0.0.1` / localhost** | "This machine only". A door bound here opens only from inside your own Mac. |
| **`0.0.0.0` / `*`** | "Every interface". A door bound here opens to anyone who can reach your Mac on the network. |
| **`host.docker.internal`** | The address a container uses to reach programs running on the Mac itself. |
| **Named volume** | Storage managed by Docker inside the VM. It survives when a container is deleted. |
| **Bind mount** | A folder on your Mac shared into a container. |
| **Log rotation** | Keeping only the newest few log files of a limited size and deleting the oldest, so logs can't grow forever. |
| **arm64 / aarch64 vs amd64 / x86_64** | Processor families. Your Mac is arm64. Images built only for amd64 (Intel/AMD) need slower emulation. |

## How to do it

All commands run in the macOS Terminal. `~/dev/rag-platform/` is the root of this repository.

### 1 · Add the runtime to the Brewfile and install

Append to the Brewfile (already done in [`bootstrap/Brewfile`](../../bootstrap/Brewfile)):

```ruby
# ---- Containers (Step 3) ----
cask "orbstack"             # Linux VM + Docker engine + CLI + Compose + single-node Kubernetes (used in Step 29)
brew "dive"                 # inspect image layers: find bloat and accidentally baked-in secrets
```

```bash
cd ~/dev/rag-platform/bootstrap
brew bundle --file=Brewfile
open -a OrbStack                # first launch: accept the prompts, choose "Docker" when asked
```

OrbStack installs the `docker` command plus the Compose and buildx plugins. Check them:

```bash
docker version                  # both "Client" and "Server" sections should appear
docker compose version          # Compose v2 is "docker compose" (with a space); the old "docker-compose" is retired
docker context ls               # the context marked * should be orbstack
```

> **LICENSING**
> OrbStack is free for personal, non-commercial use and paid for commercial use. A learning lab on your own
> machine counts as personal use. If you later reuse this setup for paid client work, buy a licence or switch to
> Colima (see Alternatives). Licence terms change, so check OrbStack's current terms when you install.

### 2 · Cap the VM's resources

Open the OrbStack app → **Settings → System**:

- **Memory limit: 24 GB** to start. Raise it to 32 GB later if `docker stats` shows memory pressure.
- **CPU limit: 8 cores.** The model servers need the remaining performance cores for tokenising and handling
  requests.

The same settings from the command line (run `orb config show` first to confirm the key names on your version):

```bash
orb config show
orb config set memory_mib 24576     # 24 GB × 1024 = 24576 MiB
orb config set cpu 8
```

Restart OrbStack after changing these.

### 3 · Switch on log rotation in the Docker engine

By default, Docker keeps every line a container prints, forever. A chatty service (OpenSearch at debug level, or a
container stuck crashing and restarting) can fill your disk. Open OrbStack **Settings → Docker** (the engine
configuration, equivalent to Docker's `daemon.json`) and set:

```json
{
    "log-driver": "json-file",
    "log-opts": { "max-size": "10m", "max-file": "3" }
}
```

The same JSON is kept in this repo at
[`bootstrap/home/.orbstack/config/docker.json`](../../bootstrap/home/.orbstack/config/docker.json).

> **IN PLAIN ENGLISH**
> Each container keeps at most 3 log files of 10 MB each (about 30 MB). When the third fills up, the oldest is
> deleted. Long-term logs will go to Loki in Step 21, which is where retention should be managed.

Apply the change and check it:

```bash
docker info --format '{{.LoggingDriver}}'     # expect: json-file
```

**Scripted version of parts 2 and 3.** [`bootstrap/orbstack-setup.sh`](../../bootstrap/orbstack-setup.sh) prints
`orb config show`, sets `memory_mib 24576` and `cpu 8`, merges the log settings into OrbStack's engine config
(keeping a `.bak` of the old one), restarts OrbStack, and then runs the checks from part 1 and 3:

```bash
bash ~/dev/rag-platform/bootstrap/orbstack-setup.sh
VM_MEMORY_MIB=32768 bash ~/dev/rag-platform/bootstrap/orbstack-setup.sh   # later, if you need 32 GB
CHECK_ONLY=1 bash ~/dev/rag-platform/bootstrap/orbstack-setup.sh          # just report, change nothing
```

### 4 · Lab: learn the behaviour the platform depends on

You can type each part by hand (recommended the first time) or replay all of them with
[`bootstrap/labs/container-lab.sh`](../../bootstrap/labs/container-lab.sh), which runs parts A–F, asserts the
expected results, and cleans up after itself.

#### A) Check containers are native arm64

```bash
docker run --rm alpine uname -m     # aarch64 = native arm64. x86_64 here would mean emulation.
```

Some images are published only for amd64. They still run, through Rosetta emulation, but more slowly and sometimes
with strange bugs. Before adopting an image, check its supported platforms:

```bash
docker buildx imagetools inspect postgres:17 | grep -i platform     # look for linux/arm64
```

#### B) Container → host networking (the path LiteLLM will use to reach mlx-lm)

Start a stand-in "model server" on your Mac, listening on localhost only:

```bash
# Terminal 1 · macOS host
mkdir -p /tmp/fake-model && echo '{"ok":true}' > /tmp/fake-model/health
uv run --python 3.12 python -m http.server 8099 --bind 127.0.0.1 --directory /tmp/fake-model
```

Call it from inside a container:

```bash
# Terminal 2 · call it from a container
docker run --rm --add-host=host.docker.internal:host-gateway \
  curlimages/curl -s http://host.docker.internal:8099/health
# {"ok":true}
```

The guide's Figure 8:

```text
 INSIDE THE LINUX VM                                   macOS HOST
 ┌──────────────────┐   "localhost" = the container    ┌────────────────────┐
 │ LiteLLM container│ ── itself, NOT the Mac            │ mlx-lm server      │
 │                  │                                   │ 127.0.0.1:8081     │
 │                  │ ── host.docker.internal:8081 ───► │                    │
 └──────────────────┘                                   └────────────────────┘
```

> **WHY ADD `--add-host` IF ORBSTACK DOESN'T NEED IT?**
> OrbStack and Docker Desktop define `host.docker.internal` automatically, so the flag isn't strictly needed
> there. Include it anyway: it makes the same setup work on every runtime, including Colima and Linux CI machines.
> You'll add the equivalent `extra_hosts` line to every Compose service that calls a model.

> **WATCH OUT · Security difference between runtimes**
> The host server is bound to `127.0.0.1`, so it is not exposed to your Wi-Fi network, and OrbStack still forwards
> container traffic to it. On some other runtimes (Colima, for example) you'd have to bind to `0.0.0.0` instead,
> which exposes the server to your local network. That's a real security difference between runtimes.

Stop the fake server with **Ctrl + C** in Terminal 1.

#### C) Host → container: publish ports to localhost only

```bash
docker run -d --name web-open            -p 8088:80 nginx:alpine   # listens on ALL interfaces
docker run -d --name web-local -p 127.0.0.1:8089:80 nginx:alpine   # listens on localhost only
lsof -nP -iTCP -sTCP:LISTEN | grep -E '8088|8089'                   # list listening doors
```

The guide's Figure 9: the same container published two ways.

```text
 -p 8088:80                                  -p 127.0.0.1:8089:80
 door open to the street (all interfaces)    door opens from inside only (localhost)
 You (this Mac) ──► nginx ◄── stranger on    You (this Mac) ──► nginx    stranger on café Wi-Fi ✗
                              café Wi-Fi
 lsof shows *:8088                           lsof shows 127.0.0.1:8089
```

Compare the output:

- Port 8088 shows `*:8088`: anyone on your café Wi-Fi could reach it.
- Port 8089 shows `127.0.0.1:8089`: only your Mac.

> **PLATFORM RULE FROM NOW ON**
> Every published port is bound to `127.0.0.1`. Postgres, Redis and similar services ship with default
> credentials that are widely known. Exposing them on all interfaces is one of the most common real-world causes
> of data leaks.

```bash
docker rm -f web-open web-local     # clean up
```

#### D) Storage: named volumes vs bind mounts

```bash
docker volume create lab-data
docker run --rm -v lab-data:/data alpine sh -c 'echo "persisted at $(date)" > /data/note.txt'
docker run --rm -v lab-data:/data alpine cat /data/note.txt     # survives the container being deleted
docker volume rm lab-data
```

The guide's Figure 10: named volumes live inside the VM and are fast; bind mounts share a Mac folder, and every
read and write crosses the VM boundary.

```text
 LINUX VM                                                       macOS (your Mac's folders)
 database container ── fast · normal Linux disk ──► named volume  lab-data:/data
 app/config container ── slower · every read/write crosses the VM wall ──────────► bind mount ./config:/etc/app
```

| | Named volume (`lab-data:/data`) | Bind mount (`./folder:/data`) |
|---|---|---|
| **Where it lives** | Inside the Linux VM's filesystem | On macOS, shared into the VM |
| **Speed for databases** | Fast, native Linux disk access | Slower: every file operation crosses the VM boundary |
| **Permissions & fsync** (how "save to disk" is guaranteed) | Normal Linux behaviour | Can behave differently, which some databases dislike |
| **Use it for** | Database and index data (Postgres, Qdrant, OpenSearch, SeaweedFS) | Config files and source code you edit on the Mac |

> **ANALOGY**
> A named volume is a storage locker inside the building: quick to reach. A bind mount is a shared folder passed
> back and forth through a window between your house and the building: convenient for things you edit, too slow
> for a database that saves constantly.

#### E) Per-container resource limits

```bash
docker run -d --name capped --memory 256m --cpus 0.5 nginx:alpine
docker stats --no-stream capped     # MEM USAGE / LIMIT shows the 256MiB cap
docker rm -f capped
```

There are now **two layers of limits**:

- The **VM cap** (from part 2) protects your models from the containers as a whole.
- **Per-container caps** protect services from each other.

Both get written into Compose in later steps.

#### F) Housekeeping

```bash
docker system df        # space used by images, containers, volumes, build cache
docker image prune      # remove dangling (unused, untagged) images
# docker system prune -a --volumes   # nuclear option: deletes ALL volumes too. Never run it once real data exists.
```

### 5 · Write the decision down

Create a notes file recording what you decided and why. In Step 4 it becomes a proper ADR (Architecture Decision
Record) in the repository. It is committed at [`bootstrap/NOTES-step3.md`](../../bootstrap/NOTES-step3.md):

```markdown
# Step 3 decisions
- Runtime: OrbStack (personal use; fast, low idle memory, built-in Kubernetes). Fallback: Colima.
- VM cap: 24 GB RAM, 8 CPUs, because unified memory is shared with the models.
- Architecture: models run natively on macOS (need the Metal GPU); all services run in containers
  and reach models via host.docker.internal.
- Rules: publish ports on 127.0.0.1 only; named volumes for data; log rotation 10m x 3.
```

## Benefits

- **One stack definition:** every service starts, stops and resets together. Environments are reproducible and
  disposable.
- **Close to production:** the same Linux images and the same service-to-service networking as a Kubernetes
  cluster, which makes Step 29 a translation rather than a rewrite.
- **Isolation:** a misbehaving service is capped and can't take down your models or your Mac.
- **Safe experimentation:** trying OpenSearch 3 against 2.x, or Qdrant against pgvector, is just a tag change.
- **Security habits learned early:** localhost-only ports, volume hygiene and log limits are exactly what auditors
  check in production.

## Drawbacks and risks

- **No GPU inside containers.** On macOS, no runtime passes Apple's Metal GPU into Linux containers. Some
  experimental setups (Podman with libkrun) offer Vulkan-based GPU access for llama.cpp-style workloads, but it's
  slower than native Metal and doesn't support MLX. So model serving stays native.
- **Two networks to reason about.** The host network and the VM network add a layer that can cause bugs, such as
  a container calling `localhost` and getting itself instead of the Mac. Always use `host.docker.internal` for
  services on the Mac.
- **Memory is spent twice.** The VM holds memory for its own Linux kernel and file cache on top of what the
  containers use.
- **Bind-mount performance.** Much better than it used to be (VirtioFS), but still slower than volumes for
  databases.
- **Licensing.** Docker Desktop and OrbStack both need paid licences in many commercial settings. This is a real
  governance question that enterprises track.
- **Image supply chain.** Every `docker pull` runs someone else's code. Pinning, verifying and scanning images
  comes in Steps 11 and 27.

## Alternatives

| Runtime | What it is, in plain words | Licence (check current terms) | Choose it when |
|---|---|---|---|
| **OrbStack** (our choice) | Lightweight VM + Docker engine + built-in Kubernetes. Very fast start-up, low idle memory. | Free for personal use; paid for commercial | Personal Mac lab, or teams willing to pay for speed and polish |
| **Docker Desktop** | Docker's official app: GUI, extensions, built-in Kubernetes, Docker Scout scanning, Docker Model Runner (runs models natively on the Mac GPU, outside containers) | Free for individuals, education and small businesses (<250 employees and <$10M revenue); paid above that | Your employer already has Docker subscriptions, or you want the vendor-supported default |
| **Colima** | Open-source command-line tool on top of Lima VMs, running the Docker or containerd engine | Free (MIT) | Open-source-only policies, or no licence budget. More manual setup, e.g. `colima start --cpu 8 --memory 24 --vm-type vz`. |
| **Podman / Podman Desktop** | Red Hat's engine with no background daemon; containers can run without admin rights ("rootless") | Free (Apache 2.0) | Security-focused environments, Red Hat/OpenShift shops. Mostly Docker-compatible, with some differences in Compose behaviour. |
| **Rancher Desktop** | SUSE's desktop app with k3s Kubernetes and a choice of containerd or dockerd | Free (Apache 2.0) | Kubernetes-first workflows that still want a GUI |
| **Apple `container`** | Apple's open-source tool (2025) that runs each container in its own lightweight VM | Free (Apache 2.0) | Experimenting with Apple's approach. Young: no Compose equivalent yet, and best on recent macOS versions. |
| **Lima** (on its own) | The VM layer underneath Colima | Free | Custom VM setups, or full Linux distributions alongside containers |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Personal learning lab on your own Mac | OrbStack: fastest, lowest overhead, and includes the Kubernetes you'll need in Step 29 |
| Employee at a company with Docker subscriptions | Docker Desktop: the supported, centrally managed product |
| Open-source-only policy, or no budget | Colima + the Docker CLI. Everything in this curriculum works on it. |
| Security-sensitive (government, finance) with rootless requirements | Podman |
| CI build machines (Step 27) | None of these. Linux CI machines run Docker natively, with no VM. |
| Model serving that needs the GPU | Never in a container on macOS. Run it natively, as decided above. |

## Common mistakes

- **Running two runtimes at once** (e.g. OrbStack and Docker Desktop), then wondering which one `docker` is talking
  to. Check `docker context ls` and uninstall the one you don't use.
- **Putting database data on bind mounts** from your Mac folders. You'll get slow databases and odd permission
  errors. Use named volumes.
- **Publishing ports without `127.0.0.1:`**, which exposes services to your local network.
- **Calling `localhost` from inside a container** to reach the model server. Inside a container, localhost is the
  container itself. Use `host.docker.internal`.
- **Leaving the VM memory uncapped**, then getting out-of-memory errors when a 27B model loads next to OpenSearch.
- **Using `:latest` image tags.** Your stack changes whenever someone upstream publishes. Pin versions; Step 11
  also pins digests (exact fingerprints).
- **Running `docker system prune -a --volumes` casually.** It deletes your databases.

## Done when

- [ ] `cask "orbstack"` and `brew "dive"` are in the Brewfile, and `brew bundle check` passes
- [ ] `docker version` shows both Client and Server, and `docker context ls` points at OrbStack
- [ ] The VM is capped at about 24 GB memory and 8 CPUs
- [ ] Log rotation is set (`max-size 10m`, `max-file 3`)
- [ ] `docker run --rm alpine uname -m` prints `aarch64`
- [ ] A container reached the Mac's `127.0.0.1:8099` server via `host.docker.internal`
- [ ] You saw the difference between `*:8088` and `127.0.0.1:8089` in `lsof`
- [ ] You can explain in one sentence why models run natively and services run in containers: containers on
      macOS run inside a Linux VM that can't use the Metal GPU MLX needs.
- [ ] `NOTES-step3.md` records the decisions

## Recap

> **RECAP**
> You installed OrbStack, capped its VM at 24 GB and 8 CPUs, switched on log rotation, and learned four rules the
> whole platform follows:
> 1. Models run natively on macOS.
> 2. Services run in containers and reach the models via `host.docker.internal`.
> 3. Ports are published on `127.0.0.1` only.
> 4. Data lives in named volumes.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| [`bootstrap/Brewfile`](../../bootstrap/Brewfile) | Appended the "Containers (Step 3)" section: `cask "orbstack"` and `brew "dive"`. |
| [`bootstrap/home/.orbstack/config/docker.json`](../../bootstrap/home/.orbstack/config/docker.json) | Reference copy of the Docker engine config (log rotation: `json-file`, 10m × 3). Copied to `~/.orbstack/config/docker.json`, or pasted into OrbStack Settings → Docker. |
| [`bootstrap/orbstack-setup.sh`](../../bootstrap/orbstack-setup.sh) | Applies parts 2–3 from the command line (VM cap 24576 MiB / 8 CPUs, merges the log settings, restarts OrbStack) and runs the checks; `CHECK_ONLY=1` only reports. |
| [`bootstrap/labs/container-lab.sh`](../../bootstrap/labs/container-lab.sh) | Replays lab parts A–F with assertions (arch, host.docker.internal, 127.0.0.1 port binding, named volume persistence, 256 MiB cap, housekeeping) and cleans up. |
| [`bootstrap/NOTES-step3.md`](../../bootstrap/NOTES-step3.md) | The Step 3 decision notes, exactly as in the guide; becomes an ADR in Step 4. |
| [`docs/steps/step-03-container-runtime.md`](step-03-container-runtime.md) | This write-up. |
| [`docs/steps/README.md`](README.md) | Step index; Step 3 row added. |
| [`docs/glossary.md`](../glossary.md) | Step 3 terms added. |
| [`CHANGELOG.md`](../../CHANGELOG.md) | Step 3 entry added. |

## Notes for this repository

- The guide configures log rotation through the OrbStack app (Settings → Docker). The same JSON is kept as a
  reference copy at `bootstrap/home/.orbstack/config/docker.json`, mirroring OrbStack's engine config file under
  `~` (`~/.orbstack/config/docker.json`). Copy it there during workstation setup, or let
  `bootstrap/orbstack-setup.sh` merge it, or paste it into the app.
- `bootstrap/orbstack-setup.sh` and `bootstrap/labs/container-lab.sh` are additions of this repository (not in the
  guide) that script the chapter's own commands. The `orb config` key names (`memory_mib`, `cpu`) are the guide's;
  check `orb config show` if your OrbStack version differs.
- The lab script pins image tags (`alpine:3.22`, `curlimages/curl:8.16.0`, `nginx:1.29-alpine`) instead of the
  guide's untagged `alpine` / `nginx:alpine`, following the chapter's own "don't use `:latest`" rule. Each can be
  overridden with `ALPINE_IMAGE`, `CURL_IMAGE`, `NGINX_IMAGE`, `INSPECT_IMAGE`. It also adds one extra check to
  part B: calling `localhost` from inside a container fails, which demonstrates Figure 8.
- `NOTES-step3.md` lives in `bootstrap/` exactly where the guide puts it.
- Validation done here (Linux x86_64 container, no macOS, no OrbStack): the Brewfile parses as Ruby (`ruby -c`),
  `docker.json` parses with `jq`, both scripts pass `bash -n`. The full lab script ran end to end against a local
  `dockerd` (images pulled through the `mirror.gcr.io` Docker Hub mirror because of Hub rate limits, and with
  `FAKE_MODEL_BIND=0.0.0.0`, since plain Linux Docker can't forward to a host server on 127.0.0.1 — the same
  runtime difference the WATCH OUT box describes): host.docker.internal returned `{"ok":true}`, `lsof` showed
  `*:8088` vs `127.0.0.1:8089`, the volume note persisted, and `docker stats` showed the 256MiB limit. The arch
  check prints `x86_64` here (native on this machine); on the Mac it must print `aarch64`. `orbstack-setup.sh`
  needs OrbStack on macOS and was not run.
