# Step 15 · Valkey (Redis-compatible): cache, queues and locks

*Step 15 of 38 · Phase C · Data stores*

## At a glance

| | |
|---|---|
| **Goal** | Add a fast in-memory data store for the platform's short-lived, high-speed needs: an LLM response cache in the gateway, a durable job queue for ingestion, locks that stop two workers processing the same document, and later session memory. We use Valkey, the open-source, Redis-compatible project under the Linux Foundation. |
| **Time** | About 75 minutes. |
| **You'll end up with** | A `valkey` service (9.1.x, pinned) with an ACL: default user off, separate `admin`, `litellm` and `rag_app` users, dangerous commands blocked, app keys limited to `rag:*`; memory and eviction settings safe for cache and queues, persistence on; LiteLLM response caching; a Streams job-queue demo with crash recovery and a dead-letter queue, plus a lock demo; ADR-0015. |
| **New words** | In-memory store, key-value, TTL, cache hit/miss, eviction, maxmemory policy, persistence (RDB/AOF), ACL, command category, stream, consumer group, acknowledgement, pending entry, at-least-once delivery, idempotency, dead-letter queue, distributed lock, cache key, cache poisoning. |

## The big idea

> **ANALOGY · THE KITCHEN COUNTER NEXT TO THE PANTRY**
> The databases from Steps 11–14 are the pantry: big, organised, permanent. Valkey is the kitchen counter: small
> and very fast, where you keep what you're using right now:
>
> - the dish you just cooked, in case someone orders it again in the next ten minutes (cache)
> - the order tickets waiting for a cook (queue)
> - the "I'm working on this" sign on a pot (lock)
>
> When the counter fills up, you clear away leftovers (cache), but never the order tickets.

```text
  LLM response cache                                   Locks & idempotency
  same prompt → answer in ms                           one worker per document
  keys have TTL → may be evicted                       SET … NX PX (auto-expiring)

                                 Valkey
                           in-memory key-value
                     maxmemory 512 MB · volatile-lru

  Job queue (Streams)                                  Sessions / memory
  ingestion jobs, acked by workers                     chat history (Project 8)
  no TTL → never evicted                               short TTL, per user

  volatile-lru: when memory is full, only keys WITH an expiry (cache) are evicted. Queues and locks survive.
```

*Figure 47 of the guide: four jobs for one fast store. Cache entries carry an expiry and may be evicted under
memory pressure; queues and locks have no expiry, so the volatile-lru policy never evicts them.*

## What we're doing

1. Replace the Step 6 `REDIS_PASSWORD` with three per-user passwords.
2. Write a Valkey config: memory cap, eviction policy, persistence, slow-log.
3. Run `valkey` in Compose with an ACL file built in memory from secrets (same pattern as SeaweedFS in Step 14).
4. Prove the ACL: no anonymous access; the app user can't read gateway keys or flush the database.
5. Turn on LiteLLM response caching and measure a cache hit.
6. Build a job queue with Streams and consumer groups: crash recovery, retries and a dead-letter queue. Then a
   safe distributed lock.
7. Record ADR-0015.

## Why we're doing this

> **WHY THIS MATTERS**
> LLM calls take seconds and cost GPU time; repeated identical calls (evaluation reruns, retries, popular
> questions) shouldn't pay twice. Ingestion must survive a worker crashing halfway through a 500-page PDF without
> losing or duplicating work. Two workers must never re-index the same document at once. These are classic
> production problems, and an in-memory store with the right data structures solves all of them in milliseconds.

| Need | How Valkey meets it |
|---|---|
| Don't recompute identical LLM calls | Response cache with TTL in the gateway |
| Background work that survives crashes | Streams + consumer groups + acknowledgements |
| Retry failed jobs, but not forever | Delivery counters + a dead-letter queue |
| One worker per document at a time | Distributed lock with automatic expiry |
| Shared state across gateway replicas (later) | Rate-limit and spend counters (Capstone, multi-instance) |
| Least privilege | ACL users, command categories, key patterns |
| Survive restarts | AOF + RDB persistence |

> **IN A COMPANY**
> Redis-compatible stores sit in almost every production architecture. The licensing story is a real governance
> case study: Redis moved away from its open-source licence in 2024, the community forked it as Valkey under the
> Linux Foundation (BSD licence), and Redis later added an AGPL option back. Many companies standardised on Valkey;
> AWS ElastiCache and Google Memorystore offer it. Choosing a component with its licence in mind is part of an
> architect's job.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **In-memory key-value store** | A database that keeps data in RAM, retrieved by a key (a name). Extremely fast. |
| **TTL (time to live)** | An expiry time on a key; it disappears automatically afterwards. |
| **Cache hit / miss** | The answer was already stored / it had to be computed. |
| **Eviction / maxmemory policy** | What to delete when memory is full. `volatile-lru` removes the least-recently-used keys that have a TTL. |
| **Persistence: RDB / AOF** | Periodic snapshots / an append-only log of every write, replayed after a restart. |
| **ACL / command category** | Per-user rules for which keys and commands are allowed. Categories group commands, e.g. `@dangerous` (`FLUSHALL`, `KEYS`, `CONFIG`…). |
| **Stream** | An append-only log of messages, each with an ID. |
| **Consumer group** | A set of workers sharing a stream; each message goes to one worker. |
| **Acknowledgement (XACK)** | The worker's "done" signal. Until then, the message is *pending*. |
| **At-least-once delivery** | Every job is delivered at least once, but may be delivered twice after a crash. |
| **Idempotency** | Doing a job twice has the same effect as doing it once. Required with at-least-once delivery. |
| **Dead-letter queue (DLQ)** | Where jobs go after failing too many times, for a human to inspect. |
| **Distributed lock** | A short-lived "I'm working on this" marker shared by all workers. |

> **IN PLAIN ENGLISH**
> Everything in Valkey is a *key* (a name like `rag:lock:doc-3`) holding a *value*. Values can be plain strings
> (a cached answer), or richer structures such as a *stream* (an ordered list of job tickets). Because it all
> lives in RAM, reads and writes take well under a millisecond, but RAM is limited, so you must decide what is
> allowed to be thrown away when it fills up.

### Response caching, and its one big danger

```text
                                     hit  ──────────────►  answer in ~ms
  request                 in cache?
  model + prompt + params            miss ──►  call the LLM (seconds)  ──►  store with TTL (e.g. 10 minutes)

  Never let a cached answer cross a permission boundary.
  Cache keys must include everything that changes the answer: the retrieved context, the user's groups, the
  tenant, the model version.
```

*Figure 48 of the guide: a response cache returns stored answers for repeated requests in milliseconds. Its key
must include everything that changes the answer, or one user's answer could be served to another.*

A **cache key** is what the cache looks answers up by. LiteLLM's exact-match cache hashes the model, the full list
of messages and the parameters (temperature, max tokens…) into a key such as
`litellm.cache:65373e49…` and stores the answer under it with a TTL. The same request within ten minutes gets the
stored answer back; anything different (one changed word, another model, another temperature) is a miss.

> **WATCH OUT · CACHING IN RAG CAN LEAK DATA**
> Suppose an app caches answers by question text alone. An executive asks "What's the plan for hybrid work?" and
> gets an answer built from a restricted document. An ordinary employee asks the same question and receives the
> cached executive answer. That's a data leak with no bug in retrieval.
> The gateway's cache is keyed on the full prompt (which includes the retrieved, permission-filtered context), the
> model and its parameters, so it's safe. Application-level and semantic caches (Step 33) must include the user's
> permission scope in the key. This is a classic interview question.

Serving a wrong, stale or someone-else's answer from a cache like this is called **cache poisoning**: the cache
itself is "poisoned" with an entry that should never be served to the next requester. TTLs limit how long a bad
entry lives; correct keys stop it being shared in the first place.

### Memory, eviction and persistence

Valkey keeps everything in RAM, so it needs a cap (`maxmemory 512mb`) and a rule for what to delete when the cap is
reached: the **maxmemory policy**. The choice matters a lot on a shared instance:

- `allkeys-lru` deletes *any* least-recently-used key: a pure-cache setting.
- `volatile-lru` deletes only least-recently-used keys *that have a TTL*.
- `noeviction` deletes nothing and refuses new writes instead: the setting for a queue-only instance.

Our cache entries always carry a TTL; queues and locks never do (a lock has a TTL, but it is tiny, short-lived and
only while it is held). So `volatile-lru` throws away leftovers and keeps the order tickets.

Because RAM is wiped on restart, Valkey also writes to disk. **RDB** snapshots save the whole dataset now and then
(`save 900 1 300 10 60 10000`: after 900 s if at least 1 key changed, 300 s if 10 changed, 60 s if 10,000
changed). The **AOF** (append-only file) logs every write; with `appendfsync everysec` it is flushed to disk every
second, so a crash loses at most about one second of writes. On start-up Valkey replays the AOF.

### Users, key patterns and command categories (the ACL)

An **ACL** (access control list) lists users and what each may do. Each rule is short:

- `on` / `off`: the user is enabled or disabled. `user default off` turns off the anonymous user.
- `>password`: the user's password (stored only as a SHA-256 hash once loaded).
- `~pattern`: which keys the user may touch (`~*` all, `~rag:*` only keys that start with `rag:`).
- `&pattern`: the same for pub/sub channels.
- `+@category` / `-@category`: allow or deny a **command category**, a named group of commands. `@dangerous`
  contains `FLUSHALL`, `FLUSHDB`, `KEYS`, `CONFIG`, `DEBUG`, `SHUTDOWN`, `ACL` and similar; `@admin` contains
  administrative commands.

### Streams as a crash-safe job queue

A **stream** is an append-only log of messages (`XADD`), each with an ID made from a timestamp. A **consumer group**
lets several workers share one stream: `XREADGROUP … >` hands each new message to exactly one worker. The message
is then **pending** for that worker until it sends `XACK` (the **acknowledgement**). If the worker crashes, the
message stays pending; another worker can take it over with `XAUTOCLAIM` once it has been idle for long enough
(~60 s in production, 1 s in the demo). Valkey counts deliveries per message, so after a few failed attempts the
job is moved to a **dead-letter** stream instead of being retried forever.

### Locks

A **distributed lock** is a key that says "this document is being processed". `SET rag:lock:doc-3 <token> NX PX
30000` creates it only if it doesn't exist (`NX`) and makes it expire after 30 seconds (`PX`), so a crashed holder
can't block the document forever. Releasing must compare the token first (a tiny Lua script runs the compare and
delete atomically), so a worker whose lock already expired can't delete someone else's newer lock.

## How to do it

All commands run from the repository root (`~/dev/rag-platform` on your Mac). The guide works on a branch:

```bash
cd ~/dev/rag-platform
git switch -c feat/valkey
```

### 1 · Passwords

```bash
for i in 1 2 3; do openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-32; echo; done
just secrets-edit
#   remove REDIS_PASSWORD (Step 6), then add:
#   VALKEY_ADMIN_PASSWORD=<1st>   VALKEY_LITELLM_PASSWORD=<2nd>   VALKEY_APP_PASSWORD=<3rd>
```

Then update `.env.example` and `scripts/new-dev-secrets.sh` to match. In this repository both are done: the
generator writes the three `VALKEY_*` passwords with the same `rand` helper as the database passwords (32
letters/digits, so they are safe inside the `redis://` URL the gateway uses), and `.env.example` lists the three
names with what each user is for.

### 2 · Configuration

File `infra/config/valkey/valkey.conf`:

```text
# --- network (inside the Compose network; host access only via 127.0.0.1 port mapping) ---
bind 0.0.0.0
port 6379
protected-mode yes

# --- memory: cap it, and evict ONLY keys that have a TTL (cache), never queues/locks ---
maxmemory 512mb
maxmemory-policy volatile-lru

# --- persistence: snapshot + append-only log (lose at most ~1 s of writes on a crash) ---
dir /data
save 900 1 300 10 60 10000
appendonly yes
appendfsync everysec

# --- diagnostics ---
# log commands slower than 10 ms
slowlog-log-slower-than 10000
latency-monitor-threshold 100
```

`bind 0.0.0.0` only means "every interface *inside the container*"; the Compose port mapping publishes it to your
Mac on `127.0.0.1` only. `protected-mode yes` is an extra safety net that refuses outside connections whenever no
password is set. The slow-log records commands slower than 10 ms (`just kv-cli slowlog get 10`), and the latency
monitor records events over 100 ms (`just kv-cli latency latest`).

> **WATCH OUT · WHY VOLATILE-LRU AND NOT ALLKEYS-LRU?**
> `allkeys-lru` is the classic "pure cache" setting: when full, delete any least-recently-used key. On a shared
> instance that could delete a queued ingestion job or an active lock: silent data loss. `volatile-lru` only evicts
> keys with an expiry, so cache entries (which always have a TTL) go first, and queues and locks are safe. In
> larger systems you'd run separate instances for cache and for queues, each with its own policy.

### 3 · Run Valkey with an in-memory ACL file

Pick the current stable release (9.1.2 at the time of writing; check Valkey's GitHub releases) and pin its digest:

```bash
docker buildx imagetools inspect valkey/valkey:9.1.2-alpine | head -5
```

The `valkey` service in `infra/compose/compose.yaml`:

```yaml
services:
  valkey:
    image: valkey/valkey:9.1.2-alpine@sha256:48332870af354a799964c0012ae1194a0bf2bf894eb508f945810596dc2d8d11
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        umask 077
        cat > /run/valkey/users.acl <<EOF
        user default off
        user admin on >$$(cat /run/secrets/valkey_admin_password) ~* &* +@all
        user litellm on >$$(cat /run/secrets/valkey_litellm_password) ~* &* +@all -@dangerous
        user rag_app on >$$(cat /run/secrets/valkey_app_password) ~rag:* &rag:* +@all -@dangerous -@admin
        EOF
        chown -R valkey:valkey /run/valkey
        exec docker-entrypoint.sh valkey-server /etc/valkey/valkey.conf --aclfile /run/valkey/users.acl
    secrets: [valkey_admin_password, valkey_litellm_password, valkey_app_password]
    tmpfs:
      - /run/valkey:size=1m,mode=0700           # ACL file with passwords lives in RAM only
    volumes:
      - ../config/valkey/valkey.conf:/etc/valkey/valkey.conf:ro
      - valkey-data:/data
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      # "NOAUTH" means alive and correctly refusing anonymous access, so no password needed here
      test: ["CMD-SHELL", "valkey-cli ping 2>&1 | grep -qE 'PONG|NOAUTH'"]
      interval: 10s
      timeout: 3s
      retries: 10
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 768m, cpus: "1" }     # a bit above maxmemory for overhead

volumes:
  valkey-data:

secrets:
  valkey_admin_password:   { environment: VALKEY_ADMIN_PASSWORD }
  valkey_litellm_password: { environment: VALKEY_LITELLM_PASSWORD }
  valkey_app_password:     { environment: VALKEY_APP_PASSWORD }
```

How it works: Compose mounts the three passwords as secret *files*; at start-up the shell writes the ACL file into
a RAM-only `tmpfs` folder (`umask 077` makes it readable by its owner only), and starts Valkey with
`--aclfile`. Nothing with a password ever touches the disk or appears in `docker inspect`. (The `$$` is Compose's
escape for a literal `$`, so the substitution happens inside the container, not on your Mac.) The two extra lines
(`chown` and `docker-entrypoint.sh`) make Valkey run as the image's unprivileged `valkey` user instead of root; see
*Notes for this repository*.

> **IN PLAIN ENGLISH · READING THE ACL LINES**
>
> - `user default off`: no anonymous access at all.
> - `~*` / `~rag:*`: which keys the user may touch (all keys / only keys starting with `rag:`).
> - `&*` / `&rag:*`: the same, for pub/sub channels.
> - `+@all -@dangerous -@admin`: all commands except dangerous ones (`FLUSHALL`, `KEYS`, `CONFIG`, `DEBUG`…) and
>   admin ones.
> - `>password`: the user's password (from the secret file).
>
> The app can only see its own `rag:*` keys. It can't read the gateway's cache or wipe the database.

A `just` recipe gives you an admin shell without ever putting the password on a command line (it travels in the
`REDISCLI_AUTH` environment variable, which `valkey-cli` reads):

```text
# Valkey CLI as admin (password via env var, never as an argument)
kv-cli *args:
    sops exec-env secrets/dev.enc.env 'docker compose -f infra/compose/compose.yaml exec -e REDISCLI_AUTH="$VALKEY_ADMIN_PASSWORD" valkey valkey-cli --user admin {{args}}'
```

Start it and check:

```bash
just up && just ps
docker compose -f infra/compose/compose.yaml exec valkey valkey-cli ping   # NOAUTH: anonymous refused
just kv-cli ping                                                         # PONG
just kv-cli acl list                                                     # the four users (passwords shown as hashes)
just kv-cli info memory | grep -E 'used_memory_human|maxmemory_human|maxmemory_policy'
```

You should see `NOAUTH Authentication required.`, then `PONG`, then four `user …` lines with `#<sha256>` instead
of passwords, and `maxmemory_human:512.00M` / `maxmemory_policy:volatile-lru`. `just kv-cli config get appendonly`
prints `yes`.

### 4 · Turn on gateway response caching

Give LiteLLM its Valkey connection (in the Step 9 wrapper) and enable caching. The `litellm` service changes in
`infra/compose/compose.yaml`:

```yaml
    command:
      - >
        export LITELLM_MASTER_KEY="$$(cat /run/secrets/litellm_master_key)"
        TEI_API_KEY="$$(cat /run/secrets/tei_api_key)"
        LITELLM_SALT_KEY="$$(cat /run/secrets/litellm_salt_key)"
        DATABASE_URL="postgresql://litellm:$$(cat /run/secrets/litellm_db_password)@litellm-db:5432/litellm"
        REDIS_URL="redis://litellm:$$(cat /run/secrets/valkey_litellm_password)@valkey:6379/0" &&
        exec litellm --config /app/config.yaml --host 0.0.0.0 --port 4000
    secrets: [litellm_master_key, tei_api_key, litellm_salt_key, litellm_db_password,
              valkey_litellm_password]
    depends_on:
      litellm-db: { condition: service_healthy }
      valkey:     { condition: service_healthy }
```

And in `infra/config/litellm/config.yaml`, under `litellm_settings:`:

```yaml
litellm_settings:
  # …existing settings…
  cache: true                   # exact-match response cache
  cache_params:
    type: redis                 # Valkey speaks the Redis protocol
    ttl: 600                    # 10 minutes: long enough for reruns, short enough to stay fresh
    namespace: "litellm.cache"
```

The connection string (user `litellm`, its password, host `valkey` on the Compose network) comes only from
`REDIS_URL`, so the config file still holds no secrets. Then measure:

```bash
just up                                                    # recreates litellm with the new settings
just with-secrets uv run --with openai python - <<'PY'
import os, time
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:4000/v1", api_key=os.environ["RAG_API_GATEWAY_KEY"])
msg = [{"role": "user", "content": "Define retrieval-augmented generation in one sentence."}]
for i in range(2):
    t = time.perf_counter()
    c.chat.completions.create(model="qwen-fast", messages=msg, max_tokens=60, temperature=0)
    print(f"call {i+1}: {time.perf_counter() - t:.2f}s")
t = time.perf_counter()
c.chat.completions.create(model="qwen-fast", messages=msg, max_tokens=60, temperature=0,
                          extra_body={"cache": {"no-cache": True}})   # force a fresh answer
print(f"no-cache: {time.perf_counter() - t:.2f}s")
PY
```

> **TIP · WHAT YOU SHOULD SEE**
> The first call takes about a second or more (the model runs). The second returns in a few milliseconds (cache
> hit). The no-cache call takes the full time again. Per-request controls like `no-cache` matter: evaluation runs
> that measure the model must bypass the cache, or they'd measure the cache instead.

You can also see the entry itself: `just kv-cli --scan --pattern 'litellm.cache:*'` lists the cache keys, and
`just kv-cli ttl <key>` shows the seconds left (at most 600). On a cache hit the gateway also returns the response
header `x-litellm-cache-key`.

> **WATCH OUT · CACHING AND RANDOMNESS**
> With `temperature > 0`, the same prompt normally gives different answers. A cache freezes the first one for the
> TTL. That's fine for factual Q&A, but wrong where variety is the point (brainstorming), so disable caching per
> request or per route there.

### 5 · A crash-safe job queue, and a lock

`scripts/kv_queue_demo.py` connects as `rag_app` and runs the whole story:

1. **ACL proof**: reading the gateway key `litellm.cache:anything` and `FLUSHALL` are both rejected.
2. **Queue setup**: creates the consumer group `rag:ingest:workers` on the stream `rag:ingest:jobs`
   (`MKSTREAM` creates the stream too; `BUSYGROUP` on re-runs is ignored) and adds three jobs
   (`doc-1`…`doc-3`), capping the stream at about 10,000 entries (`MAXLEN ~`).
3. **Worker A** reads one job with `XREADGROUP` and acknowledges it with `XACK`.
4. **Worker B** reads one job and "crashes" (never acknowledges): the pending count is 1.
5. **Recovery**: after 1.2 s, worker A runs `XAUTOCLAIM` for jobs idle longer than 1 s (in production ~60 s). For
   each reclaimed job it checks the delivery counter from `XPENDING`: at 3 or more it moves the job to the
   dead-letter stream `rag:ingest:dead`; otherwise it processes and acknowledges it ("delivery 2").
6. **Lock**: `SET rag:lock:doc-3 <random token> NX PX 30000` succeeds; a second attempt returns `None`; a Lua
   script deletes the key only if it still holds *our* token.
7. Prints the stream and dead-letter lengths.

```bash
just with-secrets uv run --with redis scripts/kv_queue_demo.py
```

Expected output (document numbers move along on re-runs, because earlier runs leave unread jobs in the stream):

```text
ACL   : read gateway cache key rejected -> NoPermissionError
ACL   : FLUSHALL rejected -> NoPermissionError
queue : worker-a did doc-1
queue : worker-b took doc-2 and crashed; pending = 1
queue : worker-a reclaimed doc-2 (delivery 2)
lock  : acquired rag:lock:doc-3 | second attempt: None
lock  : released safely
info  : stream length = 3 | dead-letter = 0
```

```text
                                   ┌──────────── worker A: XREADGROUP → XACK
  producer ── XADD job ──► stream rag:ingest:jobs
                                   └──────────── worker B crashes: job stays PENDING
                                                     │  XAUTOCLAIM after 60 s
                                                     ▼
                                          worker A takes it over
                                          (after 3 failed deliveries → dead-letter stream)

  At-least-once delivery: a job may run twice, so every job must be idempotent (safe to repeat).
```

*Figure 49 of the guide: a Streams job queue. Workers in a consumer group acknowledge finished jobs; a crashed
worker's job stays pending until another worker reclaims it; jobs failing too often go to a dead-letter stream.*

> **TIP · WHAT YOU JUST PROVED**
>
> - The app user can't read the gateway's keys or wipe the database.
> - A job taken by a crashed worker wasn't lost: it stayed pending and another worker reclaimed it.
> - The lock let only one worker in; a second attempt got `None`.
> - Only the owner, holding the matching token, could release the lock. Because the lock expires on its own, a
>   crashed holder can't block the document forever.

> **WATCH OUT · AT-LEAST-ONCE MEANS 'MAYBE TWICE'**
> The reclaimed job will run a second time if worker B actually finished but crashed before acknowledging. So every
> ingestion job must be idempotent, e.g. "upsert chunks for document X at content hash Y" rather than "append
> chunks". Step 31's pipeline is built on this rule.

The single demo run never reaches the dead-letter branch (a job is reclaimed once and then acknowledged). The test
`tests/test_valkey.py::test_crashed_job_is_reclaimed_and_poison_job_dead_lettered` drives a "poison" job through
three deliveries and into a dead-letter stream, so that path is proven too.

### 6 · Record the decision

```bash
just adr "Use Valkey for cache, queues and locks"
```

The result is `docs/adr/0015-use-valkey-for-cache-queues-and-locks.md` (status Accepted): Valkey 9.1.x,
digest-pinned, on `127.0.0.1:6379`; the ACL built in tmpfs from SOPS secrets with `default` off, `admin`,
`litellm` (all keys, no `@dangerous`) and `rag_app` (`rag:*` only, no `@dangerous`/`@admin`); 512 MB with
`volatile-lru`, AOF everysec + RDB; a 10-minute exact-match LiteLLM cache; Streams + consumer groups, `XAUTOCLAIM`,
a 3-try dead-letter stream, idempotent jobs and `SET NX PX` locks released by token. Alternatives: Redis Open
Source 8.x, separate cache and queue instances, RabbitMQ/Kafka/Redpanda, and a Postgres `SKIP LOCKED` queue. It is
listed in `docs/adr/README.md`.

```bash
git add -A
git commit -m "feat(valkey): ACL-secured Valkey with gateway caching, Streams job queue and locks"
git push -u origin feat/valkey
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Speed:** repeated LLM calls answer in milliseconds; cheap coordination for every service.
- **Crash-safe background work:** consumer groups, acknowledgements, reclaiming and dead-letter queues.
- **Correct concurrency:** expiring, token-checked locks keep one worker per document.
- **Least privilege:** per-user ACLs; dangerous commands blocked; the app sees only `rag:*`.
- **Safe memory behaviour:** `volatile-lru` evicts cache, never work.
- **Licence-clean and portable:** BSD-licensed, with the Redis protocol supported everywhere.

## Drawbacks and risks

- **RAM-bound:** everything lives in memory; size the cap and watch `used_memory`.
- **Not a system of record:** persistence limits loss, but critical data belongs in Postgres or object storage.
- **Cache correctness:** stale or wrongly shared answers are easy to create. TTLs and permission-aware keys are
  mandatory.
- **At-least-once delivery requires idempotent jobs;** forgetting this causes duplicates.
- **Lock subtleties:** single-instance locks are fine here; locks across several independent instances need more
  care.
- **Single instance:** no replication or failover locally (managed services or Sentinel/cluster in production).

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **Valkey** (our choice) | Linux Foundation fork of Redis, BSD licence | Redis-compatible needs with a permissive licence |
| **Redis Open Source 8** | The original, with query engine and vector sets built in | You want Redis's newest modules and accept its licences |
| **Dragonfly / KeyDB** | Redis-compatible, multi-threaded alternatives | Very high single-node throughput |
| **Memcached** | Simple, cache-only store | Pure caching with no data structures or persistence |
| **RabbitMQ / Kafka / Redpanda / NATS** | Dedicated messaging systems | Complex routing, replay, very high volume, or event streaming (Step 36) |
| **Managed (ElastiCache/MemoryDB, Memorystore, Azure Cache)** | Hosted Redis/Valkey | Cloud production (Step 37) |

The ADR also weighed two more options: **separate cache and queue instances** (clean eviction policies, but more
services and memory: the production pattern, not needed locally) and a **Postgres-based queue** with
`SELECT … FOR UPDATE SKIP LOCKED` (no new service, but it adds write load to the system of record).

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local platform needing cache + simple queues | One Valkey with `volatile-lru` and TTL discipline (this step) |
| Production with heavy cache and critical queues | Separate cache (`allkeys-lru`) and queue (`noeviction`) instances |
| Event streaming, replay, many consumers | Kafka/Redpanda (Step 36, CDC) |
| Semantic cache over embeddings | A vector-capable store (Redis 8 vector sets, Qdrant) with permission-aware keys (Step 33) |
| Multi-replica gateway rate limiting | LiteLLM coordinated through Redis/Valkey (Capstone) |

## Common mistakes

- Leaving the default user enabled with no password: anyone who can reach the port has full access.
- `allkeys-lru` on an instance that also holds queues, so jobs are evicted silently.
- Cache keys without permission scope (cross-user data leaks), or caching where randomness is wanted.
- Forgetting `XACK`, so the pending list grows forever, or never reclaiming pending jobs.
- Non-idempotent jobs under at-least-once delivery, causing duplicates.
- Locks without expiry, or releasing a lock you don't own (always compare the token).
- Passwords on the command line (`-a pass`). Use `REDISCLI_AUTH` or ACL files.
- Using `KEYS *` in production code. It blocks the server; use `SCAN`.

## Done when

- [ ] `REDIS_PASSWORD` is replaced by `VALKEY_ADMIN/LITELLM/APP_PASSWORD` (encrypted); `.env.example` and the
      generator are updated
- [ ] `valkey` runs pinned at 9.1.x; anonymous `ping` gets `NOAUTH`; `just kv-cli ping` gets `PONG`
- [ ] `info memory` shows maxmemory 512mb and `volatile-lru`; AOF is on
- [ ] LiteLLM's repeated call is a cache hit (milliseconds) and `no-cache` forces a fresh answer
- [ ] `kv_queue_demo.py` shows ACL rejections, a crashed job reclaimed, and a working lock
- [ ] ADR-0015 is merged through a PR

## Recap

> **RECAP**
> Valkey gives the platform a fast, least-privilege counter-top: an exact-match LLM cache in the gateway, a
> crash-safe job queue with retries and a dead-letter stream, token-checked expiring locks, and safe eviction that
> never throws away work. That completes Phase C, the data layer: Postgres (truth), Qdrant (vectors), OpenSearch
> (keywords + hybrid), S3 object storage (originals) and Valkey (speed). Phase D starts next: identity, with
> Keycloak in Step 16.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/config/valkey/valkey.conf` | Valkey settings: listen on 6379 in the Compose network, 512 MB cap with `volatile-lru`, RDB snapshots + AOF everysec in `/data`, slow-log and latency monitor. No users or passwords. |
| `infra/compose/compose.yaml` (changed) | New `valkey` service (9.1.2-alpine pinned by tag@digest, ACL file built from three secret files in a RAM-only tmpfs, runs as the unprivileged `valkey` user, only 127.0.0.1:6379 published, password-free NOAUTH/PONG healthcheck, 768 MB / 1 CPU limit), the `valkey-data` volume and three `valkey_*` secrets; the `litellm` wrapper now exports `REDIS_URL` with the `litellm` user's password and waits for a healthy `valkey`. |
| `infra/config/litellm/config.yaml` (changed) | Turns on LiteLLM's exact-match response cache (`type: redis`, `ttl: 600`, namespace `litellm.cache`). |
| `scripts/new-dev-secrets.sh` (changed) | Generates `VALKEY_ADMIN_PASSWORD`, `VALKEY_LITELLM_PASSWORD` and `VALKEY_APP_PASSWORD` instead of `REDIS_PASSWORD`. |
| `.env.example` (changed) | Lists the three `VALKEY_*` names (no values) instead of `REDIS_PASSWORD`. |
| `justfile` (changed) | `just kv-cli …`: `valkey-cli` as admin inside the container, password passed through `REDISCLI_AUTH`. |
| `scripts/kv_queue_demo.py` | The Streams job queue (consumer group, crash recovery, delivery counter, dead-letter), the token-checked lock and the ACL proof, as the `rag_app` user. |
| `tests/test_valkey.py` | Static checks of the service, ACL lines, config, gateway cache, secrets, recipe, script and ADR; live checks (opt-in) of NOAUTH for anonymous clients, the running settings and users, each user's limits, crash recovery and dead-lettering, the lock, and the demo itself. |
| `tests/test_gateway_governance.py` (changed) | The Step 10 check of the gateway's secrets and dependencies now expects the Valkey password and the `valkey` dependency. |
| `pyproject.toml`, `uv.lock` (changed) | `redis` (the Redis-protocol Python client, which works with Valkey) added to the dev group so mypy and the tests can check the demo. |
| `docs/adr/0015-use-valkey-for-cache-queues-and-locks.md` | ADR-0015, plus its row in `docs/adr/README.md`. |
| `docs/steps/step-15-valkey-cache-queues-locks.md` | This write-up, plus its row in `docs/steps/README.md`, the changelog entry and new glossary terms. |

## Notes for this repository

- **The image digest is real.** The guide leaves `<digest>`. The multi-arch index digest of
  `valkey/valkey:9.1.2-alpine` is `sha256:48332870af354a799964c0012ae1194a0bf2bf894eb508f945810596dc2d8d11`
  (`docker buildx imagetools inspect` output; `valkey-server --version` in the image prints `v=9.1.2`).
- **Valkey runs as the `valkey` user, not root.** The guide's command ends with
  `exec valkey-server /etc/valkey/valkey.conf --aclfile /run/valkey/users.acl`. Because the start-up command
  replaces the image's entrypoint, that would run the server as **root**. This repository adds
  `chown -R valkey:valkey /run/valkey` and starts through the image's own `docker-entrypoint.sh`, which hands over to
  the unprivileged `valkey` user (uid 999) with `setpriv` before running exactly the same `valkey-server …` command.
  The ACL file is still created with `umask 077` in the `0700` tmpfs, now owned by `valkey`. Verified: `ps` inside
  the container shows `valkey  1  valkey-server 0.0.0.0:6379`.
- **One comment moved in `valkey.conf`.** The guide writes `slowlog-log-slower-than 10000   # log commands slower
  than 10 ms`. Valkey's config parser does not support comments after a value (it would read `#`, `log`, … as extra
  arguments and refuse to start), so the comment sits on its own line above the setting. Everything else is the
  guide's file.
- **The demo prints the error type.** The guide's demo prints `str(e).split()[0]`, intended to show the server's
  `NOPERM` code. redis-py removes that code from the message and raises a `NoPermissionError` instead, so the line
  would print `No` or `User`. The script prints `type(e).__name__` (`NoPermissionError`). Other small changes, none
  affecting behaviour with the defaults: host and port can be overridden with `VALKEY_HOST` / `VALKEY_PORT`
  (default `127.0.0.1:6379`; from a container use `valkey`), a few `Any` annotations and one typed list satisfy
  strict mypy, the one-line `print(...); r.xack(...)` statements are split over two lines, and ruff formatted the
  code.
- **`redis` is a dev dependency.** The guide runs the demo with `uv run --with redis`, which still works. The
  workspace's dev group also gets `redis>=8.1.0` so that strict mypy can check the script and `tests/test_valkey.py`
  can run its live checks.
- **No real passwords are committed.** Only the three names appear, in `.env.example`; the generator creates real
  values per machine, encrypted by SOPS. Your existing `secrets/dev.enc.env` is updated with `just secrets-edit` as
  in section 1.
- **Faithful formatting fixes.** Line wraps from the PDF inside the Compose file (the `rag_app` ACL line, the
  `DATABASE_URL`, the `secrets:` list), the `kv-cli` recipe, the ADR table and the Python were rejoined and
  indentation reconstructed.
- **What was validated here (Linux container, Docker, no Mac, no SOPS key, no models).** The real
  `valkey/valkey:9.1.2-alpine` image (same digest) was started with this Compose file and random test passwords. The
  container became **healthy**; anonymous `valkey-cli ping` printed `NOAUTH Authentication required.`; the admin
  ping (via `REDISCLI_AUTH`, exactly as `just kv-cli` does it) printed `PONG`; `acl list` showed the four users with
  hashed passwords and `default off`; `info memory` showed `maxmemory_human:512.00M` and
  `maxmemory_policy:volatile-lru`; `appendonly` was `yes` and the AOF files appeared in `/data`; the ACL file had
  mode `0600` in a `0700` tmpfs. `kv_queue_demo.py` printed the expected output above on repeated runs. The
  LiteLLM image could not be pulled from `ghcr.io` here, so the gateway cache was checked with LiteLLM **1.104.0**
  (the same version as the image) installed from PyPI, using this `config.yaml` plus a throwaway mock chat model and
  `REDIS_URL` for the `litellm` user: call 1 took **0.98 s** (miss), call 2 **0.02 s** with header
  `x-litellm-cache-key: litellm.cache:65373e49…` (hit), the `no-cache` call was not served from the cache, the key
  had a TTL of 599 s, and the gateway logged no permission errors with the `-@dangerous` user. A separate
  throwaway Valkey with a 3 MB cap and `volatile-lru` evicted 301 TTL cache keys while all 50 entries of the job
  stream (a key without a TTL) survived. All the checks are automated in `tests/test_valkey.py` (18 tests passed live; without Valkey the
  live ones skip). The containers, volumes and the temporary LiteLLM install were removed afterwards.
