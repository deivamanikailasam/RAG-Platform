"""More RAG architectures, part 1 (extension 03): named presets in the `pipeline` slot, so the
common names people search for are one word in rag.yaml.

    vector          dense (embedding) search only, WITH the configured transformer, reranker and
                    post-processors. `naive` is the bare baseline (no reranking); this is "vector
                    RAG done properly"
    keyword         keyword (BM25) search only, with the same reranker: vectorless, no embeddings
    rag-fusion      N rephrasings of the question (a model writes them), each searched on its own,
                    fused with RRF, then reranked against the original question. `multi-query` is
                    the same component under its other common name
    hyde            search with a hypothetical answer passage as well as the question
    conversational  a follow-up is rewritten into a standalone question first (model, or a
                    heuristic without one); needs `memory:` to have a conversation to rewrite
    long-context    per question: if the best documents fit the context budget WHOLE, send whole
                    documents instead of chunks; otherwise the usual chunks
    table           questions about rows of CSV tables: the matching rows, cited (no model needed);
                    `sql` is the text-to-SQL option for sums, counts and comparisons

Every preset gathers context through the SearchPipeline (access filter, reranker,
post-processors), and the shared answer steps (guards, citations, cache, memory) never change.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from rag_core import filters as _filters
from rag_core.components.architectures import (
    Retrieval,
    Standard,
    TableSpec,
    content_words,
    split_compound,
)
from rag_core.components.basics import ApproxTokenCounter, words
from rag_core.components.generation import AnswerParams, is_abstention
from rag_core.components.retrieval import (
    DenseRetriever,
    KeywordRetriever,
    LlmTransformer,
    LlmTransformParams,
    Passage,
    ReciprocalRankFusion,
    RetrieverParams,
    _run_all,
)
from rag_core.registry import Container, register
from rag_core.types import Access, Chunk, Query, ScoredChunk

log = logging.getLogger("rag_core.presets")
LlmSlot = Literal["llm", "judge_llm", "answer_llm"]


def _llm(c: Container, slot: str) -> Any:
    """The named model slot, else `llm`, else None (the preset then uses its heuristic)."""
    for name in (slot, "llm"):
        if c.has(name):
            return c.get(name)
    return None


# ================================================================ vector and keyword only


class SingleRetrieverParams(AnswerParams):
    candidates: int = Field(default=30, ge=1, le=500)  # per search text, before reranking


class SingleRetriever(Standard):
    """One kind of search only (dense or keyword), with everything else Step 32 configures."""

    kind: Literal["dense", "keyword"] = "dense"

    def __init__(self, params: SingleRetrieverParams) -> None:
        super().__init__(params)
        self.sp = params

    def retrieve(self, pipe: Any, query: Query) -> Retrieval:
        cls = DenseRetriever if self.kind == "dense" else KeywordRetriever
        r = pipe.search.search_with(
            query, None, cls(pipe.c, RetrieverParams(candidates=self.sp.candidates))
        )
        return Retrieval(r.hits, {"architecture": self.name, "search": r.trace})


class VectorOnly(SingleRetriever):
    """Vector RAG: embedding search only, then the configured reranker and post-processors."""

    name = "vector"
    kind = "dense"


class KeywordOnly(SingleRetriever):
    """Keyword RAG: BM25 only. No embeddings at query time, exact words, codes and names."""

    name = "keyword"
    kind = "keyword"


@register("pipeline", "vector", params=SingleRetrieverParams,
          summary="vector RAG: dense search only, with the configured transformer, reranker and post-processors")  # fmt: skip
def _vector(p: SingleRetrieverParams, c: Container) -> VectorOnly:
    if not c.has("vector_store"):
        raise ValueError("the vector pipeline needs a vector_store (and an embedder)")
    return VectorOnly(p)


@register("pipeline", "keyword", params=SingleRetrieverParams,
          summary="vectorless: keyword (BM25) search only, then the configured reranker; no embeddings")  # fmt: skip
def _keyword(p: SingleRetrieverParams, c: Container) -> KeywordOnly:
    if not c.has("keyword_index"):
        raise ValueError("the keyword pipeline needs a keyword_index")
    return KeywordOnly(p)


# ================================================================ rag-fusion / multi-query


def heuristic_variants(text: str, n: int) -> list[str]:
    """Rephrasings without a model: the question's content words only, and the parts of a
    compound question. Fewer and plainer than a model's, but free and deterministic."""
    out: list[str] = []
    bare = " ".join(w for w in words(text) if w in content_words(text))
    if bare and bare.lower() != text.lower():
        out.append(bare)
    parts = split_compound(text, 4)
    if len(parts) > 1:
        out.extend(parts)
    return out[:n]


def _usable(lines: Sequence[str], question: str) -> list[str]:
    """Drop what a model must not turn into a search: refusals, "I don't know", empty lines."""
    return [
        t
        for t in lines
        if t.strip() and not is_abstention(t) and t.strip().lower() != question.lower()
    ]


class PerTextFusion:
    """Each search text through the configured retriever on its own (in parallel), then the
    lists fused with RRF: a passage found by several rephrasings rises to the top."""

    def __init__(self, inner: Any, k: int, parallel: bool) -> None:
        self.inner, self.k, self.parallel = inner, k, parallel
        self._fusion: Any = None

    def retrieve(self, query: Query, texts: Sequence[str]) -> list[ScoredChunk]:
        def job(text: str) -> Callable[[], list[ScoredChunk]]:
            return lambda: list(self.inner.retrieve(query, [text]))

        jobs = [job(t) for t in texts]
        lists = [x for x in _run_all(jobs, self.parallel) if x]
        if len(lists) < 2:
            return lists[0] if lists else []
        self._fusion = ReciprocalRankFusion(self.k)
        fused: list[ScoredChunk] = self._fusion.fuse(lists)
        return fused


class FusionPresetParams(AnswerParams):
    variants: int = Field(default=4, ge=1, le=8)  # rephrasings besides the question itself
    variant_source: Literal["llm", "heuristic"] = "llm"  # heuristic: no model call (or no model)
    llm_slot: LlmSlot = "llm"  # the fast helper model
    rrf_k: int = Field(default=60, ge=1)
    parallel: bool = True


class RagFusion(Standard):
    """RAG-Fusion: one model call writes N rephrasings; each is searched in parallel; the lists
    are fused with reciprocal rank fusion and reranked against the ORIGINAL question. Better
    recall on vaguely worded questions, for one cheap model call and N searches."""

    name = "rag-fusion"

    def __init__(self, params: FusionPresetParams, llm: Any) -> None:
        super().__init__(params)
        self.fp, self.llm = params, llm

    def variants(self, query: Query) -> tuple[list[str], str]:
        if self.fp.variant_source == "llm" and self.llm is not None:
            t = LlmTransformer("multi-query", self.llm,
                               LlmTransformParams(n=self.fp.variants, include_original=False))  # fmt: skip
            made = _usable(t.transform(query), query.text)
            if made:
                return made[: self.fp.variants], "llm"
        return heuristic_variants(query.text, self.fp.variants), "heuristic"

    def retrieve(self, pipe: Any, query: Query) -> Retrieval:
        made, source = self.variants(query)
        texts = [query.text, *made]
        r = pipe.search.search_with(
            query, texts, PerTextFusion(pipe.search.retriever, self.fp.rrf_k, self.fp.parallel)
        )
        return Retrieval(r.hits, {"architecture": "rag-fusion", "variants": made, "source": source,
                                  "search": r.trace})  # fmt: skip


def _fusion_preset(p: FusionPresetParams, c: Container) -> RagFusion:
    return RagFusion(p, _llm(c, p.llm_slot) if p.variant_source == "llm" else None)


register("pipeline", "rag-fusion", params=FusionPresetParams, status="mocked",
         summary="RAG-Fusion: N model-written rephrasings searched in parallel, fused by RRF, reranked")(_fusion_preset)  # fmt: skip
register("pipeline", "multi-query", params=FusionPresetParams, status="mocked",
         summary="the rag-fusion pipeline under its other name (multi-query retrieval + RRF + rerank)")(_fusion_preset)  # fmt: skip


# ================================================================ hyde


class HydePresetParams(AnswerParams):
    llm_slot: LlmSlot = "llm"
    keep_question: bool = True  # search with the question as well as the invented passage


class Hyde(Standard):
    """HyDE: a model writes the passage it would expect to find; that passage is embedded like a
    document and searched with the question. Helps when questions and documents are worded very
    differently. The invented passage is never shown, and keyword search ignores it."""

    name = "hyde"

    def __init__(self, params: HydePresetParams, llm: Any) -> None:
        super().__init__(params)
        self.hp, self.llm = params, llm

    def retrieve(self, pipe: Any, query: Query) -> Retrieval:
        texts: list[str] = [query.text]
        if self.llm is not None:
            made = LlmTransformer("hyde", self.llm,
                                  LlmTransformParams(include_original=False)).transform(query)  # fmt: skip
            passages: list[str] = [
                t for t in made if isinstance(t, Passage) and not is_abstention(t)
            ]
            texts = ([query.text] if self.hp.keep_question else []) + passages or [query.text]
        r = pipe.search.search_with(query, texts)
        return Retrieval(r.hits, {"architecture": "hyde", "passage": any(isinstance(t, Passage) for t in texts),
                                  "search": r.trace})  # fmt: skip


@register("pipeline", "hyde", params=HydePresetParams, status="mocked",
          summary="HyDE: search with a model-written hypothetical answer passage as well as the question")  # fmt: skip
def _hyde(p: HydePresetParams, c: Container) -> Hyde:
    return Hyde(p, _llm(c, p.llm_slot))


# ================================================================ conversational


class ConversationalParams(AnswerParams):
    rewriter: Literal["llm", "heuristic"] = "llm"  # heuristic: last question + this one, no model
    llm_slot: LlmSlot = "llm"


class Conversational(Standard):
    """Conversational RAG: with `memory:`, a follow-up ("and for part-timers?") is rewritten into
    a standalone question before searching; the question as asked is searched too. A first
    question costs nothing extra."""

    name = "conversational"

    def __init__(self, params: ConversationalParams, llm: Any) -> None:
        super().__init__(params)
        self.cp, self.llm = params, llm

    def texts(self, query: Query) -> tuple[list[str], str]:
        if not query.history:
            return [query.text], "none"
        if self.cp.rewriter == "llm" and self.llm is not None:
            made = LlmTransformer("rewrite", self.llm, LlmTransformParams()).transform(query)
            made = _usable(made, query.text)
            if made:
                return [made[0], query.text], "llm"
        last = next((t.text for t in reversed(query.history) if t.role == "user"), "")
        return [f"{last} {query.text}".strip(), query.text], "heuristic"

    def retrieve(self, pipe: Any, query: Query) -> Retrieval:
        texts, how = self.texts(query)
        r = pipe.search.search_with(query, texts)
        return Retrieval(r.hits, {"architecture": "conversational", "rewrite": how, "texts": texts,
                                  "memory": pipe.memory is not None, "search": r.trace})  # fmt: skip


@register("pipeline", "conversational", params=ConversationalParams, status="mocked",
          summary="conversational RAG: rewrite a follow-up into a standalone question (with memory), then standard")  # fmt: skip
def _conversational(p: ConversationalParams, c: Container) -> Conversational:
    return Conversational(p, _llm(c, p.llm_slot) if p.rewriter == "llm" else None)


# ================================================================ long-context routing


class LongContextParams(AnswerParams):
    max_documents: int = Field(default=3, ge=1, le=20)  # whole documents considered per question
    budget_tokens: int | None = Field(
        default=None, ge=100
    )  # default: the context builder's max_tokens
    max_document_chunks: int = Field(default=200, ge=1)
    min_score_share: float = Field(default=0.0, ge=0, le=1)  # a document's best hit vs the top hit


_SKIP_NODES = ("summary", "document-summary", "section")  # extension 02's extra nodes: not the text


class LongContext(Standard):
    """Long-context routing: search as usual to find the right documents, then decide. If the
    top documents fit the context budget WHOLE, the model gets whole documents (no chunk
    boundary can cut an answer in half); if not, it gets the usual best chunks."""

    name = "long-context"

    def __init__(self, params: LongContextParams) -> None:
        super().__init__(params)
        self.lp = params

    def _budget(self, pipe: Any) -> int:
        if self.lp.budget_tokens:
            return self.lp.budget_tokens
        return int(getattr(getattr(pipe.builder, "p", None), "max_tokens", 3000))

    def whole(self, pipe: Any, query: Query, uri: str) -> list[Chunk]:
        from rag_core.components.hierarchy import fetch

        wanted = _filters.combine(query.filters, {"document": uri})
        found = {h.chunk.id: h.chunk for h in fetch(pipe.c, query.principal, wanted,
                                                    self.lp.max_document_chunks, query.text)
                 if h.chunk.metadata.get("node_kind") not in _SKIP_NODES}  # fmt: skip
        return sorted(found.values(), key=lambda c: c.index)

    def retrieve(self, pipe: Any, query: Query) -> Retrieval:
        base = pipe.search.search(query)
        info: dict[str, Any] = {"architecture": "long-context", "search": base.trace}
        if not base.hits:
            return Retrieval([], info | {"route": "chunks"})
        top = max(h.score for h in base.hits) or 1.0
        order: list[str] = []
        for h in base.hits:
            if h.chunk.document_uri not in order and h.score >= self.lp.min_score_share * top:
                order.append(h.chunk.document_uri)
        budget, used = self._budget(pipe), 0
        counter = getattr(pipe, "counter", None) or ApproxTokenCounter()
        stuffed: list[tuple[str, list[Chunk]]] = []
        for uri in order[: self.lp.max_documents]:
            chunks = self.whole(pipe, query, uri)
            cost = sum(
                counter.count(c.text) + 12 for c in chunks
            )  # + the <doc> tag, as the builder counts
            if chunks and used + cost <= budget:
                stuffed.append((uri, chunks))
                used += cost
        if not stuffed:
            return Retrieval(base.hits, info | {"route": "chunks", "budget": budget})
        hits = [ScoredChunk(c, float(len(stuffed) - d), {"long_context": float(len(stuffed) - d)})
                for d, (_, chunks) in enumerate(stuffed) for c in chunks]  # fmt: skip
        return Retrieval(hits, info | {"route": "whole-documents", "documents": [u for u, _ in stuffed],
                                       "tokens": used, "budget": budget})  # fmt: skip


@register("pipeline", "long-context", params=LongContextParams,
          summary="per question: whole documents when they fit the context budget, else the usual chunks")  # fmt: skip
def _long_context(p: LongContextParams, c: Container) -> LongContext:
    return LongContext(p)


# ================================================================ table QA (row lookup)


class TableParams(AnswerParams):
    tables: dict[str, TableSpec]
    max_rows: int = Field(default=10, ge=1, le=200)
    min_overlap: int = Field(default=1, ge=1)  # question words a row must share
    with_documents: bool = True  # also run the standard search, so prose and rows mix


class TableLookup(Standard):
    """Table QA without a model: the rows of a CSV table that share the most words with the
    question (values and column names) become one cited passage with the header row. Answers
    lookups ("what is the per diem in London?"); sums, counts and comparisons need `sql`.
    Tables carry access like documents: a table this person can't see is never read."""

    name = "table"

    def __init__(self, params: TableParams, base: Path | None = None) -> None:
        super().__init__(params)
        self.tp = params
        self.data: dict[str, tuple[list[str], list[list[str]]]] = {}
        for name, spec in params.tables.items():
            path = Path(spec.path) if base is None else base / spec.path
            rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
            if not rows:
                raise ValueError(f"table {name!r}: {path} is empty")
            self.data[name] = (rows[0], [r for r in rows[1:] if any(v.strip() for v in r)])

    def _access(self, name: str) -> Access:
        s = self.tp.tables[name]
        return Access(s.classification, tuple(s.groups))

    def lookup(self, query: Query, name: str) -> tuple[list[str], list[list[str]]]:
        header, rows = self.data[name]
        asked = set(content_words(query.text))
        named = asked & {w for h in header for w in words(h)}  # columns the question names
        scored = []
        for i, r in enumerate(rows):
            have = {w for v in r for w in words(v)}
            n = len(asked & have)
            if n >= self.tp.min_overlap:
                scored.append((n, len(named), -i, r))
        if not scored:
            return header, []
        best = max(s[0] for s in scored)
        keep = [
            s for s in sorted(scored, key=lambda s: (-s[0], -s[2])) if s[0] == best
        ]  # the best matches only
        return header, [s[3] for s in keep[: self.tp.max_rows]]

    def retrieve(self, pipe: Any, query: Query) -> Retrieval:
        docs = pipe.search.search(query) if self.tp.with_documents else None
        hits: list[ScoredChunk] = []
        info: dict[str, Any] = {"architecture": "table", "tables": {}}
        for name in self.tp.tables:
            access = self._access(name)
            if not access.allows(query.principal):
                continue
            header, rows = self.lookup(query, name)
            info["tables"][name] = len(rows)
            if not rows:
                continue
            body = "\n".join(" | ".join(r) for r in rows)
            text = f"Rows of table {name} ({self.tp.tables[name].description or 'CSV'}):\n{' | '.join(header)}\n{body}"
            key = hashlib.sha256(f"{name}\x00{body}".encode()).hexdigest()[:12]
            chunk = Chunk(id=f"table-{key}", document_uri=f"table://{name}", index=0, text=text,
                          token_count=len(text.split()), access=access,
                          metadata={"title": f"Table: {name}", "rows": len(rows)})  # fmt: skip
            hits.append(ScoredChunk(chunk, 1.0, {"table": float(len(rows))}))
        return Retrieval([*hits, *(docs.hits if docs else [])], info)


@register("pipeline", "table", params=TableParams,
          summary="table QA: the CSV rows that match the question, cited (no model); sql for aggregates")  # fmt: skip
def _table(p: TableParams, c: Container) -> TableLookup:
    return TableLookup(p)


__all__ = [
    "Conversational",
    "Hyde",
    "KeywordOnly",
    "LongContext",
    "PerTextFusion",
    "RagFusion",
    "TableLookup",
    "VectorOnly",
    "heuristic_variants",
]
