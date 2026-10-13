"""The search pipeline (Step 32): question in, the best permitted chunks out, every stage traced.

pipeline = SearchPipeline(config.load("rag.yaml", "local"))
result = pipeline.search(Query("How many days of leave?", principal, k=5))
result.hits      # ScoredChunk, best first; .scores shows dense/sparse/fusion/rerank per hit
result.trace     # which components ran, the search texts, counts and milliseconds per stage
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace

from rag_core.components.retrieval import (
    DenseRetriever,
    HybridRetriever,
    KeywordRetriever,
    Passage,
    RetrieverParams,
)
from rag_core.registry import ComponentError, Container
from rag_core.types import Query, ScoredChunk

log = logging.getLogger("rag_core.search")
tracer = trace.get_tracer("rag_core.search")
MAX_TEXTS = 8  # a transformer can't turn one question into 50 searches


@dataclass(frozen=True)
class SearchResult:
    hits: list[ScoredChunk]
    texts: list[str]  # what was actually searched for
    trace: dict[str, Any] = field(default_factory=dict)


def _name(obj: Any) -> str:
    return type(obj).__name__


class SearchPipeline:
    def __init__(self, container: Container) -> None:
        self.c = container
        self.transformer = (
            container.get("query_transformer") if container.has("query_transformer") else None
        )
        self.retriever = (
            container.get("retriever") if container.has("retriever") else self._default_retriever()
        )
        self.reranker = container.get("reranker") if container.has("reranker") else None
        self.post = container.get("postprocessors") if container.has("postprocessors") else []
        self.leaks = 0  # chunks a store returned that the caller may not see (should stay 0)

    def _default_retriever(self) -> Any:
        """No retriever configured: use what the profile has (hybrid if it has both stores)."""
        dense, sparse = self.c.has("vector_store"), self.c.has("keyword_index")
        if dense and sparse:
            return HybridRetriever(self.c, RetrieverParams())
        if dense:
            return DenseRetriever(self.c, RetrieverParams())
        if sparse:
            return KeywordRetriever(self.c, RetrieverParams())
        raise ComponentError("search needs a vector_store and/or a keyword_index")

    def search(self, query: Query) -> SearchResult:
        ms: dict[str, float] = {}
        counts: dict[str, int] = {}

        def timed(stage: str, t0: float) -> None:
            ms[stage] = round((time.perf_counter() - t0) * 1000, 1)

        with tracer.start_as_current_span("rag.search", attributes={"rag.k": query.k}) as span:
            t0 = time.perf_counter()
            with tracer.start_as_current_span("rag.search.transform"):
                texts = self.transformer.transform(query) if self.transformer else [query.text]
            texts = [t for t in texts if str(t).strip()][:MAX_TEXTS] or [query.text]
            timed("transform", t0)

            t0 = time.perf_counter()
            with tracer.start_as_current_span(
                "rag.search.retrieve", attributes={"rag.texts": len(texts)}
            ) as s:
                hits = self.retriever.retrieve(query, texts)
                s.set_attribute("rag.candidates", len(hits))
            counts["retrieved"] = len(hits)
            timed("retrieve", t0)

            # Defence in depth: every store filters by access already. If one ever returns a chunk
            # this caller may not see (a bug, a misconfigured plugin), it's dropped and counted.
            allowed = [h for h in hits if h.chunk.access.allows(query.principal)]
            if len(allowed) != len(hits):
                self.leaks += len(hits) - len(allowed)
                log.error("store returned %d chunk(s) the caller may not see: dropped",
                          len(hits) - len(allowed))  # fmt: skip
                span.set_attribute("rag.search.leaks_dropped", len(hits) - len(allowed))
            hits = allowed

            if self.reranker is not None and hits:
                t0 = time.perf_counter()
                # rerank against the (rewritten) question, never a hypothetical passage
                rq = next((str(t) for t in texts if not isinstance(t, Passage)), query.text)
                top_n = int(getattr(self.reranker, "top_n", len(hits)))
                with tracer.start_as_current_span("rag.search.rerank",
                                                  attributes={"rag.rerank.in": min(len(hits), top_n)}):  # fmt: skip
                    hits = self.reranker.rerank(rq, hits, len(hits))
                counts["reranked"] = len(hits)
                timed("rerank", t0)

            t0 = time.perf_counter()
            for pp in self.post:
                with tracer.start_as_current_span(f"rag.search.post.{_name(pp)}"):
                    hits = pp.process(query, hits)
                counts[_name(pp)] = len(hits)
            timed("postprocess", t0)

            hits = hits[: query.k]
            counts["returned"] = len(hits)
            span.set_attribute("rag.returned", len(hits))
        components = {
            "query_transformer": _name(self.transformer) if self.transformer else None,
            "retriever": _name(self.retriever),
            # set once fusion was actually needed (several lists); a plugin retriever may not have one
            "fusion": _name(f)
            if (f := getattr(self.retriever, "_fusion", None)) is not None
            else None,
            "reranker": _name(self.reranker) if self.reranker else None,
            "postprocessors": [_name(p) for p in self.post],
        }
        return SearchResult(hits, [str(t) for t in texts],
                            {"components": components, "texts": [str(t) for t in texts], "counts": counts, "ms": ms})  # fmt: skip
