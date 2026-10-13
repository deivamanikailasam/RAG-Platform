"""Extension 02: context compression, embedding options (instructions, Matryoshka, late chunking,
sparse vectors, multi-vector reranking) and the new slots, all offline."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from pydantic import SecretStr

from rag_core import config as cfg
from rag_core.answer import AnswerPipeline
from rag_core.components.basics import ApproxTokenCounter, HashingEmbedder, ScriptedLLM
from rag_core.components.compression import (
    EmbeddingFilter,
    EmbeddingFilterParams,
    ExtractiveCompressor,
    ExtractiveParams,
    LlmExtract,
    LlmExtractParams,
    LlmLingua,
    LlmLinguaParams,
    Summarize,
    SummarizeParams,
    compress_all,
)
from rag_core.components.embeddings import (
    Bm25Sparse,
    Bm25SparseParams,
    ColbertParams,
    ColbertReranker,
    InstructedEmbedder,
    LateChunkingEmbedder,
    LateChunkingParams,
    MatryoshkaEmbedder,
    MaxSimParams,
    MaxSimReranker,
    MemorySparseIndex,
    QdrantSparseIndex,
    QdrantSparseParams,
    TeiSparse,
    TeiSparseParams,
    TeiTokenEncoder,
    maxsim,
)
from rag_core.components.enrichment import GatewayEmbedder, GatewayEmbedderParams
from rag_core.ingest import IngestionPipeline
from rag_core.registry import ComponentError, Container
from rag_core.search import SearchPipeline
from rag_core.testing.conformance import (
    ALICE,
    check_compressor,
    check_embedder,
    check_keyword_index,
    check_reranker,
    check_sparse_embedder,
)
from rag_core.types import Access, Chunk, Document, Element, Query, ScoredChunk, Source

ROOT = Path(__file__).resolve().parents[3]
T = ApproxTokenCounter()
HR = Access("internal", ("hr",))

HANDBOOK = b"""# Staff handbook

Welcome to the staff handbook of Example Pty Ltd. It explains leave and expenses.

## 4 Leave

All staff accrue leave from their first day.

### 4.1 Annual leave

Full-time staff get 20 days of annual leave per year. Leave must be approved by your manager.
Book annual leave in the HR portal at least two weeks ahead.

### 4.2 Parental leave

Parental leave is 18 weeks at full pay. It can start up to six weeks before the due date.
Partners get four weeks of paid partner leave.

## 5 Expenses

Meals are reimbursed up to 90 dollars a day. Keep every receipt for audit.
Flights under six hours are booked in economy class.
"""


def offline(**slots: Any) -> Container:
    config = cfg.resolve(yaml.safe_load((ROOT / "rag.yaml").read_text()), "offline", env={})
    config.update(slots)
    return Container({k: v for k, v in config.items() if v != "none"}, "test")


def ingest(
    c: Container, data: bytes = HANDBOOK, uri: str = "file:///docs/handbook.md"
) -> list[str]:
    result = IngestionPipeline(c).ingest(Source(uri, data, access=HR))
    assert result.status == "indexed", result
    return list(result.chunk_ids)


def search(c: Container, text: str, k: int = 5, **kw: Any) -> list[ScoredChunk]:
    return SearchPipeline(c).search(Query(text, ALICE, k=k, **kw)).hits


def hit(c: Chunk, score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(c, score, {"fusion": score})


# ================================================================ compression


def test_compressors_conform() -> None:
    emb = HashingEmbedder(256)
    check_compressor(ExtractiveCompressor(ExtractiveParams()))
    check_compressor(ExtractiveCompressor(ExtractiveParams(method="embedding", threshold=0.1), emb))
    check_compressor(EmbeddingFilter(EmbeddingFilterParams(threshold=0.1), emb))
    check_compressor(EmbeddingFilter(EmbeddingFilterParams(threshold=0.1, level="sentence"), emb))

    def extract(system: str, user: str) -> str:
        doc = user.split("<document>")[1]
        if "18 weeks" in doc:
            return "Parental leave is 18 weeks at full pay. Everyone gets a free car."
        return "NO_OUTPUT"

    check_compressor(LlmExtract(ScriptedLLM(fn=extract), LlmExtractParams()))
    check_compressor(
        Summarize(
            ScriptedLLM(default="Parental leave is 18 weeks."), T, SummarizeParams(min_tokens=5)
        )
    )


def test_extractive_keeps_relevant_sentences_with_neighbours() -> None:
    text = (
        "Intro sentence here. Parental leave is 18 weeks. It is paid at full rate. Coffee is free."
    )
    h = hit(Chunk("a", "doc://a", 0, text, 20, HR))
    q = Query("how long is parental leave", ALICE)
    out = ExtractiveCompressor(ExtractiveParams(threshold=0.3)).compress(q, [h])
    assert out[0].chunk.text == "Parental leave is 18 weeks."
    assert out[0].chunk.metadata["compressed"] == ["extractive"]
    wide = ExtractiveCompressor(ExtractiveParams(threshold=0.3, neighbours=1)).compress(q, [h])
    assert (
        wide[0].chunk.text
        == "Intro sentence here. Parental leave is 18 weeks. It is paid at full rate."
    )
    none = Query("pension contributions", ALICE)
    assert (
        ExtractiveCompressor(ExtractiveParams(threshold=0.5, drop_empty=True)).compress(none, [h])
        == []
    )
    assert len(ExtractiveCompressor(ExtractiveParams(threshold=0.5)).compress(none, [h])) == 1


def test_llm_extract_verifies_and_drops() -> None:
    text = "Parental leave is 18 weeks at full pay. The café opens at 8."
    llm = ScriptedLLM(default="Parental leave is 18 weeks at full pay. Everyone gets a free car.")
    out = LlmExtract(llm, LlmExtractParams()).compress(
        Query("parental leave", ALICE), [hit(Chunk("a", "d", 0, text, 9))]
    )
    assert out[0].chunk.text == "Parental leave is 18 weeks at full pay."
    assert LlmExtract(ScriptedLLM(default="NO_OUTPUT"), LlmExtractParams()).compress(
        Query("x", ALICE), [hit(Chunk("a", "d", 0, text, 9))]) == []  # fmt: skip

    class Down:
        model = "down"

        def complete(self, *a: Any, **k: Any) -> str:
            raise RuntimeError("gateway down")

    kept = LlmExtract(Down(), LlmExtractParams()).compress(
        Query("x", ALICE), [hit(Chunk("a", "d", 0, text, 9))]
    )
    assert kept[0].chunk.text == text
    with pytest.raises(RuntimeError):
        LlmExtract(Down(), LlmExtractParams(fail_open=False)).compress(
            Query("x", ALICE), [hit(Chunk("a", "d", 0, text, 9))]
        )


def test_summarize_discards_ungrounded_summaries() -> None:
    text = " ".join(["Parental leave is 18 weeks at full pay for the primary carer."] * 5)
    h = hit(Chunk("a", "d", 0, text, 60))
    bad = Summarize(
        ScriptedLLM(default="I cannot help with that."), T, SummarizeParams(min_tokens=5)
    )
    assert bad.compress(Query("leave", ALICE), [h])[0].chunk.text == text
    good = Summarize(
        ScriptedLLM(default="Parental leave is 18 weeks at full pay."),
        T,
        SummarizeParams(min_tokens=5),
    )
    assert (
        good.compress(Query("leave", ALICE), [h])[0].chunk.text
        == "Parental leave is 18 weeks at full pay."
    )


def test_llmlingua_is_a_reference_with_a_clear_install_hint() -> None:
    class Fake:
        def compress_prompt(
            self, ctx: list[str], rate: float, force_tokens: list[str]
        ) -> dict[str, Any]:
            words = ctx[0].split()
            return {"compressed_prompt": " ".join(words[: max(1, int(len(words) * rate))])}

    out = LlmLingua(LlmLinguaParams(rate=0.5), Fake()).compress(
        Query("x", ALICE), [hit(Chunk("a", "d", 0, "one two three four", 4))])  # fmt: skip
    assert out[0].chunk.text == "one two"
    with pytest.raises(ComponentError, match=r"rag-core\[llmlingua\]"):
        offline(compressors=["llmlingua"]).get("compressors")


def test_compression_in_the_answer_pipeline_reports_savings() -> None:
    c = offline(compressors=[{"use": "extractive", "threshold": 0.3}], cache="none")
    ingest(c)
    answer = AnswerPipeline(c).answer("How many weeks of parental leave?", ALICE)
    info = answer.trace["compression"]
    assert info["tokens_saved"] > 0
    assert info["tokens_after"] < info["tokens_before"]
    assert info["steps"][0]["compressor"] == "ExtractiveCompressor"
    assert "18 weeks" in answer.text
    assert answer.citations
    _, data = compress_all([], Query("x", ALICE), [], T)
    assert data["ratio"] == 1.0


# ================================================================ embedding options


UNIT_X, UNIT_Y = [1.0] + [0.0] * 15, [0.0, 1.0] + [0.0] * 14


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class Recorder:
    model, dimensions = "rec", 16

    def __init__(self) -> None:
        self.seen: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.seen += list(texts)
        return [[1.0] * 16 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        raise AssertionError("the wrapper owns the query prefix")


def test_instructed_prefixes() -> None:
    c = offline(
        embedder={
            "use": "instructed",
            "preset": "e5",
            "inner": {"use": "hashing", "dimensions": 64},
        }
    )
    e = c.get("embedder")
    check_embedder(e)
    assert e.model.startswith("hashing-v1+prefix-")
    rec = Recorder()
    nomic = InstructedEmbedder(rec, "search_query: ", "search_document: ")
    nomic.embed_documents(["a"])
    nomic.embed_query("b")
    assert rec.seen == ["search_document: a", "search_query: b"]
    assert (
        offline(embedder={"use": "instructed", "inner": {"use": "hashing"}}).get("embedder").model
        == "hashing-v1"
    )


def test_matryoshka_truncates_and_renormalises() -> None:
    e = MatryoshkaEmbedder(HashingEmbedder(256), 64)
    check_embedder(e)
    v = e.embed_query("annual leave policy")
    assert len(v) == 64
    assert math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-9)
    assert e.model == "hashing-v1@64"
    with pytest.raises(ComponentError, match="can't keep 512"):
        offline(
            embedder={
                "use": "matryoshka",
                "dimensions": 512,
                "inner": {"use": "hashing", "dimensions": 256},
            }
        ).get("embedder")


def test_gateway_embedder_can_request_dimensions() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": [0.1] * 256} for i in range(len(body["input"]))]
            },
        )

    p = GatewayEmbedderParams(dimensions=256, request_dimensions=True)
    e = GatewayEmbedder(
        p,
        SecretStr("k"),
        httpx.Client(base_url="http://gw/", transport=httpx.MockTransport(handler)),
    )
    e.embed_documents(["a"])
    assert bodies[0]["dimensions"] == 256
    p2 = GatewayEmbedderParams(dimensions=256)
    GatewayEmbedder(
        p2,
        SecretStr("k"),
        httpx.Client(base_url="http://gw/", transport=httpx.MockTransport(handler)),
    ).embed_documents(["a"])
    assert "dimensions" not in bodies[1]


def test_late_chunking_keeps_the_context_of_a_chunk() -> None:
    late = LateChunkingEmbedder(LateChunkingParams(dimensions=256, window=12))
    check_embedder(late)
    text = ("Parental leave is available to every employee who becomes a parent. "
            "It lasts 18 weeks and is paid at the full rate.")  # fmt: skip
    doc = Document("doc://p", "Leave", (Element("paragraph", text),), "s")
    chunks = [Chunk("a", "doc://p", 0, "Parental leave is available to every employee who becomes a parent.", 12),
              Chunk("b", "doc://p", 1, "It lasts 18 weeks and is paid at the full rate.", 12),
              Chunk("c", "doc://p", 2, "A summary not in the text.", 6)]  # fmt: skip
    v = late.embed_chunks(doc, chunks)
    alone = late.embed_documents([ch.text for ch in chunks])
    q = late.embed_query("parental leave")
    assert dot(q, v[1]) > dot(q, alone[1]), (
        "the pronoun chunk carries 'parental leave' from its context"
    )
    assert v[2] == alone[2], "a chunk not in the text is embedded on its own"
    windowed = LateChunkingEmbedder(LateChunkingParams(dimensions=64, max_tokens=64))
    long = Document(
        "doc://l",
        "L",
        (Element("paragraph", " ".join(f"word{i} filler text." for i in range(200))),),
        "s",
    )
    parts = [Chunk(str(i), "doc://l", i, f"word{i} filler text.", 3) for i in range(0, 200, 50)]
    assert len(windowed.embed_chunks(long, parts)) == 4


def test_late_chunking_through_ingestion_and_tei() -> None:
    c = offline(embedder={"use": "late-chunking", "dimensions": 128}, reranker="none")
    ingest(c)
    assert search(c, "parental leave weeks", k=3)[0].chunk.text.count("18 weeks") == 1

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("tokenize"):
            return httpx.Response(200, json=[[{"id": 0, "text": "[CLS]", "special": True, "start": 0, "stop": 0},
                                             {"id": 1, "text": "hello", "special": False, "start": 0, "stop": 5},
                                             {"id": 2, "text": "world", "special": False, "start": 6, "stop": 11},
                                             {"id": 3, "text": "[SEP]", "special": True, "start": 0, "stop": 0}]])  # fmt: skip
        return httpx.Response(200, json=[[[9.0] * 16, UNIT_X, UNIT_Y, [9.0] * 16]])

    enc = TeiTokenEncoder(
        "http://tei",
        16,
        client=httpx.Client(base_url="http://tei/", transport=httpx.MockTransport(handler)),
    )
    late = LateChunkingEmbedder(LateChunkingParams(backend="tei", dimensions=16), enc)
    doc = Document("doc://t", "t", (Element("paragraph", "hello world"),), "s")
    v = late.embed_chunks(
        doc, [Chunk("h", "doc://t", 0, "hello", 1), Chunk("w", "doc://t", 1, "world", 1)]
    )
    assert v == [UNIT_X, UNIT_Y]


def test_sparse_embedders_conform() -> None:
    check_sparse_embedder(Bm25Sparse(Bm25SparseParams()))

    def handler(req: httpx.Request) -> httpx.Response:
        texts = json.loads(req.content)["inputs"]
        from rag_core.components.basics import words

        return httpx.Response(200, json=[[{"index": hash(w) % 30000, "value": 0.5} for w in set(words(t))]
                                         for t in texts])  # fmt: skip

    client = httpx.Client(base_url="http://tei/", transport=httpx.MockTransport(handler))
    splade = TeiSparse(TeiSparseParams(), client)
    check_sparse_embedder(splade)
    assert splade.idf is False


def test_sparse_keyword_index_conforms_and_runs_hybrid() -> None:
    check_keyword_index(lambda: MemorySparseIndex(Bm25Sparse(Bm25SparseParams())))
    c = offline(keyword_index="sparse", sparse_embedder={"use": "bm25", "k1": 1.2}, reranker="none")
    ingest(c)
    hits = search(c, "receipt audit", k=3)
    assert "Keep every receipt" in hits[0].chunk.text
    assert "sparse" in hits[0].scores or "fusion" in hits[0].scores
    idx = c.get("keyword_index")
    assert idx.idf is True
    assert idx.search_all("receipt", 3)
    assert idx.update_access("file:///docs/handbook.md", Access("internal", ("finance",))) > 0
    assert not idx.search("receipt", ALICE, 3)


def test_qdrant_sparse_collection_shape() -> None:
    calls: list[tuple[str, str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        calls.append((req.method, req.url.path, body))
        if req.url.path.endswith("/exists"):
            return httpx.Response(200, json={"result": {"exists": False}})
        if req.method == "GET":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {"params": {"sparse_vectors": {"sparse": {"modifier": "idf"}}}}
                    }
                },
            )
        if req.url.path.endswith("/points/query"):
            return httpx.Response(200, json={"result": {"points": []}})
        return httpx.Response(200, json={"result": {}})

    client = httpx.Client(base_url="http://q", transport=httpx.MockTransport(handler))
    idx = QdrantSparseIndex(
        QdrantSparseParams(create_if_missing=True, api_key_env=None),
        Bm25Sparse(Bm25SparseParams()),
        client,
    )
    idx.index([Chunk("a", "doc://a", 0, "parental leave", 2, HR)])
    create = next(b for m, p, b in calls if m == "PUT" and p == "/collections/rag_chunks_sparse")
    assert create == {"vectors": {}, "sparse_vectors": {"sparse": {"modifier": "idf"}}}
    point = next(b for m, p, b in calls if p.endswith("/points"))["points"][0]
    assert set(point["vector"]["sparse"]) == {"indices", "values"}
    idx.search("parental", ALICE, 3, {"department": "hr"})
    query = next(b for m, p, b in calls if p.endswith("/points/query"))
    assert query["using"] == "sparse"
    assert query["filter"]["must"][-1] == {"key": "metadata.department", "match": {"value": "hr"}}
    with pytest.raises(TypeError):
        idx.upsert([], [])


def test_maxsim_and_colbert_rerankers() -> None:
    check_reranker(MaxSimReranker(MaxSimParams()))
    assert maxsim([[1.0, 0.0]], [[1.0, 0.0], [0.0, 1.0]]) == 1.0
    assert maxsim([], [[1.0]]) == 0.0

    class FakeColbert:
        def encode(self, texts: list[str], is_query: bool) -> list[list[list[float]]]:
            return [[[1.0, 0.0] if "parental" in t.lower() else [0.0, 1.0]] for t in texts]

    check_reranker(ColbertReranker(ColbertParams(), FakeColbert()))
    with pytest.raises(ComponentError, match=r"rag-core\[pylate\]"):
        offline(reranker="colbert").get("reranker")


# ================================================================ config


def test_every_new_component_validates_in_a_profile() -> None:
    c = offline(
        chunker={"use": "hierarchical", "leaf_tokens": 120, "index_sections": True},
        enrichers=["context-header", "metadata", {"use": "summary-tree"}, {"use": "summary", "attach": True},
                   {"use": "llm-metadata", "fields": {"department": {"values": ["hr"]}}}],
        embedder={"use": "matryoshka", "dimensions": 128, "inner": {"use": "instructed", "preset": "nomic",
                                                                    "inner": {"use": "hashing", "dimensions": 256}}},
        sparse_embedder="bm25", keyword_index="sparse", retriever={"use": "section", "inner": {"use": "hybrid"}},
        reranker="maxsim", postprocessors=["auto-merge", "section-expand", "summary-expand"],
        compressors=["embedding-filter", "extractive", "llm-extract", "summarize"],
    )  # fmt: skip
    assert c.validate() == []
    built = c.build_all()
    assert built["embedder"].model == built["embedder"].inner.model + "@128"
    assert len(built["compressors"]) == 4
    bad = offline(compressors={"use": "extractive"})
    assert any("expected a list" in p for p in bad.validate())
