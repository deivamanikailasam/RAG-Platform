"""Hierarchies (extension 02): chunks that know the tree they came from, and the components that
use it at query time.

    document ─▶ section ─▶ subsection ─▶ … ─▶ paragraph leaves        (`hierarchical` chunker)
    leaves ─cluster─▶ summaries ─cluster─▶ summaries of summaries     (`summary-tree` enricher)
    one summary per document                                          (`summary` enricher)

Query time:
    auto-merge      enough children of one parent retrieved: return the parent instead
    section         "what does section 4.2 say?": return exactly that section
    section-expand  return the whole section a hit belongs to, within a token budget
    summary-expand  a summary was found: bring in the document's best detailed chunks too

Sections are looked up with an ordinary filtered search ({"document": …, "section_path": …},
extension 01's filter language), so every store supports them and permissions always apply.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core import filters as _filters
from rag_core.components.basics import ApproxTokenCounter, cosine
from rag_core.components.chunking import (
    SECTION_KEYS,
    StructureChunker,
    StructureParams,
    _Base,
    section_meta,
)
from rag_core.registry import Container, register, spec
from rag_core.text import content_words, extractive_summary, grounded, sentences
from rag_core.types import Chunk, Document, Element, Principal, Query, ScoredChunk

LlmSlot = Literal["llm", "judge_llm", "answer_llm"]
SUMMARY_KINDS = ("summary", "document-summary")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _counter(c: Container) -> Any:
    return c.get("token_counter") if c.has("token_counter") else ApproxTokenCounter()


# ================================================================ the hierarchical chunker


class HierarchicalParams(_Strict):
    leaf_tokens: int = Field(200, ge=16, le=8192)  # paragraphs are packed into leaves this big
    leaf_overlap: int = Field(0, ge=0)
    # a section bigger than this isn't stored with its leaves: too big to merge into or expand to
    max_node_tokens: int = Field(2000, ge=64)
    index_sections: bool = False  # also index section nodes: search at several granularities


@dataclass
class _Node:
    kind: str  # document | section
    heading: str
    level: int  # heading level; 0 for the document
    path: list[str]
    items: list[Any] = field(default_factory=list)  # _Node | Element, then _Node | str (leaves)
    id: str = ""
    text: str = ""
    tokens: int = 0


class HierarchicalChunker(_Base):
    """A tree of any depth: the document, its sections and subsections (from heading levels), and
    paragraph leaves packed to `leaf_tokens`. Leaves are indexed; each carries its parent's id and
    its `ancestors` (id, kind, heading, number of children and, if small enough, text), which is
    what `auto-merge` and `section-expand` use at query time without another lookup."""

    def __init__(self, counter: Any, p: HierarchicalParams) -> None:
        super().__init__(counter)
        self.p = p
        self._units = StructureChunker(counter, StructureParams(max_tokens=p.leaf_tokens,
                                       overlap_tokens=min(p.leaf_overlap, p.leaf_tokens - 1), min_tokens=0))._units  # fmt: skip

    def _tree(self, doc: Document) -> _Node:
        root = _Node("document", doc.title, 0, [])
        stack = [root]
        for e in doc.elements:
            if e.kind in ("heading", "title"):
                level = max(1, e.level)
                while len(stack) > 1 and stack[-1].level >= level:
                    stack.pop()
                node = _Node("section", e.text, level, [*stack[-1].path, e.text])
                stack[-1].items.append(node)
                stack.append(node)
            else:
                stack[-1].items.append(e)
        return root

    def _leaves(self, node: _Node) -> bool:
        """Pack each run of paragraphs into leaves; drop empty sections. True if any content."""
        out: list[Any] = []
        run: list[Element] = []

        def flush() -> None:
            units = [u for e in run for u in self._units(e)]
            out.extend(self._windows(units, self.p.leaf_tokens, self.p.leaf_overlap, "\n\n"))
            run.clear()

        for item in node.items:
            if isinstance(item, Element):
                run.append(item)
                continue
            flush()
            if self._leaves(item):
                out.append(item)
        flush()
        node.items = [i for i in out if not isinstance(i, str) or i.strip()]
        return bool(node.items)

    def _texts(self, node: _Node, uri: str) -> str:
        node.id = hashlib.sha256(f"{uri}\x00node\x00{'/'.join(node.path)}".encode()).hexdigest()[
            :24
        ]
        parts = [] if node.kind == "document" else [node.heading]
        parts += [i if isinstance(i, str) else self._texts(i, uri) for i in node.items]
        full = "\n\n".join(parts)
        node.tokens = self.counter.count(full)
        node.text = full if node.tokens <= self.p.max_node_tokens else ""
        return full

    @staticmethod
    def _ref(node: _Node) -> dict[str, Any]:
        return {"id": node.id, "kind": node.kind, "heading": node.heading, "path": list(node.path),
                "children": len(node.items), "tokens": node.tokens, "text": node.text}  # fmt: skip

    def chunk(self, document: Document) -> list[Chunk]:
        root = self._tree(document)
        if not self._leaves(root):
            return []
        self._texts(root, document.uri)
        pieces: list[tuple[str, dict[str, Any]]] = []
        node_ids: dict[int, str] = {}  # piece position -> node id (indexed section nodes)

        def walk(node: _Node, ancestors: list[dict[str, Any]]) -> None:
            chain = [*ancestors, self._ref(node)]
            if self.p.index_sections and node.kind == "section" and node.text:
                node_ids[len(pieces)] = node.id
                pieces.append((node.text, {**section_meta(node.path), "node_kind": "section",
                               "node_level": len(ancestors), "ancestors": ancestors,
                               "parent_id": ancestors[-1]["id"] if ancestors else None}))  # fmt: skip
            for item in node.items:
                if isinstance(item, _Node):
                    walk(item, chain)
                else:
                    pieces.append((item, {**section_meta(node.path), "node_kind": "leaf",
                                   "node_level": len(chain), "ancestors": chain, "parent_id": node.id}))  # fmt: skip

        walk(root, [])
        chunks = self._make(document, pieces)
        out = []
        for i, c in enumerate(chunks):
            c = replace(
                c, parent_id=str(c.metadata["parent_id"]) if c.metadata.get("parent_id") else None
            )
            out.append(replace(c, id=node_ids[i]) if i in node_ids else c)
        return out


@register("chunker", "hierarchical", params=HierarchicalParams,
          summary="a tree of any depth (document > section > subsection > paragraph); leaves know their ancestors (for auto-merge, section-expand)")  # fmt: skip
def _hierarchical(p: HierarchicalParams, c: Container) -> HierarchicalChunker:
    return HierarchicalChunker(c.get("token_counter"), p)


# ================================================================ auto-merging


class AutoMergeParams(_Strict):
    threshold: float = Field(0.5, gt=0, le=1)  # share of a parent's children that must be found
    min_children: int = Field(2, ge=1)  # and at least this many
    max_levels: int = Field(3, ge=1, le=10)  # merge upwards at most this many times


def _node_chunk(child: Chunk, node: dict[str, Any], ancestors: list[dict[str, Any]],
                merged: list[str]) -> Chunk:  # fmt: skip
    keep = {k: v for k, v in child.metadata.items()
            if k not in (*SECTION_KEYS, "ancestors", "parent_id", "node_kind", "node_level", "merged_children")}  # fmt: skip
    meta = {**keep, **section_meta(list(node.get("path") or [])), "node_kind": node["kind"],
            "node_level": len(ancestors), "ancestors": ancestors, "merged_children": merged,
            "parent_id": ancestors[-1]["id"] if ancestors else None}  # fmt: skip
    return Chunk(id=str(node["id"]), document_uri=child.document_uri, index=child.index, text=str(node["text"]),
                 token_count=int(node.get("tokens") or 0), access=child.access, embed_text="",
                 parent_id=meta["parent_id"], metadata=meta)  # fmt: skip


class AutoMerge:
    """LlamaIndex's auto-merging retriever as a post-processor: when at least `threshold` of a
    parent's children were retrieved, they are replaced by the parent (one coherent passage
    instead of fragments), and again one level up, up to `max_levels`. Needs `hierarchical`
    chunks; any other chunk passes through unchanged."""

    def __init__(self, p: AutoMergeParams) -> None:
        self.p = p

    def _once(self, hits: list[ScoredChunk]) -> tuple[list[ScoredChunk], bool]:
        groups: dict[str, list[int]] = {}
        for i, h in enumerate(hits):
            anc = h.chunk.metadata.get("ancestors") or []
            if anc and anc[-1].get("text"):
                groups.setdefault(str(anc[-1]["id"]), []).append(i)
        merge: dict[int, ScoredChunk] = {}
        drop: set[int] = set()
        present = {h.chunk.id: i for i, h in enumerate(hits)}
        for pid, idx in groups.items():
            parent = (hits[idx[0]].chunk.metadata["ancestors"])[-1]
            distinct = list(dict.fromkeys(hits[i].chunk.id for i in idx))
            n = max(1, int(parent.get("children") or 1))
            if len(distinct) < self.p.min_children or len(distinct) / n < self.p.threshold:
                continue
            first = hits[idx[0]]
            anc = list(first.chunk.metadata["ancestors"])[:-1]
            best = max(hits[i].score for i in idx)
            node = _node_chunk(first.chunk, parent, anc, distinct)
            merge[idx[0]] = replace(first, chunk=node).with_score(best, "auto_merge")
            drop |= set(idx[1:])
            if pid in present and present[pid] not in idx:  # the parent itself was also indexed
                drop.add(present[pid])
        if not merge:
            return hits, False
        return [merge.get(i, h) for i, h in enumerate(hits) if i not in drop], True

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        hits = list(candidates)
        for _ in range(self.p.max_levels):
            hits, changed = self._once(hits)
            if not changed:
                break
        return hits


@register("postprocessor", "auto-merge", params=AutoMergeParams,
          summary="enough children of one parent retrieved (hierarchical chunks): return the parent instead, recursively")  # fmt: skip
def _auto_merge(p: AutoMergeParams, c: Container) -> AutoMerge:
    return AutoMerge(p)


# ================================================================ summaries (RAPTOR, document summary)

SUMMARY_SYSTEM = "You summarise documents faithfully, using only facts stated in the text."
SUMMARY_PROMPT = """Summarise the following text in at most {n} sentences. Keep names, numbers
and terms exactly as written. Answer with the summary only.

{text}"""


class _Summariser:
    """An LLM summary when one is configured AND its output is grounded in the text; otherwise
    (offline, or the model refused or invented) an extractive summary of the central sentences."""

    def __init__(self, c: Container, use_llm: bool, llm_slot: str, min_overlap: float,
                 max_input_tokens: int, max_sentences: int) -> None:  # fmt: skip
        self.c, self.use_llm, self.slot, self.min_overlap = c, use_llm, llm_slot, min_overlap
        self.max_chars, self.n = max_input_tokens * 4, max_sentences

    def __call__(self, texts: Sequence[str]) -> tuple[str, str]:
        joined = "\n\n".join(texts)[: self.max_chars]
        if self.use_llm and self.c.has(self.slot):
            try:
                reply = (
                    self.c.get(self.slot)
                    .complete(
                        SUMMARY_SYSTEM,
                        SUMMARY_PROMPT.format(n=self.n, text=joined),
                        max_tokens=60 * self.n,
                    )
                    .strip()
                )
            except (RuntimeError, OSError, ValueError):
                reply = ""
            if grounded(reply, joined, self.min_overlap):
                return reply, "llm"
        return extractive_summary(texts, self.n), "extractive"


class SummaryTreeParams(_Strict):
    cluster_size: int = Field(5, ge=2, le=50)  # about this many chunks per cluster
    max_levels: int = Field(3, ge=1, le=6)
    min_chunks: int = Field(3, ge=2)  # documents with fewer chunks get no tree
    max_sentences: int = Field(4, ge=1, le=20)  # per summary
    use_llm: bool = True  # False: always extractive (free, offline)
    llm_slot: LlmSlot = "llm"
    min_overlap: float = Field(0.5, ge=0, le=1)  # an LLM summary must reuse this share of its words
    max_input_tokens: int = Field(6000, ge=200)


def kmeans(vectors: Sequence[Sequence[float]], k: int, iterations: int = 10) -> list[list[int]]:
    """Deterministic k-means by cosine (centroids start evenly spaced): clusters of indexes,
    ordered by their first member."""
    n = len(vectors)
    k = max(1, min(k, n))
    centroids = [list(vectors[round(i * (n - 1) / max(1, k - 1))]) if k > 1 else list(vectors[0])
                 for i in range(k)]  # fmt: skip
    assign = [0] * n
    for _ in range(iterations):
        new = [max(range(k), key=lambda j, v=v: cosine(v, centroids[j])) for v in vectors]  # type: ignore[misc]
        if new == assign and _ > 0:
            break
        assign = new
        for j in range(k):
            members = [vectors[i] for i in range(n) if assign[i] == j]
            if members:
                centroids[j] = [sum(col) / len(members) for col in zip(*members, strict=True)]
    groups: dict[int, list[int]] = {}
    for i, j in enumerate(assign):
        groups.setdefault(j, []).append(i)
    return sorted(groups.values(), key=lambda g: g[0])


_NODE_KEYS = (*SECTION_KEYS, "ancestors", "parent_id", "node_kind", "node_level", "window",
              "parent_text", "children", "tree_level", "summary_by", "context", "questions")  # fmt: skip


def _common(chunks: Sequence[Chunk]) -> dict[str, Any]:
    """The metadata every chunk shares (title, document fields, language…), for a summary of them."""
    first = chunks[0].metadata
    return {k: v for k, v in first.items() if k not in _NODE_KEYS
            and all(c.metadata.get(k) == v for c in chunks[1:])}  # fmt: skip


class SummaryTree:
    """RAPTOR (Sarthi et al., 2024), per document: cluster the chunks by embedding, summarise each
    cluster, then cluster and summarise the summaries, up to a root. The summaries are indexed
    next to the chunks, so "what is this policy about?" matches a summary and "how many weeks?"
    matches a detailed chunk. Each summary records the ids of the nodes it summarises."""

    def __init__(self, c: Container, p: SummaryTreeParams) -> None:
        self.c, self.p = c, p
        self.summarise = _Summariser(c, p.use_llm, p.llm_slot, p.min_overlap, p.max_input_tokens,
                                     p.max_sentences)  # fmt: skip

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]:
        level_items = [c for c in chunks if c.metadata.get("node_kind") not in SUMMARY_KINDS]
        if len(level_items) < self.p.min_chunks:
            return chunks
        embedder, counter = self.c.get("embedder"), _counter(self.c)
        out = list(chunks)
        next_index = max((c.index for c in chunks), default=-1) + 1
        for level in range(1, self.p.max_levels + 1):
            k = math.ceil(len(level_items) / self.p.cluster_size)
            if len(level_items) < 2 or k >= len(level_items):
                break
            vectors = embedder.embed_documents([c.indexed_text for c in level_items])
            new: list[Chunk] = []
            for group in kmeans(vectors, k):
                members = [level_items[i] for i in group]
                text, by = self.summarise([m.text for m in members])
                if not text:
                    continue
                meta = {**_common(members), "section": "", "node_kind": "summary", "tree_level": level,
                        "children": [m.id for m in members], "summary_by": by}  # fmt: skip
                new.append(Chunk(id=Chunk.make_id(document.uri, next_index, text), document_uri=document.uri,
                                 index=next_index, text=text, token_count=counter.count(text),
                                 access=document.access, metadata=meta))  # fmt: skip
                next_index += 1
            out += new
            level_items = new
            if k == 1:
                break
        return out


@register("enricher", "summary-tree", params=SummaryTreeParams,
          summary="RAPTOR: cluster chunks, summarise clusters recursively (LLM, extractive offline), index the summaries")  # fmt: skip
def _summary_tree(p: SummaryTreeParams, c: Container) -> SummaryTree:
    return SummaryTree(c, p)


class DocSummaryParams(_Strict):
    max_sentences: int = Field(5, ge=1, le=30)
    index: bool = True  # add the summary as a chunk of its own (a "document summary index")
    attach: bool = False  # also put it in every chunk's metadata as doc_summary
    use_llm: bool = True
    llm_slot: LlmSlot = "llm"
    min_overlap: float = Field(0.5, ge=0, le=1)
    max_input_tokens: int = Field(8000, ge=200)


class DocumentSummary:
    """One summary per document, indexed as its own chunk (node_kind "document-summary"): the
    "document summary index" (LlamaIndex). Broad questions find the right document by its
    summary; `summary-expand` then brings that document's best detailed chunks."""

    def __init__(self, c: Container, p: DocSummaryParams) -> None:
        self.c, self.p = c, p
        self.summarise = _Summariser(c, p.use_llm, p.llm_slot, p.min_overlap, p.max_input_tokens,
                                     p.max_sentences)  # fmt: skip

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]:
        base = [c for c in chunks if c.metadata.get("node_kind") not in SUMMARY_KINDS]
        if not base:
            return chunks
        text, by = self.summarise([c.text for c in base])
        if not text:
            return chunks
        out = (
            [replace(c, metadata={**c.metadata, "doc_summary": text}) for c in chunks]
            if self.p.attach
            else list(chunks)
        )
        if self.p.index:
            i = max(c.index for c in chunks) + 1
            meta = {**_common(base), "section": "", "node_kind": "document-summary", "summary_by": by,
                    "children": [c.id for c in base]}  # fmt: skip
            out.append(Chunk(id=Chunk.make_id(document.uri, i, text), document_uri=document.uri, index=i, text=text,
                             token_count=_counter(self.c).count(text), access=document.access, metadata=meta))  # fmt: skip
        return out


@register("enricher", "summary", params=DocSummaryParams,
          summary="one summary per document, indexed as a chunk (document summary index) and/or attached to every chunk")  # fmt: skip
def _doc_summary(p: DocSummaryParams, c: Container) -> DocumentSummary:
    return DocumentSummary(c, p)


# ================================================================ looking sections up


def fetch(
    c: Container, principal: Principal, filters: dict[str, Any], k: int, text: str
) -> list[ScoredChunk]:
    """Chunks matching a filter, through the profile's own stores (so permissions apply): the
    vector store when there is one (every row matching the filter is a candidate), else the
    keyword index (which needs `text` to share a word with them)."""
    if c.has("vector_store"):
        vec = c.get("embedder").embed_query(text)
        return list(c.get("vector_store").search(vec, principal, k, filters))
    if c.has("keyword_index"):
        return list(c.get("keyword_index").search(text, principal, k, filters))
    return []


def join_section(
    chunks: Sequence[Chunk], counter: Any, budget: int, around: int | None = None
) -> str:
    """The chunks of one section as one passage, in document order, without the sentences the
    chunker repeated as overlap; over the budget, the chunks nearest `around` are kept."""
    ordered = sorted({c.id: c for c in chunks}.values(), key=lambda c: c.index)
    if around is not None and ordered:
        centre = min(range(len(ordered)), key=lambda i: abs(ordered[i].index - around))
        picked, used = {centre}, counter.count(ordered[centre].text)
        lo, hi = centre - 1, centre + 1
        while lo >= 0 or hi < len(ordered):
            for j in (hi, lo):
                if 0 <= j < len(ordered) and j not in picked:
                    n = counter.count(ordered[j].text)
                    if used + n <= budget:
                        picked.add(j)
                        used += n
            lo, hi = lo - 1, hi + 1
        ordered = [ordered[i] for i in sorted(picked)]
    seen: set[str] = set()
    parts: list[str] = []
    for c in ordered:
        fresh = [s for s in (sentences(c.text) or [c.text]) if s not in seen]
        seen.update(fresh)
        if fresh:
            parts.append(" ".join(fresh) if len(fresh) > 1 or "\n" not in c.text else c.text)
    text = "\n\n".join(parts)
    while parts and counter.count(text) > budget and len(parts) > 1:
        parts.pop()
        text = "\n\n".join(parts)
    return text


def _section_chunk(first: Chunk, text: str, ids: list[str], counter: Any, how: str) -> Chunk:
    return replace(first, text=text, embed_text="", token_count=counter.count(text),
                   metadata={**first.metadata, "expanded": how, "expanded_from": ids})  # fmt: skip


class SectionExpandParams(_Strict):
    max_tokens: int = Field(1200, ge=50)  # a section bigger than this: the part around the hit
    include_subsections: bool = False  # "4.2" also brings 4.2.1, 4.2.2 …
    max_hits: int = Field(8, ge=1, le=50)  # expand at most this many (each may cost a lookup)
    max_chunks: int = Field(60, ge=1, le=500)  # chunks read per section


class SectionExpand:
    """Replace each hit by the whole section it belongs to (up to `max_tokens`), so the model reads
    the full rule, not one fragment of it. Hits from the same section become one candidate.
    Hierarchical chunks carry their section's text already; other chunks are looked up with a
    filtered search on `document` + `section` (structure, parent-child, proposition chunks…)."""

    def __init__(self, c: Container, p: SectionExpandParams) -> None:
        self.c, self.p = c, p

    def _section(self, query: Query, h: ScoredChunk) -> tuple[str, list[str]] | None:
        meta = h.chunk.metadata
        counter = _counter(self.c)
        for anc in reversed(meta.get("ancestors") or []):  # hierarchical: no lookup needed
            if (
                anc.get("kind") == "section"
                and anc.get("text")
                and int(anc.get("tokens") or 0) <= self.p.max_tokens
            ):
                return str(anc["text"]), [h.chunk.id]
        section = str(meta.get("section") or "")
        if not section:
            return None
        wanted: dict[str, Any] = {"document": h.chunk.document_uri}
        wanted |= {"section_path": section} if self.p.include_subsections else {"section": section}
        found = fetch(self.c, query.principal, _filters.combine(query.filters, wanted), self.p.max_chunks,
                      str(meta.get("heading") or section))  # fmt: skip
        chunks = [f.chunk for f in found if f.chunk.metadata.get("node_kind") not in SUMMARY_KINDS]
        if h.chunk.id not in {c.id for c in chunks}:
            chunks.append(h.chunk)
        return join_section(chunks, counter, self.p.max_tokens, around=h.chunk.index), [
            c.id for c in chunks
        ]

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        out: list[ScoredChunk] = []
        done: dict[tuple[str, str], int] = {}
        counter = _counter(self.c)
        for n, h in enumerate(candidates):
            key = (h.chunk.document_uri, str(h.chunk.metadata.get("section") or ""))
            if n >= self.p.max_hits or not key[1]:
                out.append(h)
                continue
            if key in done:  # this section is already in, with this hit's text
                continue
            got = self._section(query, h)
            if got is None:
                out.append(h)
                continue
            done[key] = len(out)
            out.append(
                replace(h, chunk=_section_chunk(h.chunk, got[0], got[1], counter, "section"))
            )
        return out


@register("postprocessor", "section-expand", params=SectionExpandParams,
          summary="replace a hit by the whole section it belongs to, within a token budget; hits of one section merge")  # fmt: skip
def _section_expand(p: SectionExpandParams, c: Container) -> SectionExpand:
    return SectionExpand(c, p)


class SummaryExpandParams(_Strict):
    per_summary: int = Field(3, ge=1, le=20)  # detailed chunks added for each summary found
    keep_summary: bool = True


class SummaryExpand:
    """A summary (summary-tree or document summary) was retrieved: add the best detailed chunks of
    its document for this question, right after it (or instead of it)."""

    def __init__(self, c: Container, p: SummaryExpandParams) -> None:
        self.c, self.p = c, p

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        seen = {h.chunk.id for h in candidates}
        out: list[ScoredChunk] = []
        for h in candidates:
            if h.chunk.metadata.get("node_kind") not in SUMMARY_KINDS:
                if h.chunk.id not in {o.chunk.id for o in out}:
                    out.append(h)
                continue
            if self.p.keep_summary:
                out.append(h)
            wanted = {"document": h.chunk.document_uri, "node_kind": {"nin": list(SUMMARY_KINDS)}}
            for i, d in enumerate(fetch(self.c, query.principal, _filters.combine(query.filters, wanted),
                                        self.p.per_summary, query.text)):  # fmt: skip
                if d.chunk.id not in seen:
                    seen.add(d.chunk.id)
                    out.append(d.with_score(h.score - (i + 1) * 1e-6, "summary_expand"))
        return out


@register("postprocessor", "summary-expand", params=SummaryExpandParams,
          summary="a retrieved summary brings its document's best detailed chunks for the question")  # fmt: skip
def _summary_expand(p: SummaryExpandParams, c: Container) -> SummaryExpand:
    return SummaryExpand(c, p)


# ================================================================ the section retriever

SECTION_REF = re.compile(
    r"(?:\bsection|\bsec\.|§|\bchapter|\bclause|\bpart|\barticle|\bappendix|\bannex)\s*"
    r"(\d+(?:\.\d+)*|[A-Z]\b)", re.IGNORECASE,
)  # fmt: skip
SECTION_CUE = re.compile(
    r"\b(section|sections|chapter|part|heading|clause|article|appendix|annex|paragraph)\b|§", re.I
)


class SectionParams(_Strict):
    inner: dict[str, Any] | None = None  # the retriever for everything else; default: the profile's
    scan: int = Field(10, ge=1, le=100)  # top hits whose headings are compared with the question
    max_tokens: int = Field(2000, ge=50)  # the section as one candidate, within this budget
    max_chunks: int = Field(80, ge=1, le=500)
    require_cue: bool = True  # a heading title only counts when the question says "section", …


class SectionRetriever:
    """Returns EXACTLY the section asked for, as one candidate at the top, then the usual results.
    "What does section 4.2 say?" → the chunks whose `section_numbers` contain "4.2" (in the
    document that ranks best for the question); "Show me the Parental leave section" → the
    deepest heading whose words are all in the question, among the top hits."""

    def __init__(self, c: Container, p: SectionParams, inner: Any) -> None:
        self.c, self.p, self.inner = c, p, inner
        self._info: dict[str, Any] = {}

    @property
    def _fusion(self) -> Any:  # the search trace names the inner retriever's fusion
        return getattr(self.inner, "_fusion", None)

    def last_info(self) -> dict[str, Any]:
        return dict(self._info)

    def _by_title(self, query: Query, hits: list[ScoredChunk]) -> tuple[str, str] | None:
        if self.p.require_cue and not SECTION_CUE.search(query.text):
            return None
        asked = {w for w in content_words(query.text) if not w.isdigit()}
        best: tuple[int, int, int] | None = None
        found = None
        for rank, h in enumerate(hits[: self.p.scan]):
            paths = list(h.chunk.metadata.get("section_path") or [])
            for depth, path in enumerate(paths):
                ws = {w for w in content_words(path.split(" > ")[-1]) if not w.isdigit()}
                if ws and ws <= asked:
                    key = (len(ws), depth, -rank)
                    if best is None or key > best:
                        best, found = key, (h.chunk.document_uri, path)
        return found

    def retrieve(self, query: Query, texts: Sequence[str]) -> list[ScoredChunk]:
        hits = list(self.inner.retrieve(query, texts))
        self._info = {"inner": type(self.inner).__name__}
        m = SECTION_REF.search(query.text)
        wanted: dict[str, Any] | None = None
        if m:
            number = m.group(1).rstrip(".")
            number = number.upper() if number.isalpha() else number
            wanted = {"section_numbers": number}
            self._info["section"] = {"number": number}
        elif (t := self._by_title(query, hits)) is not None:
            wanted = {"document": t[0], "section_path": t[1]}
            self._info["section"] = {"heading": t[1], "document": t[0]}
        if wanted is None:
            return hits
        found = [f.chunk for f in fetch(self.c, query.principal, _filters.combine(query.filters, wanted),
                                        self.p.max_chunks, query.text)
                 if f.chunk.metadata.get("node_kind") not in SUMMARY_KINDS]  # fmt: skip
        if not found:
            self._info["section"]["found"] = 0
            return hits
        rank = {h.chunk.document_uri: i for i, h in reversed(list(enumerate(hits)))}
        uri = min({c.document_uri for c in found}, key=lambda u: (rank.get(u, len(hits)), u))
        chunks = [c for c in found if c.document_uri == uri]
        counter = _counter(self.c)
        text = join_section(chunks, counter, self.p.max_tokens)
        first = min(chunks, key=lambda c: c.index)
        top = max((h.score for h in hits), default=0.0) + 1.0
        section = ScoredChunk(_section_chunk(first, text, [c.id for c in chunks], counter, "section-lookup"),
                              top, {"section": top})  # fmt: skip
        self._info["section"] |= {"found": len(chunks), "document": uri}
        inside = {c.id for c in chunks}
        return [section, *[h for h in hits if h.chunk.id not in inside]]


@register("retriever", "section", params=SectionParams,
          summary='"section 4.2" or a heading title in the question: that exact section first, then the usual results')  # fmt: skip
def _section(p: SectionParams, c: Container) -> SectionRetriever:
    if p.inner is not None:
        raw = dict(p.inner)
        s = spec("retriever", str(raw.pop("use")))
        inner = s.factory(s.params.model_validate(raw), c)
    else:  # what the profile has: hybrid with both stores, else the one it has
        from rag_core.components.retrieval import (
            DenseRetriever,
            HybridRetriever,
            KeywordRetriever,
            RetrieverParams,
        )

        dense, sparse = c.has("vector_store"), c.has("keyword_index")
        cls = HybridRetriever if dense and sparse else DenseRetriever if dense else KeywordRetriever
        inner = cls(c, RetrieverParams())
    return SectionRetriever(c, p, inner)
