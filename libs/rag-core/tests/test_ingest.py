"""The ingestion pipeline end to end (Step 31): every format, skip-if-unchanged, replacement,
deletion, PII, failures, and the queue worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rag_core.components.queues import Job, MemoryQueue, ValkeyParams, ValkeyStreamQueue
from rag_core.ingest import IngestionPipeline, Worker, load_source
from rag_core.registry import Container
from rag_core.testing.conformance import ALICE, BOB
from rag_core.types import Access, Principal, Source

EVERYONE = Principal("x", ("hr", "eng"), ("public", "internal", "confidential"))


def make_container(**over: Any) -> Container:
    cfg: dict[str, Any] = {
        "token_counter": "approx",
        "parsers": ["markdown", "html", "pdf", "docx", "csv", "text"],
        "normalizers": ["unicode", "boilerplate"],
        "pii": {"use": "regex", "strategy": "mask"},
        "chunker": {"use": "structure", "max_tokens": 120, "overlap_tokens": 0},
        "enrichers": [{"use": "context-header"}],
        "embedder": {"use": "hashing", "dimensions": 128},
        "vector_store": "memory",
        "keyword_index": "memory-bm25",
        "manifest": "memory",
        "queue": "memory",
    }
    cfg.update(over)
    return Container(cfg)


def test_every_format_is_indexed_with_its_access(sources: dict[str, Source]) -> None:
    c = make_container()
    p = IngestionPipeline(c)
    results = {k: p.ingest(s) for k, s in sources.items()}
    assert {k: r.status for k, r in results.items()} == dict.fromkeys(sources, "indexed")
    vec, kw = c.get("vector_store"), c.get("keyword_index")
    assert vec.count() == sum(r.chunks for r in results.values())
    # the HR-only leave policy: found by HR, invisible to engineering
    assert (
        kw.search("parental leave", ALICE, 3)[0].chunk.document_uri
        == "file:///docs/leave-policy.md"
    )
    assert all(
        h.chunk.document_uri != "file:///docs/leave-policy.md"
        for h in kw.search("parental leave", BOB, 10)
    )
    assert results["pdf"].chunks >= 1
    assert results["md"].pii == ("email", "phone")


def test_what_is_stored_is_redacted_and_enriched(sources: dict[str, Source]) -> None:
    c = make_container()
    IngestionPipeline(c).ingest(sources["md"])
    hits = c.get("keyword_index").search("contact parental", ALICE, 5)
    chunk = next(h.chunk for h in hits if "Parental leave is" in h.chunk.text)
    assert "hr@example.com" not in chunk.text
    assert "[EMAIL]" in chunk.text
    assert chunk.embed_text.startswith("Leave policy > Parental leave\n\n")
    assert chunk.metadata["pii_redacted"] == ["email", "phone"]


def test_unchanged_sources_are_skipped_and_changes_replace_old_chunks(
    sources: dict[str, Source],
) -> None:
    c = make_container()
    p = IngestionPipeline(c)
    first = p.ingest(sources["md"])
    assert p.ingest(sources["md"]).status == "unchanged"
    edited = Source(sources["md"].uri, sources["md"].data.replace(b"18 weeks", b"20 weeks").replace(b"## Annual leave\n", b""),
                    access=sources["md"].access)  # fmt: skip
    again = p.ingest(edited)
    assert again.status == "indexed"
    kw = c.get("keyword_index")
    texts = [h.chunk.text for h in kw.search("weeks parental leave", ALICE, 20)]
    assert any("20 weeks" in t for t in texts)
    assert not any("18 weeks" in t for t in texts)  # the old version's chunks are gone
    assert c.get("vector_store").count() == again.chunks <= first.chunks


def test_a_pipeline_change_reindexes_everything(sources: dict[str, Source]) -> None:
    c1 = make_container()
    p1 = IngestionPipeline(c1)
    p1.ingest(sources["md"])
    c2 = make_container(chunker={"use": "structure", "max_tokens": 60, "overlap_tokens": 0})
    c2._built["manifest"] = c1.get("manifest")  # same manifest, different chunker
    c2._built["vector_store"], c2._built["keyword_index"] = (
        c1.get("vector_store"),
        c1.get("keyword_index"),
    )
    assert IngestionPipeline(c2).ingest(sources["md"]).status == "indexed"


def test_delete_removes_from_every_store(sources: dict[str, Source]) -> None:
    c = make_container()
    p = IngestionPipeline(c)
    n = p.ingest(sources["md"]).chunks
    events: list[dict[str, Any]] = []
    p.on_event = events.append
    assert p.delete(sources["md"].uri).chunks == n
    assert c.get("vector_store").count() == 0
    assert c.get("keyword_index").search("leave", ALICE, 5) == []
    assert c.get("manifest").get(sources["md"].uri) is None
    assert events == [
        {"event": "rag.ingest", "uri": sources["md"].uri, "status": "deleted", "chunks": n}
    ]


def test_failures_are_recorded_not_raised() -> None:
    c = make_container()
    r = IngestionPipeline(c).ingest(Source("file:///x.pdf", b"%PDF-1.4 broken"))
    assert r.status == "failed"
    assert "unreadable PDF" in r.detail
    assert c.get("manifest").get("file:///x.pdf").status == "failed"


def test_events_feed_lineage_and_audit(sources: dict[str, Source]) -> None:
    events: list[dict[str, Any]] = []
    IngestionPipeline(make_container(), on_event=events.append).ingest(sources["html"])
    (e,) = events
    assert e["status"] == "indexed"
    assert e["sha256"] == sources["html"].sha256
    assert len(e["pipeline"]) == 16


def test_load_source_from_file_and_s3(tmp_path: Path) -> None:
    import boto3
    from moto import mock_aws

    (tmp_path / "a.md").write_text("# A\n\ntext")
    assert load_source(f"file://{tmp_path}/a.md").data == b"# A\n\ntext"
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="rag-originals")
        s3.put_object(Bucket="rag-originals", Key="hr/a.md", Body=b"hello")
        src = load_source("s3://rag-originals/hr/a.md", Access("internal", ("hr",)), s3_client=s3)
    assert src.data == b"hello"
    assert src.access.groups == ("hr",)
    with pytest.raises(ValueError, match="unsupported source"):
        load_source("ftp://x/y")


def test_worker_retries_then_parks_jobs(sources: dict[str, Source], tmp_path: Path) -> None:
    (tmp_path / "ok.md").write_bytes(sources["md"].data)
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4 broken")
    c = make_container()
    q: MemoryQueue = c.get("queue")
    q.put(
        Job(
            "upsert",
            f"file://{tmp_path}/ok.md",
            access={"classification": "internal", "groups": ["hr"]},
        )
    )
    q.put(Job("upsert", f"file://{tmp_path}/bad.pdf"))
    q.put(Job("upsert", f"file://{tmp_path}/missing.md"))  # an I/O error: retried, then parked
    q.put(Job("delete", f"file://{tmp_path}/ok.md"))
    results = Worker(IngestionPipeline(c), q).run()
    assert [r.status for r in results] == ["indexed", "failed", "deleted"]
    assert sorted(j.uri.rsplit("/", 1)[1] for j, _ in q.dead) == ["bad.pdf", "missing.md"]
    missing = next(j for j, _ in q.dead if j.uri.endswith("missing.md"))
    assert missing.attempts == 3  # tried max_attempts times
    assert q.size() == 0


def test_valkey_stream_queue_semantics() -> None:
    import fakeredis

    r = fakeredis.FakeRedis(decode_responses=True)
    q = ValkeyStreamQueue(ValkeyParams(max_attempts=2, consumer="w1"), client=r)
    ValkeyStreamQueue(
        ValkeyParams(consumer="w2"), client=r
    )  # a second worker: the group already exists
    q.put(Job("upsert", "file:///a"))
    job = q.get(block_ms=10)
    assert job is not None
    assert job.uri == "file:///a"
    assert job.id
    q.fail(job, "boom")  # back on the stream with attempts=1
    again = q.get(block_ms=10)
    assert again is not None
    assert again.attempts == 1
    q.fail(again, "boom again")  # attempts=2 = max: parked
    assert q.get(block_ms=10) is None
    assert r.xlen("rag:ingest:dead") == 1
    q.put(Job("delete", "file:///b"))
    j = q.get(block_ms=10)
    assert j is not None
    q.ack(j)
    assert q.size() == 0
