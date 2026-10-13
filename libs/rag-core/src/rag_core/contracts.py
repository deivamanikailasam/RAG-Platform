"""The contract of every switchable part (Step 30).

A component is anything that satisfies one of these Protocols. Nothing else is required: no base
class, no framework. The registry (registry.py) names them so a config file can pick one.

Kinds, in pipeline order:

    ingestion   parser · normalizer · pii · chunker · enricher · token_counter · embedder
    storage     vector_store · keyword_index · cache · queue
    query       query_transformer · retriever · fusion · reranker · postprocessor
    answer      compressor · context_builder · generator · guard · memory
    (extension 02: sparse_embedder, used by the sparse keyword indexes)
    (extension 04: answer_formatter, judge, connector)
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
class DocumentEmbedder(Embedder, Protocol):
    """Extension 02: an embedder that needs the whole document to embed its chunks (late
    chunking). Ingestion calls embed_chunks instead of embed_documents when it is available."""

    def embed_chunks(self, document: Document, chunks: Sequence[Chunk]) -> list[list[float]]: ...


@runtime_checkable
class SparseEmbedder(Protocol):
    """Extension 02: text in, a weight per vocabulary id out ({id: weight}), e.g. BM25 or SPLADE."""

    model: str
    idf: bool  # True: the index multiplies by the inverse document frequency at search time

    def embed_sparse_documents(self, texts: Sequence[str]) -> list[dict[int, float]]: ...

    def embed_sparse_query(self, text: str) -> dict[int, float]: ...


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
class Compressor(Protocol):
    """Extension 02: shorten (or drop) retrieved chunks for THIS question before the context is
    built. Keeps each chunk's id, document and metadata, so citations still resolve."""

    def compress(self, query: Query, hits: Sequence[ScoredChunk]) -> list[ScoredChunk]: ...


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


@runtime_checkable
class AnswerFormatter(Protocol):
    """Extension 04: shape a checked answer for its reader (citation style, a JSON object, a
    confidence score, follow-up questions). Runs after the output guards; must not add claims."""

    def format(self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]) -> Answer: ...


@runtime_checkable
class Judge(Protocol):
    """Extension 04: scores one answer for evaluation (0..1 per metric, None = can't say)."""

    name: str

    def score(self, question: str, answer: str, contexts: Sequence[str],
              reference: str | None = None) -> dict[str, float | None]: ...  # fmt: skip


class SourceRef(Protocol):
    uri: str
    version: str  # mtime+size, an ETag, a revision number: changes when the content changes


@runtime_checkable
class Connector(Protocol):
    """Extension 04: where sources come from (a folder, a bucket, a wiki). Lists what exists now,
    with a version that changes when the content does, and fetches one item."""

    def list(self) -> Iterator[SourceRef]: ...

    def fetch(self, ref: SourceRef) -> Source: ...


class Verdict(Protocol):
    action: str  # "allow" | "redact" | "block" | "flag"
    reasons: tuple[str, ...]
    replacement: object | None


__all__ = [
    "LLM",
    "Answer",
    "AnswerFormatter",
    "Chunk",
    "Chunker",
    "Compressor",
    "Connector",
    "Context",
    "ContextBuilder",
    "Document",
    "DocumentEmbedder",
    "Element",
    "Embedder",
    "Enricher",
    "Fusion",
    "Generator",
    "Guard",
    "Judge",
    "KeywordIndex",
    "Normalizer",
    "Parser",
    "PiiRedactor",
    "PostProcessor",
    "QueryTransformer",
    "Reranker",
    "Retriever",
    "SourceRef",
    "SparseEmbedder",
    "TokenCounter",
    "VectorStore",
    "Verdict",
]  # fmt: skip
