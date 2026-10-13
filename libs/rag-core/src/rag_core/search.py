"""The search pipeline (Step 32): question in, the best permitted chunks out, every stage traced.

pipeline = SearchPipeline(config.load("rag.yaml", "local"))
result = pipeline.search(Query("How many days of leave?", principal, k=5))
result.hits      # ScoredChunk, best first; .scores shows dense/sparse/fusion/rerank per hit
result.trace     # which components ran, the search texts, counts and milliseconds per stage
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

from opentelemetry import trace

from rag_core import filters as _filters
from rag_core.components.retrieval import (
    DenseRetriever,
    HybridRetriever,
    KeywordRetriever,
    Passage,
    RetrieverParams,
)
from rag_core.components.searchcache import search_key
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
        # extension 01: cached results, keyed by access, question, filter and index epoch
        self.cache = container.get("search_cache") if container.has("search_cache") else None
        self._settings = hashlib.sha256(
            json.dumps(dict(container.config), sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
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

    def _transform(self, query: Query) -> tuple[list[str], dict[str, Any]]:
        """The search texts, and the metadata filter a self-query transformer found (or {})."""
        if self.transformer is None:
            return [query.text], {}
        if hasattr(self.transformer, "analyze"):
            texts, found = self.transformer.analyze(query)
            return list(texts), dict(found or {})
        return list(self.transformer.transform(query)), {}

    def search(self, query: Query) -> SearchResult:
        # extension 01: an invalid metadata filter fails HERE, with a clear message, before any
        # model or store is called (rag-api turns it into a 422)
        _filters.parse(query.filters)
        key = None
        if self.cache is not None:
            key = search_key(query.principal, query.text, query.history, query.filters, query.k,
                             f"{self._settings}|{self.cache.epoch()}")  # fmt: skip
            cached = self.cache.get(key)
            if cached is not None:
                hits, texts = cached
                return SearchResult(hits, texts, {"cache": "hit", "texts": texts, "counts": {"returned": len(hits)},
                                                  "components": {"search_cache": _name(self.cache)}, "ms": {}})  # fmt: skip
        result = self._search(query)
        if self.cache is not None and key is not None:
            result.trace["cache"] = "miss"
            self.cache.put(key, result.hits, result.texts)
        return result

    def search_with(self, query: Query, texts: list[str] | None = None,
                    retriever: Any = None) -> SearchResult:  # fmt: skip
        """The same search with the architecture's own search texts and/or retriever (extension
        03: rag-fusion's variants, hyde's passage, `vector`'s dense-only retriever). Access
        checks, the reranker and the post-processors run exactly as in `search`; not cached."""
        _filters.parse(query.filters)
        return self._search(query, texts, retriever)

    def _search(self, query: Query, given: list[str] | None = None,
                retriever: Any = None) -> SearchResult:  # fmt: skip
        retriever = retriever if retriever is not None else self.retriever
        ms: dict[str, float] = {}
        counts: dict[str, int] = {}
        info: dict[str, Any] = {}

        def timed(stage: str, t0: float) -> None:
            ms[stage] = round((time.perf_counter() - t0) * 1000, 1)

        with tracer.start_as_current_span("rag.search", attributes={"rag.k": query.k}) as span:
            t0 = time.perf_counter()
            with tracer.start_as_current_span("rag.search.transform"):
                texts, found = (list(given), {}) if given else self._transform(query)
            texts = [t for t in texts if str(t).strip()][:MAX_TEXTS] or [query.text]
            timed("transform", t0)
            asked = query
            if found:  # self-query: ANDed with the caller's filter (never replacing it)
                query = replace(query, filters=_filters.combine(query.filters, found))
                info["filters"] = {"request": dict(asked.filters), "self_query": found}

            t0 = time.perf_counter()
            with tracer.start_as_current_span(
                "rag.search.retrieve", attributes={"rag.texts": len(texts)}
            ) as s:
                hits = retriever.retrieve(query, texts)
                if not hits and found and getattr(self.transformer, "fallback_on_empty", True):
                    # the extracted filter matched nothing: a wrong guess costs recall, not the answer
                    hits = retriever.retrieve(asked, texts)
                    info["filters"]["fallback"] = True
                    query = asked
                s.set_attribute("rag.candidates", len(hits))
            counts["retrieved"] = len(hits)
            timed("retrieve", t0)
            if hasattr(retriever, "last_info"):  # ensemble members, router's route
                info["retriever"] = retriever.last_info()

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
            "query_transformer": _name(self.transformer)
            if self.transformer and not given
            else None,
            "retriever": _name(retriever),
            # set once fusion was actually needed (several lists); a plugin retriever may not have one
            "fusion": _name(f) if (f := getattr(retriever, "_fusion", None)) is not None else None,
            "reranker": _name(self.reranker) if self.reranker else None,
            "postprocessors": [_name(p) for p in self.post],
        }
        trace_data = {
            "components": components,
            "texts": [str(t) for t in texts],
            "counts": counts,
            "ms": ms,
        }
        return SearchResult(hits, [str(t) for t in texts], trace_data | info)
