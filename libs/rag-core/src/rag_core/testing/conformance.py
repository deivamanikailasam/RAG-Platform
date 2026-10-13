"""The same checks for every implementation of a contract (Step 30).

A project that writes its own vector store, keyword index or embedder runs these in its tests:

    from rag_core.testing.conformance import check_vector_store
    def test_my_store_conforms(): check_vector_store(lambda: MyStore(...), HashingEmbedder(64))

Passing them means the store can replace the built-in one without anything else changing.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from rag_core.types import Access, Chunk, Principal, ScoredChunk

ALICE = Principal("alice", groups=("hr",), classifications=("public", "internal", "confidential"))
BOB = Principal("bob", groups=("eng",), classifications=("public", "internal"))
OTHER_TENANT = Principal(
    "carol", groups=("hr",), classifications=("public", "internal", "confidential"), tenant="acme"
)


def sample_chunks() -> list[Chunk]:
    rows = [
        (
            "doc://leave",
            0,
            "Annual leave is 20 days per year for full-time staff.",
            Access("internal", ("hr",)),
        ),
        (
            "doc://leave",
            1,
            "Parental leave is 18 weeks, paid at the full rate.",
            Access("internal", ("hr",)),
        ),
        (
            "doc://salary",
            0,
            "Salary bands for engineers are confidential.",
            Access("confidential", ("hr",)),
        ),
        (
            "doc://handbook",
            0,
            "The office opens at 8 am and the café serves coffee.",
            Access("public"),
        ),
        (
            "doc://eng",
            0,
            "Deployments happen through pull requests and Argo CD.",
            Access("internal", ("eng",)),
        ),
    ]
    return [Chunk(Chunk.make_id(u, i, t), u, i, t, len(t.split()), a, metadata={"lang": "en", "doc": u})
            for u, i, t, a in rows]  # fmt: skip


def check_embedder(embedder: Any) -> None:
    v = embedder.embed_documents(["annual leave policy", "deployment pipeline"])
    assert len(v) == 2
    assert all(len(x) == embedder.dimensions for x in v), "vector length must equal .dimensions"
    assert embedder.model, "an embedder must name its model (stored with every vector)"
    q = embedder.embed_query("annual leave policy")
    assert len(q) == embedder.dimensions
    assert all(math.isfinite(x) for x in q)


def check_vector_store(make: Callable[[], Any], embedder: Any) -> None:
    store = make()
    chunks = sample_chunks()
    store.upsert(chunks, embedder.embed_documents([c.indexed_text for c in chunks]))
    assert store.count() == len(chunks)
    store.upsert(chunks[:1], embedder.embed_documents([chunks[0].indexed_text]))  # idempotent
    assert store.count() == len(chunks), "upserting the same chunk id twice must not duplicate it"
    q = embedder.embed_query("how many days of annual leave")
    hits = store.search(q, ALICE, 3)
    assert hits, "no results"
    assert hits[0].chunk.document_uri == "doc://leave", (
        f"best hit should be the leave policy, got {hits[0].chunk.document_uri}"
    )
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True), (
        "results must be best first"
    )
    _check_access(lambda p, k, f=None: store.search(q, p, k, f))
    assert store.delete_document("doc://leave") == 2
    assert all(h.chunk.document_uri != "doc://leave" for h in store.search(q, ALICE, 10))


def check_keyword_index(make: Callable[[], Any]) -> None:
    index = make()
    chunks = sample_chunks()
    index.index(chunks)
    index.index(chunks[:1])  # idempotent
    hits = index.search("parental leave weeks", ALICE, 3)
    assert hits
    assert hits[0].chunk.text.startswith("Parental leave"), hits[0].chunk.text
    assert len({h.chunk.id for h in index.search("leave", ALICE, 10)}) == 2, (
        "re-indexing must not duplicate"
    )
    _check_access(lambda p, k, f=None: index.search("leave salary office deployments", p, k, f))
    assert index.delete_document("doc://leave") == 2
    assert not index.search("parental", ALICE, 3)


def check_reranker(reranker: Any) -> None:
    """A reranker (Step 32) re-orders the candidates it is given: it never invents, duplicates or
    drops-and-replaces chunks, returns at most k, best first, and records its score per hit."""
    chunks = sample_chunks()
    # retrieval order on purpose NOT the right one: the parental leave chunk is second
    candidates = [
        ScoredChunk(c, 1.0 - i / 10, {"fusion": 1.0 - i / 10}) for i, c in enumerate(chunks)
    ]
    out = reranker.rerank("parental leave weeks", candidates, 3)
    assert 0 < len(out) <= 3, f"expected 1-3 results for k=3, got {len(out)}"
    ids = [h.chunk.id for h in out]
    assert len(ids) == len(set(ids)), "a reranker must not return the same chunk twice"
    assert set(ids) <= {c.id for c in chunks}, "a reranker must only return chunks it was given"
    assert [h.score for h in out] == sorted((h.score for h in out), reverse=True), (
        "results must be best first"
    )
    assert all("rerank" in h.scores or "rerank_skipped" in h.scores for h in out), (
        "every hit must record the reranker's score (or that it was skipped)"
    )
    assert all("fusion" in h.scores for h in out), "earlier scores must be kept for explanations"
    assert out[0].chunk.text.startswith("Parental leave"), (
        f"the best passage should be the parental leave one, got {out[0].chunk.text!r}"
    )
    assert reranker.rerank("parental leave weeks", [], 3) == [], "no candidates: no results"


def _check_access(search: Callable[..., list[Any]]) -> None:
    alice = {h.chunk.document_uri for h in search(ALICE, 10)}
    bob = {h.chunk.document_uri for h in search(BOB, 10)}
    assert "doc://salary" not in bob, "LEAK: a confidential chunk reached someone without clearance"
    assert "doc://leave" not in bob, (
        "LEAK: a group-restricted chunk reached someone outside the group"
    )
    assert "doc://eng" not in alice, "LEAK: a chunk reached someone outside its group"
    assert search(OTHER_TENANT, 10) == [], "LEAK: a chunk crossed tenants"
    only = search(ALICE, 10, {"doc": "doc://handbook"})
    assert {h.chunk.document_uri for h in only} <= {"doc://handbook"}, "metadata filter ignored"


def check_access_update(make: Callable[[], Any], embedder: Any = None) -> None:
    """Permissions change at the source: after update_access the store answers with the NEW
    access, for vector stores (embedder given) and keyword indexes alike. Revocation is immediate."""
    store, chunks = make(), sample_chunks()
    if embedder is not None:
        store.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))

        def find(who: Principal, text: str) -> set[str]:
            return {h.chunk.document_uri for h in store.search(embedder.embed_query(text), who, 10)}
    else:
        store.index(chunks)

        def find(who: Principal, text: str) -> set[str]:
            return {h.chunk.document_uri for h in store.search(text, who, 10)}

    assert "doc://salary" not in find(BOB, "salary bands engineers")
    assert store.update_access("doc://salary", Access("internal", ("eng",))) == 1
    assert "doc://salary" in find(BOB, "salary bands engineers"), "grant not applied"
    assert "doc://salary" not in find(ALICE, "salary bands engineers"), "old access still applies"
    assert store.update_access("doc://leave", Access("restricted", ("executives",))) == 2
    assert "doc://leave" not in find(ALICE, "annual leave parental leave"), (
        "LEAK: revocation not applied"
    )


# ---- extension 01: metadata filters and similarity metrics ----------------------------------------

VIEWER = Principal("eve", groups=("all",), classifications=("public", "internal"))
HR_VIEWER = Principal(
    "hana", groups=("all", "hr"), classifications=("public", "internal", "confidential")
)


def filter_chunks() -> list[Chunk]:
    """Six one-chunk documents with the metadata the filter checks need. Every text holds the
    words "staff policy note", so an unfiltered search finds all that the person may see."""
    every = Access("internal", ("all",))
    rows: list[tuple[str, Access, dict[str, Any]]] = [
        ("f1", every, {"department": "hr", "doc_type": "policy", "tags": ["leave", "parental"],
                       "updated": "2024-03-01", "version": 3, "language": "en", "archived": False}),
        ("f2", every, {"department": "hr", "doc_type": "guide", "tags": ["leave"],
                       "updated": "2025-06-15T09:30:00Z", "version": 1, "language": "fr"}),
        ("f3", every, {"department": "it", "doc_type": "policy", "tags": ["vpn", "security"],
                       "updated": "2026-01-10", "version": 2, "language": "en"}),
        ("f4", every, {"department": "finance", "doc_type": "form", "tags": [],
                       "updated": "2023-12-31", "version": 2.5, "language": "en", "archived": True}),
        ("f5", every, {"department": "it", "doc_type": "guide", "version": 7, "language": "de"}),
        # only HR, with clearance: a filter that matches it must still never show it to others
        ("f6", Access("confidential", ("hr",)), {"department": "hr", "doc_type": "policy",
                                                 "updated": "2025-01-01", "language": "en"}),
    ]  # fmt: skip
    out = []
    for name, access, meta in rows:
        uri, text = (
            f"doc://{name}",
            f"Staff policy note {name}: {meta['department']} {meta['doc_type']}.",
        )
        out.append(
            Chunk(
                Chunk.make_id(uri, 0, text), uri, 0, text, len(text.split()), access, metadata=meta
            )
        )
    return out


# filter -> the documents VIEWER must get (f6 is never among them: VIEWER may not see it)
FILTER_CASES: list[tuple[dict[str, Any], set[str]]] = [
    ({"department": "hr"}, {"f1", "f2"}),
    ({"department": ["hr", "finance"]}, {"f1", "f2", "f4"}),
    ({"department": {"in": ["hr", "finance"]}}, {"f1", "f2", "f4"}),
    ({"department": {"ne": "hr"}}, {"f3", "f4", "f5"}),
    ({"department": {"nin": ["hr", "it"]}}, {"f4"}),
    ({"tags": "leave"}, {"f1", "f2"}),
    ({"tags": {"in": ["vpn", "parental"]}}, {"f1", "f3"}),
    ({"tags": {"ne": "leave"}}, {"f3", "f4", "f5"}),
    ({"tags": {"exists": True}}, {"f1", "f2", "f3"}),
    ({"tags": {"exists": False}}, {"f4", "f5"}),
    ({"updated": {"gte": "2025-01-01"}}, {"f2", "f3"}),
    ({"updated": {"gt": "2025-06-15"}}, {"f2", "f3"}),
    ({"updated": {"lt": "2024-01-01"}}, {"f4"}),
    ({"updated": {"range": {"gte": "2024-01-01", "lt": "2026-01-01"}}}, {"f1", "f2"}),
    ({"version": {"gte": 2.5}}, {"f1", "f4", "f5"}),
    ({"version": {"lt": 2}}, {"f2"}),
    ({"version": 2}, {"f3"}),
    ({"archived": True}, {"f4"}),
    ({"archived": {"ne": True}}, {"f1", "f2", "f3", "f5"}),
    ({"or": [{"department": "finance"}, {"language": "de"}]}, {"f4", "f5"}),
    ({"not": {"doc_type": "policy"}}, {"f2", "f4", "f5"}),
    ({"and": [{"department": "it"}, {"not": {"tags": "vpn"}}]}, {"f5"}),
    ({"document": "doc://f3"}, {"f3"}),
    ({"document": {"in": ["doc://f1", "doc://f5"]}}, {"f1", "f5"}),
    ({"department": "hr", "doc_type": "policy"}, {"f1"}),
    ({"department": "nobody"}, set()),
]


def check_metadata_filters(make: Callable[[], Any], embedder: Any = None) -> None:
    """Every filter operator gives exactly the expected documents, on top of (never instead of)
    the permission filter. Vector stores when an embedder is given, keyword indexes otherwise."""
    store, chunks = make(), filter_chunks()
    if embedder is not None:
        store.upsert(chunks, embedder.embed_documents([c.indexed_text for c in chunks]))
        q = embedder.embed_query("staff policy note")

        def find(who: Principal, flt: dict[str, Any] | None) -> set[str]:
            return {
                h.chunk.document_uri.removeprefix("doc://") for h in store.search(q, who, 20, flt)
            }
    else:
        store.index(chunks)

        def find(who: Principal, flt: dict[str, Any] | None) -> set[str]:
            return {
                h.chunk.document_uri.removeprefix("doc://")
                for h in store.search("staff policy note", who, 20, flt)
            }

    assert find(VIEWER, None) == {"f1", "f2", "f3", "f4", "f5"}, (
        "unfiltered search must find every visible document"
    )
    wrong = {}
    for flt, want in FILTER_CASES:
        got = find(VIEWER, flt)
        if got != want:
            wrong[str(flt)] = (sorted(got), sorted(want))
    assert not wrong, "filters gave the wrong documents (got, want): " + "; ".join(
        f"{k}: {v}" for k, v in wrong.items()
    )
    # the filter narrows; the permission filter still applies
    assert find(HR_VIEWER, {"department": "hr", "doc_type": "policy"}) == {"f1", "f6"}
    assert find(OTHER_TENANT, {"department": "hr"}) == set(), "LEAK: a filter crossed tenants"


def check_metrics(make: Callable[[Any], Any], dims: int = 4) -> None:
    """A vector store gives, for each metric it supports, the same ranking as exact arithmetic,
    with scores where higher = more similar. `make(metric)` returns an EMPTY store for it, or None
    when the store doesn't support that metric. Vectors are padded with zeros to `dims` (which
    changes no metric)."""
    from rag_core.similarity import similarity

    # vectors chosen so that the metrics DISAGREE: cosine likes direction, dot likes length too
    rows = {
        "a": [1.0, 0.0, 0.0, 0.0],
        "b": [3.0, 3.0, 0.0, 0.0],
        "c": [0.5, 0.1, 0.0, 0.0],
        "d": [0.0, 0.0, 2.0, 0.0],
    }
    q = [1.0, 0.2, 0.0, 0.0]
    every = Access("internal", ("all",))
    chunks = [
        Chunk(Chunk.make_id(f"doc://{n}", 0, n), f"doc://{n}", 0, f"vector {n}", 2, every)
        for n in rows
    ]
    pad = [0.0] * (dims - len(q))
    for metric in ("cosine", "dot", "l2", "l1"):
        store = make(metric)
        if store is None:  # not supported by this store
            continue
        store.upsert(chunks, [v + pad for v in rows.values()])
        hits = store.search(q + pad, VIEWER, 4)
        got = [h.chunk.document_uri.removeprefix("doc://") for h in hits]
        exact = {n: similarity(metric, q, v) for n, v in rows.items()}
        want = sorted(exact, key=lambda n: -exact[n])
        assert got == want, f"{metric}: ranking {got}, exact arithmetic says {want}"
        for h in hits:
            n = h.chunk.document_uri.removeprefix("doc://")
            assert math.isclose(h.score, exact[n], rel_tol=2e-2, abs_tol=2e-3), (
                f"{metric}: score of {n} is {h.score}, expected {exact[n]} (higher = more similar)"
            )


# ---------------------------------------------------------------- extension 02


def sample_document() -> Any:
    """A small structured document: a title, numbered sections, a subsection, a table."""
    from rag_core.types import Document, Element

    els = (
        Element("title", "Leave policy", level=1),
        Element("paragraph", "All staff accrue leave from their first day of work."),
        Element("heading", "4 Leave types", level=2),
        Element("heading", "4.1 Annual leave", level=3),
        Element(
            "paragraph",
            "Full-time staff get 20 days of annual leave per year. "
            "Leave must be approved by your manager. Book it in the HR portal.",
        ),
        Element("heading", "4.2 Parental leave", level=3),
        Element(
            "paragraph",
            "Parental leave is 18 weeks at full pay. It can start up to six "
            "weeks before the due date. Partners get four weeks.",
        ),
        Element("table", "| Type | Weeks |\n| Primary carer | 18 |\n| Partner | 4 |"),
        Element("heading", "5 Public holidays", level=2),
        Element("paragraph", "Public holidays are paid. Working on one earns a day in lieu."),
    )
    return Document("doc://policy", "Leave policy", els, "sha-policy", Access("internal", ("hr",)))


def check_chunker(chunker: Any, document: Any = None) -> None:
    """A chunker (Step 31) returns non-empty chunks of the document, with stable ids (the same
    input gives the same ids: re-ingesting is idempotent), positions in order, the document's
    access copied to every chunk, and the document's words all still findable somewhere."""
    doc = document or sample_document()
    chunks = chunker.chunk(doc)
    assert chunks, "no chunks"
    assert all(c.text.strip() for c in chunks), "empty chunk"
    assert all(c.document_uri == doc.uri for c in chunks)
    assert all(c.access == doc.access for c in chunks), (
        "every chunk must carry the document's access"
    )
    assert len({c.id for c in chunks}) == len(chunks), "chunk ids must be unique"
    assert [c.id for c in chunker.chunk(doc)] == [c.id for c in chunks], "ids must be stable"
    assert [c.index for c in chunks] == sorted(c.index for c in chunks), "indexes in order"
    assert all(c.token_count > 0 for c in chunks)
    from rag_core.text import content_words

    seen = {
        w for c in chunks for w in content_words(c.text + " " + str(c.metadata.get("window", "")))
    }
    lost = {w for e in doc.elements for w in content_words(e.text)} - seen
    assert len(lost) <= 3, f"the chunks lost these words of the document: {sorted(lost)[:10]}"


def check_compressor(compressor: Any) -> None:
    """A compressor (extension 02) only shortens or drops what it is given: same ids, documents
    and access, never a chunk it wasn't given, never longer, best kept for the question."""
    from rag_core.types import Query

    chunks = sample_chunks()
    long = Chunk("long", "doc://leave", 5, "Parental leave is 18 weeks at full pay. The office "
                 "café opens at 8 am. Deployments use Argo CD.", 20, Access("internal", ("hr",)))  # fmt: skip
    hits = [ScoredChunk(c, 1.0 - i / 10) for i, c in enumerate([long, *chunks])]
    out = compressor.compress(Query("how many weeks of parental leave", ALICE), hits)
    given = {h.chunk.id: h.chunk for h in hits}
    assert out, "a compressor must not drop every chunk that answers the question"
    for h in out:
        orig = given.get(h.chunk.id)
        assert orig is not None, "a compressor must only return chunks it was given"
        assert h.chunk.document_uri == orig.document_uri
        assert h.chunk.access == orig.access
        assert len(h.chunk.text) <= len(orig.text), "compression must not lengthen a chunk"
    assert len({h.chunk.id for h in out}) == len(out), "no duplicates"
    assert any("18 weeks" in h.chunk.text for h in out), "the answer must survive compression"
    assert compressor.compress(Query("anything", ALICE), []) == []


def check_sparse_embedder(embedder: Any) -> None:
    """A sparse embedder (extension 02): {id: weight} with positive weights; texts sharing words
    share ids; a model name; and the idf flag the index needs."""
    docs = embedder.embed_sparse_documents(["annual leave policy", "deployment pipeline"])
    assert len(docs) == 2, "one sparse vector per text"
    assert all(docs), "a text with words must have a non-empty sparse vector"
    assert all(isinstance(i, int) and w > 0 for d in docs for i, w in d.items())
    q = embedder.embed_sparse_query("annual leave")
    assert set(q) & set(docs[0]), "a query must share ids with a text that has its words"
    assert not set(q) & set(docs[1]) or len(set(q) & set(docs[0])) > len(set(q) & set(docs[1]))
    assert embedder.model, "a sparse embedder must name its model"
    assert isinstance(embedder.idf, bool)
