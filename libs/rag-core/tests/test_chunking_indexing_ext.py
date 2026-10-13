"""Extension 02: hierarchical chunking and RAPTOR summaries, more chunkers, metadata extraction
and section retrieval, all offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_core import config as cfg
from rag_core.components.basics import ApproxTokenCounter, ScriptedLLM
from rag_core.components.chunkers import (
    CodeChunker,
    CodeParams,
    PropositionChunker,
    PropositionParams,
)
from rag_core.components.chunking import (
    StructureChunker,
    StructureParams,
    section_meta,
    section_number,
)
from rag_core.components.hierarchy import (
    AutoMerge,
    AutoMergeParams,
    HierarchicalChunker,
    HierarchicalParams,
    kmeans,
)
from rag_core.components.metadata import (
    LlmMetadata,
    LlmMetadataParams,
    MetaField,
    RuleMetadata,
    RuleMetadataParams,
    check_value,
)
from rag_core.ingest import IngestionPipeline
from rag_core.registry import ComponentError, Container
from rag_core.search import SearchPipeline
from rag_core.testing.conformance import (
    ALICE,
    BOB,
    check_chunker,
    sample_document,
)
from rag_core.text import (
    detect_language,
    extract_dates,
    extract_entities,
    extractive_summary,
    grounded,
    guess_doc_type,
    yake_keywords,
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


# ================================================================ section metadata (structure)


def test_section_numbers_and_paths() -> None:
    assert section_number("4.2 Parental leave") == "4.2"
    assert section_number("Section 3: Pay") == "3"
    assert section_number("Appendix b") == "B"
    assert section_number("A guide to leave") is None
    assert section_number("Parental leave") is None
    meta = section_meta(["4 Leave", "4.2 Parental leave"])
    assert meta["section"] == "4 Leave > 4.2 Parental leave"
    assert meta["heading"] == "4.2 Parental leave"
    assert meta["section_path"] == ["4 Leave", "4 Leave > 4.2 Parental leave"]
    assert meta["section_numbers"] == ["4", "4.2"]
    assert section_meta([]) == {"section": ""}


def test_structure_chunks_record_the_section_and_cut_code_between_lines() -> None:
    check_chunker(
        StructureChunker(T, StructureParams(max_tokens=40, overlap_tokens=0, min_tokens=0))
    )
    code = "\n".join(f"x{i} = compute_value({i}) + other_value({i})" for i in range(40))
    doc = Document("doc://c", "Code", (Element("code", code),), "sha")
    chunks = StructureChunker(T, StructureParams(max_tokens=60, overlap_tokens=10)).chunk(doc)
    assert len(chunks) > 1
    assert all(line.startswith("x") for c in chunks for line in c.text.split("\n")), "cut mid-line"


# ================================================================ hierarchical + auto-merge


def deep_document() -> Document:
    els = [Element("title", "Manual", level=1)]
    for a in (1, 2):
        els.append(Element("heading", f"{a} Part", level=2))
        for b in (1, 2):
            els.append(Element("heading", f"{a}.{b} Chapter", level=3))
            for c in (1, 2):
                els.append(Element("heading", f"{a}.{b}.{c} Topic", level=4))
                els += [Element("paragraph", f"Fact {a}.{b}.{c}.{n} is about topic {a}{b}{c} number {n}.")
                        for n in (1, 2)]  # fmt: skip
    return Document("doc://manual", "Manual", tuple(els), "sha-m", HR)


def test_hierarchical_builds_a_tree_of_any_depth() -> None:
    chunker = HierarchicalChunker(T, HierarchicalParams(leaf_tokens=16))
    check_chunker(chunker)
    check_chunker(chunker, deep_document())
    leaves = chunker.chunk(deep_document())
    assert len(leaves) == 16
    leaf = leaves[0]
    chain = leaf.metadata["ancestors"]
    assert [a["kind"] for a in chain] == ["document", "section", "section", "section", "section"]
    assert [a["heading"] for a in chain[2:]] == ["1 Part", "1.1 Chapter", "1.1.1 Topic"]
    assert leaf.parent_id == chain[-1]["id"] == leaf.metadata["parent_id"]
    assert chain[-1]["children"] == 2
    assert leaf.metadata["section_numbers"] == ["1", "1.1", "1.1.1"]
    assert "Fact 1.1.1.2" in chain[-1]["text"]
    with_sections = HierarchicalChunker(
        T, HierarchicalParams(leaf_tokens=16, index_sections=True)
    ).chunk(deep_document())
    sections = [c for c in with_sections if c.metadata["node_kind"] == "section"]
    assert len(sections) == 1 + 2 + 4 + 8  # the title, parts, chapters, topics
    assert {c.id for c in sections} >= {a["id"] for a in chain[1:]}
    small = HierarchicalChunker(T, HierarchicalParams(leaf_tokens=16, max_node_tokens=64)).chunk(
        deep_document()
    )
    assert small[0].metadata["ancestors"][0]["text"] == "", "a node over the budget isn't stored"


def test_auto_merge_returns_the_parent_recursively() -> None:
    leaves = HierarchicalChunker(T, HierarchicalParams(leaf_tokens=16)).chunk(deep_document())
    merge = AutoMerge(AutoMergeParams(threshold=0.5, min_children=2))
    q = Query("topic", ALICE)
    # both children of 1.1.1 -> the topic; one child of 1.1.2 alone stays a leaf
    out = merge.process(q, [hit(leaves[0], 0.9), hit(leaves[2], 0.8), hit(leaves[1], 0.7)])
    assert [h.chunk.metadata.get("heading") for h in out] == ["1.1.1 Topic", "1.1.2 Topic"]
    assert out[0].chunk.metadata["merged_children"] == [leaves[0].id, leaves[1].id]
    assert out[0].score == 0.9
    assert "auto_merge" in out[0].scores
    assert "Fact 1.1.1.1" in out[0].chunk.text
    assert "Fact 1.1.1.2" in out[0].chunk.text
    # all four leaves of chapter 1.1: topic 1.1.1 and 1.1.2 merge, then the chapter
    out = merge.process(q, [hit(c, 1 - i / 10) for i, c in enumerate(leaves[:4])])
    assert len(out) == 1
    assert out[0].chunk.metadata["heading"] == "1.1 Chapter"
    assert out[0].chunk.metadata["node_kind"] == "section"
    # under the threshold: unchanged; other chunks pass through
    other = Chunk("x", "doc://o", 0, "unrelated", 1, HR)
    assert merge.process(q, [hit(leaves[0]), hit(other)]) == [hit(leaves[0]), hit(other)]
    strict = AutoMerge(AutoMergeParams(threshold=1.0, min_children=2))
    assert len(strict.process(q, [hit(leaves[0]), hit(leaves[2])])) == 2


def test_hierarchical_and_auto_merge_through_the_pipelines() -> None:
    c = offline(chunker={"use": "hierarchical", "leaf_tokens": 20},
                postprocessors=[{"use": "auto-merge", "threshold": 0.5}], reranker="none")  # fmt: skip
    ingest(c)
    hits = search(c, "parental leave weeks pay partners due date", k=8)
    assert any(h.chunk.metadata.get("merged_children") for h in hits)


# ================================================================ propositions and code


def test_propositions_rule_based_offline() -> None:
    chunker = PropositionChunker(T, PropositionParams(use_llm=False))
    check_chunker(chunker)
    chunks = chunker.chunk(sample_document())
    texts = [c.text for c in chunks]
    assert "Parental leave is 18 weeks at full pay." in texts
    assert "Parental leave: It can start up to six weeks before the due date." in texts
    assert any(t.startswith("| Type") for t in texts), "a table stays whole"
    prop = next(c for c in chunks if c.text.startswith("Parental leave is"))
    assert "Partners get four weeks" in prop.metadata["window"], (
        "the passage is kept for window-expand"
    )
    assert prop.metadata["proposition_by"] == "rules"


def test_propositions_from_an_llm_are_checked() -> None:
    def fn(system: str, user: str) -> str:
        if "Parental leave is 18" in user:
            return "- Parental leave lasts 18 weeks.\n- Parental leave is paid at full pay.\n- The moon is cheese made."
        return "I don't know."

    chunker = PropositionChunker(T, PropositionParams(), ScriptedLLM(fn=fn))
    chunks = chunker.chunk(sample_document())
    by_llm = [c.text for c in chunks if c.metadata["proposition_by"] == "llm"]
    assert by_llm == ["Parental leave lasts 18 weeks.", "Parental leave is paid at full pay."]
    assert any(c.metadata["proposition_by"] == "rules" for c in chunks), (
        "refusals fall back to rules"
    )
    c = offline(chunker={"use": "proposition"})
    assert isinstance(c.get("chunker"), PropositionChunker)


PYTHON = '''import os


# Read the configuration.
@cache
def load_config(path):
    """Load it."""
    return open(path).read()


class Store:
    def get(self, key):
        return key


def main():
    print(load_config(os.environ["CFG"]))
'''


def test_code_chunker_cuts_at_definitions() -> None:
    doc = Document("file:///src/app.py", "app.py", (Element("paragraph", PYTHON),), "sha", HR)
    chunker = CodeChunker(T, CodeParams(max_tokens=30, overlap_tokens=0))
    check_chunker(chunker, doc)
    chunks = chunker.chunk(doc)
    assert chunks[0].metadata["code_language"] == "python"
    blocks = chunker.blocks(doc.text, "python")
    assert [b[0] for b in blocks] == [1, 4, 11, 16], "comments and decorators start their block"
    assert blocks[1][1][:3] == ["# Read the configuration.", "@cache", "def load_config(path):"]
    load = next(c for c in chunks if "def load_config" in c.text)
    assert "# Read the configuration.\n@cache\ndef load_config" in load.text
    assert load.metadata["symbols"] == ["load_config"]
    assert load.metadata["line_start"] in (1, 4)
    assert any(c.metadata["section"] == "Store" for c in chunks)
    whole = CodeChunker(T, CodeParams(max_tokens=400, overlap_tokens=0)).chunk(doc)
    assert len(whole) == 1, "small definitions are packed together"
    go = Document(
        "file:///x.go",
        "x.go",
        (Element("paragraph", "package x\n\nfunc A() {}\n\nfunc B() {}"),),
        "s",
    )
    gochunks = CodeChunker(T, CodeParams(max_tokens=16, overlap_tokens=0)).chunk(go)
    assert gochunks[-1].metadata["symbols"] == ["A", "B"]
    assert gochunks[-1].metadata["code_language"] == "go"


# ================================================================ RAPTOR summary tree and document summaries


def test_kmeans_is_deterministic_and_groups_similar_vectors() -> None:
    vecs = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9]]
    assert kmeans(vecs, 2) == [[0, 1], [2, 3]]
    assert kmeans(vecs, 1) == [[0, 1, 2, 3]]


def test_summary_tree_indexes_summaries_of_summaries() -> None:
    c = offline(chunker={"use": "structure", "max_tokens": 30, "overlap_tokens": 0, "min_tokens": 0},
                enrichers=[{"use": "summary-tree", "cluster_size": 2, "max_levels": 3}], reranker="none")  # fmt: skip
    ingest(c)
    store = c.get("vector_store")
    rows = [store.get(i) for i in store._rows]
    summaries = [r for r in rows if r is not None and r.metadata.get("node_kind") == "summary"]
    assert summaries, "no summaries"
    levels = {s.metadata["tree_level"] for s in summaries}
    assert len(levels) >= 2, levels
    top = max(summaries, key=lambda s: s.metadata["tree_level"])
    assert (
        top.metadata["summary_by"] == "extractive"
    )  # offline: the scripted LLM says "I don't know."
    assert all(
        child in {r.id for r in rows if r} for s in summaries for child in s.metadata["children"]
    )
    assert top.metadata["title"] == "Staff handbook"
    hits = search(c, "what is the staff handbook about", k=10)
    assert any(h.chunk.metadata.get("node_kind") == "summary" for h in hits)


def test_summary_tree_uses_a_grounded_llm_summary() -> None:
    def fn(system: str, user: str) -> str:
        return "Staff get annual leave and parental leave, and meals are reimbursed."

    c = offline(chunker={"use": "structure", "max_tokens": 30, "overlap_tokens": 0, "min_tokens": 0},
                enrichers=[{"use": "summary-tree", "cluster_size": 3}])  # fmt: skip
    c._built["llm"] = ScriptedLLM(fn=fn)
    tree = c.get("enrichers")[0]
    doc = c.get("parsers")[0].parse(Source("file:///h.md", HANDBOOK, "text/markdown"))
    chunks = tree.enrich(doc, c.get("chunker").chunk(doc))
    by = {
        ch.metadata.get("summary_by") for ch in chunks if ch.metadata.get("node_kind") == "summary"
    }
    assert by == {"llm"} or by == {"llm", "extractive"}


def test_document_summary_and_summary_expand() -> None:
    c = offline(enrichers=["context-header", {"use": "summary", "attach": True, "max_sentences": 2}],
                postprocessors=["summary-expand"], reranker="none")  # fmt: skip
    ids = ingest(c)
    store = c.get("vector_store")
    summary = next(
        store.get(i) for i in ids if store.get(i).metadata.get("node_kind") == "document-summary"
    )
    assert summary is not None
    assert len(summary.metadata["children"]) == len(ids) - 1
    assert all(store.get(i).metadata.get("doc_summary") == summary.text for i in ids[:-1])
    hits = SearchPipeline(c).search(Query(summary.text, ALICE, k=6)).hits
    assert any(h.chunk.id == summary.id for h in hits)
    from rag_core.components.hierarchy import SummaryExpand, SummaryExpandParams

    out = SummaryExpand(c, SummaryExpandParams(per_summary=2)).process(
        Query("parental leave weeks", ALICE), [hit(summary, 0.5)])  # fmt: skip
    assert out[0].chunk.id == summary.id
    assert len(out) == 3
    assert all(
        h.chunk.metadata.get("node_kind") is None and "summary_expand" in h.scores for h in out[1:]
    )
    assert "18 weeks" in out[1].chunk.text
    only = SummaryExpand(c, SummaryExpandParams(keep_summary=False)).process(
        Query("leave", ALICE), [hit(summary)]
    )
    assert summary.id not in {h.chunk.id for h in only}


def test_extractive_summary_picks_central_sentences() -> None:
    text = ("Leave is important. Annual leave is 20 days. Parental leave is 18 weeks. "
            "The canteen sells soup.")  # fmt: skip
    out = extractive_summary([text], 2)
    assert "soup" not in out
    assert out.count(".") == 2
    assert grounded("Annual leave is 20 days.", text)
    assert not grounded("I don't know.", text)


# ================================================================ sections


def test_section_retriever_by_number_and_by_title() -> None:
    c = offline(chunker={"use": "structure", "max_tokens": 25, "overlap_tokens": 0, "min_tokens": 0},
                retriever={"use": "section"}, reranker="none", postprocessors=[])  # fmt: skip
    ingest(c)
    pipe = SearchPipeline(c)
    r = pipe.search(Query("What does section 4.2 say?", ALICE, k=3))
    top = r.hits[0].chunk
    assert "18 weeks" in top.text
    assert "Partners get four weeks" in top.text
    assert "20 days" not in top.text
    assert top.metadata["expanded"] == "section-lookup"
    assert r.trace["retriever"]["section"]["number"] == "4.2"
    whole = pipe.search(Query("Summarise section 4", ALICE, k=3)).hits[0].chunk.text
    assert "20 days" in whole
    assert "18 weeks" in whole
    by_title = pipe.search(Query("Show me the annual leave section", ALICE, k=3)).hits[0].chunk
    assert "20 days" in by_title.text
    assert "18 weeks" not in by_title.text
    plain = pipe.search(Query("how many days of annual leave", ALICE, k=3))
    assert "section" not in plain.trace["retriever"], "no cue: an ordinary search"
    assert pipe.search(Query("section 9.9", ALICE, k=3)).trace["retriever"]["section"]["found"] == 0
    assert pipe.search(Query("section 4.2", BOB, k=3)).hits == [], "permissions still apply"


def test_section_expand_returns_the_whole_section() -> None:
    c = offline(chunker={"use": "structure", "max_tokens": 16, "overlap_tokens": 0, "min_tokens": 0},
                reranker="none", postprocessors=[{"use": "section-expand", "max_tokens": 400}])  # fmt: skip
    ingest(c)
    hits = search(c, "how many weeks of parental leave", k=3)
    top = hits[0].chunk
    assert "18 weeks" in top.text, top.text
    assert "Partners get four weeks" in top.text, top.text
    assert len(top.metadata["expanded_from"]) >= 2
    sections = [h.chunk.metadata["section"] for h in hits]
    assert len(sections) == len(set(sections)), "hits of one section are merged"
    tight = offline(chunker={"use": "structure", "max_tokens": 16, "overlap_tokens": 0, "min_tokens": 0},
                    reranker="none", postprocessors=[{"use": "section-expand", "max_tokens": 50}])  # fmt: skip
    ingest(tight)
    assert T.count(search(tight, "parental leave weeks", k=1)[0].chunk.text) <= 50


def test_filter_by_section_path() -> None:
    c = offline(
        chunker={"use": "structure", "max_tokens": 25, "overlap_tokens": 0, "min_tokens": 0},
        reranker="none",
    )
    ingest(c)
    hits = search(c, "leave staff", k=10, filters={"section_path": "Staff handbook > 4 Leave"})
    assert hits
    assert all(h.chunk.metadata["section"].startswith("Staff handbook > 4 Leave") for h in hits)
    hits = search(c, "leave staff", k=10, filters={"section_numbers": "4.1"})
    assert {h.chunk.metadata["heading"] for h in hits} == {"4.1 Annual leave"}


def test_hierarchical_section_expand_needs_no_lookup() -> None:
    leaves = HierarchicalChunker(T, HierarchicalParams(leaf_tokens=16)).chunk(deep_document())
    c = offline()
    out = c.get("postprocessors")  # build the container's own stores once
    del out
    from rag_core.components.hierarchy import SectionExpand, SectionExpandParams

    expanded = SectionExpand(c, SectionExpandParams()).process(Query("x", ALICE), [hit(leaves[0])])
    assert "Fact 1.1.1.2" in expanded[0].chunk.text


# ================================================================ metadata extraction


def test_text_helpers() -> None:
    assert extract_dates("Valid from 2025-03-01, signed 1/4/2025 and on 2 May 2024, or March 3, 2023.") == [
        "2023-03-03", "2024-05-02", "2025-03-01", "2025-04-01"]  # fmt: skip
    assert extract_dates("31/02/2025") == []
    found = extract_entities("See POL-117 and https://x.example/a. Pay $1,200 or 5% to Example Pty Ltd.",
                             ["code", "url", "money", "percent", "org"])  # fmt: skip
    assert found["code"] == ["POL-117"]
    assert found["url"] == ["https://x.example/a"]
    assert found["money"] == ["$1,200"]
    assert found["percent"] == ["5%"]
    assert found["org"] == ["Example Pty Ltd"]
    assert (
        detect_language("Der Urlaub ist für alle Mitarbeiter und die Leitung nicht verhandelbar.")[
            0
        ]
        == "de"
    )
    assert detect_language("Les congés sont pour tous les salariés et la direction.")[0] == "fr"
    assert detect_language("ok")[0] == "und"
    assert guess_doc_type("file:///a/leave.md", "Leave policy", "This policy applies") == "policy"
    assert guess_doc_type("file:///x/app.py", "app", "") == "code"
    assert guess_doc_type("file:///m.md", "Board meeting minutes", "Attendees: …") == "minutes"
    assert guess_doc_type("file:///n.md", "Notes", "random words") == "document"
    assert "kubernetes" in yake_keywords(
        "Kubernetes runs pods. Kubernetes schedules pods on nodes. The weather is fine.", 3
    )


def test_rule_metadata_enricher() -> None:
    c = offline(enrichers=["context-header", {"use": "metadata", "keywords": 3}], reranker="none")
    data = HANDBOOK + b"\nThis handbook is effective from 1 July 2025 (ref POL-117).\n"
    ids = ingest(c, data)
    store = c.get("vector_store")
    chunks = [store.get(i) for i in ids]
    meta = [ch.metadata for ch in chunks if ch]
    assert all(m["doc_type"] == "guide" for m in meta)
    assert all(m["language"] == "en" for m in meta)
    assert all(len(m["keywords"]) <= 3 and m["doc_keywords"] for m in meta)
    dated = [m for m in meta if m.get("dates")]
    assert dated
    assert dated[0]["date_latest"] == "2025-07-01"
    assert any("POL-117" in m.get("entities", []) for m in meta)
    hits = search(c, "handbook", k=10, filters={"date_latest": {"gte": "2025-01-01"}})
    assert hits
    assert all(h.chunk.metadata["date_latest"] >= "2025-01-01" for h in hits)
    with pytest.raises(ComponentError, match="unknown entity kinds"):
        offline(enrichers=[{"use": "metadata", "entity_kinds": ["planet"]}]).get("enrichers")


def test_rule_metadata_respects_existing_values() -> None:
    doc = Document("doc://d", "Contract", (Element("paragraph", "Der Vertrag gilt für alle und die Firma."),), "s",
                   metadata={"doc_type": "contract"})  # fmt: skip
    chunk = Chunk(
        "c",
        "doc://d",
        0,
        doc.elements[0].text,
        8,
        metadata={"doc_type": "contract", "language": "en"},
    )
    out = RuleMetadata(RuleMetadataParams(extract=["doc_type", "language"])).enrich(doc, [chunk])[0]
    assert out.metadata["doc_type"] == "contract"
    assert out.metadata["language"] == "de", (
        "the parser's default 'en' is replaced by the detection"
    )
    pre = RuleMetadata(RuleMetadataParams(extract=["doc_type"], prefix="x_")).enrich(doc, [chunk])[
        0
    ]
    assert pre.metadata["x_doc_type"] == "contract"


SCHEMA = {
    "department": {"type": "keyword", "values": ["hr", "finance"], "required": True},
    "effective": {"type": "date"},
    "audience": {"type": "list", "values": ["staff", "managers"]},
    "pages": {"type": "integer"},
    "confidential": {"type": "boolean"},
}


def test_llm_metadata_is_checked_against_the_schema() -> None:
    reply = json.dumps({"department": "HR", "effective": "2025-07-01", "audience": ["staff", "aliens"],
                        "pages": "12", "confidential": "no", "extra": "ignored"})  # fmt: skip
    llm = ScriptedLLM(default=reply)
    p = LlmMetadataParams.model_validate({"fields": SCHEMA})
    out = LlmMetadata(llm, p).extract("Handbook", "text")
    # the department is required and valid; the invalid list is dropped, not stored half-right
    assert out == {
        "department": "hr",
        "effective": "2025-07-01",
        "pages": 12,
        "confidential": False,
    }
    assert len(llm.calls) == 1

    answers = iter(['{"department": "sales"}', '```json\n{"department": "finance"}\n```'])
    retry = ScriptedLLM(fn=lambda s, u: next(answers))
    assert LlmMetadata(retry, p).extract("t", "x") == {"department": "finance"}
    assert "previous answer was invalid" in retry.calls[1][1]
    assert LlmMetadata(ScriptedLLM(default="no idea"), p).extract("t", "x") == {}

    c = offline(
        enrichers=[{"use": "llm-metadata", "fields": SCHEMA, "prefix": "m_"}], reranker="none"
    )
    c._built["llm"] = ScriptedLLM(default=reply)
    ids = ingest(c)
    assert c.get("vector_store").get(ids[0]).metadata["m_department"] == "hr"
    with pytest.raises(ComponentError, match="not a valid field name"):
        offline(enrichers=[{"use": "llm-metadata", "fields": {"bad name": {}}}]).get("enrichers")


def test_check_value_types() -> None:
    assert check_value(MetaField(type="number"), "1,234.5") == 1234.5
    assert check_value(MetaField(type="string", max_chars=3), "abcdef") == "abc"
    assert check_value(MetaField(type="keyword"), " Any ") == "Any"
    for f, v in [(MetaField(type="date"), "soon"), (MetaField(type="boolean"), "maybe"),
                 (MetaField(type="integer"), True), (MetaField(type="keyword", values=["a"]), "b")]:  # fmt: skip
        with pytest.raises((ValueError, TypeError)):
            check_value(f, v)
