"""Built-in components every profile can use (Step 30): token counters, an LLM client for the
gateway, a deterministic offline embedder and LLM, and in-memory stores.

The in-memory and fake components aren't toys: they make every pipeline runnable and testable on
a laptop with nothing else running, and they are the reference the real adapters are compared to.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from rag_core import filters as _filters
from rag_core.registry import Container, register
from rag_core.similarity import Metric, similarity
from rag_core.types import Access, Chunk, Principal, ScoredChunk

WORD = re.compile(r"[\w]+(?:['\u2019][\w]+)?", re.UNICODE)  # keeps "don't" whole


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text)]


def matches_filters(chunk: Chunk, filters: Mapping[str, object] | None) -> bool:
    """Does the chunk satisfy a metadata filter (rag_core.filters)? The Step 32 forms still work:
    {key: value} is "equal", {key: [a, b]} is "any of"."""
    return _filters.matcher(filters)(chunk)


# ---------------------------------------------------------------- token counters


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApproxParams(_Strict):
    chars_per_token: float = Field(4.0, gt=0)


class ApproxTokenCounter:
    """Good enough for budgets: ~4 characters per token for English. Never under-counts words."""

    def __init__(self, chars_per_token: float = 4.0) -> None:
        self.chars_per_token = chars_per_token

    def count(self, text: str) -> int:
        return max(len(words(text)), math.ceil(len(text) / self.chars_per_token)) if text else 0


@register(
    "token_counter",
    "approx",
    params=ApproxParams,
    summary="characters/4, at least one per word; no model files",
)
def _approx(p: ApproxParams, c: Container) -> ApproxTokenCounter:
    return ApproxTokenCounter(p.chars_per_token)


class HfTokenizerParams(_Strict):
    tokenizer_file: str  # the model's tokenizer.json, downloaded with the model (Step 8)


class HfTokenCounter:
    def __init__(self, path: str) -> None:
        from tokenizers import Tokenizer  # optional dependency: rag-core[tokenizers]

        self._tok = Tokenizer.from_file(path)

    def count(self, text: str) -> int:
        return len(self._tok.encode(text, add_special_tokens=False).ids)


@register("token_counter", "hf-tokenizer", params=HfTokenizerParams, status="reference", requires=("tokenizers",),
          summary="exact counts with the embedding model's own tokenizer.json")  # fmt: skip
def _hf(p: HfTokenizerParams, c: Container) -> HfTokenCounter:
    return HfTokenCounter(p.tokenizer_file)


# ---------------------------------------------------------------- LLMs


class GatewayParams(_Strict):
    model: str = "qwen-fast"  # a LiteLLM model alias (Step 9)
    base_url: str = "http://litellm:4000/v1"
    api_key_env: str = "LLM_GATEWAY_KEY"  # the NAME of the variable, never the key
    api_key_file: str | None = None  # or a file OpenBao Agent writes: /run/bao/rag_api_gateway_key
    timeout: float = 120.0
    max_retries: int = Field(1, ge=0)


class GatewayLLM:
    """Chat completions through the LiteLLM gateway (OpenAI-compatible): budgets, fallbacks and
    logging (Steps 9-10) apply to every call a pipeline makes."""

    def __init__(self, model: str, base_url: str, api_key: SecretStr, timeout: float = 120.0,
                 max_retries: int = 1, client: httpx.Client | None = None) -> None:  # fmt: skip
        self.model = model
        self._http = client or httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=timeout)
        self._key = api_key
        self._retries = max_retries

    def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 512, temperature: float = 0.0,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, **(extra or {})}  # fmt: skip
        last: Exception | None = None
        for _ in range(self._retries + 1):
            try:
                r = self._http.post("chat/completions", json=body,
                                    headers={"Authorization": f"Bearer {self._key.get_secret_value()}"})  # fmt: skip
                if r.status_code >= 500 or r.status_code == 429:
                    last = httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                    continue
                r.raise_for_status()
                data: dict[str, Any] = r.json()
                return data
            except httpx.TransportError as e:
                last = e
        raise RuntimeError(f"gateway call failed after {self._retries + 1} attempt(s): {last}")

    def complete(
        self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0
    ) -> str:
        data = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                         max_tokens=max_tokens, temperature=temperature)  # fmt: skip
        return str(data["choices"][0]["message"]["content"] or "")

    def complete_with_usage(self, system: str, user: str, *, max_tokens: int = 512,
                            temperature: float = 0.0) -> tuple[str, dict[str, int]]:  # fmt: skip
        """The reply and the token counts the gateway reported (for budgets, audit and cost)."""
        data = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                         max_tokens=max_tokens, temperature=temperature)  # fmt: skip
        usage = {k: int(v) for k, v in (data.get("usage") or {}).items() if isinstance(v, int)}
        return str(data["choices"][0]["message"]["content"] or ""), usage

    def stream(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0,
               usage: dict[str, int] | None = None) -> Iterator[str]:  # fmt: skip
        """Token deltas as the model produces them (server-sent events). `usage`, if given, is
        filled with the token counts when the stream ends. No retries once text has been sent."""
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}  # fmt: skip
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}"}
        with self._http.stream("POST", "chat/completions", json=body, headers=headers) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                event = json.loads(payload)
                if usage is not None and event.get("usage"):
                    usage.update(
                        {k: int(v) for k, v in event["usage"].items() if isinstance(v, int)}
                    )
                for choice in event.get("choices") or []:
                    if delta := (choice.get("delta") or {}).get("content"):
                        yield str(delta)


class FileSecret(SecretStr):
    """A secret read from a file on EVERY use, so a key rotated by OpenBao Agent (Step 28) is
    picked up without a restart. Never stored in config, never in an environment variable."""

    def __init__(self, path: str) -> None:
        super().__init__("")
        self._path = path
        self.get_secret_value()  # fail at start-up (missing file), not on the first request

    def get_secret_value(self) -> str:
        return Path(self._path).read_text().strip()


def gateway_key(env: str, file: str | None) -> SecretStr:
    """The gateway key: from a file when one is configured (containers), else an env var (dev)."""
    return FileSecret(file) if file else SecretStr(os.environ.get(env, ""))


@register("llm", "gateway", params=GatewayParams, status="mocked",
          summary="any model behind the LiteLLM gateway (OpenAI-compatible chat completions)")  # fmt: skip
def _gateway(p: GatewayParams, c: Container) -> GatewayLLM:
    return GatewayLLM(
        p.model, p.base_url, gateway_key(p.api_key_env, p.api_key_file), p.timeout, p.max_retries
    )


class ScriptedParams(_Strict):
    replies: dict[str, str] = Field(default_factory=dict)  # substring of the prompt -> reply
    default: str = ""


class ScriptedLLM:
    """A predictable LLM for tests and offline demos: answers by matching parts of the prompt."""

    model = "scripted"

    def __init__(self, replies: dict[str, str] | None = None, default: str = "",
                 fn: Callable[[str, str], str] | None = None) -> None:  # fmt: skip
        self.replies, self.default, self.fn = dict(replies or {}), default, fn
        self.calls: list[tuple[str, str]] = []

    def complete(
        self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0
    ) -> str:
        self.calls.append((system, user))
        if self.fn is not None:
            return self.fn(system, user)
        for needle, reply in self.replies.items():
            if needle in user or needle in system:
                return reply
        return self.default

    def complete_with_usage(self, system: str, user: str, *, max_tokens: int = 512,
                            temperature: float = 0.0) -> tuple[str, dict[str, int]]:  # fmt: skip
        """The reply plus word counts standing in for token counts (Step 33's usage records)."""
        reply = self.complete(system, user, max_tokens=max_tokens, temperature=temperature)
        return reply, {"prompt_tokens": len(words(system)) + len(words(user)),
                       "completion_tokens": len(words(reply))}  # fmt: skip

    def stream(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0,
               usage: dict[str, int] | None = None) -> Iterator[str]:  # fmt: skip
        """The reply word by word, like a streaming model; `usage` is filled at the end."""
        reply, counts = self.complete_with_usage(system, user, max_tokens=max_tokens,
                                                 temperature=temperature)  # fmt: skip
        yield from re.findall(r"\S+\s*|\s+", reply)
        if usage is not None:
            usage.update(counts)


@register(
    "llm", "scripted", params=ScriptedParams, summary="canned replies for tests and offline demos"
)
def _scripted(p: ScriptedParams, c: Container) -> ScriptedLLM:
    return ScriptedLLM(p.replies, p.default)


# ---------------------------------------------------------------- embedders


class HashingParams(_Strict):
    dimensions: int = Field(256, ge=16, le=4096)


class HashingEmbedder:
    """Deterministic, offline "embeddings": hashed words and word pairs, L2-normalised.
    Captures word overlap, not meaning. For tests, demos and CI, never for production quality."""

    model = "hashing-v1"

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dimensions
        toks = words(text)
        feats = toks + [f"{a} {b}" for a, b in itertools.pairwise(toks)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dimensions] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@register(
    "embedder",
    "hashing",
    params=HashingParams,
    summary="offline, deterministic word-hash vectors (tests, CI, demos)",
)
def _hashing(p: HashingParams, c: Container) -> HashingEmbedder:
    return HashingEmbedder(p.dimensions)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------- in-memory stores


class MemoryVectorParams(_Strict):
    metric: Metric = "cosine"  # cosine | dot | l2 | l1 (extension 01): exact, so every metric works


class MemoryVectorStore:
    """Exact (brute-force) search with any metric. Fine to ~50k chunks; the reference every real
    store is compared to (the same scores, the same filters, the same permissions)."""

    def __init__(self, metric: Metric = "cosine") -> None:
        self.metric: Metric = metric
        self._rows: dict[str, tuple[Chunk, list[float]]] = {}
        self._lock = threading.Lock()

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        with self._lock:
            for ch, v in zip(chunks, vectors, strict=True):
                self._rows[ch.id] = (ch, list(v))

    def delete_document(self, document_uri: str) -> int:
        with self._lock:
            ids = [i for i, (ch, _) in self._rows.items() if ch.document_uri == document_uri]
            for i in ids:
                del self._rows[i]
        return len(ids)

    def search(self, vector: Sequence[float], principal: Principal, k: int,
               filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        wanted = _filters.matcher(filters)  # validated once, before any row is looked at
        hits = [ScoredChunk(ch, s, {"dense": s}) for ch, v in list(self._rows.values())
                if ch.access.allows(principal) and wanted(ch)
                for s in [similarity(self.metric, vector, v)]]  # fmt: skip
        return sorted(hits, key=lambda h: -h.score)[:k]

    def update_access(self, document_uri: str, access: Access) -> int:
        """Step 36: new permissions on every chunk of the document, in place (no re-embedding)."""
        with self._lock:
            ids = [i for i, (ch, _) in self._rows.items() if ch.document_uri == document_uri]
            for i in ids:
                ch, v = self._rows[i]
                self._rows[i] = (replace(ch, access=access), v)
        return len(ids)

    def count(self) -> int:
        return len(self._rows)

    def get(self, chunk_id: str) -> Chunk | None:
        row = self._rows.get(chunk_id)
        return row[0] if row else None


@register("vector_store", "memory", params=MemoryVectorParams,
          summary="exact search in memory, any metric (cosine/dot/l2/l1); dev, tests, small corpora")  # fmt: skip
def _memvec(p: MemoryVectorParams, c: Container) -> MemoryVectorStore:
    return MemoryVectorStore(p.metric)


class BM25Params(_Strict):
    k1: float = 1.5
    b: float = 0.75


class MemoryKeywordIndex:
    """Okapi BM25, the classic keyword ranking (what OpenSearch and Elasticsearch use by default)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._docs: dict[str, tuple[Chunk, Counter[str], int]] = {}
        self._df: defaultdict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def index(self, chunks: Sequence[Chunk]) -> None:
        with self._lock:
            for ch in chunks:
                self._remove(ch.id)
                tf = Counter(words(ch.indexed_text))
                self._docs[ch.id] = (ch, tf, sum(tf.values()))
                for term in tf:
                    self._df[term] += 1

    def _remove(self, chunk_id: str) -> None:
        old = self._docs.pop(chunk_id, None)
        if old:
            for term in old[1]:
                self._df[term] -= 1

    def delete_document(self, document_uri: str) -> int:
        with self._lock:
            ids = [i for i, (ch, _, _) in self._docs.items() if ch.document_uri == document_uri]
            for i in ids:
                self._remove(i)
        return len(ids)

    def update_access(self, document_uri: str, access: Access) -> int:
        """Step 36: new permissions on every chunk of the document, in place (no re-indexing)."""
        with self._lock:
            ids = [i for i, (ch, _, _) in self._docs.items() if ch.document_uri == document_uri]
            for i in ids:
                ch, tf, length = self._docs[i]
                self._docs[i] = (replace(ch, access=access), tf, length)
        return len(ids)

    def search_all(self, text: str, k: int) -> list[ScoredChunk]:
        """Every tenant and group: for the erasure job only (Step 36), never for people."""
        return self._rank(text, k, lambda ch: True)

    def search(self, text: str, principal: Principal, k: int,
               filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        wanted = _filters.matcher(filters)
        return self._rank(text, k, lambda ch: ch.access.allows(principal) and wanted(ch))

    def _rank(self, text: str, k: int, visible: Callable[[Chunk], bool]) -> list[ScoredChunk]:
        n = len(self._docs) or 1
        avg = sum(length for _, _, length in self._docs.values()) / n
        terms = set(words(text))
        hits = []
        for ch, tf, length in list(self._docs.values()):
            if not visible(ch):
                continue
            score = 0.0
            for t in terms:
                if t in tf:
                    idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                    score += (
                        idf
                        * tf[t]
                        * (self.k1 + 1)
                        / (tf[t] + self.k1 * (1 - self.b + self.b * length / avg))
                    )
            if score > 0:
                hits.append(ScoredChunk(ch, score, {"sparse": score}))
        return sorted(hits, key=lambda h: -h.score)[:k]


@register(
    "keyword_index",
    "memory-bm25",
    params=BM25Params,
    summary="BM25 keyword ranking in memory (dev, tests)",
)
def _membm25(p: BM25Params, c: Container) -> MemoryKeywordIndex:
    return MemoryKeywordIndex(p.k1, p.b)
