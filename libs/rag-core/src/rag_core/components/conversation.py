"""Conversation memory and answer caches (Step 33).

Memory: the earlier turns of a conversation, so "and for part-timers?" can be understood.
Caches: the same question from someone with the same access, against the same index and the same
prompt, gets the stored answer instead of a new model call.

Both are keyed by WHO is asking. A session belongs to one person; a cached answer is only reused
for people who can see exactly the same documents (Principal.fingerprint, Step 30).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rag_core.components.basics import cosine, words
from rag_core.registry import Container, register
from rag_core.types import Answer, Citation, Principal, Turn


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def session_key(principal: Principal, session_id: str) -> str:
    # The person is part of the key: knowing someone's session id doesn't give you their history
    return f"{principal.tenant}:{principal.subject}:{session_id}"


# ================================================================ memory


class MemoryParams(_Strict):
    max_turns: int = Field(default=10, ge=2, le=100)  # user + assistant turns kept per session
    ttl_seconds: int = Field(
        default=86_400, ge=60
    )  # a conversation is forgotten after a day of silence


class InMemoryMemory:
    """Conversation turns in this process. Lost on restart; not shared between replicas."""

    def __init__(self, p: MemoryParams) -> None:
        self.p = p
        self._data: dict[str, tuple[float, deque[Turn]]] = {}
        self._lock = threading.Lock()

    def history(self, principal: Principal, session_id: str) -> tuple[Turn, ...]:
        key = session_key(principal, session_id)
        with self._lock:
            entry = self._data.get(key)
            if entry is None or time.monotonic() - entry[0] > self.p.ttl_seconds:
                self._data.pop(key, None)
                return ()
            return tuple(entry[1])

    def append(self, principal: Principal, session_id: str, *turns: Turn) -> None:
        key = session_key(principal, session_id)
        with self._lock:
            _, q = self._data.get(key, (0.0, deque(maxlen=self.p.max_turns)))
            q.extend(turns)
            self._data[key] = (time.monotonic(), q)

    def forget(self, principal: Principal, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_key(principal, session_id), None)


@register(
    "memory",
    "memory",
    params=MemoryParams,
    summary="conversation turns in process memory (dev, tests)",
)
def _mem(p: MemoryParams, c: Container) -> InMemoryMemory:
    return InMemoryMemory(p)


class ValkeyMemoryParams(MemoryParams):
    url_env: str | None = "RAG_VALKEY_URL"
    url_file: str | None = None  # /run/bao/valkey_url (OpenBao Agent, Step 31)
    prefix: str = "rag:memory:"


def _valkey(url_env: str | None, url_file: str | None) -> Any:
    import os

    import redis

    url = Path(url_file).read_text().strip() if url_file else os.environ.get(url_env or "", "")
    if not url:
        raise ValueError("no Valkey URL: set url_file or the url_env variable")
    return redis.Redis.from_url(url, decode_responses=True)


class ValkeyMemory:
    """Conversation turns in Valkey (Step 15): shared by every replica, expiring on their own."""

    def __init__(self, p: ValkeyMemoryParams, client: Any = None) -> None:
        self.p = p
        self.r = client or _valkey(p.url_env, p.url_file)

    def _key(self, principal: Principal, session_id: str) -> str:
        return (
            self.p.prefix + hashlib.sha256(session_key(principal, session_id).encode()).hexdigest()
        )

    def history(self, principal: Principal, session_id: str) -> tuple[Turn, ...]:
        raw = self.r.lrange(self._key(principal, session_id), 0, -1)
        return tuple(Turn(**json.loads(x)) for x in raw)

    def append(self, principal: Principal, session_id: str, *turns: Turn) -> None:
        key = self._key(principal, session_id)
        pipe = self.r.pipeline()
        for t in turns:
            pipe.rpush(key, json.dumps({"role": t.role, "text": t.text}))
        pipe.ltrim(key, -self.p.max_turns, -1)
        pipe.expire(key, self.p.ttl_seconds)
        pipe.execute()

    def forget(self, principal: Principal, session_id: str) -> None:
        self.r.delete(self._key(principal, session_id))


@register("memory", "valkey", status="mocked", params=ValkeyMemoryParams, requires=("valkey",),
          summary="conversation turns in Valkey: shared by replicas, expiring (TTL)")  # fmt: skip
def _vmem(p: ValkeyMemoryParams, c: Container) -> ValkeyMemory:
    return ValkeyMemory(p)


# ================================================================ caches


def cache_key(principal: Principal, question: str, history: Sequence[Turn], version: str) -> str:
    """Same visible documents + same question (normalised) + same conversation + same pipeline
    version (index epoch, prompt, model, settings) = same answer."""
    norm = " ".join(words(question))
    hist = "|".join(f"{t.role}:{t.text}" for t in history)
    raw = f"{principal.fingerprint}\x00{norm}\x00{hist}\x00{version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _dump(a: Answer) -> str:
    return json.dumps({"text": a.text, "abstained": a.abstained,
                       "citations": [asdict(c) for c in a.citations], "trace": dict(a.trace)},
                      default=str)  # fmt: skip


def _load(raw: str) -> Answer:
    d = json.loads(raw)
    return Answer(text=d["text"], abstained=d["abstained"],
                  citations=tuple(Citation(**c) for c in d["citations"]), trace=d.get("trace", {}))  # fmt: skip


class CacheParams(_Strict):
    ttl_seconds: int = Field(default=3600, ge=1)
    max_items: int = Field(default=10_000, ge=1)


class MemoryCache:
    """Exact-match answer cache in this process (LRU + TTL). `invalidate()` (called after every
    ingestion change) starts a new epoch, so no answer survives a change to the documents."""

    def __init__(self, p: CacheParams) -> None:
        self.p = p
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._epoch = 0
        self.hits = self.misses = 0

    def epoch(self) -> str:
        return str(self._epoch)

    def invalidate(self) -> None:
        with self._lock:
            self._epoch += 1
            self._data.clear()

    def get(
        self, key: str, principal: Principal | None = None, question: str = ""
    ) -> Answer | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None or time.monotonic() - entry[0] > self.p.ttl_seconds:
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return _load(entry[1])

    def put(
        self, key: str, answer: Answer, principal: Principal | None = None, question: str = ""
    ) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), _dump(answer))
            self._data.move_to_end(key)
            while len(self._data) > self.p.max_items:
                self._data.popitem(last=False)


@register(
    "cache", "memory", params=CacheParams, summary="exact-match answer cache in process (LRU + TTL)"
)
def _mcache(p: CacheParams, c: Container) -> MemoryCache:
    return MemoryCache(p)


class ValkeyCacheParams(CacheParams):
    url_env: str | None = "RAG_VALKEY_URL"
    url_file: str | None = None
    prefix: str = "rag:answer:"


class ValkeyCache:
    """Exact-match answer cache in Valkey: shared by replicas. The epoch is a counter in Valkey, so
    one ingestion change invalidates every replica's cache at once."""

    def __init__(self, p: ValkeyCacheParams, client: Any = None) -> None:
        self.p = p
        self.r = client or _valkey(p.url_env, p.url_file)
        self.hits = self.misses = 0

    def epoch(self) -> str:
        return str(self.r.get(self.p.prefix + "epoch") or "0")

    def invalidate(self) -> None:
        self.r.incr(self.p.prefix + "epoch")  # old keys simply stop matching and expire

    def get(
        self, key: str, principal: Principal | None = None, question: str = ""
    ) -> Answer | None:
        raw = self.r.get(self.p.prefix + key)
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return _load(raw)

    def put(
        self, key: str, answer: Answer, principal: Principal | None = None, question: str = ""
    ) -> None:
        self.r.set(self.p.prefix + key, _dump(answer), ex=self.p.ttl_seconds)


@register("cache", "valkey", status="mocked", params=ValkeyCacheParams, requires=("valkey",),
          summary="exact-match answer cache in Valkey: shared by replicas, epoch invalidation")  # fmt: skip
def _vcache(p: ValkeyCacheParams, c: Container) -> ValkeyCache:
    return ValkeyCache(p)


class SemanticCacheParams(CacheParams):
    threshold: float = Field(
        default=0.95, gt=0.5, le=1.0
    )  # how similar a question must be to reuse
    max_items: int = Field(default=2000, ge=1)


class SemanticCache:
    """Reuses an answer for a question that MEANS nearly the same ("how many leave days?" ≈ "how
    much annual leave do I get?"). Only among people with the same access, same epoch. Risky:
    "primary carer" and "secondary carer" questions can look 96% alike. Measure before enabling."""

    def __init__(self, p: SemanticCacheParams, embedder: Any) -> None:
        self.p, self.emb = p, embedder
        self.exact = MemoryCache(p)
        self._rows: list[
            tuple[str, str, list[float], str]
        ] = []  # fingerprint, epoch, vector, answer
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def epoch(self) -> str:
        return self.exact.epoch()

    def invalidate(self) -> None:
        with self._lock:
            self.exact.invalidate()
            self._rows.clear()

    def get(
        self, key: str, principal: Principal | None = None, question: str = ""
    ) -> Answer | None:
        if (a := self.exact.get(key)) is not None:
            self.hits += 1
            return a
        if principal is None or not question:
            self.misses += 1
            return None
        v = self.emb.embed_query(question)
        best, best_sim = None, 0.0
        with self._lock:
            for fp, ep, vec, raw in self._rows:
                if fp == principal.fingerprint and ep == self.epoch():
                    sim = cosine(v, vec)
                    if sim > best_sim:
                        best, best_sim = raw, sim
        if best is not None and best_sim >= self.p.threshold:
            self.hits += 1
            a = _load(best)
            return Answer(
                a.text,
                a.citations,
                a.abstained,
                trace={**a.trace, "semantic_similarity": round(best_sim, 4)},
            )
        self.misses += 1
        return None

    def put(
        self, key: str, answer: Answer, principal: Principal | None = None, question: str = ""
    ) -> None:
        self.exact.put(key, answer)
        if principal is None or not question:
            return
        v = self.emb.embed_query(question)
        with self._lock:
            self._rows.append((principal.fingerprint, self.epoch(), v, _dump(answer)))
            del self._rows[: max(0, len(self._rows) - self.p.max_items)]


@register("cache", "semantic", params=SemanticCacheParams,
          summary="reuse answers to near-identical questions (embedding similarity), per access set")  # fmt: skip
def _scache(p: SemanticCacheParams, c: Container) -> SemanticCache:
    return SemanticCache(p, c.get("embedder"))
