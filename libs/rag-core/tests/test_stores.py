"""Every store passes the same conformance checks (Step 31): pgvector and Postgres full-text
search on a real Postgres, Qdrant on a real Qdrant, OpenSearch by its exact requests.

RAG_TEST_PGVECTOR_DSN=postgres://postgres@127.0.0.1:55433/postgres                     (any Postgres with pgvector)
qdrant on PATH (just tools qdrant)
Tests skip when those aren't available.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from rag_core.components.basics import HashingEmbedder
from rag_core.components.opensearch import (
    OpenSearchKeywordIndex,
    OpenSearchParams,
    OpenSearchVectorStore,
)
from rag_core.components.pgstore import PgFullTextIndex, PgParams, PgVectorStore
from rag_core.components.qdrant import QdrantParams, QdrantStore
from rag_core.testing.conformance import (
    ALICE,
    BOB,
    check_access_update,
    check_keyword_index,
    check_vector_store,
    sample_chunks,
)
from rag_core.testing.postgres import apply_migrations

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = ROOT / "infra/db/rag/migrations"
DIMS = 64


# ---- Postgres ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_dsn() -> str:
    admin = os.environ.get("RAG_TEST_PGVECTOR_DSN")
    if not admin:
        pytest.skip("RAG_TEST_PGVECTOR_DSN not set (a throwaway Postgres with pgvector)")
    import psycopg
    from psycopg.conninfo import make_conninfo

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS rag_core_test WITH (FORCE)")
        conn.execute("CREATE DATABASE rag_core_test")
    dsn = make_conninfo(admin, dbname="rag_core_test")
    # the REAL migrations: Step 11's tables, then Step 31's and Step 36's changes
    apply_migrations(dsn, DIMS, MIGRATIONS_DIR)
    return dsn


def pg_params(dsn: str, collection: str) -> PgParams:
    os.environ["RAG_TEST_DB_DSN"] = dsn
    with __import__("psycopg").connect(dsn) as conn:
        version = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()[0]
    vtype = "vector" if tuple(int(x) for x in version.split(".")[:2]) < (0, 7) else "halfvec"
    return PgParams(
        dsn_env="RAG_TEST_DB_DSN", collection=collection, dimensions=DIMS, vector_type=vtype
    )


def test_pgvector_conforms(pg_dsn: str) -> None:
    n = iter(range(100))
    check_vector_store(
        lambda: PgVectorStore(pg_params(pg_dsn, f"vec-{next(n)}")), HashingEmbedder(DIMS)
    )


def test_postgres_fts_conforms(pg_dsn: str) -> None:
    n = iter(range(100))
    check_keyword_index(lambda: PgFullTextIndex(pg_params(pg_dsn, f"fts-{next(n)}")))


def test_postgres_stores_change_access_in_place(pg_dsn: str) -> None:
    """Step 36: access changes on the document row reach every chunk, vector and keyword alike."""
    n = iter(range(100))
    check_access_update(
        lambda: PgVectorStore(pg_params(pg_dsn, f"reacl-vec-{next(n)}")), HashingEmbedder(DIMS)
    )
    check_access_update(lambda: PgFullTextIndex(pg_params(pg_dsn, f"reacl-fts-{next(n)}")))


def test_postgres_vector_and_keyword_share_rows(pg_dsn: str) -> None:
    """Both on the same tables: one write path, one delete, one permission model."""
    p = pg_params(pg_dsn, "shared")
    vec, fts = PgVectorStore(p), PgFullTextIndex(p)
    chunks = sample_chunks()
    e = HashingEmbedder(DIMS)
    fts.index(chunks)  # keyword-only rows first (no vectors)…
    assert vec.count() == 0
    vec.upsert(
        chunks, e.embed_documents([c.text for c in chunks])
    )  # …then vectors fill the same rows
    assert vec.count() == len(chunks)
    assert (
        fts.search("parental", ALICE, 3)[0].chunk.id
        == vec.search(e.embed_query("parental leave weeks"), ALICE, 1)[0].chunk.id
    )
    assert vec.delete_document("doc://leave") == 2
    assert fts.search("parental", ALICE, 3) == []


def test_postgres_refuses_vectors_of_the_wrong_size(pg_dsn: str) -> None:
    with pytest.raises(ValueError, match="64 dimensions"):
        PgVectorStore(pg_params(pg_dsn, "dims")).upsert(sample_chunks()[:1], [[0.1] * 32])


# ---- Qdrant ---------------------------------------------------------------------------------------
def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def qdrant_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    binary = shutil.which("qdrant")
    if binary is None:
        pytest.skip("qdrant not installed (just tools qdrant)")
    tmp = tmp_path_factory.mktemp("qdrant")
    http, grpc = _port(), _port()
    env = {**{k: v for k, v in os.environ.items() if "proxy" not in k.lower()},
            "QDRANT__SERVICE__HTTP_PORT": str(http), "QDRANT__SERVICE__GRPC_PORT": str(grpc),
            "QDRANT__SERVICE__HOST": "127.0.0.1", "QDRANT__STORAGE__STORAGE_PATH": str(tmp / "storage"),
            "QDRANT__STORAGE__SNAPSHOTS_PATH": str(tmp / "snapshots"), "QDRANT__TELEMETRY_DISABLED": "true",
            "QDRANT__SERVICE__API_KEY": "test-admin-key"}  # fmt: skip
    proc = subprocess.Popen(  # noqa: S603 - the pinned qdrant binary
        [binary], cwd=tmp, env=env, stdout=(tmp / "log").open("w"), stderr=subprocess.STDOUT
    )
    url = f"http://127.0.0.1:{http}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/readyz", timeout=1, trust_env=False).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            pytest.fail("qdrant didn't start: " + (tmp / "log").read_text()[-2000:])
        yield url
    finally:
        proc.terminate()
        proc.wait(10)


def qdrant_store(url: str, collection: str) -> QdrantStore:
    os.environ["RAG_TEST_QDRANT_KEY"] = "test-admin-key"
    return QdrantStore(QdrantParams(url=url, collection=collection, api_key_env="RAG_TEST_QDRANT_KEY",
                                dimensions=DIMS, create_if_missing=True))  # fmt: skip


def test_qdrant_conforms(qdrant_url: str) -> None:
    n = iter(range(100))
    check_vector_store(lambda: qdrant_store(qdrant_url, f"conf_{next(n)}"), HashingEmbedder(DIMS))


def test_qdrant_changes_access_in_place(qdrant_url: str) -> None:
    """Step 36: the payload's access fields are overwritten without re-embedding."""
    n = iter(range(100))
    check_access_update(lambda: qdrant_store(qdrant_url, f"reacl_{next(n)}"), HashingEmbedder(DIMS))


def test_qdrant_needs_its_key(qdrant_url: str) -> None:
    store = QdrantStore(
        QdrantParams(url=qdrant_url, collection="x", api_key_env=None, dimensions=DIMS)
    )
    with pytest.raises(RuntimeError, match=r"401|403|Unauthorized|Must provide"):
        store.count()


def test_qdrant_refuses_to_invent_a_production_collection(qdrant_url: str) -> None:
    os.environ["RAG_TEST_QDRANT_KEY"] = "test-admin-key"
    store = QdrantStore(
        QdrantParams(
            url=qdrant_url,
            collection="never_created",
            api_key_env="RAG_TEST_QDRANT_KEY",
            dimensions=DIMS,
        )
    )
    with pytest.raises(RuntimeError, match="doesn't exist"):
        store.count()


# ---- OpenSearch: the exact requests --------------------------------------------------------------


class FakeOpenSearch:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        parsed: object = (
            [json.loads(x) for x in body.splitlines()]
            if "ndjson" in request.headers.get("content-type", "")
            else (json.loads(body) if body else None)
        )
        self.requests.append((request.method, request.url.path, parsed))
        if request.url.path.endswith("/_search"):
            src = {"chunk_key": "k1", "source_uri": "doc://a", "chunk_index": 0, "text": "t", "token_count": 1,
                    "classification": "internal", "acl_groups": ["hr"], "tenant_id": "default"}  # fmt: skip
            return httpx.Response(200, json={"hits": {"hits": [{"_score": 3.5, "_source": src}]}})
        if request.url.path.endswith("_delete_by_query"):
            return httpx.Response(200, json={"deleted": 2})
        return httpx.Response(200, json={"errors": False, "items": []})


def test_opensearch_bm25_request_is_permission_filtered() -> None:
    fake = FakeOpenSearch()
    idx = OpenSearchKeywordIndex(
        OpenSearchParams(index="rag-chunks"),
        client=httpx.Client(base_url="http://os", transport=httpx.MockTransport(fake)),
    )
    hits = idx.search("parental leave", BOB, 5, {"lang": "en"})
    assert hits[0].chunk.id == "k1"
    assert hits[0].scores == {"sparse": 3.5}
    _, path, body = fake.requests[-1]
    assert path == "/rag-chunks/_search"
    flt = body["query"]["bool"]["filter"]  # type: ignore[index]
    assert {"term": {"tenant_id": "default"}} in flt
    assert {"terms": {"classification": ["public", "internal"]}} in flt
    assert {"bool": {"should": [{"term": {"classification": "public"}}, {"terms": {"acl_groups": ["eng"]}}],
                    "minimum_should_match": 1}} in flt  # fmt: skip
    assert {"term": {"metadata.lang": "en"}} in flt


def test_opensearch_knn_filters_during_the_search_and_bulk_writes() -> None:
    fake = FakeOpenSearch()
    store = OpenSearchVectorStore(
        OpenSearchParams(dimensions=DIMS),
        client=httpx.Client(base_url="http://os", transport=httpx.MockTransport(fake)),
    )
    chunks = sample_chunks()
    store.upsert(chunks, HashingEmbedder(DIMS).embed_documents([c.text for c in chunks]))
    _, path, lines = fake.requests[-1]
    assert path == "/_bulk"
    assert len(lines) == 2 * len(chunks)  # type: ignore[arg-type]
    assert lines[0] == {"index": {"_index": "rag-chunks", "_id": chunks[0].id}}  # type: ignore[index]
    assert len(lines[1]["embedding"]) == DIMS  # type: ignore[index]
    assert lines[1]["acl_groups"] == ["hr"]  # type: ignore[index]
    store.search([0.1] * DIMS, ALICE, 4)
    knn = fake.requests[-1][2]["query"]["knn"]["embedding"]  # type: ignore[index]
    assert knn["k"] == 4
    assert knn["filter"]["bool"]["filter"][0] == {"term": {"tenant_id": "default"}}
    assert store.delete_document("doc://leave") == 2
    assert re.search(r"_delete_by_query$", fake.requests[-1][1])


def test_postgres_manifest_round_trip(pg_dsn: str) -> None:
    from rag_core.components.pgstore import PgManifest
    from rag_core.components.queues import ManifestEntry

    m = PgManifest(pg_params(pg_dsn, "manifest"))
    assert m.get("file:///a") is None
    m.put(ManifestEntry("file:///a", "sha1", "p1", 3, "indexed"))
    m.put(ManifestEntry("file:///a", "sha2", "p1", 4, "indexed"))  # an update, not a second row
    got = m.get("file:///a")
    assert got is not None
    assert (got.content_sha256, got.chunk_count) == ("sha2", 4)
    assert [e.source_uri for e in m.all()] == ["file:///a"]
    m.delete("file:///a")
    assert m.get("file:///a") is None


# ---- Step 32: the whole search pipeline on real Postgres ----------------------------------------


def test_hybrid_search_on_postgres_end_to_end(pg_dsn: str) -> None:
    """Step 32 on the real tables: the handbook ingested into pgvector + Postgres full-text search,
    searched through the whole pipeline, scored by the same evaluation as the offline profile."""
    from rag_core import evaluate as ev
    from rag_core.registry import Container
    from rag_core.search import SearchPipeline
    from rag_core.types import Principal, Query

    p = pg_params(pg_dsn, "handbook")
    store = {"dsn_env": "RAG_TEST_DB_DSN", "collection": "handbook", "dimensions": DIMS,
             "vector_type": p.vector_type}  # fmt: skip
    doc = ev.load_dataset(ROOT / "examples/eval/handbook.yaml")
    config = ev.variant_configs(ROOT / "rag.yaml", "offline", doc, ["all-together"])["all-together"]
    config |= {"embedder": {"use": "hashing", "dimensions": DIMS}, "vector_store": {"use": "pgvector", **store},
               "keyword_index": {"use": "postgres-fts", **store}}  # fmt: skip
    scores = ev.run_variant("postgres", config, doc, ROOT / "examples/eval")
    assert scores.leaks == 0
    assert scores.recall >= 0.85, scores.per_case
    # the rows carry Step 11's numeric document id (rag-api's policy check and audit use it)
    staff = Principal("eval-staff", ("all-staff",), ("public", "internal"))
    hits = SearchPipeline(Container(config, "pg")).search(Query("My VPN shows E-4021", staff)).hits
    assert hits[0].chunk.document_uri.endswith("vpn-troubleshooting.md")
    assert isinstance(hits[0].chunk.metadata["document_id"], int)
