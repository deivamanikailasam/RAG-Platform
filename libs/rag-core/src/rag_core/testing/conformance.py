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
