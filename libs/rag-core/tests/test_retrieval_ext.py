"""Extension 01: more fusion methods, the ensemble and router retrievers, self-query, the
retrieval-result cache, and metric-aware in-memory search, all offline."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import fakeredis
import pytest
import yaml

from rag_core import config as cfg
from rag_core.answer import AnswerPipeline
from rag_core.components.basics import HashingEmbedder, MemoryVectorStore, ScriptedLLM
from rag_core.components.conversation import cache_key
from rag_core.components.multiretrieval import EnsembleParams, Router, RouterParams
from rag_core.components.retrieval import (
    BordaCount,
    CombMnz,
    CombSum,
    RelativeScoreFusion,
    WeightedFusion,
)
from rag_core.components.searchcache import (
    MemorySearchCache,
    SearchCacheParams,
    ValkeySearchCache,
    ValkeySearchCacheParams,
)
from rag_core.components.selfquery import SelfQuery, SelfQueryParams
from rag_core.filters import FilterError
from rag_core.ingest import IngestionPipeline
from rag_core.registry import ComponentError, Container, Overlay
from rag_core.search import SearchPipeline
from rag_core.similarity import VectorIndexParams, similarity
from rag_core.testing.conformance import (
    ALICE,
    VIEWER,
    filter_chunks,
    sample_chunks,
)
from rag_core.types import Access, Chunk, Principal, Query, ScoredChunk, Source

ROOT = Path(__file__).resolve().parents[3]


def hit(cid: str, score: float, source: str = "dense") -> ScoredChunk:
    return ScoredChunk(Chunk(cid, "doc://a", 0, cid, 1, Access("public")), score, {source: score})


def ids(hits: Sequence[ScoredChunk]) -> list[str]:
    return [h.chunk.id for h in hits]


def offline(**slots: Any) -> Container:
    config = cfg.resolve(yaml.safe_load((ROOT / "rag.yaml").read_text()), "offline", env={})
    config.update(slots)
    return Container({k: v for k, v in config.items() if v != "none"}, "test")


DENSE = [hit("a", 0.90), hit("b", 0.80), hit("c", 0.10)]
SPARSE = [hit("c", 30.0, "sparse"), hit("d", 20.0, "sparse"), hit("a", 10.0, "sparse")]


# ---------------------------------------------------------------- fusion


def test_relative_score_is_weighted_with_one_alpha() -> None:
    rel = RelativeScoreFusion({"dense": 0.7, "sparse": 0.3}).fuse([DENSE, SPARSE])
    weighted = WeightedFusion({"dense": 0.7, "sparse": 0.3}).fuse([DENSE, SPARSE])
    assert [(h.chunk.id, h.score) for h in rel] == [(h.chunk.id, h.score) for h in weighted]
    c = offline(fusion={"use": "relative-score", "alpha": 0.7})
    assert c.get("fusion").weights == pytest.approx({"dense": 0.7, "sparse": 0.3})


def test_combsum_and_combmnz() -> None:
    s = {h.chunk.id: h.score for h in CombSum({}).fuse([DENSE, SPARSE])}
    # min-max: dense a=1, b=0.875, c=0; sparse c=1, d=0.5, a=0
    assert s == pytest.approx({"a": 1.0, "b": 0.875, "c": 1.0, "d": 0.5})
    m = {h.chunk.id: h.score for h in CombMnz({}).fuse([DENSE, SPARSE])}
    assert m == pytest.approx({"a": 2.0, "b": 0.875, "c": 2.0, "d": 0.5})  # found twice: doubled
    # z-scores: a chunk at the bottom of one list is PENALISED (below the mean), not just unhelped
    z = CombSum({}, "zscore").fuse([DENSE, SPARSE])
    assert ids(z)[0] == "b"


def test_borda_counts_positions() -> None:
    out = {h.chunk.id: h.score for h in BordaCount({}).fuse([DENSE, SPARSE])}
    assert out == {"a": 3 + 1, "b": 2, "c": 1 + 3, "d": 2}


def test_list_weights_override_source_weights() -> None:
    out = CombSum({"dense": 100.0}).fuse([DENSE, SPARSE], list_weights=[0.0, 1.0])
    assert ids(out)[0] == "c"
    with pytest.raises(ValueError, match="one weight per ranked list"):
        CombSum({}).fuse([DENSE, SPARSE], list_weights=[1.0])


@pytest.mark.parametrize(
    "name", ["rrf", "weighted", "dbsf", "relative-score", "combsum", "combmnz", "borda"]
)
def test_every_fusion_finds_both_sides_in_the_pipeline(name: str) -> None:
    c = offline(fusion={"use": name}, reranker="none", postprocessors=[])
    chunks = sample_chunks()
    c.get("vector_store").upsert(
        chunks, c.get("embedder").embed_documents([x.text for x in chunks])
    )
    c.get("keyword_index").index(chunks)
    hits = SearchPipeline(c).search(Query("parental leave weeks", ALICE, k=3)).hits
    assert hits[0].chunk.text.startswith("Parental leave")
    assert "fusion" in hits[0].scores


# ---------------------------------------------------------------- metrics (memory reference)


def test_memory_store_ranks_by_the_chosen_metric() -> None:
    q, near, long = [1.0, 0.0], [0.9, 0.1], [5.0, 5.0]
    assert similarity("cosine", q, near) > similarity("cosine", q, long)
    assert similarity("dot", q, long) > similarity("dot", q, near)  # length counts
    assert similarity("l2", q, q) == 1.0
    assert 0 < similarity("l2", q, long) < 1
    assert similarity("l1", q, [0.0, 0.0]) == pytest.approx(0.5)
    with pytest.raises(ValueError, match="unknown metric"):
        similarity("hamming", q, q)
    c = offline(vector_store={"use": "memory", "metric": "dot"})
    assert c.get("vector_store").metric == "dot"


def test_index_settings_are_validated() -> None:
    with pytest.raises(ValueError, match="ef_construction must be at least 2 x hnsw_m"):
        VectorIndexParams(hnsw_m=48, ef_construction=64)
    problems = Container({"vector_store": {"use": "qdrant", "index_type": "ivfflat"}}).validate()
    assert problems
    assert "no ivfflat" in problems[0]
    problems = Container(
        {"vector_store": {"use": "pgvector", "index_type": "ivfflat", "metric": "l1"}}
    ).validate()
    assert problems
    assert "no l1" in problems[0]
    problems = Container({"vector_store": {"use": "opensearch-knn", "metric": "l1"}}).validate()
    assert problems
    assert "nmslib" in problems[0]


# ---------------------------------------------------------------- ensemble and router


def two_collections(**slots: Any) -> tuple[Container, list[Chunk]]:
    """The main profile, plus an 'archive' collection in a second in-memory store."""
    c = offline(reranker="none", postprocessors=[], query_transformer="none", **slots)
    emb = c.get("embedder")
    main, archive = sample_chunks(), [
        Chunk("arch1", "doc://archive-2019", 0, "Parental leave was 12 weeks in 2019.", 7, Access("internal", ("hr",)))
    ]  # fmt: skip
    c.get("vector_store").upsert(main, emb.embed_documents([x.text for x in main]))
    c.get("keyword_index").index(main)
    return c, archive


def test_overlay_changes_some_slots_and_shares_the_rest() -> None:
    c = offline()
    o = Overlay(c, {"vector_store": {"use": "memory", "metric": "l2"}}, "child")
    assert o.get("embedder") is c.get("embedder")  # shared
    assert o.get("vector_store") is not c.get("vector_store")
    assert o.get("vector_store").metric == "l2"
    with pytest.raises(ComponentError, match="unknown slot"):
        Overlay(c, {"vectorstore": "memory"}, "x")


def test_ensemble_searches_every_member_in_parallel_and_fuses() -> None:
    c, archive = two_collections(retriever={"use": "ensemble", "members": [
        {"name": "vectors", "retriever": {"use": "dense"}},
        {"name": "keywords", "retriever": {"use": "keyword"}, "weight": 0.5},
        {"name": "archive", "retriever": {"use": "dense"}, "slots": {"vector_store": {"use": "memory"}}},
    ]}, fusion={"use": "combsum"})  # fmt: skip
    pipe = SearchPipeline(c)
    member = pipe.retriever.members[2][
        2
    ].get()  # the archive's own store, filled like ingestion would
    member.c.get("vector_store").upsert(
        archive, c.get("embedder").embed_documents([archive[0].text])
    )
    result = pipe.search(Query("parental leave weeks", ALICE, k=10))
    uris = [h.chunk.document_uri for h in result.hits]
    assert "doc://archive-2019" in uris
    assert "doc://leave" in uris
    assert result.trace["retriever"]["members"]["archive"] == 1
    assert result.trace["components"]["fusion"] == "CombSum"
    # permissions still apply to every member: BOB isn't in hr
    bob = Principal("bob", ("eng",), ("public", "internal"))
    assert "doc://archive-2019" not in {
        h.chunk.document_uri for h in pipe.search(Query("parental leave", bob, k=10)).hits
    }


def test_ensemble_settings_are_checked() -> None:
    with pytest.raises(ValueError, match="unique"):
        EnsembleParams.model_validate(
            {"members": [{"retriever": {"use": "dense"}}, {"retriever": {"use": "dense"}}]}
        )
    with pytest.raises(ValueError, match="profile OR slots"):
        EnsembleParams.model_validate({"members": [{"name": "a", "profile": "x", "slots": {"embedder": "hashing"}},
                                                   {"name": "b"}]})  # fmt: skip
    with pytest.raises(ValueError, match="unknown operator"):
        EnsembleParams.model_validate(
            {"members": [{"name": "a", "filter": {"x": {"like": 1}}}, {"name": "b"}]}
        )


ROUTES = {
    "hr": {"keywords": ["leave", "parental", "salary"], "description": "HR policies",
           "filter": {"doc": ["doc://leave", "doc://salary"]}},
    "it": {"keywords": ["deployment", "argo cd"], "description": "engineering docs", "retriever": {"use": "keyword"}},
    "general": {"description": "everything else"},
}  # fmt: skip


def test_router_rules_pick_by_keywords_and_default() -> None:
    c, _ = two_collections()
    router = Router(c, RouterParams.model_validate({"routes": ROUTES, "default": "general"}))
    assert router.choose("How many weeks of parental leave?") == (["hr"], "rules")
    assert router.choose("How does a deployment through Argo CD work?") == (["it"], "rules")
    assert router.choose("When does the office open?") == (["general"], "rules")
    multi = Router(c, RouterParams.model_validate({"routes": ROUTES, "multi": True}))
    assert multi.choose("leave before a deployment")[0] == ["hr", "it"]


def test_router_applies_the_route_and_reports_it() -> None:
    c, _ = two_collections(retriever={"use": "router", "routes": ROUTES, "default": "general"})
    result = SearchPipeline(c).search(Query("parental leave and salary", ALICE, k=10))
    assert {h.chunk.document_uri for h in result.hits} <= {
        "doc://leave",
        "doc://salary",
    }  # the route's filter
    assert result.trace["retriever"] == {"route": "hr", "how": "rules"}


def test_llm_router_with_fallback_to_rules() -> None:
    c, _ = two_collections()
    p = RouterParams.model_validate({"routes": ROUTES, "mode": "llm"})
    assert Router(c, p, ScriptedLLM(default="it")).choose("anything") == (["it"], "llm")
    assert (
        Router(c, p, ScriptedLLM(default="I am not sure")).choose("parental leave")[1]
        == "rules (llm fallback)"
    )

    def boom(system: str, user: str) -> str:
        raise RuntimeError("gateway down")

    assert Router(c, p, ScriptedLLM(fn=boom)).choose("parental leave") == (
        ["hr"],
        "rules (llm fallback)",
    )
    with pytest.raises(ValueError, match="default"):
        RouterParams.model_validate({"routes": ROUTES, "default": "nope"})


def test_router_route_can_use_another_profile(tmp_path: Path) -> None:
    rag = tmp_path / "rag.yaml"
    rag.write_text(yaml.safe_dump({"version": 1, "profiles": {"it-helpdesk": {
        "embedder": {"use": "hashing", "dimensions": 64}, "keyword_index": "memory-bm25"}}}))  # fmt: skip
    c, _ = two_collections()
    router = Router(c, RouterParams.model_validate({"routes": {
        "it": {"keywords": ["vpn"], "profile": "it-helpdesk", "file": str(rag), "retriever": {"use": "keyword"}},
        "main": {}}}))  # fmt: skip
    assert router.retrieve(Query("vpn error", ALICE), ["vpn error"]) == []  # its own (empty) index
    assert router.last_info() == {"route": "it", "how": "rules"}


# ---------------------------------------------------------------- self-query

SCHEMA = {
    "department": {"values": {"hr": ["human resources", "people team"], "it": ["tech support"], "finance": []}},
    "doc_type": {"values": {"policy": ["policies"], "guide": ["guides", "how to"], "form": ["forms"]}},
    "language": {"values": {"en": ["english"], "fr": ["french"], "de": ["german"]}},
    "updated": {"type": "date", "aliases": ["updated", "changed", "modified"]},
    "version": {"type": "number"},
}  # fmt: skip


def sq(mode: str = "rules", llm: Any = None, **kw: Any) -> SelfQuery:
    return SelfQuery(
        SelfQueryParams.model_validate({"fields": SCHEMA, "mode": mode, **kw}),
        llm,
        today=date(2026, 10, 13),
    )


@pytest.mark.parametrize(("question", "want"), [
    ("HR policies updated after 2025", {"and": [{"department": "hr"}, {"doc_type": "policy"}, {"updated": {"gte": "2026-01-01"}}]}),
    ("guides from the people team since March 2025", {"and": [{"department": "hr"}, {"doc_type": "guide"}, {"updated": {"gte": "2025-03-01"}}]}),
    ("finance forms changed before 2024", {"and": [{"department": "finance"}, {"doc_type": "form"}, {"updated": {"lt": "2024-01-01"}}]}),
    ("policies in French modified in 2025", {"and": [{"doc_type": "policy"}, {"language": "fr"}, {"updated": {"gte": "2025-01-01", "lt": "2026-01-01"}}]}),
    ("what changed between 2024-02-01 and 2024-03-15", {"updated": {"gte": "2024-02-01", "lt": "2024-03-16"}}),
    ("IT or finance policies updated this year", {"and": [{"department": {"in": ["it", "finance"]}}, {"doc_type": "policy"}, {"updated": {"gte": "2026-01-01", "lt": "2027-01-01"}}]}),
    ("How many days of annual leave?", {}),
], ids=lambda v: str(v)[:30])  # fmt: skip
def test_self_query_rules(question: str, want: dict[str, Any]) -> None:
    assert sq().analyze(Query(question, ALICE)) == ([question], want)


def test_self_query_llm_is_checked_against_the_schema() -> None:
    good = ScriptedLLM(
        default='Here: {"filter": {"department": "hr", "updated": {"gte": "2026-01-01"}}}'
    )
    assert sq("llm", good).analyze(Query("people stuff lately", ALICE))[1] == {
        "and": [{"department": {"eq": "hr"}}, {"updated": {"gte": "2026-01-01"}}]}  # fmt: skip
    assert "department" in good.calls[0][0]
    assert "2026-10-13" in good.calls[0][0]
    # an undeclared field, an undeclared value, a broken reply: the rules answer instead
    for reply in ('{"filter": {"classification": "public"}}', '{"filter": {"department": "legal"}}',
                  '{"filter": {"updated": {"gte": 5}}}', "no json at all", '{"filter": {"x": {"like": 1}}}'):  # fmt: skip
        assert sq("llm", ScriptedLLM(default=reply)).analyze(Query("HR policies", ALICE))[1] == {
            "and": [{"department": "hr"}, {"doc_type": "policy"}]}, reply  # fmt: skip
    assert (
        sq("llm", ScriptedLLM(default='{"filter": {}}')).analyze(Query("HR policies", ALICE))[1]
        == {}
    )


def test_self_query_schema_is_validated() -> None:
    with pytest.raises(ValueError, match="date_field"):
        SelfQueryParams.model_validate({"fields": SCHEMA, "date_field": "doc_type"})
    with pytest.raises(ValueError, match="not a valid field name"):
        SelfQueryParams.model_validate({"fields": {"bad name": {}}})


def filter_container(**slots: Any) -> Container:
    c = offline(reranker="none", postprocessors=[], **slots)
    chunks = filter_chunks()
    c.get("vector_store").upsert(
        chunks, c.get("embedder").embed_documents([x.text for x in chunks])
    )
    c.get("keyword_index").index(chunks)
    return c


def test_self_query_filter_is_applied_with_the_callers_and_falls_back_when_empty() -> None:
    c = filter_container(query_transformer={"use": "self-query", "fields": SCHEMA})
    pipe = SearchPipeline(c)
    r = pipe.search(Query("staff note from the people team", VIEWER, k=10))
    assert {h.chunk.document_uri for h in r.hits} == {"doc://f1", "doc://f2"}
    assert r.trace["filters"]["self_query"] == {"department": "hr"}
    # the caller's filter still applies: ANDed, never replaced
    r = pipe.search(Query("staff note from the people team", VIEWER, {"language": "fr"}, k=10))
    assert {h.chunk.document_uri for h in r.hits} == {"doc://f2"}
    # nothing matches the extracted filter: search again without it (the caller's filter stays)
    r = pipe.search(Query("staff note: finance guides", VIEWER, {"language": "en"}, k=10))
    assert r.trace["filters"]["fallback"] is True
    assert {h.chunk.metadata["language"] for h in r.hits} == {"en"}


def test_self_query_inside_a_chain() -> None:
    c = filter_container(query_transformer={"use": "chain", "steps": [
        {"use": "self-query", "fields": SCHEMA}, {"use": "expand-terms", "terms": {"it": "information technology"}}]})  # fmt: skip
    r = SearchPipeline(c).search(Query("staff policy note it policies", VIEWER, k=10))
    assert r.trace["filters"]["self_query"] == {
        "and": [{"department": {"eq": "it"}}, {"doc_type": {"eq": "policy"}}]
    }
    assert {h.chunk.document_uri for h in r.hits} == {"doc://f3"}


def test_invalid_filter_fails_before_any_search() -> None:
    c = filter_container()
    with pytest.raises(FilterError, match="unknown operator"):
        SearchPipeline(c).search(Query("x", VIEWER, {"a": {"like": "b"}}))


# ---------------------------------------------------------------- the retrieval-result cache


class CountingStore(MemoryVectorStore):
    calls = 0

    def search(self, *a: Any, **kw: Any) -> list[ScoredChunk]:
        CountingStore.calls += 1
        return super().search(*a, **kw)


def cached_container(cache: Any) -> Container:
    c = offline(retriever="dense", reranker="none", postprocessors=[], query_transformer="none",
                search_cache={"use": "memory"}, cache="none")  # fmt: skip
    c._built.update({"vector_store": CountingStore(), "search_cache": cache})
    return c


@pytest.mark.parametrize("cache", [
    lambda: MemorySearchCache(SearchCacheParams()),
    lambda: ValkeySearchCache(ValkeySearchCacheParams(), client=fakeredis.FakeRedis(decode_responses=True)),
], ids=["memory", "valkey"])  # fmt: skip
def test_search_cache_hits_misses_and_invalidation(cache: Any) -> None:
    c = cached_container(cache())
    ingest = IngestionPipeline(c)
    ingest.ingest(Source("file:///leave.md", b"# Leave\n\nParental leave is 18 weeks at full pay.",
                         "text/markdown", Access("internal", ("hr",))))  # fmt: skip
    pipe = SearchPipeline(c)
    CountingStore.calls = 0
    first = pipe.search(Query("parental leave", ALICE, k=3))
    again = pipe.search(Query("Parental   leave?", ALICE, k=3))  # same words: same key
    assert CountingStore.calls == 1
    assert again.trace["cache"] == "hit"
    assert first.trace["cache"] == "miss"
    assert [h.chunk.id for h in again.hits] == [h.chunk.id for h in first.hits]
    assert again.hits[0].chunk.access == first.hits[0].chunk.access
    # another access set, another filter, another k: not the same entry
    pipe.search(
        Query(
            "parental leave",
            Principal("x", ("eng", "hr"), ("public", "internal", "confidential")),
            k=3,
        )
    )
    pipe.search(Query("parental leave", ALICE, {"lang": "en"}, k=3))
    pipe.search(Query("parental leave", ALICE, k=4))
    assert CountingStore.calls == 4
    # ingestion starts a new epoch: no result outlives a change to the documents
    ingest.ingest(Source("file:///new.md", b"# New\n\nParental leave is now 20 weeks.", "text/markdown",
                         Access("internal", ("hr",))))  # fmt: skip
    after = pipe.search(Query("parental leave", ALICE, k=3))
    assert after.trace["cache"] == "miss"
    assert CountingStore.calls == 5
    assert "file:///new.md" in {h.chunk.document_uri for h in after.hits}


def test_answer_cache_key_includes_the_filter() -> None:
    plain = cache_key(ALICE, "leave?", (), "v1")
    assert plain == cache_key(
        ALICE, "leave?", (), "v1", {}
    )  # no filter: the Step 33 key, unchanged
    assert plain != cache_key(ALICE, "leave?", (), "v1", {"department": "hr"})
    assert cache_key(ALICE, "q", (), "v", {"a": 1, "b": 2}) == cache_key(
        ALICE, "q", (), "v", {"b": 2, "a": 1}
    )


def test_answers_take_a_filter() -> None:
    c = filter_container(cache={"use": "memory"})
    a = AnswerPipeline(c).answer("staff policy note", VIEWER, filters={"department": "finance"})
    assert a.trace["context"]["documents"] == ["doc://f4"]
    b = AnswerPipeline(c).answer("staff policy note", VIEWER, filters={"department": "it"})
    assert b.trace.get("cache") == "miss"
    assert set(b.trace["context"]["documents"]) == {
        "doc://f3",
        "doc://f5",
    }


def test_hashing_embedder_is_unit_length_so_dot_equals_cosine() -> None:
    e = HashingEmbedder(64)
    a, b = e.embed_documents(["annual leave", "parental leave"])
    assert similarity("dot", a, b) == pytest.approx(similarity("cosine", a, b))


# ---------------------------------------------------------------- the command line


def test_cli_search_filter_and_index_ddl(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from rag_core.cli import main

    hb = ROOT / "examples/corpus/handbook"
    base = ["search", "How many weeks of leave?", "--file", str(ROOT / "rag.yaml"), "--profile", "offline",
            "--group", "hr", "--ingest", str(hb / "parental-leave.md"), str(hb / "sick-leave.md")]  # fmt: skip
    assert main([*base, "--filter", "title=Sick leave", "--json"]) == 0
    out = capsys.readouterr().out
    hits = __import__("json").loads(out)["hits"]
    assert hits
    assert {h["document"].rsplit("/", 1)[-1] for h in hits} == {"sick-leave.md"}
    assert main([*base, "--filter", "title>=yesterday"]) == 2
    assert "ISO date" in capsys.readouterr().err
    monkeypatch.setenv(
        "RAG__VECTOR_STORE", "{use: pgvector, dsn_env: RAG_TEST_UNSET_DSN, metric: dot}"
    )
    assert main(["index", "ddl", "--file", str(ROOT / "rag.yaml"), "--profile", "offline"]) == 0
    assert "USING hnsw (embedding halfvec_ip_ops)" in capsys.readouterr().out
