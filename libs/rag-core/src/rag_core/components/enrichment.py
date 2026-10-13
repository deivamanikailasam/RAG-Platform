"""Enrichers and embedders (Step 31).

Enrichers decide WHAT is embedded for a chunk ("embed_text"); the chunk's own text, the part that
is shown and cited, never changes. A chunk saying "It is 18 weeks." embeds far better as
"Leave policy > Parental leave: It is 18 weeks."
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from rag_core.registry import Container, register, spec
from rag_core.types import Chunk, Document


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
    batch_size: int = Field(32, ge=1, le=2048)
    # Asymmetric models embed questions differently from documents (Step 8). Step 24's registered
    # prompt "query-instruction" holds the production value; this is the fallback.
    query_instruction: str = (
        "Instruct: Given a question, retrieve passages that answer it\nQuery: {query}"
    )
    timeout: float = 120.0


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

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.p.batch_size):
            batch = list(texts[i : i + self.p.batch_size])
            r = self._http.post(
                "embeddings",
                json={"model": self.model, "input": batch},
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
        return self._embed([self.p.query_instruction.format(query=text)])[0]


@register("embedder", "gateway", params=GatewayEmbedderParams, status="mocked",
            summary="any embedding model behind the LiteLLM gateway, batched, dimension-checked")  # fmt: skip
def _gw_embedder(p: GatewayEmbedderParams, c: Container) -> GatewayEmbedder:
    return GatewayEmbedder(p, SecretStr(os.environ.get(p.api_key_env, "")))


class CachedParams(_Strict):
    inner: dict[str, Any]  # the real embedder: {use: gateway, …}
    max_items: int = Field(100_000, ge=1)


class CachedEmbedder:
    """Never embed the same text twice with the same model: re-ingesting an unchanged chunk, or
    a popular query, costs nothing. Keyed by (model, sha256(text))."""

    def __init__(self, inner: Any, max_items: int) -> None:
        self.inner, self.model, self.dimensions = inner, inner.model, inner.dimensions
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._max = max_items
        self._lock = threading.Lock()
        self.hits = self.misses = 0

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

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        keys = [self._key("d", t) for t in texts]
        cached = [self._get(k) for k in keys]
        missing = [i for i, v in enumerate(cached) if v is None]
        self.hits += len(texts) - len(missing)
        self.misses += len(missing)
        if missing:
            fresh = self.inner.embed_documents([texts[i] for i in missing])
            for i, v in zip(missing, fresh, strict=True):
                cached[i] = v
                self._put(keys[i], v)
        return [v for v in cached if v is not None]

    def embed_query(self, text: str) -> list[float]:
        key = self._key("q", text)
        v = self._get(key)
        if v is None:
            self.misses += 1
            v = self.inner.embed_query(text)
            self._put(key, v)
        else:
            self.hits += 1
        return v


@register(
    "embedder",
    "cached",
    params=CachedParams,
    summary="wraps any embedder: the same text is never embedded twice (LRU)",
)
def _cached(p: CachedParams, c: Container) -> CachedEmbedder:
    inner_spec = dict(p.inner)
    s = spec("embedder", str(inner_spec.pop("use")))
    return CachedEmbedder(s.factory(s.params.model_validate(inner_spec), c), p.max_items)
