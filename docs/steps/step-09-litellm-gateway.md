# Step 9 · The LiteLLM gateway: one front door for every model

*Step 9 of 38 · Phase B · Model serving*

## At a glance

| | |
|---|---|
| **Goal** | Put a gateway in front of all four model servers, so every application talks to **one address** (`127.0.0.1:4000`), with **one API format**, **one key**, and **role-based model names** (`qwen-quality`, `qwen-fast`, `embedder`, `reranker`) instead of ports and repository IDs. |
| **Time** | About 75 minutes. |
| **You'll end up with** | The platform's first Docker Compose stack: LiteLLM pinned to an exact image, hardened, health-checked, reading secrets from files; a version-controlled gateway config; a smoke-test script using the official OpenAI SDK; `just up` / `down` / `logs` recipes and ADR-0009. |
| **New words** | Gateway, reverse proxy, model alias (model group), deployment, routing, provider prefix, master key, virtual key, streaming (SSE), liveness / readiness, image tag vs digest, Compose project, healthcheck, restart policy, `no-new-privileges`. |

## The big idea

> **ANALOGY · THE SWITCHBOARD OPERATOR**
> Without a switchboard, every person in a building needs every other person's direct number, and there's no record
> of who called whom. With an operator, everyone dials one number and asks for a role: "the quick assistant,
> please". The operator checks you're allowed to call, connects you to whoever currently fills that role, and writes
> the call in the log book.
>
> Swap the person behind a role (a new model) and nobody's phone book changes. That operator is LiteLLM.

*(Guide Figure 28. **Without a gateway**, the RAG API, the ingestion jobs, the evaluation harness and a notebook each
connect straight to the 27B model on :8081, the 35B model on :8082, the embedder on :8083 and the reranker on :8084:
16 links, with URLs, model IDs and keys scattered everywhere. **With a gateway**, the four applications each connect
to LiteLLM on :4000, and LiteLLM connects to the four servers: 4 + 4 links, and one place for keys, limits and
logs.)*

## What we're doing

1. Write the gateway config: four role names, each mapped to a backend on your Mac.
2. Create the platform's first Compose file (`infra/compose/compose.yaml`) with LiteLLM: image pinned by digest,
   localhost-only port, memory cap, healthcheck, restart policy, privilege hardening, file-based secrets.
3. Start it with `just up` (secrets decrypted only in memory).
4. Smoke-test chat, streaming, embeddings and reranking through the gateway, plus the security checks (no key, wrong
   key, unknown model).
5. Point future clients at the gateway only.
6. Add `just` recipes and ADR-0009.

## Why we're doing this

> **WHY THIS MATTERS**
> Without a gateway, every service hard-codes model URLs, model IDs and keys. Changing a model means editing every
> service, nothing is logged centrally, and there's no single place to apply limits. The gateway is the control
> point for everything that governance, cost control, security and observability need from the model layer.

| Need | How the gateway meets it |
|---|---|
| Swap or upgrade a model without touching applications | Clients call role names; the mapping lives in one config file |
| One API for chat, embeddings and reranking | OpenAI-compatible `/v1/chat/completions`, `/v1/embeddings`, plus `/rerank` |
| Authentication in front of servers that have none (mlx-lm) | Every request needs a gateway key; model servers only accept localhost |
| Stop clients making the mlx server load arbitrary models | The gateway always sends the exact configured model ID (Step 7 risk closed) |
| Central usage records: who used which model, how many tokens | Every call passes through one place (dashboards and budgets in Step 10, traces in Step 22) |
| Resilience | Retries and timeouts now; fallbacks and rate limits in Step 10 |

> **IN A COMPANY**
> An AI gateway (sometimes called an LLM gateway or model router) is now a standard enterprise component. It's where
> organisations enforce approved models, per-team keys and budgets, data-handling rules, audit logging and failover
> between providers. Interviewers frequently ask how you'd control model access and spend across many teams; the
> answer starts here.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Gateway / reverse proxy | A server that sits in front of other servers, receives every request, applies rules, and forwards it. |
| Model alias (model group) | The public name clients use (`qwen-fast`). LiteLLM calls it `model_name`. |
| Deployment | One real backend behind an alias. An alias can have several, for load-balancing or failover. |
| Provider prefix | In `litellm_params.model`, the part before `/` says which protocol to speak. `openai/…` means "speak the OpenAI API to this `api_base`"; the rest is the model ID sent to the backend. |
| Master key | The gateway's root credential. It can do everything, so it's only for admins. |
| Virtual key | A per-app or per-person key created by the gateway, with its own budget and limits. Needs a database (Step 10). |
| Streaming (SSE) | Sending the answer token by token as it's generated (Server-Sent Events), instead of all at the end. |
| Liveness / readiness | Two health questions: "is the process alive?" (restart it if not) and "can it serve traffic yet?" |
| Image tag vs digest | A tag (`v1.104.0`) is a movable label; a digest (`@sha256:…`) is the exact, unchangeable image fingerprint. |
| Healthcheck / restart policy | Compose runs a check command periodically, and restarts the container automatically according to the policy. |

### The gateway and the reverse proxy

A reverse proxy is the receptionist of a building: visitors never walk straight to an office, they all stop at one
desk, which checks who they are and sends them on. An AI gateway is a reverse proxy that understands model traffic:
it knows what a chat request, an embedding request and a rerank request look like, counts tokens, and can retry or
redirect them.

### Aliases, deployments and routing

The **alias** is the job title ("the quick assistant"); the **deployment** is the person currently doing that job (the
Qwen3.6-35B-A3B server on :8082). **Routing** is the operator's decision about who picks up. Today every alias has
exactly one deployment; Step 10 adds a second one as a fallback, and nothing in the applications changes.

### The provider prefix

The `model` line in the config does two jobs at once. Everything before the first `/` (`openai/`, `huggingface/`)
tells LiteLLM *which language to speak* to the backend; everything after it is the *exact model ID* it sends.

### Master key and virtual keys

The master key is the building's master key: it opens every door, including the admin office. It's fine for you and
for the smoke test today, but apps should never hold it. Step 10 gives the gateway a database so it can cut
**virtual keys**: one per app, each with its own budget, rate limit and allowed models.

### Streaming

Without streaming, you wait for the whole answer and then see it at once. With **Server-Sent Events**, the server
keeps the connection open and sends each new piece of text as soon as it's generated, so a chat UI can start typing
after a fraction of a second. The gateway passes the stream through unchanged, in the same OpenAI format.

### Liveness and readiness

LiteLLM answers two questions on two URLs. `/health/liveliness` (LiteLLM's spelling) answers "is the process alive?";
if not, restart it. `/health/readiness` answers "is it ready to serve traffic?" and reports more detail. Our Compose
healthcheck uses liveness, because it must not depend on the model servers being up.

### Tag vs digest

A tag is a sticky note on a box: someone can move the note to a different box. A digest is the box's serial number:
it can only ever mean one exact set of bytes. We write both (`tag@digest`): the tag so humans can read it, the
digest so the machine runs exactly what we tested.

### Compose project, healthcheck and restart policy

A **Compose project** is the group of containers one Compose file starts. `name: rag-platform` means every container
is named `rag-platform-<service>-1`, and every later service (Postgres, Qdrant, OpenSearch …) joins the same project.
The **healthcheck** is a small command Docker runs inside the container every 15 seconds; `docker ps` then shows
`healthy` or `unhealthy`, not just `running`. The **restart policy** `unless-stopped` brings the container back after
a crash or a reboot, unless you stopped it on purpose.

### What happens to one request

*(Guide Figure 29.)* A client sends `POST /v1/chat/completions` with `model="qwen-fast"` and a bearer key to LiteLLM
on :4000. LiteLLM asks (1) is the key valid? and (2) which deployment is "qwen-fast"? It then calls
`host.docker.internal:8082` with `model="lmstudio-community/…-MLX-4bit"`, receives the streamed tokens plus usage
(prompt / completion tokens), passes the same stream back in the same OpenAI format, and records who called, which
model, how many tokens, how long it took and the status.

## How to do it

All commands run on your Mac in the repository folder (`~/dev/rag-platform`).

```bash
cd ~/dev/rag-platform
git switch -c feat/gateway
just health                                                # all four model servers must be ok first
```

### 1 · Write the gateway config

The file is [`infra/config/litellm/config.yaml`](../../infra/config/litellm/config.yaml):

```yaml
# LiteLLM gateway: role names (model_name) -> real backends on the Mac.
# Clients only ever use the role names. Change a backend here, not in apps.

model_list:
  - model_name: qwen-quality                                  # careful answers, synthesis
    litellm_params:
      model: openai/mlx-community/Qwen3.8-27B-8bit            # "openai/" = OpenAI protocol; the rest is the EXACT id mlx loaded
      api_base: http://host.docker.internal:8081/v1
      api_key: "not-used"                                     # mlx-lm has no auth; LiteLLM requires a non-empty value
      timeout: 600                                            # long answers on a 27B model can take minutes
    model_info:
      mode: chat

  - model_name: qwen-fast                                     # rewriting, routing, quick replies (thinking off at the server)
    litellm_params:
      model: openai/lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit   # use YOUR exact repo id (Step 7)
      api_base: http://host.docker.internal:8082/v1
      api_key: "not-used"
      timeout: 120
    model_info:
      mode: chat

  - model_name: embedder                                      # TEI OpenAI-compatible route; served name from Step 8
    litellm_params:
      model: openai/qwen3-embedding-0.6b
      api_base: http://host.docker.internal:8083/v1
      api_key: os.environ/TEI_API_KEY
    model_info:
      mode: embedding

  - model_name: reranker                                      # TEI /rerank via LiteLLM's Hugging Face rerank provider
    litellm_params:
      model: huggingface/BAAI/bge-reranker-v2-m3
      api_base: http://host.docker.internal:8084
      api_key: os.environ/TEI_API_KEY
    model_info:
      mode: rerank

litellm_settings:
  drop_params: true             # silently drop OpenAI parameters a backend doesn't support, instead of erroring
  num_retries: 1                # one retry on transient errors (fallbacks come in Step 10)
  request_timeout: 600

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

`os.environ/NAME` is LiteLLM's way of saying "read this value from the environment variable `NAME`", so no key is
ever written in the file.

> **IN PLAIN ENGLISH · THE MODEL LINE**
> `openai/mlx-community/Qwen3.8-27B-8bit` means: "talk to this backend using the OpenAI API, and ask it for the model
> called `mlx-community/Qwen3.8-27B-8bit`." That ID must exactly match what the mlx server loaded. A different ID
> would make mlx try to load another model (the memory risk from Step 7). Now only this config decides which ID is
> sent, and clients can't change it.

> **WATCH OUT · THE QUERY INSTRUCTION IS STILL THE CLIENT'S JOB**
> The gateway forwards text unchanged. Applications must still add the query instruction to search queries (Step 8's
> embedding contract) and must not add it to documents. Step 31 builds this into a shared helper in `libs/`.

### 2 · Pick and pin the image

Find the latest non-pre-release version on the LiteLLM GitHub releases page (`rc` and `dev` tags are previews), then
get its digest:

```bash
docker pull ghcr.io/berriai/litellm:v1.104.0                                   # example: use the current stable release
docker buildx imagetools inspect ghcr.io/berriai/litellm:v1.104.0 | head -5    # "Digest: sha256:…" plus platforms
```

Write the image as `tag@digest` in Compose. The tag keeps it readable; the digest makes it exact. Confirm
`linux/arm64` is among the platforms (Step 3).

For this repository the inspect gave the multi-platform index digest
`sha256:625981c83410a3ea68eb0697590a57ec1d764d634514d54fa5db0591077ee839`, with `linux/amd64` and `linux/arm64`
images inside it. Because it is the *index* digest, the same line works on an Apple Silicon Mac and on an x86 CI
runner: Docker picks the right platform from the index.

### 3 · Create the first Compose file

The file is [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml):

```yaml
# The platform stack. Start with:   just up   (secrets are decrypted in memory by sops)
name: rag-platform

services:
  litellm:
    image: ghcr.io/berriai/litellm:v1.104.0@sha256:625981c83410a3ea68eb0697590a57ec1d764d634514d54fa5db0591077ee839
    # The image only reads keys from environment variables, so a tiny wrapper reads the secret FILES
    # and exports them inside the container process only. They never appear in `docker inspect`.
    entrypoint: ["/bin/sh", "-c"]
    command:
      - >
        export LITELLM_MASTER_KEY="$$(cat /run/secrets/litellm_master_key)"
        TEI_API_KEY="$$(cat /run/secrets/tei_api_key)" &&
        exec litellm --config /app/config.yaml --host 0.0.0.0 --port 4000
    secrets: [litellm_master_key, tei_api_key]
    volumes:
      - ../config/litellm/config.yaml:/app/config.yaml:ro     # config is read-only inside the container
    ports:
      - "127.0.0.1:4000:4000"                                 # localhost only (Step 3 rule)
    extra_hosts:
      - "host.docker.internal:host-gateway"                   # reach the native model servers, on any runtime
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 2g, cpus: "2" }

secrets:
  litellm_master_key:
    environment: LITELLM_MASTER_KEY             # supplied by `sops exec-env` when you run `just up`
  tei_api_key:
    environment: TEI_API_KEY
```

How the secrets travel: `just up` runs `docker compose` *inside* `sops exec-env`, so the two keys exist only as
environment variables of that one `docker compose` command. The top-level `secrets:` block tells Compose to take each
value from that environment and mount it as a file under `/run/secrets/` in the container (the Step 6 pattern). The
`$$` is Compose's escape for a literal `$`, so the shell *inside the container* runs `cat` on those files, exports
the values, and then `exec`s LiteLLM, which reads them through `os.environ/…`. The container's configured
environment never contains the keys.

> **WHY `--HOST 0.0.0.0` INSIDE THE CONTAINER IS FINE**
> Inside the container, LiteLLM must listen on all of the container's own interfaces, or Docker couldn't forward
> traffic to it. What matters for your safety is the published port on your Mac, which is `127.0.0.1:4000`, so only
> your Mac can reach it.

> **WATCH OUT · IF YOUR IMAGE VERSION HAS NO `/BIN/SH`**
> Some hardened images remove the shell. Then the wrapper won't work. Use
> `environment: { LITELLM_MASTER_KEY: "${LITELLM_MASTER_KEY}" }` instead (values still come from `sops exec-env`), and
> record this as a documented exception in ADR-0009, since the key becomes visible in `docker inspect`.

| Hardening line | What it protects against |
|---|---|
| `image: …@sha256:…` | A moved tag or swapped image changing what runs |
| `ports: 127.0.0.1:…` | The gateway being reachable from your network |
| `:ro` config mount | A compromised process rewriting its own routing |
| `secrets:` + wrapper | Keys appearing in `docker inspect`, compose files or images |
| `no-new-privileges` | A process inside the container gaining extra privileges (e.g. via setuid binaries) |
| `limits` | A runaway gateway eating memory your models need (unified memory, Step 3) |
| `healthcheck` + `restart` | A hung or crashed gateway staying down unnoticed |

### 4 · `just` recipes and first start

Added to the [`justfile`](../../justfile) (the `compose` variable sits with the other variables at the top):

```just
compose       := "docker compose -f infra/compose/compose.yaml"

# Start / stop the container stack (secrets decrypted in memory)
up:
    sops exec-env secrets/dev.enc.env '{{compose}} up -d'
    {{compose}} ps

down:
    {{compose}} down

ps:
    {{compose}} ps

# Follow logs of one service:   just logs litellm
logs service="litellm":
    {{compose}} logs -f --tail 100 {{service}}

# Gateway checks
gateway-health:
    @curl -sf http://127.0.0.1:4000/health/liveliness > /dev/null && echo "  gateway :4000 alive" || echo "  gateway :4000 DOWN"
    @curl -sf http://127.0.0.1:4000/health/readiness | jq -c . || true

# End-to-end smoke test through the gateway (chat, streaming, embeddings, rerank, security checks)
gateway-smoke:
    sops exec-env secrets/dev.enc.env "uv run --with openai scripts/gateway_smoke.py"
```

```bash
just up
just gateway-health
just logs                                          # watch start-up; Ctrl+C to stop following
docker inspect rag-platform-litellm-1 --format '{{json .Config.Env}}' | grep -c MASTER_KEY   # 0 = key not exposed
```

After about 30 seconds `just ps` should show the `litellm` container as `(healthy)`.

### 5 · Smoke-test everything through the gateway

The script is [`scripts/gateway_smoke.py`](../../scripts/gateway_smoke.py). With the official OpenAI SDK pointed
at `http://127.0.0.1:4000/v1` and the master key, it:

1. lists the models the gateway offers (only the four role names);
2. asks both chat roles, `qwen-fast` and `qwen-quality`, "In one sentence, what is a vector database?" and prints
   the start of each answer and the token count;
3. streams "Count to five." from `qwen-fast`, printing each piece as it arrives;
4. embeds two texts with `embedder` and prints "2 vectors of 1024 dims";
5. calls `/rerank` with `reranker`, a question and two documents, and prints each document's index and relevance
   score;
6. runs the **security checks**, each of which **must fail**: a wrong key (`sk-wrong`) must be rejected with
   `AuthenticationError`, and an unknown model (`gpt-5`) must be rejected with `BadRequestError` / `NotFoundError`.

```bash
just with-secrets uv run --with openai scripts/gateway_smoke.py
# or simply:
just gateway-smoke
```

> **TIP · IF SOMETHING FAILS, READ THE GATEWAY LOGS FIRST**
> `just logs` shows exactly which backend URL was called and what came back. Common causes:
>
> - A model server is down: run `just health`.
> - A model ID that doesn't match the mlx server.
> - The TEI key isn't reaching the container: check `secrets/dev.enc.env` has `TEI_API_KEY`.
> - Embeddings fail on encoding format: some LiteLLM/TEI version combinations need `encoding_format: float`; set it
>   in the client call.
> - Rerank fails: for the reranker `api_base`, check in the logs which path LiteLLM appended (it should call TEI's
>   `/rerank`).

> **WHAT YOU JUST PROVED**
> One address, one key, four capabilities, standard SDK, and the gateway refuses requests with a bad key or for
> models that aren't on the approved list. That last part is your first allow-list control: nothing reaches a model
> unless the config says so.

### 6 · Make the gateway the only door

From now on, every service and script uses only these two settings, never ports 8081–8084. Appended to
[`.env.example`](../../.env.example):

```text
# --- Gateway (Step 9): the ONLY way applications reach models ---
LLM_GATEWAY_URL=http://127.0.0.1:4000                # from containers: http://litellm:4000
LLM_GATEWAY_KEY=<virtual key from Step 10; master key only for admin tasks>
```

From another container in the same Compose project, the gateway's address is its service name, `http://litellm:4000`;
from your Mac it is `http://127.0.0.1:4000`.

> **WATCH OUT · THE MASTER KEY IS TEMPORARY FOR APPS**
> Right now the smoke test uses the master key, which can do everything. Step 10 adds a small database so the gateway
> can issue virtual keys: one per application, each with its own budget, rate limit and allowed models. Apps will
> switch to those, and the master key goes back to admin-only use.

### 7 · Record the decision: ADR-0009

```bash
just adr "Route all model access through a LiteLLM gateway"
```

Then fill it in: [`docs/adr/0009-route-all-model-access-through-a-litellm-gateway.md`](../adr/0009-route-all-model-access-through-a-litellm-gateway.md).
In short: all model access goes through LiteLLM on 127.0.0.1:4000 in Docker Compose (digest-pinned image, read-only
config, file-based secrets, no-new-privileges, limits, liveness healthcheck); clients use the four role names; model
servers are never called directly by applications. Alternatives considered: direct calls (fails governance needs),
Portkey / Kong AI Gateway / Envoy AI Gateway (heavier or partly commercial), a custom FastAPI proxy (reinventing a
mature tool), and cloud gateways (not local, lock-in; mapped in Step 37). Revisit when policy needs exceed LiteLLM or
multi-region HA is required.

```bash
git add -A
git commit -m "feat(gateway): LiteLLM gateway in Compose with role-based model routing"
git push -u origin feat/gateway
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Decoupling:** applications know role names, not ports, repositories or keys. A model swap is one config change,
  reviewed in a PR.
- **Security in front of insecure backends:** authentication, an allow-list of models, and a fixed model ID that
  closes the "load any model" risk.
- **One standard API** for chat, streaming, embeddings and reranking, usable with the OpenAI SDK, LangChain,
  LlamaIndex, DSPy and more.
- **A pattern for every later service:** the Compose conventions (digest pin, localhost port, secrets as files,
  limits, healthcheck, restart, `no-new-privileges`) are reused in Steps 11–22.
- **Ready for governance:** budgets, rate limits, fallbacks, usage logs and traces all attach here in Steps 10 and 22.

## Drawbacks and risks

- **A single point of failure.** If the gateway is down, everything is down. Healthchecks and restarts help locally;
  production runs several replicas behind a load balancer.
- **Extra latency.** A few milliseconds per hop, negligible against model time, but it exists.
- **A fast-moving dependency.** LiteLLM releases very frequently. Pin by digest, read release notes, and upgrade
  deliberately; the smoke test is your regression check.
- **A high-value target.** It holds every key and sees every prompt. Keep it localhost-only, protect the master key,
  and keep its own logs free of secrets.
- **Abstraction gaps.** Provider-specific features (thinking settings, special parameters) don't always map cleanly
  through a generic API. `drop_params` hides some mismatches; test what you rely on.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **LiteLLM proxy (our choice)** | Open-source, Python, 100+ providers, keys/budgets/fallbacks, OpenAI-compatible | You want a capable OSS gateway that runs anywhere, including locally |
| Portkey Gateway | AI gateway with routing, guardrails and observability (OSS core + managed) | You want built-in guardrails and a managed option |
| Kong AI Gateway / Envoy AI Gateway | AI plugins for established API gateways | Your company already runs Kong or Envoy for all APIs |
| Cloudflare / Vercel AI Gateway | Hosted gateways in front of cloud model APIs | Cloud model providers, edge deployments |
| Cloud-native (Bedrock, Azure API Management + Azure OpenAI, Vertex AI) | The cloud's own model access controls | You're all-in on one cloud (Step 37) |
| Custom proxy (FastAPI, Go) | Your own code | Very specific policies, or extreme latency budgets |
| No gateway | Apps call model servers directly | One-off prototypes only |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local or self-hosted models, one team, learning lab | LiteLLM (this step) |
| Many teams sharing models, chargeback needed | LiteLLM with virtual keys and budgets (Step 10), or Portkey |
| Company already standardised on Kong or Envoy | Their AI gateway plugins, for one policy engine for all APIs |
| Mix of cloud providers with failover between them | LiteLLM / Portkey with multi-provider fallbacks |
| Single-cloud enterprise | That cloud's native gateway, plus a portable gateway if you want to avoid lock-in |

## Common mistakes

- Letting apps keep calling ports 8081–8084 "just for now". Bypassing the gateway bypasses auth, limits and logs.
- Using `:latest` or an unpinned tag for the gateway image. A surprise upgrade can change routing behaviour.
- Model IDs in config that don't match the backend, so mlx-lm tries to load another model.
- Giving the master key to applications. Use virtual keys (Step 10).
- Putting keys directly in `config.yaml`. Use `os.environ/…`, filled from secret files.
- Publishing port 4000 on all interfaces.
- Forgetting `extra_hosts`, so the gateway works on OrbStack but breaks on Colima or Linux CI.
- No healthcheck, so a hung gateway looks "running" in `docker ps`.

## Done when

- [ ] `infra/config/litellm/config.yaml` defines `qwen-quality`, `qwen-fast`, `embedder` and `reranker`, with the
      exact model IDs
- [ ] `infra/compose/compose.yaml` pins LiteLLM by tag@digest and has localhost port, secrets, limits, healthcheck,
      restart and `no-new-privileges`
- [ ] `just up` starts it, and `just ps` shows it healthy
- [ ] `docker inspect` does not show the master key in the environment
- [ ] `gateway_smoke.py` succeeds for both chats, streaming, embeddings and rerank
- [ ] The smoke test shows a bad key and an unknown model are rejected
- [ ] `.env.example` documents `LLM_GATEWAY_URL` and `LLM_GATEWAY_KEY`
- [ ] ADR-0009 and all files are merged through a PR

## Recap

> **RECAP**
> Every model now sits behind one front door: LiteLLM on `127.0.0.1:4000`. Clients use role names, the official
> OpenAI SDK, and a key. The gateway authenticates, allow-lists models, sends exact model IDs, retries, and sees every
> call. It's also the platform's first Compose service, establishing the container conventions (digest pins,
> localhost ports, file-based secrets, limits, healthchecks) every later service will follow. Step 10 gives the
> gateway a memory: virtual keys, budgets, rate limits and fallbacks.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/config/litellm/config.yaml` | The gateway config: four role names mapped to the exact backends on the Mac, keys read from the environment. |
| `infra/compose/compose.yaml` | The platform's first Compose stack: the hardened, digest-pinned LiteLLM service on 127.0.0.1:4000 with file-based secrets. |
| `infra/compose/.gitkeep`, `infra/config/.gitkeep` (removed) | Placeholders no longer needed now that both folders hold real files. |
| `justfile` (changed) | `compose` variable and the `up`, `down`, `ps`, `logs`, `gateway-health` and `gateway-smoke` recipes. |
| `.env.example` (changed) | Documents `LLM_GATEWAY_URL` and `LLM_GATEWAY_KEY`, the only two settings apps use to reach models. |
| `scripts/gateway_smoke.py` | End-to-end smoke test through the gateway with the OpenAI SDK, including the bad-key and unknown-model checks. |
| `tests/test_gateway.py` | Checks the config and Compose rules, and runs the smoke test against a fake LiteLLM on :4000. |
| `pyproject.toml`, `uv.lock` (changed) | `openai`, `pyyaml` and `types-pyyaml` added to the dev dependencies for the smoke test's type check and the tests. |
| `docs/adr/0009-route-all-model-access-through-a-litellm-gateway.md` | ADR-0009: the decision, alternatives, consequences and when to revisit. |
| `docs/adr/README.md` (changed) | ADR-0009 added to the index. |
| `docs/steps/step-09-litellm-gateway.md` | This write-up. |
| `docs/steps/README.md`, `docs/glossary.md`, `CHANGELOG.md` (changed) | Step index row, the new glossary terms, and the changelog entry. |

## Notes for this repository

- **The real digest is pinned.** The guide leaves `<digest-from-step-2>` for you to fill in. Here
  `docker buildx imagetools inspect ghcr.io/berriai/litellm:v1.104.0` was run on 2026-10-12 and returned the index
  digest `sha256:625981c8…e839` (linux/amd64 + linux/arm64), which is what `compose.yaml` pins. When you upgrade,
  re-run the inspect for the new stable tag and replace both the tag and the digest in one PR.
- **Model IDs.** `qwen-quality` and `qwen-fast` use the same repository IDs as the `justfile` variables
  `quality_model` / `fast_model` (Step 7), and the embedder uses the served name `qwen3-embedding-0.6b` from Step 8; a
  test fails if they drift apart. If you serve a different repo, change both places.
- **Smoke-test tweaks (all small, for strict mypy and honest results).** Compared with the guide's script: the answer
  text and the usage are read defensively (`content or ""`, `usage.total_tokens if usage else "?"`), because the SDK
  types both as optional; empty stream chunks (a final usage-only chunk) are skipped; the security-check clients use
  `max_retries=0` so a rejection is reported at once; the "connection" branch also catches the SDK's own
  `APIConnectionError` (the SDK never raises `urllib`'s `URLError`); and the script exits with code 1 if any security
  check was *accepted* or could not connect, so it can gate CI. Output lines are the guide's.
- **Extra dev dependencies.** The smoke test still runs with `uv run --with openai` as the guide says, but `openai` is
  also in the dev group so strict mypy can type-check the script and the tests can run it. `pyyaml` (+ its type stubs)
  lets the tests read the YAML files.
- **An extra recipe.** `just gateway-smoke` is a shortcut for the guide's `just with-secrets uv run --with openai
  scripts/gateway_smoke.py`. The echo lines in `gateway-health` use the same "  name :port ok/DOWN" style as
  `just health` (the PDF's tick/cross symbols did not survive extraction).
- **What was validated here (Linux container, no Mac, no model servers).** `docker compose -f
  infra/compose/compose.yaml config` resolves the file cleanly (localhost port, read-only bind of the config, the two
  file secrets from the environment, `no-new-privileges`, 2 GB / 2 CPU limits). The image's manifest and digest were
  confirmed with `docker buildx imagetools inspect`, but its layers could not be downloaded here (the blob host is
  blocked by this container's network policy), so LiteLLM itself was not started. The secrets wrapper was proven with
  the same `entrypoint`/`command`/`secrets` on an Alpine container: the keys reached the process (correct lengths)
  and `docker inspect … .Config.Env | grep -c MASTER_KEY` printed `0`. The smoke test runs end to end against a fake
  OpenAI-compatible gateway (models, chat, SSE streaming, embeddings, `/rerank`, 401 for a bad key, 400 for an unknown
  model), and fails as it should when the fake accepts any model. ruff, strict mypy and the whole test suite pass.
