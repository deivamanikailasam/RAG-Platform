"""Enrichers and embedders (Step 31).

Enrichers decide WHAT is embedded for a chunk ("embed_text"); the chunk's own text, the part that
is shown and cited, never changes. A chunk saying "It is 18 weeks." embeds far better as
"Leave policy > Parental leave: It is 18 weeks."
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from rag_core.components.basics import gateway_key
from rag_core.registry import Container, register, spec
from rag_core.types import Chunk, Document

log = logging.getLogger("rag_core.enrichment")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- enrichers


class HeaderParams(_Strict):
    template: str = "{header}\n\n{text}"


class ContextHeaderEnricher:
    """Prepends "Title > Section > Subsection" (the title once, even if it's also the top heading).
    Free, and usually the best first improvement."""

    def __init__(self, template: str) -> None:
        self.template = template

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]:
        out = []
        for c in chunks:
            parts = [document.title] + [
                s for s in str(c.metadata.get("section") or "").split(" > ") if s
            ]
            header = " > ".join(p for i, p in enumerate(parts) if p and (i == 0 or p != parts[0]))
            out.append(replace(c, embed_text=self.template.format(header=header, title=document.title, text=c.text,
                                            section=c.metadata.get("section") or "")))  # fmt: skip
        return out


@register(
    "enricher",
    "context-header",
    params=HeaderParams,
    summary='embeds "Title > Section" with each chunk (free, strong)',
)
def _header(p: HeaderParams, c: Container) -> ContextHeaderEnricher:
    return ContextHeaderEnricher(p.template)


CONTEXT_PROMPT = """<document>
{document}
</document>
Here is a chunk from that document:
<chunk>
{chunk}
</chunk>
Write one or two short sentences that situate this chunk within the overall document, to improve
search retrieval of the chunk. Answer only with those sentences."""


class LlmContextParams(_Strict):
    max_document_chars: int = Field(24000, ge=1000)  # a long document is truncated around the chunk


class LlmContextEnricher:
    """ "Contextual retrieval" (Anthropic, 2024): an LLM writes a short context for each chunk from
    the whole document; it's prepended before embedding and keyword indexing. Measurably fewer
    failed retrievals, at the cost of one LLM call per chunk at ingestion (cache-friendly)."""

    def __init__(self, llm: Any, max_chars: int) -> None:
        self.llm, self.max_chars = llm, max_chars

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]:
        full = document.text
        out = []
        for c in chunks:
            doc_text = full
            if len(full) > self.max_chars:
                pos = max(0, full.find(c.text[:80]))
                start = max(0, min(pos - self.max_chars // 2, len(full) - self.max_chars))
                doc_text = full[start : start + self.max_chars]
            context = self.llm.complete("You write retrieval context for document chunks.",
                                CONTEXT_PROMPT.format(document=doc_text, chunk=c.text), max_tokens=120).strip()  # fmt: skip
            out.append(replace(c, embed_text=f"{context}\n\n{c.embed_text or c.text}",
                            metadata={**c.metadata, "context": context}))  # fmt: skip
        return out


@register("enricher", "llm-context", params=LlmContextParams,
            summary="contextual retrieval: an LLM situates each chunk in its document (one call per chunk)")  # fmt: skip
def _llm_context(p: LlmContextParams, c: Container) -> LlmContextEnricher:
    return LlmContextEnricher(c.get("llm"), p.max_document_chars)


QUESTIONS_PROMPT = """Write {n} different questions a user might ask that this text answers.
One per line, no numbering.

{chunk}"""


class QuestionsParams(_Strict):
    n: int = Field(3, ge=1, le=10)


class QuestionsEnricher:
    """Hypothetical questions ("HyPE"): users ask questions, documents state facts; embedding the
    questions a chunk answers brings the two closer. One LLM call per chunk."""

    def __init__(self, llm: Any, n: int) -> None:
        self.llm, self.n = llm, n

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]:
        out = []
        for c in chunks:
            qs = [q.strip() for q in self.llm.complete("You write search questions.",
                    QUESTIONS_PROMPT.format(n=self.n, chunk=c.text), max_tokens=200).splitlines() if q.strip()][: self.n]  # fmt: skip
            out.append(replace(c, embed_text=(c.embed_text or c.text) + "\n\n" + "\n".join(qs),
                            metadata={**c.metadata, "questions": qs}))  # fmt: skip
        return out


@register("enricher", "questions", params=QuestionsParams,
            summary="adds the questions each chunk answers to what is embedded (one LLM call per chunk)")  # fmt: skip
def _questions(p: QuestionsParams, c: Container) -> QuestionsEnricher:
    return QuestionsEnricher(c.get("llm"), p.n)


# ---------------------------------------------------------------- embedders


class GatewayEmbedderParams(_Strict):
    model: str = "embedder"  # the LiteLLM alias (Step 9): Qwen3-Embedding-0.6B on TEI (Step 8)
    dimensions: int = Field(1024, ge=16)
    base_url: str = "http://litellm:4000/v1"
    api_key_env: str = "LLM_GATEWAY_KEY"
    api_key_file: str | None = None  # /run/bao/rag_api_gateway_key in containers (Step 32)
    batch_size: int = Field(32, ge=1, le=2048)
    # Asymmetric models embed questions differently from documents (Step 8). Step 24's registered
    # prompt "query-instruction" holds the production value; this is the fallback.
    query_instruction: str = (
        "Instruct: Given a question, retrieve passages that answer it\nQuery: {query}"
    )
    # Or take it from the prompt registry (Step 24), so search and ingestion use the reviewed,
    # versioned instruction that rag-api records in its audit events.
    query_prompt: str | None = None  # e.g. "query-instruction"
    prompts_dir: str = "prompts"
    prompt_label: str = "production"  # staging sets RAG__EMBEDDER__INNER__PROMPT_LABEL=staging
    timeout: float = 120.0
    # extension 02: ask the API for `dimensions` (Matryoshka models behind the gateway: OpenAI
    # text-embedding-3, Gemini, Voyage, Jina v3, Cohere v4): the cut happens server-side
    request_dimensions: bool = False


class GatewayEmbedder:
    """Embeddings through the gateway (OpenAI-compatible /embeddings), batched, with a check that
    the server returned the dimensions the index was built for."""

    def __init__(
        self, p: GatewayEmbedderParams, api_key: SecretStr, client: httpx.Client | None = None
    ) -> None:
        self.p, self.model, self.dimensions = p, p.model, p.dimensions
        self._key = api_key
        self._http = client or httpx.Client(
            base_url=p.base_url.rstrip("/") + "/", timeout=p.timeout
        )
        self.prompt_refs: list[str] = []  # which registered prompt versions shape the vectors
        self._render: Callable[[str], str] | None = None
        if p.query_prompt:
            from rag_common.prompts import PromptError, Registry, render

            try:
                version, sha = Registry.load(Path(p.prompts_dir)).get(
                    p.query_prompt, label=p.prompt_label
                )
            except PromptError as e:
                raise ValueError(str(e)) from e  # reported as "could not start" with the slot name
            self._render = lambda q: render(version, sha, {"query": q}).text or ""
            self.prompt_refs = [version.ref]

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.p.batch_size):
            batch = list(texts[i : i + self.p.batch_size])
            r = self._http.post(
                "embeddings",
                json={"model": self.model, "input": batch}
                | ({"dimensions": self.dimensions} if self.p.request_dimensions else {}),
                headers={"Authorization": f"Bearer {self._key.get_secret_value()}"},
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            for d in data:
                if len(d["embedding"]) != self.dimensions:
                    raise ValueError(f"{self.model} returned {len(d['embedding'])} dimensions, the index expects "
                                f"{self.dimensions}: wrong model behind the alias? (re-index needed, Step 36)")  # fmt: skip
                out.append(d["embedding"])
        return out

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        if self._render is not None:
            return self._embed([self._render(text)])[0]
        # plain substitution, not str.format: a question containing { or } must not break it
        return self._embed([self.p.query_instruction.replace("{query}", text)])[0]


@register("embedder", "gateway", params=GatewayEmbedderParams, status="mocked",
            summary="any embedding model behind the LiteLLM gateway, batched, dimension-checked")  # fmt: skip
def _gw_embedder(p: GatewayEmbedderParams, c: Container) -> GatewayEmbedder:
    return GatewayEmbedder(p, gateway_key(p.api_key_env, p.api_key_file))


class CachedParams(_Strict):
    inner: dict[str, Any]  # the real embedder: {use: gateway, …}
    max_items: int = Field(100_000, ge=1)
    # extension 04: a second level shared by every replica and surviving restarts: re-ingesting
    # after a deploy, or a new pod answering popular questions, embeds nothing it has seen before
    store: Literal["memory", "valkey"] = "memory"
    url_env: str | None = "RAG_VALKEY_URL"
    url_file: str | None = None  # /run/bao/valkey_url (OpenBao Agent)
    ttl_seconds: int = Field(
        30 * 86_400, ge=60
    )  # unused vectors expire (a model change orphans them)
    namespace: str = "rag:emb"


class ValkeyVectors:
    """Vectors in Valkey as compact JSON, keyed by model + text hash, with a TTL. MGET/pipelined
    SETs, so a batch of 64 chunks costs two round trips, not 128."""

    def __init__(self, client: Any, namespace: str, ttl_seconds: int) -> None:
        self.r, self.ns, self.ttl = client, namespace, ttl_seconds

    def get_many(self, keys: Sequence[str]) -> list[list[float] | None]:
        if not keys:
            return []
        raw = self.r.mget([f"{self.ns}:{k}" for k in keys])
        return [json.loads(v) if v else None for v in raw]

    def put_many(self, items: Sequence[tuple[str, list[float]]]) -> None:
        if not items:
            return
        pipe = self.r.pipeline()
        for k, v in items:
            pipe.set(
                f"{self.ns}:{k}",
                json.dumps([round(x, 7) for x in v], separators=(",", ":")),
                ex=self.ttl,
            )
        pipe.execute()


class CachedEmbedder:
    """Never embed the same text twice with the same model: re-ingesting an unchanged chunk, or
    a popular query, costs nothing. Keyed by (model, sha256(text)). Extension 04: with
    `store: valkey`, a shared second level behind the in-process LRU."""

    def __init__(self, inner: Any, max_items: int, shared: ValkeyVectors | None = None) -> None:
        self.inner, self.model, self.dimensions = inner, inner.model, inner.dimensions
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._max = max_items
        self._lock = threading.Lock()
        self.shared = shared
        self.hits = self.misses = self.shared_hits = 0

    def _key(self, kind: str, text: str) -> str:
        return hashlib.sha256(f"{self.model}\x00{kind}\x00{text}".encode()).hexdigest()

    def _get(self, key: str) -> list[float] | None:
        with self._lock:
            v = self._cache.get(key)
            if v is not None:
                self._cache.move_to_end(key)
            return v

    def _put(self, key: str, v: list[float]) -> None:
        with self._lock:
            self._cache[key] = v
            if len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def _lookup(self, keys: list[str]) -> list[list[float] | None]:
        found = [self._get(k) for k in keys]
        missing = [i for i, v in enumerate(found) if v is None]
        if self.shared is not None and missing:
            try:
                remote = self.shared.get_many([keys[i] for i in missing])
            except Exception as e:  # the shared cache is an optimisation: never fail on it
                log.warning("embedding cache (valkey) unavailable: %s", e)
                remote = [None] * len(missing)
            for i, v in zip(missing, remote, strict=True):
                if v is not None:
                    found[i] = v
                    self._put(keys[i], v)
                    self.shared_hits += 1
        return found

    def _store(self, items: list[tuple[str, list[float]]]) -> None:
        for k, v in items:
            self._put(k, v)
        if self.shared is not None:
            try:
                self.shared.put_many(items)
            except Exception as e:
                log.warning("embedding cache (valkey) unavailable: %s", e)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        keys = [self._key("d", t) for t in texts]
        cached = self._lookup(keys)
        missing = [i for i, v in enumerate(cached) if v is None]
        self.hits += len(texts) - len(missing)
        self.misses += len(missing)
        if missing:
            fresh = self.inner.embed_documents([texts[i] for i in missing])
            for i, v in zip(missing, fresh, strict=True):
                cached[i] = v
            self._store([(keys[i], cached[i]) for i in missing])  # type: ignore[misc]
        return [v for v in cached if v is not None]

    def embed_query(self, text: str) -> list[float]:
        key = self._key("q", text)
        v = self._lookup([key])[0]
        if v is None:
            self.misses += 1
            v = self.inner.embed_query(text)
            self._store([(key, v)])
        else:
            self.hits += 1
        return v


def _inner_embedder(raw: dict[str, Any], c: Container) -> Any:
    inner_spec = dict(raw)
    s = spec("embedder", str(inner_spec.pop("use")))
    return s.factory(s.params.model_validate(inner_spec), c)


@register(
    "embedder",
    "cached",
    params=CachedParams,
    summary="wraps any embedder: the same text is never embedded twice (LRU; shared in Valkey with store: valkey)",
)
def _cached(p: CachedParams, c: Container) -> CachedEmbedder:
    shared = None
    if p.store == "valkey":
        from rag_core.components.conversation import _valkey

        shared = ValkeyVectors(_valkey(p.url_env, p.url_file), p.namespace, p.ttl_seconds)
    return CachedEmbedder(_inner_embedder(p.inner, c), p.max_items, shared)


# ================================================================ batching and rate limits (extension 04)


class BatchedParams(_Strict):
    inner: dict[str, Any]  # the real embedder
    batch_size: int = Field(32, ge=1, le=2048)  # texts per request
    requests_per_second: float | None = Field(None, gt=0)  # a ceiling; None = as fast as it answers
    max_retries: int = Field(3, ge=0, le=10)  # transient failures (timeouts, 429, 5xx) are retried
    backoff_seconds: float = Field(1.0, ge=0)  # doubled after each failure


class BatchedEmbedder:
    """Ingestion at a pace the embedding service accepts: texts sent in batches of `batch_size`,
    at most `requests_per_second`, with exponential backoff on transient errors. A large re-index
    then finishes instead of tripping the provider's rate limit (or the gateway's budget, Step 10)
    halfway through. Invalid input (ValueError, TypeError) is not retried."""

    def __init__(self, inner: Any, p: BatchedParams, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:  # fmt: skip
        self.inner, self.p, self.clock, self.sleep = inner, p, clock, sleep
        self.model, self.dimensions = inner.model, inner.dimensions
        self._next = 0.0
        self._lock = threading.Lock()
        self.requests = self.retries = 0

    def _pace(self) -> None:
        if self.p.requests_per_second is None:
            return
        with self._lock:
            now = self.clock()
            wait = self._next - now
            self._next = max(now, self._next) + 1.0 / self.p.requests_per_second
        if wait > 0:
            self.sleep(wait)

    def _call(self, fn: Callable[[], Any]) -> Any:
        delay = self.p.backoff_seconds
        for attempt in range(self.p.max_retries + 1):
            self._pace()
            self.requests += 1
            try:
                return fn()
            except (ValueError, TypeError):
                raise
            except Exception as e:
                if attempt == self.p.max_retries:
                    raise
                self.retries += 1
                log.warning(
                    "embedding request failed (%s), retrying in %.1fs", type(e).__name__, delay
                )
                self.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")  # pragma: no cover

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.p.batch_size):
            part = list(texts[i : i + self.p.batch_size])
            out += self._call(functools.partial(self.inner.embed_documents, part))
        return out

    def embed_query(self, text: str) -> list[float]:
        return list(self._call(lambda: self.inner.embed_query(text)))


@register("embedder", "batched", params=BatchedParams,
          summary="wraps any embedder: fixed-size batches, a requests-per-second ceiling, retries with backoff")  # fmt: skip
def _batched(p: BatchedParams, c: Container) -> BatchedEmbedder:
    return BatchedEmbedder(_inner_embedder(p.inner, c), p)
