"""The data lifecycle (Step 36): access changes, retention, erasure, re-indexing, and tenant
isolation enforced by the database itself."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import pytest

from rag_core import config as cfg
from rag_core import evaluate as ev
from rag_core import lifecycle as lc
from rag_core.answer import AnswerPipeline
from rag_core.cli import main
from rag_core.components.basics import HashingEmbedder, MemoryKeywordIndex, MemoryVectorStore
from rag_core.components.conversation import (
    InMemoryMemory,
    MemoryParams,
    ValkeyMemory,
    ValkeyMemoryParams,
)
from rag_core.components.opensearch import OpenSearchKeywordIndex, OpenSearchParams
from rag_core.ingest import IngestionPipeline
from rag_core.registry import Container
from rag_core.testing.conformance import check_access_update
from rag_core.types import Access, Principal, Source, Turn

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "examples/eval/handbook.yaml"
STAFF = Principal("ann", ("all-staff",), ("public", "internal"))


def offline(**slots: Any) -> Container:
    config = cfg.resolve(
        __import__("yaml").safe_load((ROOT / "rag.yaml").read_text()), "offline", env={}
    )
    config.update(slots)
    return Container({k: v for k, v in config.items() if v != "none"}, "test")


def handbook(**slots: Any) -> Container:
    c = offline(**slots)
    ev.ingest_corpus(c, ev.load_dataset(DATASET), DATASET.parent)
    return c


def uri_of(c: Container, name: str) -> str:
    return str(next(e.source_uri for e in c.get("manifest").all() if e.source_uri.endswith(name)))


# ---------------------------------------------------------------- access changes


def test_memory_stores_change_access_in_place() -> None:
    check_access_update(MemoryVectorStore, HashingEmbedder(64))
    check_access_update(MemoryKeywordIndex)


def test_opensearch_access_update_request() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(
            path=req.url.path,
            params=dict(req.url.params),
            body=__import__("json").loads(req.content),
        )
        return httpx.Response(200, json={"updated": 3})

    idx = OpenSearchKeywordIndex(
        OpenSearchParams(url="https://os:9200"),
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://os:9200"),
    )
    assert idx.update_access("doc://a", Access("confidential", ("hr",), "acme")) == 3
    assert seen["path"] == "/rag-chunks/_update_by_query"
    assert seen["body"]["query"] == {"term": {"source_uri": "doc://a"}}
    assert seen["body"]["script"]["params"] == {
        "t": "acme",
        "c": "confidential",
        "g": ["hr"],
    }  # values as parameters


def test_revocation_reaches_search_answers_cache_and_manifest() -> None:
    c = handbook(
        pipeline="graph", graph_store="memory", enrichers=["context-header", "graph-entities"]
    )
    p = AnswerPipeline(c)
    q = "How many days a week can I work from home?"
    assert "three days" in p.answer(q, STAFF).text
    assert p.answer(q, STAFF).trace["cache"] == "hit"
    uri = uri_of(c, "remote-work.md")
    report = lc.change_access(IngestionPipeline(c), uri, Access("confidential", ("hr",)))
    assert report.items[0]["chunks"] == c.get("manifest").get(uri).chunk_count
    after = p.answer(q, STAFF)
    assert after.trace["cache"] == "miss"  # the cached answer rested on what was revoked
    assert "three days" not in after.text
    assert c.get("manifest").get(uri).access["classification"] == "confidential"
    assert all(
        ch.access.classification == "confidential"
        for ch in c.get("graph_store").chunks.values()
        if ch.document_uri == uri
    )


# ---------------------------------------------------------------- retention


def test_retention_dry_run_then_apply() -> None:
    c = handbook()
    m = c.get("manifest")
    old = uri_of(c, "annual-leave-2021.md")
    m.put(replace(m.get(old), updated_at=time.time() - 40 * lc.DAY))  # last ingested 40 days ago
    policy = lc.load_retention(ROOT / "examples/retention.yaml")
    pipe = IngestionPipeline(c)
    dry = lc.apply_retention(pipe, policy)
    assert [i["uri"] for i in dry.items] == [old]
    assert dry.items[0]["reason"].startswith("Superseded policy")
    assert m.get(old) is not None  # nothing happened
    done = lc.apply_retention(pipe, policy, apply=True)
    assert done.items[0]["chunks_deleted"] > 0
    assert m.get(old) is None
    assert all(not h.chunk.document_uri.endswith("annual-leave-2021.md")
               for h in c.get("keyword_index").search("annual leave 18 days", STAFF, 20))  # fmt: skip


# ---------------------------------------------------------------- erasure


class FakeS3:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def get_paginator(self, name: str) -> Any:
        assert name == "list_object_versions"
        return self

    def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, Any]]:  # noqa: N803 - boto3's names
        return [{"Versions": [{"Key": Prefix, "VersionId": "v1"}, {"Key": Prefix, "VersionId": "v2"},
                              {"Key": Prefix + ".bak", "VersionId": "x"}],
                 "DeleteMarkers": [{"Key": Prefix, "VersionId": "d1"}]}]  # fmt: skip

    def delete_object(self, Bucket: str, Key: str, VersionId: str) -> None:  # noqa: N803
        self.deleted.append((Key, VersionId))


def test_erase_source_removes_every_version_and_every_copy() -> None:
    c = offline()
    uri = "s3://rag-originals/hr/letter.md"
    IngestionPipeline(c).ingest(
        Source(
            uri,
            b"# Letter\n\nDear Jane, your leave is approved.",
            access=Access("internal", ("hr",)),
        )
    )
    s3 = FakeS3()
    dry = lc.erase_source(IngestionPipeline(c), uri, s3_client=s3)
    assert dry.items[0]["object_versions"] == 3  # v1, v2 and the delete marker; not letter.md.bak
    assert s3.deleted == []
    lc.erase_source(IngestionPipeline(c), uri, apply=True, s3_client=s3)
    assert sorted(s3.deleted) == [
        ("hr/letter.md", "d1"),
        ("hr/letter.md", "v1"),
        ("hr/letter.md", "v2"),
    ]
    assert c.get("vector_store").count() == 0
    assert c.get("manifest").get(uri) is None


def test_erase_subject_conversations_cache_and_mentions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PII_HMAC_KEY", "test-key")
    c = offline(pii={"use": "regex", "strategy": "pseudonymise"})
    ingest = IngestionPipeline(c)
    ingest.ingest(Source("doc://incident.md", b"# Incident 42\n\nReported by jane.doe@example.com on Monday.",
                         access=Access("confidential", ("security",), "acme")))  # fmt: skip
    ingest.ingest(
        Source(
            "doc://other.md",
            b"# Leave\n\nAnnual leave is 20 days.",
            access=Access("internal", ("all-staff",)),
        )
    )
    jane = Principal("jane-sub", ("all-staff",), ("public", "internal"))
    mem = c.get("memory")
    mem.append(jane, "s1", Turn("user", "my question"))
    mem.append(jane, "s2", Turn("user", "another"))
    mem.append(STAFF, "s1", Turn("user", "not jane"))
    epoch = c.get("cache").epoch()
    dry = lc.erase_subject(c, jane, ["jane.doe@example.com"])
    assert dry.items[0]["sessions"] == 2
    assert dry.items[2]["documents"] == [
        "doc://incident.md"
    ]  # found by its pseudonym, across tenants and groups
    assert c.get("cache").epoch() == epoch
    lc.erase_subject(c, jane, ["jane.doe@example.com"], apply=True)
    assert mem.history(jane, "s1") == ()
    assert mem.history(STAFF, "s1") != ()  # only that person
    assert c.get("cache").epoch() != epoch


def test_valkey_memory_forgets_one_person() -> None:
    r = fakeredis.FakeRedis(decode_responses=True)
    m = ValkeyMemory(ValkeyMemoryParams(), client=r)
    jane = Principal("jane")
    for s in ("a", "b", "c"):
        m.append(jane, s, Turn("user", "x"))
    m.append(STAFF, "a", Turn("user", "y"))
    assert m.count_subject(jane) == 3
    assert m.forget_subject(jane) == 3
    assert m.history(jane, "a") == ()
    assert m.history(STAFF, "a") == (Turn("user", "y"),)
    assert not any(
        "jane" in k for k in r.scan_iter()
    )  # keys are hashes: they say nothing about who
    mem = InMemoryMemory(MemoryParams())
    mem.append(jane, "a", Turn("user", "x"))
    assert mem.forget_subject(jane) == 1


# ---------------------------------------------------------------- re-indexing


def test_reindex_rebuilds_from_originals_with_the_same_access() -> None:
    src = handbook()
    dst = offline(chunker={"use": "fixed", "max_tokens": 80, "overlap_tokens": 10})
    dry = lc.reindex(src, dst)
    assert len(dry.items) == 17
    assert dst.get("vector_store").count() == 0
    done = lc.reindex(src, dst, apply=True)
    assert all(i["status"] == "indexed" for i in done.items)
    exec_uri = uri_of(src, "exec-compensation.md")
    hits = dst.get("keyword_index").search("executive bonus pool", STAFF, 10)
    assert exec_uri not in {
        h.chunk.document_uri for h in hits
    }  # still restricted after the rebuild
    assert dst.get("manifest").get(exec_uri).access["classification"] == "restricted"


def test_lifecycle_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["retention", "--rules", str(ROOT / "examples/retention.yaml"), "--file", str(ROOT / "rag.yaml"),
                 "--profile", "offline"]) == 0  # fmt: skip
    assert "dry run" in capsys.readouterr().out
    assert main(["reacl", "doc://x", "--group", "hr", "--classification", "confidential", "--file",
                 str(ROOT / "rag.yaml"), "--profile", "offline", "--json"]) == 0  # fmt: skip
    assert '"classification": "confidential"' in capsys.readouterr().out


# ---------------------------------------------------------------- tenant isolation in the database


@pytest.fixture(scope="module")
def pg_admin() -> str:
    dsn = os.environ.get("RAG_TEST_PGVECTOR_DSN")
    if not dsn:
        pytest.skip("RAG_TEST_PGVECTOR_DSN not set (a throwaway Postgres with pgvector)")
    return dsn


def test_row_level_security_isolates_tenants(pg_admin: str) -> None:
    """The real migrations, a NON-superuser role (superusers bypass RLS), two tenants."""
    import psycopg
    from psycopg.conninfo import make_conninfo

    from rag_core.testing.postgres import apply_migrations

    with psycopg.connect(pg_admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS rag_rls WITH (FORCE)")
        conn.execute("CREATE DATABASE rag_rls")
        conn.execute("DROP ROLE IF EXISTS rls_app")
        # a password: `just audit-test` runs Postgres with password authentication (Step 28)
        conn.execute("CREATE ROLE rls_app LOGIN PASSWORD 'rls-test-only'")
    admin = make_conninfo(pg_admin, dbname="rag_rls")
    apply_migrations(admin)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("GRANT USAGE ON SCHEMA rag TO rls_app")
        conn.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA rag TO rls_app")
        conn.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA rag TO rls_app")
    os.environ["RAG_RLS_DSN"] = make_conninfo(admin, user="rls_app", password="rls-test-only")  # noqa: S106 - a throwaway test role
    c = Container({"parsers": ["markdown"], "chunker": "structure", "token_counter": "approx", "embedder": "hashing",
                   "keyword_index": {"use": "postgres-fts", "dsn_env": "RAG_RLS_DSN", "collection": "rls"}})  # fmt: skip
    pipe, idx = IngestionPipeline(c), c.get("keyword_index")
    pipe.ingest(
        Source(
            "doc://acme.md",
            b"# Pricing\n\nAcme pricing is confidential to Acme.",
            access=Access("internal", ("staff",), "acme"),
        )
    )
    pipe.ingest(
        Source(
            "doc://globex.md",
            b"# Pricing\n\nGlobex pricing is confidential to Globex.",
            access=Access("internal", ("staff",), "globex"),
        )
    )
    acme = Principal("u", ("staff",), ("internal",), "acme")
    assert {h.chunk.document_uri for h in idx.search("pricing", acme, 10)} == {"doc://acme.md"}
    with psycopg.connect(
        os.environ["RAG_RLS_DSN"]
    ) as conn:  # a query that FORGETS the tenant filter
        assert conn.execute("SELECT count(*) FROM rag.documents").fetchone()[0] == 0  # type: ignore[index]  # nothing set: nothing
        conn.execute("SELECT set_config('rag.tenant', 'acme', true)")
        assert conn.execute("SELECT source_uri FROM rag.documents").fetchall() == [
            ("doc://acme.md",)
        ]
        assert conn.execute("SELECT count(*) FROM rag.chunks").fetchone()[0] == 1  # type: ignore[index]  # chunks follow their document
