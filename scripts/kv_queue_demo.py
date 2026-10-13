#!/usr/bin/env python3
"""Streams job queue (consumer group, crash recovery, dead-letter) + distributed lock + ACL checks.

Run: just with-secrets uv run --with redis scripts/kv_queue_demo.py
"""

import os
import time
from collections.abc import Callable
from typing import Any

import redis

r = redis.Redis(
    host=os.environ.get("VALKEY_HOST", "127.0.0.1"),  # from a container: valkey
    port=int(os.environ.get("VALKEY_PORT", "6379")),
    username="rag_app",
    password=os.environ["VALKEY_APP_PASSWORD"],
    decode_responses=True,
)
STREAM, GROUP, DLQ, MAX_TRIES = "rag:ingest:jobs", "rag:ingest:workers", "rag:ingest:dead", 3

# --- ACL proof: the app user is boxed in ---
checks: list[tuple[str, Callable[[], object]]] = [
    ("read gateway cache key", lambda: r.get("litellm.cache:anything")),
    ("FLUSHALL", r.flushall),
]
for label, fn in checks:
    try:
        fn()
        print(f"ACL   : {label} ALLOWED (unexpected!)")
    # the server answers NOPERM, which redis-py raises as NoPermissionError
    except redis.ResponseError as e:
        print(f"ACL   : {label} rejected -> {type(e).__name__}")

# --- queue setup ---
try:
    r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
except redis.ResponseError as e:
    if "BUSYGROUP" not in str(e):
        raise
for doc in ("doc-1", "doc-2", "doc-3"):
    r.xadd(STREAM, {"document_id": doc, "action": "ingest"}, maxlen=10_000, approximate=True)

# worker A takes a job and acknowledges it
reply: Any = r.xreadgroup(GROUP, "worker-a", {STREAM: ">"}, count=1)
((_, [(mid, job)]),) = reply
print("queue : worker-a did", job["document_id"])
r.xack(STREAM, GROUP, mid)

# worker B takes a job and "crashes" (never acknowledges)
reply = r.xreadgroup(GROUP, "worker-b", {STREAM: ">"}, count=1)
((_, [(crashed, job)]),) = reply
pending: Any = r.xpending(STREAM, GROUP)
print("queue : worker-b took", job["document_id"], "and crashed; pending =", pending["pending"])

# worker A reclaims jobs idle longer than 1 s (in production: ~60 s)
time.sleep(1.2)
autoclaim: Any = r.xautoclaim(
    STREAM, GROUP, "worker-a", min_idle_time=1000, start_id="0-0", count=10
)
_, claimed, _ = autoclaim
for mid, job in claimed:
    entry: Any = r.xpending_range(STREAM, GROUP, min=mid, max=mid, count=1)
    tries = entry[0]["times_delivered"]
    if tries >= MAX_TRIES:
        r.xadd(DLQ, job)
        r.xack(STREAM, GROUP, mid)
        print("queue :", job["document_id"], "-> dead-letter after", tries, "tries")
    else:
        print("queue : worker-a reclaimed", job["document_id"], f"(delivery {tries})")
        r.xack(STREAM, GROUP, mid)

# --- distributed lock: only one worker may index a document at a time ---
key, token = "rag:lock:doc-3", os.urandom(8).hex()
release = r.register_script(
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)
if r.set(key, token, nx=True, px=30_000):  # NX: only if free · PX: auto-expires in 30 s
    print("lock  : acquired", key, "| second attempt:", r.set(key, "other", nx=True, px=30_000))
    release(keys=[key], args=[token])  # only the owner (matching token) can release
    print("lock  : released safely")
print("info  : stream length =", r.xlen(STREAM), "| dead-letter =", r.xlen(DLQ))
