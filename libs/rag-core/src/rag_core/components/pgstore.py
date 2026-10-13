# SQL here is built from CONSTANT fragments (column lists, the access clause, the vector type
# from a validated Literal); every VALUE is a bound parameter. Hence S608 is checked and waived.
# ruff: noqa: S608
"""Postgres as vector store (pgvector) and keyword index (full-text search), on Step 11's tables
(Step 31). One database, one transaction, one permission model: often all a project needs.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core.components.queues import ManifestEntry
from rag_core.registry import Container, register
from rag_core.types import Access, Chunk, Principal, ScoredChunk


class PgParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The connection: a DSN from an env var (dev, tests) OR host + an OpenBao credentials file (Step 28)
    dsn_env: str | None = "RAG_DB_DSN"
    host: str = "rag-db"
    port: int = 5432
    dbname: str = "rag"
    credentials_file: str | None = None  # /run/bao/rag_db.json
    collection: str = "default"
    embedding_model: str = "embedder"
    dimensions: int = Field(1024, ge=16)
    vector_type: Literal["halfvec", "vector"] = "halfvec"  # halfvec needs pgvector >= 0.7
    query_instruction: str = ""
    max_chunk_tokens: int = 512
    ef_search: int = Field(80, ge=10)  # HNSW recall/speed knob per query
    text_search_config: str = "english"
    pool_size: int = Field(4, ge=1)


class PgConnection:
    """A small pool, credentials read per connection (rotation-safe, Step 28)."""

    def __init__(self, p: PgParams) -> None:
        from psycopg_pool import ConnectionPool

        from rag_common.secrets import CredentialsFile

        self.p = p
        dsn = os.environ.get(p.dsn_env, "") if p.dsn_env else ""
        if dsn:
            self.pool = ConnectionPool(dsn, min_size=0, max_size=p.pool_size, open=True,
                                check=ConnectionPool.check_connection)  # fmt: skip
        else:
            creds = (
                CredentialsFile(__import__("pathlib").Path(p.credentials_file))
                if p.credentials_file
                else None
            )

            def kwargs() -> dict[str, Any]:
                if creds is None:
                    raise RuntimeError(
                        "set dsn_env or credentials_file for the Postgres components"
                    )
                user, password = creds()
                return {"user": user, "password": password}

            from psycopg.conninfo import make_conninfo

            self.pool = ConnectionPool(make_conninfo(host=p.host, port=p.port, dbname=p.dbname), kwargs=kwargs,
                                min_size=0, max_size=p.pool_size, open=True, check=ConnectionPool.check_connection)  # fmt: skip
        self._collection_id: int | None = None

    def collection_id(self, conn: Any) -> int:
        if self._collection_id is None:
            row = conn.execute(
                "SELECT id FROM rag.collections WHERE name = %s", (self.p.collection,)
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """INSERT INTO rag.collections (name, embedding_model, embedding_revision, dimensions,
                        query_instruction, max_chunk_tokens) VALUES (%s, %s, 'unknown', %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id""",
                    (self.p.collection, self.p.embedding_model, self.p.dimensions, self.p.query_instruction,
                    self.p.max_chunk_tokens),
                ).fetchone()  # fmt: skip
            if row is None:  # pragma: no cover - INSERT … RETURNING always returns the row
                raise RuntimeError("could not create the collection")
            self._collection_id = int(row[0])
        return self._collection_id


_conns: dict[str, PgConnection] = {}


def _tenant(conn: Any, tenant: str) -> None:
    """Row-level security (Step 36 migration): the database only shows rows of this tenant ('*' for
    ingestion and maintenance, which work across tenants). Local to the current transaction."""
    conn.execute("SELECT set_config('rag.tenant', %s, true)", (tenant,))


def _shared(p: PgParams) -> PgConnection:
    """Vector store and keyword index on the same database share one pool."""
    key = p.model_dump_json()
    if key not in _conns:
        _conns[key] = PgConnection(p)
    return _conns[key]


ACCESS_SQL = """d.deleted_at IS NULL AND d.collection_id = %(collection)s AND d.tenant = %(tenant)s
AND d.classification = ANY(%(classifications)s)
AND (d.classification = 'public' OR d.acl_groups && %(groups)s)"""


def _filters_sql(filters: dict[str, object] | None, params: dict[str, Any]) -> str:
    """Metadata filters as parameters (never string-built values): key = value or key in (…)."""
    parts = []
    for i, (key, want) in enumerate((filters or {}).items()):
        params[f"fk{i}"] = key
        if isinstance(want, list | tuple | set):
            params[f"fv{i}"] = [str(w) for w in want]
            parts.append(f"c.metadata ->> %(fk{i})s = ANY(%(fv{i})s)")
        else:
            params[f"fv{i}"] = json.dumps({key: want})
            parts.append(f"c.metadata @> %(fv{i})s::jsonb")
    return "".join(f" AND {p}" for p in parts)


def _access_params(principal: Principal, collection: int) -> dict[str, Any]:
    return {"collection": collection, "tenant": principal.tenant, "classifications": list(principal.classifications),
            "groups": list(principal.groups)}  # fmt: skip


def _row_to_chunk(row: Any) -> Chunk:
    key, uri, idx, text, embed_text, tokens, parent, meta, cls, groups, tenant, doc_id = row
    # document_id: Step 11's numeric id, which rag-api's policy check and audit events use
    return Chunk(id=key, document_uri=uri, index=idx, text=text, token_count=tokens,
                access=Access(cls, tuple(groups), tenant), embed_text=embed_text or "",
                parent_id=parent, metadata={**(meta or {}), "document_id": doc_id})  # fmt: skip


SELECT_CHUNK = """c.chunk_key, d.source_uri, c.chunk_index, c.content, c.embed_text, c.token_count,
c.parent_key, c.metadata, d.classification, d.acl_groups, d.tenant, d.id"""


def _write_rows(conn: Any, collection: int, chunks: Sequence[Chunk],
                vectors: Sequence[Sequence[float]] | None, model: str, vector_type: str) -> None:  # fmt: skip
    """Upsert the documents rows, then the chunks. Access lives on the document (Step 11)."""
    docs: dict[str, Chunk] = {}
    for c in chunks:
        docs.setdefault(c.document_uri, c)
    doc_ids: dict[str, int] = {}
    for uri, c in docs.items():
        row = conn.execute(
            """SELECT id FROM rag.documents WHERE collection_id = %s AND source_uri = %s AND deleted_at IS NULL""",
            (collection, uri)).fetchone()  # fmt: skip
        values = (str(c.metadata.get("title", "")), str(c.metadata.get("doc_sha256", "")), list(c.access.groups),
                    c.access.classification, c.access.tenant)  # fmt: skip
        if row is None:
            row = conn.execute(
                """INSERT INTO rag.documents (collection_id, source_uri, title, content_sha256, acl_groups,
                    classification, tenant) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (collection, uri, *values)).fetchone()  # fmt: skip
        else:
            conn.execute("""UPDATE rag.documents SET title = %s, content_sha256 = %s, acl_groups = %s,
                            classification = %s, tenant = %s, updated_at = now() WHERE id = %s""",
                        (*values, row[0]))  # fmt: skip
        doc_ids[uri] = int(row[0])
    for i, c in enumerate(chunks):
        meta = json.dumps(
            {k: v for k, v in c.metadata.items() if k != "parent_text"}
            | ({"parent_text": c.metadata["parent_text"]} if "parent_text" in c.metadata else {}),
            default=str,
        )
        base = (doc_ids[c.document_uri], c.index, c.text, c.embed_text or None, max(1, c.token_count), meta, c.id,
                c.parent_id)  # fmt: skip
        if vectors is None:  # keyword-only: leave any existing embedding alone
            conn.execute(
                """INSERT INTO rag.chunks (document_id, chunk_index, content, embed_text, token_count, metadata,
                    chunk_key, parent_key) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (document_id, chunk_key) DO UPDATE SET content = EXCLUDED.content, embed_text = EXCLUDED.embed_text,
                    metadata = EXCLUDED.metadata""", base)  # fmt: skip
        else:
            vec = "[" + ",".join(f"{x:.7g}" for x in vectors[i]) + "]"
            conn.execute(
                f"""INSERT INTO rag.chunks (document_id, chunk_index, content, embed_text, token_count, metadata,
                    chunk_key, parent_key, embedding, embedding_model)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::{vector_type}, %s)
                    ON CONFLICT (document_id, chunk_key) DO UPDATE SET content = EXCLUDED.content, embed_text = EXCLUDED.embed_text,
                    metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding,
                    embedding_model = EXCLUDED.embedding_model""", (*base, vec, model))  # fmt: skip


def _delete(conn: Any, collection: int, uri: str) -> int:
    row = conn.execute(
        """WITH d AS (DELETE FROM rag.documents WHERE collection_id = %s AND source_uri = %s RETURNING id)
            SELECT count(*) FROM rag.chunks WHERE document_id IN (SELECT id FROM d)""", (collection, uri)).fetchone()  # fmt: skip
    return int(row[0]) if row else 0


def _update_access(db: PgConnection, document_uri: str, access: Access) -> int:
    """New permissions on the document row: every chunk follows at once (they join to it)."""
    with db.pool.connection() as conn, conn.transaction():
        _tenant(conn, "*")
        row = conn.execute("""WITH d AS (UPDATE rag.documents SET classification = %s, acl_groups = %s, tenant = %s,
                                updated_at = now() WHERE collection_id = %s AND source_uri = %s RETURNING id)
                                SELECT count(*) FROM rag.chunks WHERE document_id IN (SELECT id FROM d)""",
                            (access.classification, list(access.groups), access.tenant, db.collection_id(conn),
                             document_uri)).fetchone()  # fmt: skip
    return int(row[0]) if row else 0


class PgVectorStore:
    """pgvector HNSW search joined with the documents' access columns, in one SQL statement:
    a chunk the person may not see is never even returned by the database."""

    def __init__(self, p: PgParams) -> None:
        self.p, self.db = p, _shared(p)

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        if any(len(v) != self.p.dimensions for v in vectors):
            raise ValueError(
                f"vectors must have {self.p.dimensions} dimensions (the collection's contract)"
            )
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")  # ingestion writes for every tenant
            _write_rows(
                conn,
                self.db.collection_id(conn),
                chunks,
                vectors,
                self.p.embedding_model,
                self.p.vector_type,
            )

    def delete_document(self, document_uri: str) -> int:
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")
            return _delete(conn, self.db.collection_id(conn), document_uri)

    def update_access(self, document_uri: str, access: Access) -> int:
        return _update_access(self.db, document_uri, access)

    def search(self, vector: Sequence[float], principal: Principal, k: int,
                filters: dict[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        vt, ops = self.p.vector_type, "<=>"
        with self.db.pool.connection() as conn, conn.transaction():
            conn.execute(f"SET LOCAL hnsw.ef_search = {int(self.p.ef_search)}")
            _tenant(conn, principal.tenant)  # the database itself shows only this tenant's rows
            params = _access_params(principal, self.db.collection_id(conn))
            params |= {"q": "[" + ",".join(f"{x:.7g}" for x in vector) + "]", "k": k}
            sql = f"""SELECT {SELECT_CHUNK}, 1 - (c.embedding {ops} %(q)s::{vt}) AS score
                        FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
                        WHERE c.embedding IS NOT NULL AND {ACCESS_SQL}{_filters_sql(filters, params)}
                        ORDER BY c.embedding {ops} %(q)s::{vt} LIMIT %(k)s"""
            rows = conn.execute(sql, params).fetchall()
        return [
            ScoredChunk(_row_to_chunk(r[:-1]), float(r[-1]), {"dense": float(r[-1])}) for r in rows
        ]

    def count(self) -> int:
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")
            row = conn.execute("""SELECT count(*) FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
                            WHERE d.collection_id = %s AND c.embedding IS NOT NULL""",
                            (self.db.collection_id(conn),)).fetchone()  # fmt: skip
        return int(row[0]) if row else 0


@register("vector_store", "pgvector", params=PgParams, requires=("postgres",),
            summary="Postgres + pgvector HNSW on Step 11's tables; permissions joined in SQL")  # fmt: skip
def _pgvector(p: PgParams, c: Container) -> PgVectorStore:
    return PgVectorStore(p)


class PgFullTextIndex:
    """Postgres full-text search: stemming, stop words, websearch syntax ("leave -sick"), ranked
    with ts_rank_cd. No extra service; weaker than OpenSearch on synonyms and analyzers."""

    def __init__(self, p: PgParams) -> None:
        self.p, self.db = p, _shared(p)

    def index(self, chunks: Sequence[Chunk]) -> None:
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")  # ingestion writes for every tenant
            _write_rows(
                conn,
                self.db.collection_id(conn),
                chunks,
                None,
                self.p.embedding_model,
                self.p.vector_type,
            )

    def delete_document(self, document_uri: str) -> int:
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")
            return _delete(conn, self.db.collection_id(conn), document_uri)

    def update_access(self, document_uri: str, access: Access) -> int:
        return _update_access(self.db, document_uri, access)

    def search(self, text: str, principal: Principal, k: int,
                filters: dict[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, principal.tenant)  # the database itself shows only this tenant's rows
            params = _access_params(principal, self.db.collection_id(conn)) | {
                "q": text,
                "k": k,
                "cfg": self.p.text_search_config,
            }
            # OR the words: plain websearch_to_tsquery ANDs them, which misses answers to long questions
            sql = f"""WITH q AS (SELECT to_tsquery(%(cfg)s::regconfig, coalesce(nullif(array_to_string(array(
                        SELECT quote_literal(l) FROM unnest(tsvector_to_array(to_tsvector(%(cfg)s::regconfig, %(q)s))) l),
                        ' | '), ''), 'xxnomatchxx')) AS tsq)
                        SELECT {SELECT_CHUNK}, ts_rank_cd(c.content_tsv, q.tsq) AS score
                        FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id, q
                        WHERE c.content_tsv @@ q.tsq AND {ACCESS_SQL}{_filters_sql(filters, params)}
                        ORDER BY score DESC LIMIT %(k)s"""
            rows = conn.execute(sql, params).fetchall()
        return [
            ScoredChunk(_row_to_chunk(r[:-1]), float(r[-1]), {"sparse": float(r[-1])}) for r in rows
        ]

    def search_all(self, text: str, k: int) -> list[ScoredChunk]:
        """Every tenant and group: for the erasure job only (Step 36), never for people."""
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")
            params = {"collection": self.db.collection_id(conn), "q": text, "k": k,
                      "cfg": self.p.text_search_config}  # fmt: skip
            sql = f"""SELECT {SELECT_CHUNK}, ts_rank_cd(c.content_tsv, q.tsq) AS score
                        FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id,
                        websearch_to_tsquery(%(cfg)s::regconfig, %(q)s) q(tsq)
                        WHERE c.content_tsv @@ q.tsq AND d.deleted_at IS NULL AND d.collection_id = %(collection)s
                        ORDER BY score DESC LIMIT %(k)s"""
            rows = conn.execute(sql, params).fetchall()
        return [
            ScoredChunk(_row_to_chunk(r[:-1]), float(r[-1]), {"sparse": float(r[-1])}) for r in rows
        ]


@register("keyword_index", "postgres-fts", params=PgParams, requires=("postgres",),
            summary="Postgres full-text search on the same tables (no extra service)")  # fmt: skip
def _pgfts(p: PgParams, c: Container) -> PgFullTextIndex:
    return PgFullTextIndex(p)


class PgManifest:
    """rag.ingest_manifest (Step 31 migration): what was ingested with which pipeline. Survives
    restarts and is shared by every worker. Same connection settings as the stores."""

    def __init__(self, p: PgParams) -> None:
        self.p, self.db = p, _shared(p)

    _COLS = ("source_uri, content_sha256, pipeline_hash, chunk_count, status, detail, extract(epoch FROM updated_at), "
             "access, source_metadata")  # fmt: skip

    def get(self, uri: str) -> ManifestEntry | None:
        with self.db.pool.connection() as conn:
            row = conn.execute(f"SELECT {self._COLS} FROM rag.ingest_manifest WHERE collection = %s AND source_uri = %s",
                            (self.p.collection, uri)).fetchone()  # fmt: skip
        return _entry(row) if row else None

    def put(self, e: ManifestEntry) -> None:
        with self.db.pool.connection() as conn:
            # updated_at comes from the entry: an access change (Step 36) keeps the ingestion time,
            # which is what retention measures from
            conn.execute("""INSERT INTO rag.ingest_manifest (collection, source_uri, content_sha256, pipeline_hash,
                            chunk_count, status, detail, updated_at, access, source_metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, to_timestamp(%s), %s::jsonb, %s::jsonb)
                            ON CONFLICT (collection, source_uri) DO UPDATE SET content_sha256 = EXCLUDED.content_sha256,
                            pipeline_hash = EXCLUDED.pipeline_hash, chunk_count = EXCLUDED.chunk_count,
                            status = EXCLUDED.status, detail = EXCLUDED.detail, updated_at = EXCLUDED.updated_at,
                            access = EXCLUDED.access, source_metadata = EXCLUDED.source_metadata""",
                        (self.p.collection, e.source_uri, e.content_sha256, e.pipeline_hash, e.chunk_count, e.status,
                            e.detail, e.updated_at, json.dumps(e.access), json.dumps(e.metadata, default=str)))  # fmt: skip

    def delete(self, uri: str) -> None:
        with self.db.pool.connection() as conn:
            conn.execute(
                "DELETE FROM rag.ingest_manifest WHERE collection = %s AND source_uri = %s",
                (self.p.collection, uri),
            )

    def all(self) -> list[ManifestEntry]:
        with self.db.pool.connection() as conn:
            rows = conn.execute(f"SELECT {self._COLS} FROM rag.ingest_manifest WHERE collection = %s",
                                (self.p.collection,)).fetchall()  # fmt: skip
        return [_entry(r) for r in rows]


def _entry(r: Any) -> ManifestEntry:
    return ManifestEntry(source_uri=r[0], content_sha256=r[1], pipeline_hash=r[2], chunk_count=int(r[3]),
                        status=r[4], detail=r[5], updated_at=float(r[6]), access=dict(r[7] or {}),
                        metadata=dict(r[8] or {}))  # fmt: skip


@register("manifest", "postgres", params=PgParams, requires=("postgres",),
            summary="what was ingested, in rag.ingest_manifest (shared, durable)")  # fmt: skip
def _pgman(p: PgParams, c: Container) -> PgManifest:
    return PgManifest(p)
