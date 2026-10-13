"""The retrieval-result cache (extension 01): the same search, by someone with the same access,
against the same index, returns the stored hits instead of searching again.

What it saves: the query embedding call, the store round trips, the reranker call (often the
slowest step) and any LLM query transformation. What makes it safe:

  * the key holds the person's ACCESS FINGERPRINT (tenant, classifications, groups): two people
    share an entry only if they may see exactly the same documents (Principal.fingerprint);
  * the key holds the question, the conversation, the metadata filter, k and the search settings;
  * the key holds the INDEX EPOCH: every ingestion, deletion or permission change starts a new
    epoch (IngestionPipeline and the lifecycle commands call invalidate()), so no result outlives
    a change to the documents. With Valkey the epoch is shared, so one change clears every replica.

It sits in front of search (rag-api's /v1/search, every architecture's retrieval); the answer
cache (Step 33's `cache` slot) sits in front of whole answers. They can be used together.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rag_core import filters as _filters
from rag_core.components.basics import words
from rag_core.registry import Container, register
from rag_core.types import Access, Chunk, Principal, ScoredChunk, Turn


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def search_key(principal: Principal, question: str, history: Sequence[Turn],
               filters: Mapping[str, Any] | None, k: int, version: str) -> str:  # fmt: skip
    """Same visible documents + same question (normalised) + same conversation + same filter +
    same k + same settings and index epoch (version) = same hits."""
    norm = " ".join(words(question))
    hist = "|".join(f"{t.role}:{t.text}" for t in history)
    raw = "\x00".join(
        [principal.fingerprint, norm, hist, _filters.canonical(filters), str(k), version]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def dump_hits(hits: Sequence[ScoredChunk], texts: Sequence[str]) -> str:
    def chunk(c: Chunk) -> dict[str, Any]:
        return {"id": c.id, "uri": c.document_uri, "index": c.index, "text": c.text, "tokens": c.token_count,
                "access": [c.access.classification, list(c.access.groups), c.access.tenant],
                "embed_text": c.embed_text, "parent_id": c.parent_id, "metadata": dict(c.metadata)}  # fmt: skip

    return json.dumps({"texts": list(texts), "hits": [{"chunk": chunk(h.chunk), "score": h.score, "scores": dict(h.scores)}
                                                      for h in hits]}, default=str)  # fmt: skip


def load_hits(raw: str) -> tuple[list[ScoredChunk], list[str]]:
    d = json.loads(raw)
    hits = []
    for h in d["hits"]:
        c = h["chunk"]
        cls, groups, tenant = c["access"]
        chunk = Chunk(id=c["id"], document_uri=c["uri"], index=c["index"], text=c["text"], token_count=c["tokens"],
                      access=Access(cls, tuple(groups), tenant), embed_text=c["embed_text"], parent_id=c["parent_id"],
                      metadata=c["metadata"])  # fmt: skip
        hits.append(ScoredChunk(chunk, float(h["score"]), h["scores"]))
    return hits, list(d["texts"])


class SearchCacheParams(_Strict):
    ttl_seconds: int = Field(default=600, ge=1)  # short: a cache is a speed-up, not a store
    max_items: int = Field(default=5000, ge=1)


class MemorySearchCache:
    """In this process (LRU + TTL). Invalidated by ingestion in THIS process only: in production,
    where a separate worker ingests, use `valkey` (or a short ttl_seconds)."""

    def __init__(self, p: SearchCacheParams) -> None:
        self.p = p
        self._data: OrderedDict[str, tuple[float, tuple[list[ScoredChunk], list[str]]]] = (
            OrderedDict()
        )
        self._lock = threading.Lock()
        self._epoch = 0
        self.hits = self.misses = 0

    def epoch(self) -> str:
        return str(self._epoch)

    def invalidate(self) -> None:
        with self._lock:
            self._epoch += 1
            self._data.clear()

    def get(self, key: str) -> tuple[list[ScoredChunk], list[str]] | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None or time.monotonic() - entry[0] > self.p.ttl_seconds:
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return list(entry[1][0]), list(entry[1][1])

    def put(self, key: str, hits: Sequence[ScoredChunk], texts: Sequence[str]) -> None:
        with self._lock:
            self._data[key] = (
                time.monotonic(),
                (list(hits), list(texts)),
            )  # frozen dataclasses: safe to share
            self._data.move_to_end(key)
            while len(self._data) > self.p.max_items:
                self._data.popitem(last=False)


@register("search_cache", "memory", params=SearchCacheParams,
          summary="retrieval results cached in process (LRU + TTL), keyed by access, query, filter and index epoch")  # fmt: skip
def _memory(p: SearchCacheParams, c: Container) -> MemorySearchCache:
    return MemorySearchCache(p)


class ValkeySearchCacheParams(SearchCacheParams):
    url_env: str | None = "RAG_VALKEY_URL"
    url_file: str | None = None  # /run/bao/valkey_url
    prefix: str = "rag:search:"


class ValkeySearchCache:
    """In Valkey: shared by every replica; the epoch is a counter there, so one ingestion
    anywhere invalidates every replica's entries at once (old keys stop matching and expire)."""

    def __init__(self, p: ValkeySearchCacheParams, client: Any = None) -> None:
        from rag_core.components.conversation import _valkey

        self.p = p
        self.r = client or _valkey(p.url_env, p.url_file)
        self.hits = self.misses = 0

    def epoch(self) -> str:
        return str(self.r.get(self.p.prefix + "epoch") or "0")

    def invalidate(self) -> None:
        self.r.incr(self.p.prefix + "epoch")

    def get(self, key: str) -> tuple[list[ScoredChunk], list[str]] | None:
        raw = self.r.get(self.p.prefix + key)
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return load_hits(raw)

    def put(self, key: str, hits: Sequence[ScoredChunk], texts: Sequence[str]) -> None:
        self.r.set(self.p.prefix + key, dump_hits(hits, texts), ex=self.p.ttl_seconds)


@register("search_cache", "valkey", status="mocked", params=ValkeySearchCacheParams, requires=("valkey",),
          summary="retrieval results cached in Valkey: shared by replicas, epoch invalidation on ingest")  # fmt: skip
def _valkey_cache(p: ValkeySearchCacheParams, c: Container) -> ValkeySearchCache:
    return ValkeySearchCache(p)


__all__ = ["MemorySearchCache", "ValkeySearchCache", "dump_hits", "load_hits", "search_key"]
