"""Search: transformers, retrievers, fusion, rerankers, post-processors, the pipeline and the
evaluation command (Step 32)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
import yaml

from rag_core import config as cfg
from rag_core import evaluate as ev
from rag_core.cli import main
from rag_core.components.basics import (
    HashingEmbedder,
    MemoryKeywordIndex,
    MemoryVectorStore,
    ScriptedLLM,
)
from rag_core.components.retrieval import (
    Dedupe,
    DistributionFusion,
    GatewayReranker,
    GatewayRerankParams,
    LlmReranker,
    LlmRerankParams,
    LlmTransformer,
    LlmTransformParams,
    MaxPerDocument,
    MinScore,
    MinScoreParams,
    Mmr,
    OverlapRerankParams,
    ParentExpand,
    Passage,
    RecencyBoost,
    RecencyParams,
    ReciprocalRankFusion,
    TeiReranker,
    TeiRerankParams,
    TermExpander,
    TermOverlapReranker,
    WeightedFusion,
    WindowExpand,
    WithHistory,
)
from rag_core.registry import ComponentError, Container
from rag_core.search import SearchPipeline
from rag_core.testing.conformance import ALICE, BOB, OTHER_TENANT, check_reranker, sample_chunks
from rag_core.types import Access, Chunk, Principal, Query, ScoredChunk, Turn

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "examples/eval/handbook.yaml"


def hit(
    cid: str, score: float, source: str = "dense", uri: str = "doc://a", text: str = "", **meta: Any
) -> ScoredChunk:
    ch = Chunk(cid, uri, 0, text or f"text of {cid}", 3, Access("public"), metadata=meta)
    return ScoredChunk(ch, score, {source: score})


def ids(hits: Sequence[ScoredChunk]) -> list[str]:
    return [h.chunk.id for h in hits]


def offline(**slots: Any) -> Container:
    config = cfg.resolve(yaml.safe_load((ROOT / "rag.yaml").read_text()), "offline", env={})
    config.update(slots)
    return Container({k: v for k, v in config.items() if v != "none"}, "test")


def loaded(container: Container) -> Container:
    chunks = sample_chunks()
    emb = container.get("embedder")
    container.get("vector_store").upsert(chunks, emb.embed_documents([c.text for c in chunks]))
    container.get("keyword_index").index(chunks)
    return container


# ---------------------------------------------------------------- fusion


def test_rrf_uses_ranks_only() -> None:
    dense = [hit("a", 0.91), hit("b", 0.90), hit("c", 0.10)]
    sparse = [hit("c", 40.0, "sparse"), hit("a", 2.0, "sparse")]
    out = ReciprocalRankFusion(k=60).fuse([dense, sparse])
    assert ids(out) == ["a", "c", "b"]
    assert out[0].score == pytest.approx(1 / 61 + 1 / 62, abs=1e-6)
    assert out[0].scores["dense"] == 0.91
    assert out[0].scores["sparse"] == 2.0
    weighted = ReciprocalRankFusion(k=60, weights={"sparse": 3.0}).fuse([dense, sparse])
    assert ids(weighted)[0] == "c"  # weights per source change the winner


def test_weighted_and_dbsf_use_score_sizes() -> None:
    dense = [hit("a", 0.90), hit("b", 0.89), hit("c", 0.20)]
    sparse = [hit("b", 9.0, "sparse"), hit("c", 8.9, "sparse"), hit("a", 0.1, "sparse")]
    w = WeightedFusion({"dense": 0.5, "sparse": 0.5}).fuse([dense, sparse])
    assert ids(w)[0] == "b"  # nearly top in both beats top in one, bottom in the other
    assert w[0].scores["fusion"] == pytest.approx(0.5 * (0.69 / 0.70) + 0.5, abs=1e-3)
    d = DistributionFusion({}).fuse([dense, sparse])
    assert ids(d)[0] == "b"
    assert all(0 <= h.score <= 2 for h in d)


# ---------------------------------------------------------------- retrievers and access


@pytest.mark.parametrize("retriever", ["dense", "keyword", "hybrid"])
def test_retrievers_respect_access(retriever: str) -> None:
    c = loaded(offline(retriever=retriever, reranker="none", postprocessors=[]))
    p = SearchPipeline(c)
    for who in (ALICE, BOB, OTHER_TENANT):
        for q in (
            "salary bands for engineers",
            "parental leave weeks",
            "deployments Argo CD",
            "coffee",
        ):
            for h in p.search(Query(q, who, k=10)).hits:
                assert h.chunk.access.allows(who), f"LEAK: {who.subject} got {h.chunk.id}"
    assert "Parental" in p.search(Query("parental leave weeks", ALICE, k=1)).hits[0].chunk.text
    assert p.search(Query("parental leave weeks", OTHER_TENANT)).hits == []  # other tenant: nothing


def test_hybrid_finds_what_each_side_misses() -> None:
    c = loaded(offline(retriever="hybrid", reranker="none", postprocessors=[]))
    r = SearchPipeline(c).search(Query("Argo CD deployments", BOB, k=3))
    assert r.trace["components"]["fusion"] == "ReciprocalRankFusion"
    top = r.hits[0]
    assert {"dense", "sparse", "fusion"} <= set(top.scores)


class SpyEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        super().__init__(64)
        self.docs: list[str] = []
        self.queries: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.docs += list(texts)
        return super().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return super().embed_query(text)


class SpyIndex(MemoryKeywordIndex):
    def __init__(self) -> None:
        super().__init__()
        self.searched: list[str] = []

    def search(
        self, text: str, principal: Principal, k: int, filters: Mapping[str, object] | None = None
    ) -> list[ScoredChunk]:
        self.searched.append(text)
        return super().search(text, principal, k, filters)


def test_hyde_passage_is_embedded_as_a_document_and_not_keyword_searched() -> None:
    c = offline(retriever="hybrid", reranker="none", postprocessors=[])
    spy, idx = SpyEmbedder(), SpyIndex()
    c._built.update({"embedder": spy, "vector_store": MemoryVectorStore(), "keyword_index": idx})
    from rag_core.components.retrieval import HybridRetriever, RetrieverParams

    HybridRetriever(c, RetrieverParams()).retrieve(
        Query("leave?", ALICE), ["leave?", Passage("Staff get 20 days.")]
    )
    assert spy.queries == ["leave?"]
    assert spy.docs == ["Staff get 20 days."]
    assert idx.searched == ["leave?"]


def test_filters_reach_the_store() -> None:
    c = loaded(offline(retriever="keyword", reranker="none", postprocessors=[]))
    hits = (
        SearchPipeline(c).search(Query("leave", ALICE, filters={"doc": "doc://leave"}, k=10)).hits
    )
    assert hits
    assert {h.chunk.document_uri for h in hits} == {"doc://leave"}


# ---------------------------------------------------------------- query transformers


def transformer(kind: str, llm: Any, **kw: Any) -> LlmTransformer:
    return LlmTransformer(kind, llm, LlmTransformParams(**kw))


def test_multi_query_parses_lines_and_keeps_the_original() -> None:
    llm = ScriptedLLM(
        default="1. annual leave days\n- holiday entitlement\n2) annual leave days\n\nleave per year"
    )
    assert transformer("multi-query", llm, n=3).transform(Query("How much leave?", ALICE)) == [
        "How much leave?", "annual leave days", "holiday entitlement", "leave per year"]  # fmt: skip
    assert "3 different" in llm.calls[0][0]


def test_rewrite_uses_the_conversation() -> None:
    llm = ScriptedLLM(default="How do I fix VPN error E-4021?")
    q = Query("How do I fix it?", ALICE, history=(Turn("user", "My VPN shows E-4021"),))
    assert transformer("rewrite", llm).transform(q) == [
        "How do I fix VPN error E-4021?",
        "How do I fix it?",
    ]
    assert "My VPN shows E-4021" in llm.calls[0][1]


def test_hyde_and_step_back_and_decompose() -> None:
    hy = transformer("hyde", ScriptedLLM(default="Employees receive 20 days.")).transform(
        Query("leave?", ALICE)
    )
    assert hy == ["leave?", "Employees receive 20 days."]
    assert isinstance(hy[1], Passage)
    sb = transformer(
        "step-back", ScriptedLLM(default="What is the leave policy?\nextra")
    ).transform(Query("leave?", ALICE))
    assert sb == ["leave?", "What is the leave policy?"]
    dc = transformer(
        "decompose", ScriptedLLM(default="a?\nb?\nc?\nd?"), n=2, include_original=False
    )
    assert dc.transform(Query("a and b?", ALICE)) == ["a?", "b?"]


def test_llm_failure_falls_back_to_the_question() -> None:
    def boom(system: str, user: str) -> str:
        raise RuntimeError("gateway down")

    assert transformer("multi-query", ScriptedLLM(fn=boom)).transform(Query("leave?", ALICE)) == [
        "leave?"
    ]


def test_offline_transformers_and_chain() -> None:
    q = Query("Can I WFH on Fridays?", ALICE)
    assert TermExpander({"WFH": "work from home"}).transform(q) == [
        "Can I WFH on Fridays? (work from home)"
    ]
    q2 = Query(
        "how do I fix it?",
        ALICE,
        history=(Turn("user", "VPN E-4021"), Turn("assistant", "expired cert")),
    )
    assert WithHistory(2).transform(q2) == ["VPN E-4021 how do I fix it?"]
    c = offline(llm={"use": "scripted", "default": "alt one\nalt two"},
                query_transformer={"use": "chain", "steps": [{"use": "expand-terms", "terms": {"wfh": "work from home"}},
                                                             {"use": "multi-query", "n": 2}]})  # fmt: skip
    out = c.get("query_transformer").transform(q)
    assert out == ["Can I WFH on Fridays? (work from home)", "alt one", "alt two"]


# ---------------------------------------------------------------- rerankers


def mock_client(handler: Any, base: str) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base)


def test_gateway_reranker_request_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_GATEWAY_KEY", "sk-test")
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content), auth=req.headers["authorization"], path=req.url.path)
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.9},
                                                     {"index": 0, "relevance_score": 0.2}]})  # fmt: skip

    p = GatewayRerankParams(top_n=2, max_chars=100)
    r = GatewayReranker(p, mock_client(handler, "http://gw/"))
    out = r.rerank("q", [hit("a", 1, text="a" * 150), hit("b", 0.5), hit("c", 0.1)], 5)
    assert ids(out) == ["b", "a"]  # only top_n were read; c was never sent
    assert seen["path"] == "/rerank"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["model"] == "reranker"
    assert seen["documents"][0] == "a" * 100  # cut to max_chars
    assert out[0].scores == {"dense": 0.5, "rerank": 0.9}


def test_tei_reranker() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["texts"]
        assert body["truncate"] is True
        return httpx.Response(200, json=[{"index": 0, "score": 0.1}, {"index": 1, "score": 0.7}])

    out = TeiReranker(TeiRerankParams(), mock_client(handler, "http://tei/")).rerank(
        "q", [hit("a", 1), hit("b", 0.5)], 2
    )
    assert ids(out) == ["b", "a"]


def test_reranker_failure_is_fail_open_by_default() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    r = GatewayReranker(GatewayRerankParams(), mock_client(down, "http://gw/"))
    out = r.rerank("q", [hit("a", 1), hit("b", 0.5)], 5)
    assert ids(out) == ["a", "b"]
    assert "rerank_skipped" in out[0].scores
    assert r.failures == 1
    strict = GatewayReranker(GatewayRerankParams(fail_open=False), mock_client(down, "http://gw/"))
    with pytest.raises(httpx.HTTPStatusError):
        strict.rerank("q", [hit("a", 1)], 5)


def test_llm_listwise_reranker() -> None:
    llm = ScriptedLLM(default="3 > 1")
    out = LlmReranker(LlmRerankParams(), llm).rerank(
        "q", [hit("a", 1), hit("b", 0.9), hit("c", 0.8)], 3
    )
    assert ids(out) == ["c", "a", "b"]
    assert out[-1].score == 0.0
    assert "[3] text of c" in llm.calls[0][1]
    garbled = LlmReranker(LlmRerankParams(), ScriptedLLM(default="no idea"))
    assert ids(garbled.rerank("q", [hit("a", 1), hit("b", 0.9)], 2)) == [
        "a",
        "b",
    ]  # unparsable: fail open


@pytest.mark.parametrize("make", [
    lambda: TermOverlapReranker(OverlapRerankParams()),
    lambda: LlmReranker(LlmRerankParams(), ScriptedLLM(default="2 > 1 > 5")),
])  # fmt: skip
def test_rerankers_conform(make: Any) -> None:
    check_reranker(make())


def test_term_overlap_prefers_coverage() -> None:
    out = TermOverlapReranker(OverlapRerankParams()).rerank(
        "parental leave weeks", [hit("a", 1, text="annual leave days"), hit("b", 0.5, text="parental leave is 18 weeks")], 2)  # fmt: skip
    assert ids(out) == ["b", "a"]


# ---------------------------------------------------------------- post-processors


def test_min_score_keeps_a_minimum() -> None:
    hs = [hit("a", 0.9, "rerank"), hit("b", 0.02, "rerank")]
    q = Query("q", ALICE)
    assert ids(MinScore(MinScoreParams(threshold=0.5, stage="rerank")).process(q, hs)) == ["a"]
    assert ids(
        MinScore(MinScoreParams(threshold=0.95, stage="rerank", min_keep=1)).process(q, hs)
    ) == ["a"]
    assert (
        MinScore(MinScoreParams(threshold=0.95, stage="rerank")).process(q, hs) == []
    )  # → "I don't know"


def test_dedupe_and_cap_per_document() -> None:
    same = "Annual leave is 20 days per year for full time staff in Australia"
    hs = [
        hit("a", 0.9, text=same),
        hit("b", 0.8, text=same + "."),
        hit("c", 0.7, text="Parental leave is 18 weeks"),
    ]
    assert ids(Dedupe(0.85).process(Query("q", ALICE), hs)) == ["a", "c"]
    many = [hit(str(i), 1 - i / 10, uri="doc://x" if i < 4 else "doc://y") for i in range(6)]
    assert ids(MaxPerDocument(2).process(Query("q", ALICE), many)) == ["0", "1", "4", "5"]


def test_mmr_promotes_something_different() -> None:
    a = "annual leave is twenty days per year"
    hs = [
        hit("a1", 0.9, text=a),
        hit("a2", 0.89, text=a + " for staff"),
        hit("p", 0.5, text="parental leave eighteen weeks"),
    ]
    assert ids(Mmr(0.3, HashingEmbedder(256)).process(Query("leave", ALICE), hs)) == [
        "a1",
        "p",
        "a2",
    ]
    assert ids(Mmr(1.0, HashingEmbedder(256)).process(Query("leave", ALICE), hs)) == [
        "a1",
        "a2",
        "p",
    ]


def test_parent_and_window_expansion() -> None:
    kids = [hit("k1", 0.9, parent_text="WHOLE SECTION", parent_id="P1"), hit("k2", 0.8, parent_text="WHOLE SECTION", parent_id="P1"),
            hit("x", 0.7)]  # fmt: skip
    out = ParentExpand().process(Query("q", ALICE), kids)
    assert ids(out) == ["P1", "x"]
    assert out[0].chunk.text == "WHOLE SECTION"
    assert out[0].chunk.metadata["matched_children"] == ["k1", "k2"]
    assert "parent_text" not in out[0].chunk.metadata
    w = WindowExpand().process(
        Query("q", ALICE), [hit("s", 1, text="one sentence", window="before. one sentence. after.")]
    )
    assert w[0].chunk.text == "before. one sentence. after."


def test_recency_prefers_newer_when_close() -> None:
    hs = [
        hit("old", 0.80, updated="2021-03-01"),
        hit("new", 0.78, updated="2026-02-01"),
        hit("undated", 0.10),
    ]
    out = RecencyBoost(
        RecencyParams(weight=0.3, half_life_days=365), today=date(2026, 6, 1)
    ).process(Query("q", ALICE), hs)
    assert ids(out)[0] == "new"
    assert (
        RecencyBoost(RecencyParams(weight=0.0)).process(Query("q", ALICE), hs)[0].chunk.id == "old"
    )


# ---------------------------------------------------------------- the pipeline


class LeakyStore(MemoryVectorStore):
    """A buggy plugin store that ignores permissions."""

    def search(
        self,
        vector: Sequence[float],
        principal: Principal,
        k: int,
        filters: Mapping[str, object] | None = None,
    ) -> list[ScoredChunk]:
        return super().search(
            vector, Principal("root", ("hr", "eng"), ("public", "internal", "confidential")), k
        )


def test_pipeline_drops_what_a_buggy_store_leaks() -> None:
    c = offline(retriever="dense", reranker="none", postprocessors=[])
    c._built["vector_store"] = LeakyStore()
    loaded(c)
    p = SearchPipeline(c)
    hits = p.search(Query("salary bands", BOB, k=10)).hits
    assert all(h.chunk.access.allows(BOB) for h in hits)
    assert p.leaks > 0


def test_pipeline_trace_and_defaults() -> None:
    c = loaded(offline(reranker={"use": "term-overlap", "top_n": 2}))
    assert isinstance(c.config, dict)
    del c.config["retriever"]  # no retriever configured: hybrid, because both stores exist
    r = SearchPipeline(c).search(Query("parental leave", ALICE, k=1))
    assert r.trace["components"]["retriever"] == "HybridRetriever"
    assert r.trace["counts"]["reranked"] == 2
    assert r.trace["counts"]["returned"] == 1
    assert set(r.trace["ms"]) == {"transform", "retrieve", "rerank", "postprocess"}
    with pytest.raises(ComponentError, match="needs a vector_store"):
        SearchPipeline(Container({"embedder": "hashing"}, "x"))


def test_reranker_reads_the_question_not_the_passage() -> None:
    class Spy(TermOverlapReranker):
        asked: ClassVar[list[str]] = []

        def _scores(self, query: str, texts: list[str]) -> list[float]:
            self.asked.append(query)
            return super()._scores(query, texts)

    c = loaded(offline(llm={"use": "scripted", "default": "Parental leave is 18 weeks."},
                       query_transformer={"use": "hyde", "include_original": False}))  # fmt: skip
    c._built["reranker"] = Spy(OverlapRerankParams())
    SearchPipeline(c).search(Query("how long is parental leave?", ALICE))
    assert Spy.asked == ["how long is parental leave?"]


# ---------------------------------------------------------------- evaluation and CLI


def test_metrics() -> None:
    assert ev.metrics(["x", "a", "b"], {"a", "b"}, 5) == pytest.approx(
        (1.0, 0.5, (1 / 1.585 + 0.5) / (1 + 1 / 1.585)), abs=1e-3
    )
    assert ev.metrics(["x", "y"], {"a"}, 2) == (0.0, 0.0, 0.0)


def test_eval_search_compares_variants_and_never_leaks(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval-search", str(DATASET), "--file", str(ROOT / "rag.yaml"), "--profile", "offline",
                 "--variant", "keyword", "--variant", "all-together", "--json"]) == 0  # fmt: skip
    rows = {r["variant"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["keyword"]["recall"] >= 0.9
    assert rows["all-together"]["recall"] >= 0.9
    assert all(r["leaks"] == 0 for r in rows.values())
    assert rows["all-together"]["per_case"]["exec-bonus"]["leaks"] == []


def test_eval_search_gate_and_errors(capsys: pytest.CaptureFixture[str]) -> None:
    args = [
        "eval-search",
        str(DATASET),
        "--file",
        str(ROOT / "rag.yaml"),
        "--profile",
        "offline",
        "--variant",
        "dense",
    ]
    assert main([*args, "--fail-under", "recall=0.99"]) == 1
    assert "FAIL: dense: recall" in capsys.readouterr().err
    assert main([*args[:-1], "nope"]) == 1
    assert "unknown variant" in capsys.readouterr().err


def test_cli_search_shows_scores(capsys: pytest.CaptureFixture[str]) -> None:
    corpus = sorted(str(p) for p in (ROOT / "examples/corpus/handbook").glob("*.md"))
    assert main(["search", "My VPN shows E-4021", "--file", str(ROOT / "rag.yaml"), "--profile", "offline",
                 "--group", "all-staff", "--json", "--ingest", *corpus]) == 0  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert out["hits"][0]["document"].endswith("vpn-troubleshooting.md")
    assert {"dense", "sparse", "fusion", "rerank"} <= set(out["hits"][0]["scores"])


def test_gateway_embedder_uses_the_registered_query_prompt() -> None:
    from pydantic import SecretStr

    from rag_core.components.enrichment import GatewayEmbedder, GatewayEmbedderParams

    sent: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.extend(json.loads(req.content)["input"])
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 16}]})

    p = GatewayEmbedderParams(
        dimensions=16, query_prompt="query-instruction", prompts_dir=str(ROOT / "prompts")
    )
    e = GatewayEmbedder(p, SecretStr("k"), mock_client(handler, "http://gw/v1/"))
    e.embed_query("Can I {really} WFH?")
    assert sent[0].startswith("Instruct: Given an employee question")
    assert sent[0].endswith("Can I {really} WFH?")
    assert e.prompt_refs == ["query-instruction@1"]
    with pytest.raises(ComponentError, match="embedder 'gateway' could not start"):
        Container(
            {
                "embedder": {
                    "use": "gateway",
                    "query_prompt": "nope",
                    "prompts_dir": str(ROOT / "prompts"),
                }
            }
        ).get("embedder")


def test_secrets_come_from_files_and_rotate(tmp_path: Path) -> None:
    from rag_core.components.basics import FileSecret

    key = tmp_path / "rag_api_gateway_key"
    key.write_text("sk-one\n")
    secret = FileSecret(str(key))
    assert secret.get_secret_value() == "sk-one"
    assert "sk-one" not in repr(secret)
    key.write_text("sk-two")  # OpenBao Agent rotated it: picked up without a restart
    assert secret.get_secret_value() == "sk-two"
    with pytest.raises(ComponentError, match="reranker 'gateway' could not start"):
        Container({"reranker": {"use": "gateway", "api_key_file": str(tmp_path / "missing")}}).get(
            "reranker"
        )
    pii = tmp_path / "pii_hmac_key"
    pii.write_text("k")
    red = Container(
        {"pii": {"use": "regex", "strategy": "pseudonymise", "key_file": str(pii)}}
    ).get("pii")
    assert red.redact("mail a@b.co")[0].startswith("mail [EMAIL:")
