"""Finding and ordering the right chunks (Step 32): query transformers, retrievers, fusion,
rerankers and post-processors. Every one is a switchable component; SearchPipeline (search.py)
runs them in order:

    question ─transform─▶ search texts ─retrieve (dense / keyword / hybrid)─▶ fused candidates
             ─rerank (top_n)─▶ ordered ─post-process (dedupe, cap, MMR, expand, …)─▶ top k
"""

from __future__ import annotations

import contextvars
import itertools
import logging
import math
import re
import statistics
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from rag_core.components.basics import cosine, gateway_key, words
from rag_core.registry import Container, register, spec
from rag_core.types import Chunk, Query, ScoredChunk

log = logging.getLogger("rag_core.retrieval")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Passage(str):
    """A search text that is a hypothetical ANSWER (HyDE), not a question. Dense retrieval embeds it
    as a document (no query instruction), because it should look like the chunks it's looking for."""

    __slots__ = ()


def source_of(hits: Sequence[ScoredChunk]) -> str:
    """Which retriever produced a ranked list: "dense", "sparse" or "other"."""
    for h in hits[:1]:
        for key in ("dense", "sparse"):
            if key in h.scores:
                return key
    return "other"


# ================================================================ query transformers


class IdentityTransformer:
    def transform(self, query: Query) -> list[str]:
        return [query.text]


@register("query_transformer", "identity", summary="search with the question exactly as asked")
def _identity(p: BaseModel, c: Container) -> IdentityTransformer:
    return IdentityTransformer()


class LlmTransformParams(_Strict):
    n: int = Field(3, ge=1, le=8)  # how many texts to generate (where it applies)
    include_original: bool = True  # also search with the question as asked
    llm_slot: Literal["llm", "judge_llm"] = "llm"
    max_tokens: int = Field(300, ge=16)
    system: str | None = None  # replace the built-in instruction (e.g. from the prompt registry)


PROMPTS = {
    "rewrite": (
        "Rewrite the user's last question as ONE standalone search query. Resolve words like 'it', "
        "'that' or 'them' using the conversation. Keep names, numbers and terms exactly. "
        "Reply with the query only."
    ),
    "multi-query": (
        "Write {n} different search queries that would find documents answering the question. "
        "Vary the wording and use synonyms; keep names and numbers. One query per line, no numbering."
    ),
    "hyde": (
        "Write a short passage (3-5 sentences) in the style of a company policy document that "
        "answers the question. If you don't know the facts, write a plausible passage anyway: it is "
        "only used to search, never shown."
    ),
    "decompose": (
        "Split the question into at most {n} simpler questions that can each be answered by one "
        "document. If it is already simple, repeat it. One question per line, no numbering."
    ),
    "step-back": (
        "Write ONE more general question about the principle or policy behind the user's question "
        "(a 'step-back' question). Reply with the question only."
    ),
}


def _lines(text: str, n: int) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"')
        if line and line.lower() not in (o.lower() for o in out):
            out.append(line)
    return out[:n]


def _conversation(query: Query) -> str:
    turns = "\n".join(f"{t.role}: {t.text}" for t in query.history[-6:])
    return f"Conversation:\n{turns}\n\nLast question: {query.text}" if turns else query.text


class LlmTransformer:
    """One LLM call turns the question into search texts. If the LLM fails, search goes on with the
    question as asked: a helper must never take search down."""

    def __init__(self, kind: str, llm: Any, p: LlmTransformParams) -> None:
        self.kind, self.llm, self.p = kind, llm, p

    def transform(self, query: Query) -> list[str]:
        if self.kind == "rewrite" and not query.history:
            return [query.text]  # Step 33: nothing to resolve, so no model call (a first question)
        system = (self.p.system or PROMPTS[self.kind]).replace("{n}", str(self.p.n))
        user = _conversation(query) if self.kind == "rewrite" else query.text
        try:
            reply = str(self.llm.complete(system, user, max_tokens=self.p.max_tokens)).strip()
        except Exception as e:
            log.warning(
                "query transformer %s failed, using the question as asked: %s", self.kind, e
            )
            return [query.text]
        if self.kind == "hyde":
            made: list[str] = [Passage(reply)] if reply else []
        elif self.kind in ("rewrite", "step-back"):
            made = _lines(reply, 1)
        else:
            made = _lines(reply, self.p.n)
        if self.kind == "rewrite" and made:  # the rewrite REPLACES the question
            return [made[0], *([query.text] if self.p.include_original and query.history else [])]
        texts = ([query.text] if self.p.include_original else []) + made
        return _unique(texts) or [query.text]


def _unique(texts: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        if t.strip() and t.strip().lower() not in seen:
            seen.add(t.strip().lower())
            out.append(t)
    return out


def _make(kind: str) -> Callable[[LlmTransformParams, Container], LlmTransformer]:
    def factory(p: LlmTransformParams, c: Container) -> LlmTransformer:
        return LlmTransformer(kind, c.get(p.llm_slot), p)

    return factory


for _kind, _summary in [
    ("rewrite", "LLM: turn a follow-up ('and for part-timers?') into a standalone query"),
    ("multi-query", "LLM: n paraphrases, searched separately and fused (better recall)"),
    ("hyde", "LLM: a hypothetical answer passage, embedded like a document (HyDE)"),
    ("decompose", "LLM: split a compound question into simpler sub-questions"),
    ("step-back", "LLM: add a more general 'principle' question"),
]:
    register(
        "query_transformer", _kind, params=LlmTransformParams, summary=_summary, status="mocked"
    )(_make(_kind))


class ExpandParams(_Strict):
    terms: dict[str, str] = {}  # "wfh": "work from home": your organisation's acronyms and jargon


class TermExpander:
    """Adds the meaning of known acronyms and jargon to the question. No LLM, no cost, predictable:
    "Can I WFH on Fridays?" also searches "work from home"."""

    def __init__(self, terms: dict[str, str]) -> None:
        self.terms = {k.lower(): v for k, v in terms.items()}

    def transform(self, query: Query) -> list[str]:
        found = [self.terms[w] for w in dict.fromkeys(words(query.text)) if w in self.terms]
        return [f"{query.text} ({'; '.join(found)})" if found else query.text]


@register("query_transformer", "expand-terms", params=ExpandParams,
          summary="add the meaning of known acronyms/jargon (no LLM)")  # fmt: skip
def _expand(p: ExpandParams, c: Container) -> TermExpander:
    return TermExpander(p.terms)


class HistoryParams(_Strict):
    turns: int = Field(2, ge=1, le=6)  # how many earlier USER turns to add


class WithHistory:
    """No-LLM conversational search: add the last user turns to the question, so "how do I fix
    it?" after "my VPN shows E-4021" still finds the VPN page. Cruder than `rewrite`, but free."""

    def __init__(self, turns: int) -> None:
        self.turns = turns

    def transform(self, query: Query) -> list[str]:
        earlier = [t.text for t in query.history if t.role == "user"][-self.turns :]
        return [" ".join([*earlier, query.text])]


@register("query_transformer", "with-history", params=HistoryParams,
          summary="no-LLM follow-ups: prepend the last user turns to the question")  # fmt: skip
def _with_history(p: HistoryParams, c: Container) -> WithHistory:
    return WithHistory(p.turns)


class ChainParams(_Strict):
    steps: list[dict[str, Any]] = Field(
        min_length=1
    )  # e.g. [{use: rewrite}, {use: multi-query, n: 2}]


class ChainTransformer:
    """Several transformers in order; each one is applied to every text the previous produced."""

    def __init__(self, steps: list[Any]) -> None:
        self.steps = steps

    def transform(self, query: Query) -> list[str]:
        return self.analyze(query)[0]

    def analyze(self, query: Query) -> tuple[list[str], dict[str, Any]]:
        """The texts, plus the metadata filter any step found (a self-query step, extension 01).
        A filter-finding step reads the ORIGINAL question, wherever it is in the chain."""
        texts = [query.text]
        found: list[dict[str, Any]] = []
        for step in self.steps:
            if hasattr(step, "analyze"):
                _, f = step.analyze(query)
                if f:
                    found.append(f)
            nxt: list[str] = []
            for t in texts:
                nxt += [t] if isinstance(t, Passage) else step.transform(replace(query, text=t))
            texts = _unique(nxt)
        from rag_core.filters import combine

        return texts[:8], combine(*found)

    @property
    def fallback_on_empty(self) -> bool:
        return all(getattr(s, "fallback_on_empty", True) for s in self.steps)


@register("query_transformer", "chain", params=ChainParams,
          summary="run several transformers in order (e.g. rewrite, then multi-query)")  # fmt: skip
def _chain(p: ChainParams, c: Container) -> ChainTransformer:
    built = []
    for raw in p.steps:
        s = spec("query_transformer", str(raw.get("use")))
        built.append(
            s.factory(s.params.model_validate({k: v for k, v in raw.items() if k != "use"}), c)
        )
    return ChainTransformer(built)


# ================================================================ fusion


class FusionParams(_Strict):
    # Weight per source ("dense" = vector search, "sparse" = keyword search); missing = 1.0
    weights: dict[str, float] = {}


class RrfParams(FusionParams):
    k: int = Field(60, ge=1)  # the classic constant from the RRF paper: dampens the top ranks


def _merge_scores(a: ScoredChunk, b: ScoredChunk) -> ScoredChunk:
    keep = dict(a.scores)
    for key, v in b.scores.items():
        keep[key] = max(keep.get(key, v), v)
    return replace(a, scores=keep)


class _Fusion:
    """Every fusion: scale each ranked list (`_norm`), weight it, add the parts up per chunk.

    A list's weight comes from `list_weights` when the caller gives one per list (the ensemble
    retriever does), else from `weights` by where the list came from ("dense", "sparse")."""

    stage = "fusion"

    def __init__(self, weights: dict[str, float]) -> None:
        self.weights = weights

    def _norm(self, hits: Sequence[ScoredChunk], longest: int) -> list[float]:
        raise NotImplementedError

    def _combine(self, total: float, lists: int) -> float:
        return total  # CombMNZ multiplies by the number of lists that found the chunk

    def fuse(self, ranked: Sequence[Sequence[ScoredChunk]],
             list_weights: Sequence[float] | None = None) -> list[ScoredChunk]:  # fmt: skip
        if list_weights is not None and len(list_weights) != len(ranked):
            raise ValueError("one weight per ranked list")
        total: dict[str, float] = {}
        found: dict[str, int] = {}
        best: dict[str, ScoredChunk] = {}
        longest = max((len(h) for h in ranked), default=0)
        for i, hits in enumerate(ranked):
            w = (
                list_weights[i]
                if list_weights is not None
                else self.weights.get(source_of(hits), 1.0)
            )
            for h, v in zip(hits, self._norm(hits, longest), strict=True):
                total[h.chunk.id] = total.get(h.chunk.id, 0.0) + w * v
                found[h.chunk.id] = found.get(h.chunk.id, 0) + 1
                best[h.chunk.id] = _merge_scores(best[h.chunk.id], h) if h.chunk.id in best else h
        out = [
            best[i].with_score(round(self._combine(s, found[i]), 6), self.stage)
            for i, s in total.items()
        ]
        return sorted(out, key=lambda h: (-h.score, h.chunk.id))


def _minmax(hits: Sequence[ScoredChunk]) -> list[float]:
    s = [h.score for h in hits]
    lo, hi = (min(s), max(s)) if s else (0.0, 0.0)
    return [1.0 if hi == lo else (x - lo) / (hi - lo) for x in s]


def _zscore(hits: Sequence[ScoredChunk]) -> list[float]:
    s = [h.score for h in hits]
    if len(s) < 2 or statistics.pstdev(s) == 0:
        return [1.0] * len(s)
    mu, sd = statistics.fmean(s), statistics.pstdev(s)
    return [(x - mu) / sd for x in s]


class ReciprocalRankFusion(_Fusion):
    """RRF: 1/(k + rank) per list, summed. Uses only positions, so it needs no tuning to mix
    scores of different kinds (cosine 0.8 vs BM25 12.3). The safe default."""

    def __init__(self, k: int = 60, weights: dict[str, float] | None = None) -> None:
        super().__init__(weights or {})
        self.k = k

    def _norm(self, hits: Sequence[ScoredChunk], longest: int) -> list[float]:
        return [1.0 / (self.k + rank) for rank in range(1, len(hits) + 1)]


class WeightedFusion(_Fusion):
    """Scores scaled to 0-1 per list (min-max), then a weighted sum ("alpha" blending). Uses how
    MUCH better a hit is, not only its position; sensitive to outliers and list length."""

    def _norm(self, hits: Sequence[ScoredChunk], longest: int) -> list[float]:
        return _minmax(hits)


class RelativeScoreFusion(WeightedFusion):
    """Weaviate's "relative score fusion": the SAME arithmetic as `weighted` (min-max per list,
    weighted sum), configured the Weaviate way with one `alpha` (1 = vectors only, 0 = keywords
    only). A chunk found by one list only gets nothing from the other (0, not the list's minimum)."""


class DistributionFusion(_Fusion):
    """DBSF (as in Qdrant): scale each list by its own spread (mean ± 3 standard deviations), so one
    extreme score doesn't squash the rest."""

    def _norm(self, hits: Sequence[ScoredChunk], longest: int) -> list[float]:
        s = [h.score for h in hits]
        if len(s) < 2:
            return [1.0] * len(s)
        mu, sd = statistics.fmean(s), statistics.pstdev(s)
        if sd == 0:
            return [1.0] * len(s)
        lo, hi = mu - 3 * sd, mu + 3 * sd
        return [min(1.0, max(0.0, (x - lo) / (hi - lo))) for x in s]


class CombSum(_Fusion):
    """CombSUM (Fox & Shaw, 1994): each list's scores normalised (min-max by default), summed.
    A chunk several lists agree on rises; one list's high score alone rises less."""

    def __init__(self, weights: dict[str, float], normalize: str = "minmax") -> None:
        super().__init__(weights)
        self.normalize = normalize

    def _norm(self, hits: Sequence[ScoredChunk], longest: int) -> list[float]:
        if self.normalize == "zscore":
            return _zscore(hits)
        if self.normalize == "none":
            return [h.score for h in hits]
        return _minmax(hits)


class CombMnz(CombSum):
    """CombMNZ: CombSUM times the number of lists that found the chunk. Rewards agreement much
    more strongly: the classic choice when several similar retrievers vote."""

    def _combine(self, total: float, lists: int) -> float:
        return total * lists


class BordaCount(_Fusion):
    """Borda count (a vote): in each list the top chunk gets N points, the next N-1, …, where N is
    the length of the longest list. Uses positions only, like RRF, but gives the middle of a list
    much more weight than RRF does."""

    def _norm(self, hits: Sequence[ScoredChunk], longest: int) -> list[float]:
        return [float(longest - rank) for rank in range(len(hits))]


@register(
    "fusion",
    "rrf",
    params=RrfParams,
    summary="reciprocal rank fusion: ranks only, no tuning (default)",
)
def _rrf(p: RrfParams, c: Container) -> ReciprocalRankFusion:
    return ReciprocalRankFusion(p.k, p.weights)


class WeightedParams(_Strict):
    weights: dict[str, float] = {"dense": 0.5, "sparse": 0.5}


@register(
    "fusion", "weighted", params=WeightedParams, summary="min-max normalised scores, weighted sum"
)
def _weighted(p: WeightedParams, c: Container) -> WeightedFusion:
    return WeightedFusion(p.weights)


class RelativeScoreParams(_Strict):
    alpha: float = Field(0.5, ge=0, le=1)  # weight of vector search; keyword search gets 1 - alpha
    weights: dict[str, float] | None = None  # or explicit weights per source (overrides alpha)


@register("fusion", "relative-score", params=RelativeScoreParams,
          summary="Weaviate-style relative score fusion: min-max per list, alpha-weighted sum (= weighted)")  # fmt: skip
def _relative(p: RelativeScoreParams, c: Container) -> RelativeScoreFusion:
    return RelativeScoreFusion(
        p.weights if p.weights is not None else {"dense": p.alpha, "sparse": 1 - p.alpha}
    )


@register("fusion", "dbsf", params=FusionParams,
          summary="distribution-based score fusion (mean +/- 3 std devs), as in Qdrant")  # fmt: skip
def _dbsf(p: FusionParams, c: Container) -> DistributionFusion:
    return DistributionFusion(p.weights)


class CombParams(FusionParams):
    normalize: Literal["minmax", "zscore", "none"] = "minmax"  # none: only for scores of one kind


@register("fusion", "combsum", params=CombParams,
          summary="CombSUM: normalised scores summed across lists")  # fmt: skip
def _combsum(p: CombParams, c: Container) -> CombSum:
    return CombSum(p.weights, p.normalize)


@register("fusion", "combmnz", params=CombParams,
          summary="CombMNZ: CombSUM x number of lists that found the chunk (rewards agreement)")  # fmt: skip
def _combmnz(p: CombParams, c: Container) -> CombMnz:
    return CombMnz(p.weights, p.normalize)


@register("fusion", "borda", params=FusionParams,
          summary="Borda count: N points for first place, N-1 for second, … summed (ranks only)")  # fmt: skip
def _borda(p: FusionParams, c: Container) -> BordaCount:
    return BordaCount(p.weights)


# ================================================================ retrievers


class RetrieverParams(_Strict):
    candidates: int = Field(
        default=30, ge=1, le=500
    )  # per search text and per store, before fusion
    parallel: bool = True  # run the searches at the same time (latency = the slowest, not the sum)


Job = Callable[[], list[ScoredChunk]]


def _run_all(jobs: list[Job], parallel: bool) -> list[list[ScoredChunk]]:
    if not parallel or len(jobs) < 2:
        return [j() for j in jobs]
    # copy_context: the tracing context (current span) follows each job into its thread
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, j) for j in jobs]
        return [f.result() for f in futures]


class _Retriever:
    def __init__(self, c: Container, p: RetrieverParams) -> None:
        self.c, self.p = c, p
        self._fusion: Any = None

    @property
    def fusion(self) -> Any:
        if self._fusion is None:
            self._fusion = self.c.get("fusion") if self.c.has("fusion") else ReciprocalRankFusion()
        return self._fusion

    def _jobs(self, query: Query, texts: Sequence[str]) -> list[Job]:
        raise NotImplementedError

    def retrieve(self, query: Query, texts: Sequence[str]) -> list[ScoredChunk]:
        lists = [hits for hits in _run_all(self._jobs(query, texts), self.p.parallel) if hits]
        if not lists:
            return []
        if len(lists) == 1:
            return list(lists[0])
        fused: list[ScoredChunk] = self.fusion.fuse(lists)
        return fused

    def _dense(self, query: Query, text: str) -> Job:
        emb, store = self.c.get("embedder"), self.c.get("vector_store")

        def run() -> list[ScoredChunk]:
            vec = (
                emb.embed_documents([text])[0]
                if isinstance(text, Passage)
                else emb.embed_query(text)
            )
            return list(
                store.search(vec, query.principal, self.p.candidates, dict(query.filters) or None)
            )

        return run

    def _sparse(self, query: Query, text: str) -> Job:
        index = self.c.get("keyword_index")
        return lambda: list(index.search(str(text), query.principal, self.p.candidates,
                                         dict(query.filters) or None))  # fmt: skip

    def _dense_jobs(self, query: Query, texts: Sequence[str]) -> list[Job]:
        return [self._dense(query, t) for t in texts]

    def _sparse_jobs(self, query: Query, texts: Sequence[str]) -> list[Job]:
        # HyDE passages are skipped: invented text is fine for meaning, its exact words are noise
        return [self._sparse(query, t) for t in texts if not isinstance(t, Passage)] or [
            self._sparse(query, query.text)
        ]


class DenseRetriever(_Retriever):
    """Vector search: finds passages with the same MEANING, even in different words."""

    def _jobs(self, query: Query, texts: Sequence[str]) -> list[Job]:
        return self._dense_jobs(query, texts)


class KeywordRetriever(_Retriever):
    """Keyword (BM25-style) search: exact words, names, codes, error numbers. HyDE passages are
    skipped: invented text is fine for meaning, but its exact words are noise."""

    def _jobs(self, query: Query, texts: Sequence[str]) -> list[Job]:
        return self._sparse_jobs(query, texts)


class HybridRetriever(_Retriever):
    """Both, fused: the usual production default, because each finds what the other misses."""

    def _jobs(self, query: Query, texts: Sequence[str]) -> list[Job]:
        return self._dense_jobs(query, texts) + self._sparse_jobs(query, texts)


@register(
    "retriever", "dense", params=RetrieverParams, summary="vector search (embedder + vector_store)"
)
def _dense_r(p: RetrieverParams, c: Container) -> DenseRetriever:
    return DenseRetriever(c, p)


@register("retriever", "keyword", params=RetrieverParams, summary="keyword search (keyword_index)")
def _kw_r(p: RetrieverParams, c: Container) -> KeywordRetriever:
    return KeywordRetriever(c, p)


@register("retriever", "hybrid", params=RetrieverParams,
          summary="vector + keyword search, merged by the fusion slot (default rrf)")  # fmt: skip
def _hybrid_r(p: RetrieverParams, c: Container) -> HybridRetriever:
    return HybridRetriever(c, p)


# ================================================================ rerankers


class RerankParams(_Strict):
    top_n: int = Field(30, ge=1, le=200)  # how many candidates the reranker reads (cost/latency!)
    max_chars: int = Field(2000, ge=100)  # longer passages are cut before reranking
    fail_open: bool = True  # reranker down: keep the retrieval order (logged) instead of failing


class _Reranker:
    stage = "rerank"

    def __init__(self, p: RerankParams) -> None:
        self.p = p
        self.top_n = p.top_n
        self.failures = 0

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        raise NotImplementedError

    def rerank(self, query: str, candidates: Sequence[ScoredChunk], k: int) -> list[ScoredChunk]:
        head = list(candidates[: self.top_n])
        if not head:
            return []
        try:
            scores = self._scores(query, [h.chunk.text[: self.p.max_chars] for h in head])
        except Exception as e:
            if not self.p.fail_open:
                raise
            self.failures += 1
            log.error("reranker %s failed, keeping retrieval order: %s", type(self).__name__, e)
            return [h.with_score(h.score, "rerank_skipped") for h in head][:k]
        out = [
            h.with_score(round(float(s), 6), self.stage) for h, s in zip(head, scores, strict=True)
        ]
        return sorted(out, key=lambda h: -h.score)[:k]


class GatewayRerankParams(RerankParams):
    model: str = "reranker"  # the LiteLLM alias (Step 9): TEI, Cohere, Voyage, Jina, Bedrock …
    base_url: str = "http://litellm:4000"
    api_key_env: str = "LLM_GATEWAY_KEY"
    api_key_file: str | None = None  # /run/bao/rag_api_gateway_key in containers
    timeout: float = 30.0


class GatewayReranker(_Reranker):
    """A cross-encoder behind the gateway's Cohere-style /rerank (Step 9): reads the question and
    each passage TOGETHER, so it judges relevance far better than vector similarity."""

    def __init__(self, p: GatewayRerankParams, client: httpx.Client | None = None) -> None:
        super().__init__(p)
        self.gp = p
        self._http = client or httpx.Client(
            base_url=p.base_url.rstrip("/") + "/", timeout=p.timeout
        )
        self._key = gateway_key(p.api_key_env, p.api_key_file)

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        r = self._http.post("rerank", json={"model": self.gp.model, "query": query, "documents": texts,
                                            "top_n": len(texts)},
                            headers={"Authorization": f"Bearer {self._key.get_secret_value()}"})  # fmt: skip
        r.raise_for_status()
        scores = [0.0] * len(texts)
        for item in r.json()["results"]:
            scores[int(item["index"])] = float(item["relevance_score"])
        return scores


@register("reranker", "gateway", status="mocked", params=GatewayRerankParams,
          summary="cross-encoder via the gateway's /rerank (TEI locally; Cohere/Voyage/Jina in cloud)")  # fmt: skip
def _gw_rerank(p: GatewayRerankParams, c: Container) -> GatewayReranker:
    return GatewayReranker(p)


class TeiRerankParams(RerankParams):
    url: str = "http://host.docker.internal:8084"  # TEI's own API (Step 8), bypassing the gateway
    timeout: float = 30.0


class TeiReranker(_Reranker):
    def __init__(self, p: TeiRerankParams, client: httpx.Client | None = None) -> None:
        super().__init__(p)
        self._http = client or httpx.Client(base_url=p.url.rstrip("/") + "/", timeout=p.timeout)

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        r = self._http.post("rerank", json={"query": query, "texts": texts, "truncate": True})
        r.raise_for_status()
        scores = [0.0] * len(texts)
        for item in r.json():
            scores[int(item["index"])] = float(item["score"])
        return scores


@register("reranker", "tei", status="mocked", params=TeiRerankParams,
          summary="cross-encoder straight to TEI's /rerank (no gateway: no budgets or logs)")  # fmt: skip
def _tei_rerank(p: TeiRerankParams, c: Container) -> TeiReranker:
    return TeiReranker(p)


class LlmRerankParams(RerankParams):
    top_n: int = Field(10, ge=1, le=30)  # one prompt holds them all: keep it small
    max_chars: int = Field(600, ge=100)
    llm_slot: Literal["llm", "judge_llm"] = "judge_llm"


class LlmReranker(_Reranker):
    """Listwise reranking: the LLM sees all passages and returns their order ("3 > 1 > 2").
    Strong on reasoning-heavy questions; slow and costly, so only for a few candidates."""

    SYSTEM = ("Rank the passages by how well they answer the question. Reply ONLY with the passage "
              "numbers, best first, separated by '>', e.g. 3 > 1 > 2. Leave out passages that don't help.")  # fmt: skip

    def __init__(self, p: LlmRerankParams, llm: Any) -> None:
        super().__init__(p)
        self.llm = llm

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        passages = "\n\n".join(f"[{i}] {t}" for i, t in enumerate(texts, 1))
        reply = str(
            self.llm.complete(
                self.SYSTEM, f"Question: {query}\n\nPassages:\n{passages}", max_tokens=100
            )
        )
        order: list[int] = []
        for m in re.findall(r"\d+", reply):
            i = int(m) - 1
            if 0 <= i < len(texts) and i not in order:
                order.append(i)
        if not order:
            raise ValueError(f"no ranking in LLM reply {reply[:80]!r}")
        n = len(texts)
        scores = [0.0] * n  # left out = judged unhelpful: 0
        for pos, i in enumerate(order):
            scores[i] = 1.0 - pos / n
        return scores


@register("reranker", "llm", status="mocked", params=LlmRerankParams,
          summary="listwise LLM reranking (judge model): few candidates, high cost")  # fmt: skip
def _llm_rerank(p: LlmRerankParams, c: Container) -> LlmReranker:
    return LlmReranker(p, c.get(p.llm_slot))


class OverlapRerankParams(RerankParams):
    phrase_bonus: float = 0.5


class TermOverlapReranker(_Reranker):
    """Offline baseline: how much of the question (rare words weigh more) appears in the passage,
    with a bonus for word pairs in the same order. No model; useful in tests and CI."""

    def __init__(self, p: OverlapRerankParams) -> None:
        super().__init__(p)
        self.bonus = p.phrase_bonus

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        q = list(dict.fromkeys(words(query)))
        docs = [set(words(t)) for t in texts]
        n = len(texts)
        idf = {w: math.log(1 + n / (1 + sum(w in d for d in docs))) for w in q}
        total = sum(idf.values()) or 1.0
        pairs = [f"{a} {b}" for a, b in itertools.pairwise(q)]
        out = []
        for t, d in zip(texts, docs, strict=True):
            joined = " ".join(words(t))
            cover = sum(idf[w] for w in q if w in d) / total
            phrase = sum(pair in joined for pair in pairs) / (len(pairs) or 1)
            out.append(cover + self.bonus * phrase)
        return out


@register("reranker", "term-overlap", params=OverlapRerankParams,
          summary="offline baseline: weighted query-term coverage (tests, CI)")  # fmt: skip
def _overlap(p: OverlapRerankParams, c: Container) -> TermOverlapReranker:
    return TermOverlapReranker(p)


class CrossEncoderParams(RerankParams):
    model: str = "BAAI/bge-reranker-v2-m3"
    device: str | None = None


class CrossEncoderReranker(_Reranker):
    """A cross-encoder inside this process (sentence-transformers): no server, but the model's
    memory and CPU/GPU load land in the API process."""

    def __init__(self, p: CrossEncoderParams) -> None:
        super().__init__(p)
        from sentence_transformers import CrossEncoder  # optional dependency

        self._m = CrossEncoder(p.model, device=p.device)

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self._m.predict([(query, t) for t in texts])]


@register("reranker", "cross-encoder", params=CrossEncoderParams, status="reference",
          requires=("sentence-transformers",),
          summary="in-process cross-encoder (sentence-transformers); no server")  # fmt: skip
def _ce(p: CrossEncoderParams, c: Container) -> CrossEncoderReranker:
    return CrossEncoderReranker(p)


# ================================================================ post-processors


class MinScoreParams(_Strict):
    threshold: float
    stage: str | None = None  # which score to test ("rerank", "dense", …); default: the current one
    min_keep: int = Field(0, ge=0)  # keep at least this many, even below the threshold


class MinScore:
    """Drop weak candidates. With a reranker's 0-1 relevance, this is how "nothing relevant" becomes
    an empty result (and later an honest "I don't know") instead of five irrelevant chunks."""

    def __init__(self, p: MinScoreParams) -> None:
        self.p = p

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        def val(h: ScoredChunk) -> float:
            return h.scores.get(self.p.stage, -math.inf) if self.p.stage else h.score

        kept = [h for h in candidates if val(h) >= self.p.threshold]
        return kept if len(kept) >= self.p.min_keep else candidates[: self.p.min_keep]


@register(
    "postprocessor", "min-score", params=MinScoreParams, summary="drop candidates below a score"
)
def _min_score(p: MinScoreParams, c: Container) -> MinScore:
    return MinScore(p)


class DedupeParams(_Strict):
    threshold: float = Field(0.85, gt=0, le=1)  # Jaccard similarity of word triples


def _shingles(text: str) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i : i + 3]) for i in range(max(1, len(w) - 2))}


class Dedupe:
    """Drop near-copies (the same paragraph in two versions or two documents): they waste context."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        kept: list[tuple[ScoredChunk, set[tuple[str, ...]]]] = []
        for h in candidates:
            s = _shingles(h.chunk.text)
            if all(len(s & o) / (len(s | o) or 1) < self.threshold for _, o in kept):
                kept.append((h, s))
        return [h for h, _ in kept]


@register("postprocessor", "dedupe", params=DedupeParams, summary="drop near-duplicate chunks")
def _dedupe(p: DedupeParams, c: Container) -> Dedupe:
    return Dedupe(p.threshold)


class PerDocParams(_Strict):
    n: int = Field(2, ge=1)


class MaxPerDocument:
    """At most n chunks per document, so one long document can't crowd out all the others."""

    def __init__(self, n: int) -> None:
        self.n = n

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        seen: dict[str, int] = {}
        out = []
        for h in candidates:
            seen[h.chunk.document_uri] = seen.get(h.chunk.document_uri, 0) + 1
            if seen[h.chunk.document_uri] <= self.n:
                out.append(h)
        return out


@register(
    "postprocessor", "max-per-document", params=PerDocParams, summary="cap chunks per document"
)
def _per_doc(p: PerDocParams, c: Container) -> MaxPerDocument:
    return MaxPerDocument(p.n)


class MmrParams(_Strict):
    lambda_: float = Field(
        0.7, ge=0, le=1, alias="lambda"
    )  # 1 = relevance only, 0 = diversity only
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Mmr:
    """Maximal Marginal Relevance: pick, one by one, the candidate that is relevant AND least like
    those already picked. Fewer near-repeats, more different facts in the same context budget."""

    def __init__(self, lam: float, embedder: Any) -> None:
        self.lam, self.emb = lam, embedder

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        if len(candidates) < 3:
            return candidates
        vecs = self.emb.embed_documents([h.chunk.indexed_text for h in candidates])
        rel = [h.score for h in candidates]
        lo, hi = min(rel), max(rel)
        rel = [1.0 if hi == lo else (r - lo) / (hi - lo) for r in rel]
        picked: list[int] = []
        rest = list(range(len(candidates)))

        def mmr(i: int) -> float:
            sim = max((cosine(vecs[i], vecs[j]) for j in picked), default=0.0)
            return float(self.lam * rel[i] - (1 - self.lam) * sim)

        while rest:
            best = max(rest, key=mmr)
            picked.append(best)
            rest.remove(best)
        return [candidates[i] for i in picked]


@register(
    "postprocessor",
    "mmr",
    params=MmrParams,
    summary="diversify: relevant AND different (uses the embedder)",
)
def _mmr(p: MmrParams, c: Container) -> Mmr:
    return Mmr(p.lambda_, c.get("embedder"))


class ParentExpand:
    """Small-to-big (Step 31's parent-child chunker): the small child chunk was found, the whole
    parent section goes to the model. Children of the same parent become one candidate."""

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        out: list[ScoredChunk] = []
        index: dict[str, int] = {}
        for h in candidates:
            parent_text = h.chunk.metadata.get("parent_text")
            pid = h.chunk.parent_id or h.chunk.metadata.get("parent_id")
            if not parent_text or not pid:
                out.append(h)
                continue
            pid = str(pid)
            if pid in index:  # a sibling already brought the parent in
                prev = out[index[pid]]
                meta = dict(prev.chunk.metadata)
                meta["matched_children"] = [*meta.get("matched_children", []), h.chunk.id]
                out[index[pid]] = replace(prev, chunk=replace(prev.chunk, metadata=meta))
                continue
            meta = {k: v for k, v in h.chunk.metadata.items() if k != "parent_text"}
            meta["matched_children"] = [h.chunk.id]
            parent = replace(h.chunk, id=pid, text=str(parent_text), embed_text="", metadata=meta)
            index[pid] = len(out)
            out.append(replace(h, chunk=parent))
        return out


@register(
    "postprocessor", "parent-expand", summary="replace matched child chunks by their parent section"
)
def _parent(p: BaseModel, c: Container) -> ParentExpand:
    return ParentExpand()


class WindowExpand:
    """Sentence-window (Step 31): the single sentence was matched, its neighbours go to the model."""

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        return [replace(h, chunk=replace(h.chunk, text=str(h.chunk.metadata["window"])))
                if h.chunk.metadata.get("window") else h for h in candidates]  # fmt: skip


@register("postprocessor", "window-expand", summary="replace a matched sentence by its window")
def _window(p: BaseModel, c: Container) -> WindowExpand:
    return WindowExpand()


class RecencyParams(_Strict):
    field: str = "updated"  # a chunk metadata date (ISO 8601), e.g. copied from the source system
    half_life_days: float = Field(365, gt=0)
    weight: float = Field(0.2, ge=0, le=1)  # 0 = ignore age; 1 = age only
    missing: float = Field(0.5, ge=0, le=1)  # freshness assumed for undated chunks


class RecencyBoost:
    """Prefer newer content when relevance is similar: the 2026 policy over the 2021 one."""

    def __init__(self, p: RecencyParams, today: date | None = None) -> None:
        self.p, self.today = p, today

    def _fresh(self, value: Any) -> float:
        try:
            d = value if isinstance(value, date) else datetime.fromisoformat(str(value)).date()
        except ValueError:
            return self.p.missing
        today = self.today or datetime.now(UTC).date()
        age = max(0, (today - d).days)
        return float(0.5 ** (age / self.p.half_life_days))

    def process(self, query: Query, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        if not candidates:
            return candidates
        s = [h.score for h in candidates]
        lo, hi = min(s), max(s)
        out = []
        for h in candidates:
            rel = 1.0 if hi == lo else (h.score - lo) / (hi - lo)
            v = h.chunk.metadata.get(self.p.field)
            fresh = self._fresh(v) if v is not None else self.p.missing
            out.append(
                h.with_score(round((1 - self.p.weight) * rel + self.p.weight * fresh, 6), "recency")
            )
        return sorted(out, key=lambda h: -h.score)


@register(
    "postprocessor",
    "recency",
    params=RecencyParams,
    summary="blend relevance with freshness (half-life)",
)
def _recency(p: RecencyParams, c: Container) -> RecencyBoost:
    return RecencyBoost(p)


__all__ = [
    "Chunk", "Dedupe", "DenseRetriever", "DistributionFusion", "GatewayReranker", "HybridRetriever",
    "KeywordRetriever", "LlmReranker", "LlmTransformer", "MaxPerDocument", "MinScore", "Mmr",
    "ParentExpand", "Passage", "RecencyBoost", "ReciprocalRankFusion", "TeiReranker",
    "TermExpander", "TermOverlapReranker", "WeightedFusion", "WindowExpand", "WithHistory",
]  # fmt: skip
