"""The contract of every switchable part (Step 30).

A component is anything that satisfies one of these Protocols. Nothing else is required: no base
class, no framework. The registry (registry.py) names them so a config file can pick one.

Kinds, in pipeline order:

    ingestion   parser · normalizer · pii · chunker · enricher · token_counter · embedder
    storage     vector_store · keyword_index · cache · queue
    query       query_transformer · retriever · fusion · reranker · postprocessor
    answer      context_builder · generator · guard · memory
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

from rag_core.types import Answer, Chunk, Document, Element, Principal, Query, ScoredChunk, Source


@runtime_checkable
class Parser(Protocol):
    """Bytes of one format in, structured elements out."""

    mime_types: tuple[str, ...]

    def parse(self, source: Source) -> Document: ...


@runtime_checkable
class Normalizer(Protocol):
    """Clean elements: whitespace, Unicode, boilerplate. Must not change meaning."""

    def normalize(self, document: Document) -> Document: ...


@runtime_checkable
class PiiRedactor(Protocol):
    """Find personal data and mask, pseudonymise or drop it before anything is stored."""

    def redact(self, text: str) -> tuple[str, list[str]]: ...  # new text, kinds found


@runtime_checkable
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


@runtime_checkable
class Chunker(Protocol):
    def chunk(self, document: Document) -> list[Chunk]: ...


@runtime_checkable
class Enricher(Protocol):
    """Add context to chunks before embedding: headers, summaries, generated questions."""

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]: ...


@runtime_checkable
class Embedder(Protocol):
    model: str  # recorded with every stored vector: vectors of different models never mix
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...  # may add a query instruction (Step 24)


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None: ...

    def delete_document(self, document_uri: str) -> int: ...

    def search(self, vector: Sequence[float], principal: Principal, k: int,
               filters: dict[str, object] | None = None) -> list[ScoredChunk]: ...  # fmt: skip

    def count(self) -> int: ...


@runtime_checkable
class KeywordIndex(Protocol):
    def index(self, chunks: Sequence[Chunk]) -> None: ...

    def delete_document(self, document_uri: str) -> int: ...

    def search(self, text: str, principal: Principal, k: int,
               filters: dict[str, object] | None = None) -> list[ScoredChunk]: ...  # fmt: skip


@runtime_checkable
class QueryTransformer(Protocol):
    """One question in, one or more search queries out (rewrite, multi-query, HyDE, …)."""

    def transform(self, query: Query) -> list[str]: ...


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: Query, texts: Sequence[str]) -> list[ScoredChunk]: ...


@runtime_checkable
class Fusion(Protocol):
    """Merge ranked lists from several retrievers or queries into one."""

    def fuse(self, ranked: Sequence[Sequence[ScoredChunk]]) -> list[ScoredChunk]: ...


@runtime_checkable
class Reranker(Protocol):
    def rerank(
        self, query: str, candidates: Sequence[ScoredChunk], k: int
    ) -> list[ScoredChunk]: ...


@runtime_checkable
class PostProcessor(Protocol):
    """Diversify, threshold, expand to parents, cap per document, …"""

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]: ...


@runtime_checkable
class ContextBuilder(Protocol):
    def build(self, query: Query, candidates: Sequence[ScoredChunk]) -> Context: ...


class Context(Protocol):
    text: str
    chunks: tuple[ScoredChunk, ...]  # in the order shown to the model; [n] = position + 1
    tokens: int


@runtime_checkable
class Generator(Protocol):
    model: str

    def generate(self, query: Query, context: Context) -> Answer: ...

    def stream(self, query: Query, context: Context) -> Iterator[str]: ...


@runtime_checkable
class LLM(Protocol):
    """A plain chat model, for helpers that need one (query rewriting, judges, enrichment)."""

    model: str

    def complete(
        self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0
    ) -> str: ...


@runtime_checkable
class Guard(Protocol):
    """One safety check at one stage (Step 34)."""

    name: str
    stage: str  # "input" | "context" | "output"

    def check(self, query: Query, payload: object) -> Verdict: ...


class Verdict(Protocol):
    action: str  # "allow" | "redact" | "block" | "flag"
    reasons: tuple[str, ...]
    replacement: object | None


__all__ = [
    "LLM", "Answer", "Chunk", "Chunker", "Context", "ContextBuilder", "Document", "Element",
    "Embedder", "Enricher", "Fusion", "Generator", "Guard", "KeywordIndex", "Normalizer", "Parser",
    "PiiRedactor", "PostProcessor", "QueryTransformer", "Reranker", "Retriever", "TokenCounter",
    "VectorStore", "Verdict",
]  # fmt: skip
