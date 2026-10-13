"""The shared vocabulary of every RAG pipeline (Step 30).

Every component takes and returns these types, so any parser can feed any chunker, any retriever
any reranker, and a project can swap one part without touching the others.

    Source ──parse──▶ Document(elements) ──chunk──▶ Chunk ──embed──▶ stored
    Query ──transform──▶ queries ──retrieve──▶ ScoredChunk ──rerank──▶ Context ──generate──▶ Answer
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

Classification = Literal["public", "internal", "confidential", "restricted"]
ElementKind = Literal[
    "title", "heading", "paragraph", "list", "table", "code", "caption", "page_break"
]


@dataclass(frozen=True)
class Access:
    """Who may see something. Copied from the document to every chunk, and checked at query time.

    The same fields as Step 11's documents table and Step 18's policy input."""

    classification: Classification = "internal"
    groups: tuple[str, ...] = ()
    tenant: str = "default"

    def allows(self, principal: Principal) -> bool:
        if self.tenant != principal.tenant or self.classification not in principal.classifications:
            return False
        return self.classification == "public" or bool(set(self.groups) & set(principal.groups))


@dataclass(frozen=True)
class Principal:
    """Who is asking: what the policy engine (Step 18) decided this person may see."""

    subject: str
    groups: tuple[str, ...] = ()
    classifications: tuple[Classification, ...] = ("public",)
    tenant: str = "default"

    @property
    def fingerprint(self) -> str:
        """Same fingerprint = same visible documents. Caches are keyed by it (Step 33)."""
        raw = f"{self.tenant}|{','.join(sorted(self.classifications))}|{','.join(sorted(self.groups))}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Source:
    """Raw input: bytes plus where they came from. The original is kept in object storage (Step 14)."""

    uri: str
    data: bytes
    mime_type: str = "application/octet-stream"
    access: Access = field(default_factory=Access)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class Element:
    """One structural piece of a parsed document: a heading, a paragraph, a table, …"""

    kind: ElementKind
    text: str
    level: int = 0  # heading depth (1 = top)
    page: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Document:
    uri: str
    title: str
    elements: tuple[Element, ...]
    sha256: str  # of the ORIGINAL bytes: unchanged source = nothing to re-index
    access: Access = field(default_factory=Access)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    language: str = "en"

    @property
    def text(self) -> str:
        return "\n\n".join(e.text for e in self.elements if e.text)


@dataclass(frozen=True)
class Chunk:
    """The unit that is embedded, indexed, retrieved and cited."""

    id: str  # stable: same document + same position + same text = same id (idempotent re-ingest)
    document_uri: str
    index: int
    text: str  # what the reader sees and what is cited
    token_count: int
    access: Access = field(default_factory=Access)
    # What is embedded/indexed. Often the text plus a header ("Doc title > Section"), see Step 31.
    embed_text: str = ""
    parent_id: str | None = None  # parent-child chunking: the bigger passage this one belongs to
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def indexed_text(self) -> str:
        return self.embed_text or self.text

    @staticmethod
    def make_id(document_uri: str, index: int, text: str) -> str:
        return hashlib.sha256(f"{document_uri}\x00{index}\x00{text}".encode()).hexdigest()[:24]


@dataclass(frozen=True)
class Query:
    text: str
    principal: Principal
    # a metadata filter (rag_core.filters, extension 01): {"department": "hr", "updated": {"gte": …}}
    filters: Mapping[str, Any] = field(default_factory=dict)
    history: tuple[Turn, ...] = ()  # earlier turns of a conversation (Step 33)
    k: int = 5


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    # Where the score came from, kept for explanations, debugging and evaluation
    scores: Mapping[str, float] = field(default_factory=dict)

    def with_score(self, score: float, stage: str) -> ScoredChunk:
        return replace(self, score=score, scores={**self.scores, stage: score})


@dataclass(frozen=True)
class Citation:
    marker: int  # the [n] in the answer
    chunk_id: str
    document_uri: str
    title: str = ""


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[Citation, ...] = ()
    abstained: bool = False  # "the documents don't say": a correct answer, not a failure
    blocked: str | None = None  # a guardrail stopped it (Step 34): the reason, shown to the user
    usage: Mapping[str, int] = field(default_factory=dict)
    trace: Mapping[str, Any] = field(default_factory=dict)  # which components ran, timings, scores
    # extension 04: what answer formatters add: quotes with offsets, a JSON object, a confidence
    # score, follow-up questions. Empty unless an `answer_formatters` slot is configured.
    extras: Mapping[str, Any] = field(default_factory=dict)
