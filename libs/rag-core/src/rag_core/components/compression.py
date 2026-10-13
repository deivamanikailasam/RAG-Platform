"""Context compression (extension 02): send the model only what matters for THIS question.

Retrieved chunks are written for every reader, not for one question: most of their sentences are
irrelevant to it. Compressors run in the answer pipeline after the context guards and before the
context builder, in the order listed, and the trace records the tokens before and after:

    compressors:
      - {use: embedding-filter, threshold: 0.25}      # drop chunks that don't match at all
      - {use: extractive, threshold: 0.3}             # keep the sentences that do

A compressor keeps each chunk's id, document and metadata (so citations still point at the right
source) and only shortens its text, or drops the chunk. `rag search` is unaffected: compression
is for the model's context, not for ranking.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core.components.basics import cosine
from rag_core.registry import Container, register
from rag_core.text import content_words, grounded, overlap, sentences
from rag_core.types import Query, ScoredChunk

log = logging.getLogger("rag_core.compression")
LlmSlot = Literal["llm", "judge_llm", "answer_llm"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _with_text(h: ScoredChunk, text: str, how: str) -> ScoredChunk:
    meta = {**h.chunk.metadata, "compressed": [*h.chunk.metadata.get("compressed", []), how]}
    return replace(h, chunk=replace(h.chunk, text=text, metadata=meta))


def _query_words(query: Query) -> set[str]:
    return set(content_words(query.text))


# ================================================================ extractive


class ExtractiveParams(_Strict):
    method: Literal["overlap", "embedding"] = (
        "overlap"  # term overlap (free) or embedding similarity
    )
    threshold: float = Field(0.2, ge=0, le=1)  # a sentence below this is dropped
    max_sentences: int = Field(0, ge=0)  # per chunk; 0 = every sentence above the threshold
    neighbours: int = Field(0, ge=0, le=3)  # keep this many sentences around each kept one
    drop_empty: bool = False  # no sentence passes: drop the chunk (False: keep its best sentence)


class ExtractiveCompressor:
    """Keeps only the sentences relevant to the question, in their original order: scored by the
    share of the question's content words they contain, or by embedding similarity."""

    def __init__(self, p: ExtractiveParams, embedder: Any = None) -> None:
        self.p, self.embedder = p, embedder

    def _scores(self, query: Query, sents: list[str]) -> list[float]:
        if self.p.method == "embedding":
            q = self.embedder.embed_query(query.text)
            return [cosine(q, v) for v in self.embedder.embed_documents(sents)]
        qw = _query_words(query)
        return [len(qw & set(content_words(s))) / len(qw) if qw else 0.0 for s in sents]

    def compress(self, query: Query, hits: Sequence[ScoredChunk]) -> list[ScoredChunk]:
        out = []
        for h in hits:
            sents = sentences(h.chunk.text)
            if len(sents) < 2:
                score = self._scores(query, sents or [h.chunk.text])[0]
                if score < self.p.threshold and self.p.drop_empty:
                    continue
                out.append(h)
                continue
            scores = self._scores(query, sents)
            ranked = sorted(
                (i for i, s in enumerate(scores) if s >= self.p.threshold), key=lambda i: -scores[i]
            )
            if self.p.max_sentences:
                ranked = ranked[: self.p.max_sentences]
            if not ranked:
                if self.p.drop_empty:
                    continue
                ranked = [max(range(len(sents)), key=lambda i: scores[i])]
            keep = {j for i in ranked for j in range(i - self.p.neighbours, i + self.p.neighbours + 1)
                    if 0 <= j < len(sents)}  # fmt: skip
            text = " ".join(sents[i] for i in sorted(keep))
            out.append(_with_text(h, text, "extractive") if len(keep) < len(sents) else h)
        return out


@register("compressor", "extractive", params=ExtractiveParams,
          summary="keep only the sentences relevant to the question (term overlap or embedding similarity)")  # fmt: skip
def _extractive(p: ExtractiveParams, c: Container) -> ExtractiveCompressor:
    return ExtractiveCompressor(p, c.get("embedder") if p.method == "embedding" else None)


# ================================================================ embedding filter


class EmbeddingFilterParams(_Strict):
    threshold: float = Field(0.3, ge=-1, le=1)  # cosine similarity to the question
    level: Literal["chunk", "sentence"] = "chunk"
    min_keep: int = Field(1, ge=0)  # never drop below this many chunks (the best ones)


class EmbeddingFilter:
    """LangChain's EmbeddingsFilter: drops chunks (or sentences) whose embedding is less similar to
    the question than `threshold`. One embedding call per chunk or sentence; no LLM."""

    def __init__(self, p: EmbeddingFilterParams, embedder: Any) -> None:
        self.p, self.embedder = p, embedder

    def compress(self, query: Query, hits: Sequence[ScoredChunk]) -> list[ScoredChunk]:
        if not hits:
            return []
        q = self.embedder.embed_query(query.text)
        if self.p.level == "sentence":
            out = []
            for h in hits:
                sents = sentences(h.chunk.text) or [h.chunk.text]
                sims = [cosine(q, v) for v in self.embedder.embed_documents(sents)]
                keep = [s for s, sim in zip(sents, sims, strict=True) if sim >= self.p.threshold]
                if keep:
                    out.append(
                        _with_text(h, " ".join(keep), "embedding-filter")
                        if len(keep) < len(sents)
                        else h
                    )
            if len(out) < self.p.min_keep:
                out += [h for h in hits if h.chunk.id not in {o.chunk.id for o in out}][
                    : self.p.min_keep - len(out)
                ]
            return out
        sims = [cosine(q, v) for v in self.embedder.embed_documents([h.chunk.text for h in hits])]
        best = sorted(range(len(hits)), key=lambda i: -sims[i])[: self.p.min_keep]
        return [h for i, h in enumerate(hits) if sims[i] >= self.p.threshold or i in best]


@register("compressor", "embedding-filter", params=EmbeddingFilterParams,
          summary="drop chunks or sentences whose embedding similarity to the question is below a threshold")  # fmt: skip
def _embedding_filter(p: EmbeddingFilterParams, c: Container) -> EmbeddingFilter:
    return EmbeddingFilter(p, c.get("embedder"))


# ================================================================ LLM extraction

EXTRACT_SYSTEM = "You copy the parts of a document that answer a question. You never rewrite."
EXTRACT_PROMPT = """Question: {question}

Copy, word for word, the sentences of the document below that help answer the question. If none
do, answer exactly NO_OUTPUT.

<document>
{text}
</document>"""
NO_OUTPUT = "NO_OUTPUT"


class LlmExtractParams(_Strict):
    llm_slot: LlmSlot = "llm"
    max_chars: int = Field(6000, ge=200)  # of each chunk sent to the model
    verify: bool = True  # keep only extracted sentences that really occur in the chunk
    fail_open: bool = True  # model error: keep the chunk as it was


class LlmExtract:
    """LangChain's LLMChainExtractor: one LLM call per chunk returns only the relevant sentences
    (or NO_OUTPUT, and the chunk is dropped). With `verify`, every returned sentence must be
    (nearly) word-for-word in the chunk: a model can't slip an invented sentence into the context."""

    def __init__(self, llm: Any, p: LlmExtractParams) -> None:
        self.llm, self.p = llm, p

    def compress(self, query: Query, hits: Sequence[ScoredChunk]) -> list[ScoredChunk]:
        out = []
        for h in hits:
            try:
                reply = self.llm.complete(EXTRACT_SYSTEM, EXTRACT_PROMPT.format(
                    question=query.text, text=h.chunk.text[: self.p.max_chars]), max_tokens=600).strip()  # fmt: skip
            except (RuntimeError, OSError, ValueError) as e:
                if not self.p.fail_open:
                    raise
                log.warning("llm-extract failed, chunk kept whole: %s", e)
                out.append(h)
                continue
            if not reply or reply.startswith(NO_OUTPUT):
                continue
            if self.p.verify:
                kept = [s for s in sentences(reply) if overlap(s, h.chunk.text) >= 0.9]
                if not kept:
                    continue
                reply = " ".join(kept)
            out.append(_with_text(h, reply, "llm-extract"))
        return out


@register("compressor", "llm-extract", params=LlmExtractParams, status="mocked",
          summary="an LLM copies only the relevant sentences of each chunk (LLMChainExtractor); verified against the source")  # fmt: skip
def _llm_extract(p: LlmExtractParams, c: Container) -> LlmExtract:
    return LlmExtract(c.get(p.llm_slot), p)


# ================================================================ LLM summary

SUMMARISE_SYSTEM = "You condense documents for a reader with one question. You never add facts."
SUMMARISE_PROMPT = """Question: {question}

Summarise what the document below says that is relevant to the question, in at most {n}
sentences. Keep numbers, names and terms exactly as written.

<document>
{text}
</document>"""


class SummarizeParams(_Strict):
    llm_slot: LlmSlot = "llm"
    min_tokens: int = Field(150, ge=0)  # shorter chunks are left as they are
    max_sentences: int = Field(3, ge=1, le=20)
    min_overlap: float = Field(0.6, ge=0, le=1)  # the summary must reuse this share of its words
    max_chars: int = Field(12000, ge=200)


class Summarize:
    """Each long chunk becomes a question-focused summary (one LLM call per chunk). A summary
    that isn't grounded in its chunk (invented, or a refusal) is discarded and the chunk is kept."""

    def __init__(self, llm: Any, counter: Any, p: SummarizeParams) -> None:
        self.llm, self.counter, self.p = llm, counter, p

    def compress(self, query: Query, hits: Sequence[ScoredChunk]) -> list[ScoredChunk]:
        out = []
        for h in hits:
            if self.counter.count(h.chunk.text) < self.p.min_tokens:
                out.append(h)
                continue
            try:
                reply = self.llm.complete(SUMMARISE_SYSTEM, SUMMARISE_PROMPT.format(
                    question=query.text, n=self.p.max_sentences, text=h.chunk.text[: self.p.max_chars]),
                    max_tokens=80 * self.p.max_sentences).strip()  # fmt: skip
            except (RuntimeError, OSError, ValueError) as e:
                log.warning("summarize failed, chunk kept whole: %s", e)
                reply = ""
            ok = grounded(reply, h.chunk.text, self.p.min_overlap)
            shorter = ok and self.counter.count(reply) < self.counter.count(h.chunk.text)
            out.append(_with_text(h, reply, "summarize") if shorter else h)
        return out


@register("compressor", "summarize", params=SummarizeParams, status="mocked",
          summary="an LLM summarises each long chunk for the question; ungrounded summaries are discarded")  # fmt: skip
def _summarize(p: SummarizeParams, c: Container) -> Summarize:
    from rag_core.components.basics import ApproxTokenCounter

    counter = c.get("token_counter") if c.has("token_counter") else ApproxTokenCounter()
    return Summarize(c.get(p.llm_slot), counter, p)


# ================================================================ LLMLingua (reference)


class LlmLinguaParams(_Strict):
    model: str = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"
    rate: float = Field(0.5, gt=0, le=1)  # share of tokens to keep
    llmlingua2: bool = True  # LLMLingua-2 (token classification, fast) or the original (perplexity)
    force_tokens: list[str] = Field(default_factory=lambda: ["\n", ".", "?", "!"])
    device: str = "cpu"


class LlmLingua:
    """Token-level prompt compression with Microsoft's LLMLingua(-2): a small model scores every
    token and the least informative are removed (2-5x shorter, with some loss of fluency the
    answer model tolerates). Reference: `pip install llmlingua` (pulls torch, so it is not in
    the lock file); question-agnostic, so it pairs well with `extractive` before it."""

    def __init__(self, p: LlmLinguaParams, compressor: Any = None) -> None:
        if compressor is None:
            from llmlingua import PromptCompressor  # optional: pip install llmlingua

            compressor = PromptCompressor(
                model_name=p.model, use_llmlingua2=p.llmlingua2, device_map=p.device
            )
        self.p, self._c = p, compressor

    def compress(self, query: Query, hits: Sequence[ScoredChunk]) -> list[ScoredChunk]:
        out = []
        for h in hits:
            res = self._c.compress_prompt(
                [h.chunk.text], rate=self.p.rate, force_tokens=self.p.force_tokens
            )
            text = str(res.get("compressed_prompt") or "").strip()
            out.append(_with_text(h, text, "llmlingua") if text else h)
        return out


@register("compressor", "llmlingua", params=LlmLinguaParams, status="reference", requires=("llmlingua",),
          summary="token-level prompt compression with LLMLingua-2 (a small model drops uninformative tokens)")  # fmt: skip
def _llmlingua(p: LlmLinguaParams, c: Container) -> LlmLingua:
    return LlmLingua(p)


def compress_all(compressors: Sequence[Any], query: Query, hits: list[ScoredChunk],
                 counter: Any) -> tuple[list[ScoredChunk], dict[str, Any]]:  # fmt: skip
    """Run the compressors in order; the trace says what each saved. Tokens are counted with the
    profile's token counter, over the chunk texts the context builder would receive."""

    def tokens(hs: Sequence[ScoredChunk]) -> int:
        return sum(counter.count(h.chunk.text) for h in hs)

    before = tokens(hits)
    steps = []
    for comp in compressors:
        t0, n0 = tokens(hits), len(hits)
        hits = list(comp.compress(query, hits))
        steps.append({"compressor": type(comp).__name__, "tokens_before": t0, "tokens_after": tokens(hits),
                      "chunks_before": n0, "chunks_after": len(hits)})  # fmt: skip
    after = tokens(hits)
    return hits, {"tokens_before": before, "tokens_after": after, "tokens_saved": before - after,
                  "ratio": round(after / before, 3) if before else 1.0, "steps": steps}  # fmt: skip
