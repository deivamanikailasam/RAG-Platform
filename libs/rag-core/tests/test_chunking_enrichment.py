"""Chunkers, enrichers and embedders (Step 31)."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from rag_core.components.basics import ApproxTokenCounter, HashingEmbedder, ScriptedLLM
from rag_core.components.chunking import (
    FixedChunker,
    ParentChildChunker,
    ParentChildParams,
    RecursiveChunker,
    SemanticChunker,
    SemanticParams,
    SentenceWindowChunker,
    StructureChunker,
    StructureParams,
)
from rag_core.components.enrichment import (
    CachedEmbedder,
    ContextHeaderEnricher,
    GatewayEmbedder,
    GatewayEmbedderParams,
    LlmContextEnricher,
    QuestionsEnricher,
)
from rag_core.components.parsing import MarkdownParser
from rag_core.types import Document, Element, Source

T = ApproxTokenCounter()


def doc_of(*elements: Element) -> Document:
    return Document("doc://t", "Handbook", tuple(elements), "sha")


def long_text(n: int, topic: str = "leave") -> str:
    return " ".join(
        f"Sentence {i} is about {topic} rules and more {topic} details." for i in range(n)
    )


@pytest.mark.parametrize("make", [lambda: FixedChunker(T, 50, 10), lambda: RecursiveChunker(T, 50,
10),
                            lambda: StructureChunker(T, StructureParams(max_tokens=50, overlap_tokens=10))])  # fmt: skip
def test_no_chunk_exceeds_the_budget(make: object) -> None:
    chunks = make().chunk(doc_of(Element("paragraph", long_text(40))))  # type: ignore[operator]
    assert len(chunks) > 3
    assert max(c.token_count for c in chunks) <= 50
    assert all(c.document_uri == "doc://t" and c.metadata["title"] == "Handbook" for c in chunks)


def test_overlap_carries_context_across_the_cut() -> None:
    chunks = RecursiveChunker(T, 60, 20).chunk(doc_of(Element("paragraph", long_text(30))))
    last_sentence = chunks[0].text.split("\n\n")[-1]
    assert chunks[1].text.startswith(last_sentence)


def test_chunk_ids_are_stable_and_unique() -> None:
    d = doc_of(Element("paragraph", long_text(30)))
    a, b = FixedChunker(T, 50, 10).chunk(d), FixedChunker(T, 50, 10).chunk(d)
    assert [c.id for c in a] == [c.id for c in b]  # re-ingesting the same thing = the same ids
    assert len({c.id for c in a}) == len(a)


def test_structure_chunker_respects_sections_and_tables(sources: dict[str, Source]) -> None:
    doc = MarkdownParser().parse(sources["md"])
    chunks = StructureChunker(
        T, StructureParams(max_tokens=80, overlap_tokens=0, min_tokens=0)
    ).chunk(doc)
    sections = [c.metadata["section"] for c in chunks]
    assert "Leave policy > Annual leave" in sections
    assert "Leave policy > Parental leave" in sections
    parental = [c for c in chunks if c.metadata["section"].endswith("Parental leave")]
    assert all("Annual" not in c.text for c in parental)  # never crosses a heading
    assert any("| Primary carer | 18 | yes |" in c.text for c in parental)  # the table stays whole


def test_big_tables_repeat_their_header() -> None:
    rows = "\n".join(f"| City {i} | {i} staff |" for i in range(60))
    chunks = StructureChunker(T, StructureParams(max_tokens=60, overlap_tokens=0)).chunk(
        doc_of(
            Element("heading", "Offices", level=1), Element("table", "| City | Staff |\n" + rows)
        )
    )
    assert len(chunks) > 2
    assert all(c.text.startswith("| City | Staff |") for c in chunks)


def test_tiny_sections_join_the_next_one() -> None:
    d = doc_of(Element("heading", "Policy", 1), Element("heading", "Purpose", 2), Element("paragraph", "Short."),
                Element("heading", "Scope", 2), Element("paragraph", "Everyone in the company, everywhere."))  # fmt: skip
    chunks = StructureChunker(
        T, StructureParams(max_tokens=100, overlap_tokens=0, min_tokens=20)
    ).chunk(d)
    assert len(chunks) == 1
    assert chunks[0].metadata["section"] == "Policy"  # the heading path both share


def test_sentence_window() -> None:
    chunks = SentenceWindowChunker(T, 1).chunk(
        doc_of(Element("paragraph", "One is first. Two is next. Three ends it."))
    )
    assert [c.text for c in chunks] == ["One is first.", "Two is next.", "Three ends it."]
    assert chunks[1].metadata["window"] == "One is first. Two is next. Three ends it."
    assert chunks[0].metadata["window"] == "One is first. Two is next."


def test_semantic_chunker_cuts_where_the_topic_changes() -> None:
    text = (" ".join(f"Annual leave rule {i} says leave days accrue monthly." for i in range(6)) + " " +
            " ".join(f"Server patching step {i} requires a reboot window." for i in range(6)))  # fmt: skip
    chunks = SemanticChunker(T, HashingEmbedder(512), SemanticParams(max_tokens=400, overlap_tokens=0,

breakpoint_percentile=95)).chunk(doc_of(Element("paragraph", text)))  # fmt: skip
    assert len(chunks) == 2
    assert "leave" in chunks[0].text
    assert "patching" not in chunks[0].text
    assert "patching" in chunks[1].text
    assert "leave" not in chunks[1].text


def test_parent_child() -> None:
    d = doc_of(Element("heading", "Leave", 1), Element("paragraph", long_text(25)))
    chunks = ParentChildChunker(
        T, ParentChildParams(parent_tokens=400, child_tokens=60, child_overlap=0)
    ).chunk(d)
    assert len(chunks) > 3
    assert len({c.parent_id for c in chunks}) == 1  # all children of one parent
    assert all(c.text in str(c.metadata["parent_text"]) for c in chunks)
    assert max(c.token_count for c in chunks) <= 60


def test_context_header_changes_what_is_embedded_not_what_is_shown(
    sources: dict[str, Source],
) -> None:
    doc = MarkdownParser().parse(sources["md"])
    chunks = StructureChunker(
        T, StructureParams(max_tokens=80, overlap_tokens=0, min_tokens=0)
    ).chunk(doc)
    out = ContextHeaderEnricher("{header}\n\n{text}").enrich(doc, chunks)
    parental = next(c for c in out if c.text.startswith("Parental leave is"))
    assert parental.embed_text.startswith("Leave policy > Parental leave\n\n")
    assert parental.text.startswith("Parental leave is")  # the cited text is untouched


def test_llm_context_and_questions() -> None:
    d = doc_of(Element("paragraph", "It is 18 weeks."))
    chunks = FixedChunker(T, 50, 0).chunk(d)
    llm = ScriptedLLM(
        {
            "situate": "This chunk is about parental leave length.",
            "questions": "How long is parental leave?\nIs it paid?",
        }
    )
    ctx = LlmContextEnricher(llm, 24000).enrich(d, chunks)
    assert ctx[0].embed_text.startswith(
        "This chunk is about parental leave length.\n\nIt is 18 weeks."
    )
    q = QuestionsEnricher(llm, 2).enrich(d, ctx)
    assert q[0].embed_text.endswith("How long is parental leave?\nIs it paid?")
    assert q[0].metadata["questions"] == ["How long is parental leave?", "Is it paid?"]


def test_gateway_embedder_batches_checks_dimensions_and_adds_the_query_instruction() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        dims = 16 if "bad" not in body["input"][0] else 15
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": [0.5] * dims} for i in range(len(body["input"]))]
            },
        )

    e = GatewayEmbedder(GatewayEmbedderParams(dimensions=16, batch_size=2, query_instruction="Q: {query}"), SecretStr("k"),
                        client=httpx.Client(base_url="http://gw/v1/", transport=httpx.MockTransport(handler)))  # fmt: skip
    assert len(e.embed_documents(["a", "b", "c"])) == 3
    assert [len(b["input"]) for b in seen] == [2, 1]  # type: ignore[arg-type]
    e.embed_query("how long")
    assert seen[-1]["input"] == ["Q: how long"]
    with pytest.raises(ValueError, match="returned 15 dimensions, the index expects 16"):
        e.embed_documents(["bad"])


def test_cached_embedder_never_embeds_twice() -> None:
    e = CachedEmbedder(HashingEmbedder(64), 100)
    a = e.embed_documents(["x", "y"])
    b = e.embed_documents(["y", "z"])
    assert a[1] == b[0]
    assert (e.hits, e.misses) == (1, 3)
    e.embed_query("q")
    e.embed_query("q")
    assert e.hits == 2
