"""Chunkers: how documents are cut into the pieces that are embedded, found and cited (Step 31).

The single biggest lever on retrieval quality after the embedding model. Too big: one chunk is
about many things and matches everything weakly. Too small: the answer is split across pieces.
Six strategies, all switchable in rag.yaml; Step 26's harness decides which wins on YOUR documents.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core.components.basics import cosine
from rag_core.registry import Container, register
from rag_core.types import Chunk, Document, Element

SENTENCE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9\"'(\[])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.split(text) if s.strip()]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SizeParams(_Strict):
    max_tokens: int = Field(400, ge=16, le=8192)
    overlap_tokens: int = Field(40, ge=0)

    @model_validator(mode="after")
    def _overlap(self) -> SizeParams:
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")
        return self


def _filterable(value: Any) -> bool:
    """Source metadata copied to every chunk: scalars, and lists of scalars such as tags (extension
    01: what metadata filters can test). Nested objects stay on the document."""
    scalar = str | int | float | bool
    if isinstance(value, list | tuple):
        return all(isinstance(v, scalar) for v in value)
    return isinstance(value, scalar)


SECTION_NUMBER = re.compile(
    r"^(?:(?:section|sec\.|chapter|part|clause|article|appendix|annex|§)\s*)?(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)(?=[.):]?\s|[.):]?$)",
    re.IGNORECASE,
)


def section_number(heading: str) -> str | None:
    """ "4.2 Parental leave" -> "4.2"; "Section 3: Pay" -> "3"; "Appendix B" -> "B"; else None."""
    m = SECTION_NUMBER.match(heading.strip())
    if not m:
        return None
    num = m.group(1)
    # a lone letter only counts after a word like "Appendix" ("A guide to…" is not section A)
    if num.isalpha() and not re.match(r"^(?:section|chapter|part|appendix|annex)\b", heading, re.I):
        return None
    return num.rstrip(".").upper() if num.isalpha() else num.rstrip(".")


SECTION_KEYS = ("section", "heading", "section_path", "section_numbers")


def section_meta(path: list[str]) -> dict[str, Any]:
    """Where a chunk sits (extension 02), recorded so a filter can pick a section: `section`
    "Leave > Parental leave" (the path), `heading` "Parental leave" (the nearest heading),
    `section_path` ["Leave", "Leave > Parental leave"] (every enclosing section, so
    `{"section_path": "Leave"}` matches the whole chapter) and `section_numbers` ["4", "4.2"]
    when the headings are numbered."""
    if not path:
        return {"section": ""}
    meta: dict[str, Any] = {"section": " > ".join(path), "heading": path[-1],
                            "section_path": [" > ".join(path[: i + 1]) for i in range(len(path))]}  # fmt: skip
    numbers = [n for n in (section_number(h) for h in path) if n]
    if numbers:
        meta["section_numbers"] = numbers
    return meta


class _Base:
    def __init__(self, counter: Any) -> None:
        self.counter = counter

    def _make(self, doc: Document, pieces: Iterable[tuple[str, dict[str, Any]]]) -> list[Chunk]:
        out = []
        for i, (text, meta) in enumerate(p for p in pieces if p[0].strip()):
            text = text.strip()
            out.append(Chunk(
                id=Chunk.make_id(doc.uri, i, text), document_uri=doc.uri, index=i, text=text,
                token_count=self.counter.count(text), access=doc.access,
                metadata={"title": doc.title, "doc_sha256": doc.sha256, "language": doc.language,
                            **{k: v for k, v in doc.metadata.items() if _filterable(v)}, **meta},
            ))  # fmt: skip
        return out

    def _windows(
        self, units: list[str], max_tokens: int, overlap: int, joiner: str = " "
    ) -> list[str]:
        """Greedy packing of units (words, sentences, …) into windows of max_tokens, with overlap."""
        out: list[str] = []
        cur: list[str] = []
        size = 0
        for u in units:
            n = self.counter.count(u)
            if n > max_tokens:  # a single unit too big: hard split by words
                if cur:
                    out.append(joiner.join(cur))
                    cur, size = [], 0
                ws = u.split()
                step = max(1, max_tokens - overlap)
                out += [" ".join(ws[i : i + max_tokens]) for i in range(0, len(ws), step)]
                continue
            if cur and size + n > max_tokens:
                out.append(joiner.join(cur))
                keep: list[str] = []
                kept = 0
                for prev in reversed(cur):  # carry the tail over: context across the cut
                    t = self.counter.count(prev)
                    if kept + t > overlap:
                        break
                    keep.insert(0, prev)
                    kept += t
                cur, size = keep, kept
            cur.append(u)
            size += n
        if cur:
            out.append(joiner.join(cur))
        return out


class FixedChunker(_Base):
    """Every N tokens, with overlap. Simple and predictable; ignores structure."""

    def __init__(self, counter: Any, max_tokens: int, overlap: int) -> None:
        super().__init__(counter)
        self.max_tokens, self.overlap = max_tokens, overlap

    def chunk(self, document: Document) -> list[Chunk]:
        return self._make(
            document,
            ((t, {}) for t in self._windows(document.text.split(), self.max_tokens, self.overlap)),
        )


@register(
    "chunker",
    "fixed",
    params=SizeParams,
    summary="every N tokens with overlap; ignores structure (baseline)",
)
def _fixed(p: SizeParams, c: Container) -> FixedChunker:
    return FixedChunker(c.get("token_counter"), p.max_tokens, p.overlap_tokens)


class RecursiveChunker(_Base):
    """Split on paragraphs, then sentences, then words, only as far as needed to fit."""

    def __init__(self, counter: Any, max_tokens: int, overlap: int) -> None:
        super().__init__(counter)
        self.max_tokens, self.overlap = max_tokens, overlap

    def chunk(self, document: Document) -> list[Chunk]:
        units: list[str] = []
        for e in document.elements:
            if self.counter.count(e.text) <= self.max_tokens:
                units.append(e.text)
            else:
                units += sentences(e.text) or [e.text]
        return self._make(
            document, ((t, {}) for t in self._windows(units, self.max_tokens, self.overlap, "\n\n"))
        )


@register(
    "chunker",
    "recursive",
    params=SizeParams,
    summary="paragraphs, then sentences, then words: only as fine as needed",
)
def _recursive(p: SizeParams, c: Container) -> RecursiveChunker:
    return RecursiveChunker(c.get("token_counter"), p.max_tokens, p.overlap_tokens)


class StructureParams(SizeParams):
    min_tokens: int = Field(60, ge=0)  # merge tiny sections into the next one
    heading_path: bool = True  # "Leave policy > Parental leave" in metadata and embed text


class StructureChunker(_Base):
    """Section-aware: chunks never cross a heading; tables and code blocks stay whole (a big table
    is split by rows with its header repeated); each chunk knows its heading path."""

    def __init__(self, counter: Any, p: StructureParams) -> None:
        super().__init__(counter)
        self.p = p

    def _sections(self, doc: Document) -> list[tuple[list[str], list[Element]]]:
        path: list[str] = []
        sections: list[tuple[list[str], list[Element]]] = [([], [])]
        for e in doc.elements:
            if e.kind in ("heading", "title"):
                level = max(1, e.level)
                path = [*path[: level - 1], e.text]
                sections.append((list(path), []))
            else:
                sections[-1][1].append(e)
        return [s for s in sections if s[1]]

    def _units(self, e: Element) -> list[str]:
        if self.counter.count(e.text) <= self.p.max_tokens:
            return [e.text]
        if e.kind == "table":
            rows = e.text.split("\n")
            header, body = rows[0], rows[1:]
            out, cur = [], [header]
            for r in body:
                if self.counter.count("\n".join([*cur, r])) > self.p.max_tokens and len(cur) > 1:
                    out.append("\n".join(cur))
                    cur = [header]  # repeat the header: each part of a table stays readable
                cur.append(r)
            return [*out, "\n".join(cur)]
        if e.kind == "code":  # code is cut between lines, never mid-statement by a sentence rule
            return self._windows(e.text.split("\n"), self.p.max_tokens, 0, "\n")
        return self._windows(
            sentences(e.text) or [e.text], self.p.max_tokens, self.p.overlap_tokens
        )

    def chunk(self, document: Document) -> list[Chunk]:
        sections = [(path, self._windows([u for e in els for u in self._units(e)], self.p.max_tokens,
                                    self.p.overlap_tokens, "\n\n")) for path, els in self._sections(document)]  # fmt: skip
        # A tiny section (a two-line "Purpose" paragraph) on its own makes a weak chunk: join it to
        # the next section if both fit, labelled with the heading path they share.
        merged: list[tuple[list[str], list[str]]] = []
        joined_last = False  # one join per tiny section: never snowball several sections into one
        for path, texts in sections:
            if merged and not joined_last:
                prev_path, prev = merged[-1]
                if (len(prev) == 1 and self.counter.count(prev[0]) < self.p.min_tokens and texts
                        and self.counter.count(prev[0] + texts[0]) <= self.p.max_tokens):  # fmt: skip
                    common = [a for a, b in zip(prev_path, path, strict=False) if a == b]
                    merged[-1] = (common or prev_path, [prev[0] + "\n\n" + texts[0], *texts[1:]])
                    joined_last = True
                    continue
            joined_last = False
            merged.append((path, list(texts)))
        pieces = [(t, section_meta(path)) for path, texts in merged for t in texts]
        return self._make(document, pieces)


@register("chunker", "structure", params=StructureParams,
            summary="section-aware: never crosses headings, keeps tables/code whole, records the heading path")  # fmt: skip
def _structure(p: StructureParams, c: Container) -> StructureChunker:
    return StructureChunker(c.get("token_counter"), p)


class WindowParams(_Strict):
    window: int = Field(2, ge=0, le=10)  # sentences of context on each side


class SentenceWindowChunker(_Base):
    """One sentence per chunk (precise matching), with the surrounding sentences stored in
    metadata["window"]; the window replaces the sentence when it goes to the model (Step 32)."""

    def __init__(self, counter: Any, window: int) -> None:
        super().__init__(counter)
        self.window = window

    def chunk(self, document: Document) -> list[Chunk]:
        pieces = []
        for e in document.elements:
            sents = sentences(e.text) or [e.text]
            for i, s in enumerate(sents):
                ctx = " ".join(sents[max(0, i - self.window) : i + self.window + 1])
                pieces.append((s, {"window": ctx}))
        return self._make(document, pieces)


@register("chunker", "sentence-window", params=WindowParams,
            summary="one sentence per chunk for precise matching; neighbours kept for the answer")  # fmt: skip
def _swindow(p: WindowParams, c: Container) -> SentenceWindowChunker:
    return SentenceWindowChunker(c.get("token_counter"), p.window)


class SemanticParams(SizeParams):
    breakpoint_percentile: float = Field(90, gt=0, lt=100)  # cut where similarity drops most


class SemanticChunker(_Base):
    """Cuts where the topic changes: embeds every sentence and splits at the biggest drops in
    similarity between neighbours. Costs one embedding per sentence at ingestion."""

    def __init__(self, counter: Any, embedder: Any, p: SemanticParams) -> None:
        super().__init__(counter)
        self.embedder, self.p = embedder, p

    def chunk(self, document: Document) -> list[Chunk]:
        sents = [s for e in document.elements for s in (sentences(e.text) or [e.text])]
        if len(sents) < 3:
            return self._make(document, [(" ".join(sents), {})])
        vecs = self.embedder.embed_documents(sents)
        sims = [cosine(a, b) for a, b in itertools.pairwise(vecs)]
        cut_at = sorted(sims)[int(len(sims) * (1 - self.p.breakpoint_percentile / 100))]
        groups: list[list[str]] = [[sents[0]]]
        for s, sim in zip(sents[1:], sims, strict=True):
            if sim <= cut_at:
                groups.append([])
            groups[-1].append(s)
        texts = [
            t for g in groups for t in self._windows(g, self.p.max_tokens, self.p.overlap_tokens)
        ]
        return self._make(document, ((t, {}) for t in texts))


@register("chunker", "semantic", params=SemanticParams,
            summary="cuts where the topic changes (sentence-embedding similarity drops); slower to ingest")  # fmt: skip
def _semantic(p: SemanticParams, c: Container) -> SemanticChunker:
    return SemanticChunker(c.get("token_counter"), c.get("embedder"), p)


class ParentChildParams(_Strict):
    parent_tokens: int = Field(1200, ge=64)
    child_tokens: int = Field(200, ge=16)
    child_overlap: int = Field(20, ge=0)


class ParentChildChunker(_Base):
    """Small children are searched (precise), their big parent is what the model reads (complete).
    Children carry parent_id and the parent's text; expansion happens in Step 32's post-processing."""

    def __init__(self, counter: Any, p: ParentChildParams) -> None:
        super().__init__(counter)
        self.parents = StructureChunker(
            counter, StructureParams(max_tokens=p.parent_tokens, overlap_tokens=0, min_tokens=0)
        )
        self.p = p

    def chunk(self, document: Document) -> list[Chunk]:
        pieces = []
        for parent in self.parents.chunk(document):
            for t in self._windows(
                sentences(parent.text) or [parent.text], self.p.child_tokens, self.p.child_overlap
            ):
                pieces.append((t, {"parent_id": parent.id, "parent_text": parent.text, "section": "",
                            **{k: v for k, v in parent.metadata.items() if k in SECTION_KEYS}}))  # fmt: skip
        chunks = self._make(document, pieces)
        return [replace(c, parent_id=str(c.metadata["parent_id"])) for c in chunks]


@register("chunker", "parent-child", params=ParentChildParams,
            summary="search small chunks, give the model their larger parent section")  # fmt: skip
def _parent_child(p: ParentChildParams, c: Container) -> ParentChildChunker:
    return ParentChildChunker(c.get("token_counter"), p)
