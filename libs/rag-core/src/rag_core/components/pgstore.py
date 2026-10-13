# SQL here is built from CONSTANT fragments (column lists, the access clause, the vector type
# from a validated Literal); every VALUE is a bound parameter. Hence S608 is checked and waived.
# ruff: noqa: S608
"""Postgres as vector store (pgvector) and keyword index (full-text search), on Step 11's tables
(Step 31). One database, one transaction, one permission model: often all a project needs.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core import filters as _filters
from rag_core.components.queues import ManifestEntry
from rag_core.registry import Container, register
from rag_core.similarity import VectorIndexParams, check_contract
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
        self._version: tuple[int, int] | None = None

    def pgvector_version(self, conn: Any) -> tuple[int, int]:
        """(major, minor) of the vector extension: iterative scans need 0.8, l1 and halfvec 0.7."""
        if self._version is None:
            row = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            major, minor = (int(x) for x in str(row[0] if row else "0.0").split(".")[:2])
            self._version = (major, minor)
        return self._version

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
    """Vector store and keyword index on the same database share one pool (keyed by the
    connection settings only: the vector store's index settings don't need a pool of their own)."""
    base = PgParams.model_validate(p.model_dump(include=set(PgParams.model_fields)))
    key = base.model_dump_json()
    if key not in _conns:
        _conns[key] = PgConnection(p)
    return _conns[key]


ACCESS_SQL = """d.deleted_at IS NULL AND d.collection_id = %(collection)s AND d.tenant = %(tenant)s
AND d.classification = ANY(%(classifications)s)
AND (d.classification = 'public' OR d.acl_groups && %(groups)s)"""


def _filters_sql(filters: Mapping[str, object] | None, params: dict[str, Any]) -> str:
    """The metadata filter (extension 01) as ' AND (…)', every value a bound parameter. It is
    appended to ACCESS_SQL: it can only narrow what the permission filter already allows."""
    return _filters.to_sql(filters, params)


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


# pgvector's operator per metric, and how its result becomes a "higher = better" score
PG_OPS: dict[str, tuple[str, str, str]] = {
    # metric: (distance operator, operator class suffix, score from the distance d)
    "cosine": ("<=>", "cosine_ops", "1 - ({d})"),
    "dot": ("<#>", "ip_ops", "-({d})"),  # <#> is the NEGATIVE inner product (smaller = closer)
    "l2": ("<->", "l2_ops", "1 / (1 + ({d}))"),
    "l1": ("<+>", "l1_ops", "1 / (1 + ({d}))"),  # pgvector >= 0.7
}
OUTER = """s.chunk_key, s.source_uri, s.chunk_index, s.content, s.embed_text, s.token_count, s.parent_key,
s.metadata, s.classification, s.acl_groups, s.tenant, s.id"""


class PgVectorParams(PgParams, VectorIndexParams):
    """The Postgres connection (PgParams) plus the vector index settings (extension 01)."""

    model_config = ConfigDict(extra="forbid")
    ef_search: int = Field(80, ge=10, le=1000)  # hnsw.ef_search per query
    lists: int = Field(
        100, ge=1
    )  # ivfflat: clusters (rows / 1000 up to 1M rows is the usual start)
    probes: int = Field(10, ge=1)  # ivfflat: clusters searched per query (recall/speed knob)
    # pgvector >= 0.8: keep scanning the index until k rows pass the filters (strict or
    # metadata filters otherwise return fewer than k); relaxed = slightly out of order, re-sorted
    iterative_scan: Literal["off", "relaxed_order", "strict_order"] = "relaxed_order"
    # binary: search 1-bit codes first (hamming distance, ~32x smaller index), then re-score the
    # best `oversample` x k candidates with the full vectors. halfvec (the default vector_type)
    # is already 16-bit scalar quantization.
    quantization: Literal["none", "binary"] = "none"
    oversample: float = Field(4.0, ge=1.0, le=50.0)
    # create the metric's index on first use (dev, tests: needs the table owner's rights). In
    # production a migration creates it: `rag index ddl --profile <p>` prints the statement
    create_index: bool = False

    @model_validator(mode="after")
    def _supported(self) -> PgVectorParams:
        if self.index_type == "ivfflat" and self.metric == "l1":
            raise ValueError(
                "pgvector's ivfflat has no l1 operator class: use index_type hnsw or flat"
            )
        if self.index_type == "ivfflat" and self.quantization != "none":
            raise ValueError("binary quantization is supported with index_type hnsw or flat")
        return self


def pg_index_ddl(p: PgVectorParams, concurrently: bool = True) -> str | None:
    """The CREATE INDEX statement for these settings; None for flat (no index: exact scan)."""
    if p.index_type == "flat":
        return None
    _, ops, _ = PG_OPS[p.metric]
    how = "CONCURRENTLY IF NOT EXISTS" if concurrently else "IF NOT EXISTS"
    if p.quantization == "binary":
        name = f"chunks_embedding_bq_hnsw_m{p.hnsw_m}_ef{p.ef_construction}"
        return (f"CREATE INDEX {how} {name} ON rag.chunks USING hnsw "
                f"((binary_quantize(embedding)::bit({p.dimensions})) bit_hamming_ops) "
                f"WITH (m = {p.hnsw_m}, ef_construction = {p.ef_construction})")  # fmt: skip
    opclass = f"{p.vector_type}_{ops}"
    if p.index_type == "ivfflat":
        return (f"CREATE INDEX {how} chunks_embedding_ivf_{ops.removesuffix('_ops')}_l{p.lists} "
                f"ON rag.chunks USING ivfflat (embedding {opclass}) WITH (lists = {p.lists})")  # fmt: skip
    return (f"CREATE INDEX {how} chunks_embedding_hnsw_{ops.removesuffix('_ops')}_m{p.hnsw_m}_ef{p.ef_construction} "
            f"ON rag.chunks USING hnsw (embedding {opclass}) WITH (m = {p.hnsw_m}, ef_construction = {p.ef_construction})")  # fmt: skip


class PgVectorStore:
    """pgvector search joined with the documents' access columns, in one SQL statement: a chunk
    the person may not see is never even returned by the database. The metric, index type and
    quantization are settings (extension 01); the collection records which metric it was built
    for, and a search with another one is refused (the embedding contract)."""

    def __init__(self, p: PgParams) -> None:
        self.p = (
            p if isinstance(p, PgVectorParams) else PgVectorParams.model_validate(p.model_dump())
        )
        self.db = _shared(self.p)
        self._checked = False

    def _vec(self, v: Sequence[float]) -> str:
        return "[" + ",".join(f"{x:.7g}" for x in v) + "]"

    def contract(self) -> dict[str, Any]:
        return {"metric": self.p.metric, "dimensions": self.p.dimensions}

    def _check(self, conn: Any, claim: bool = False) -> None:
        """The collection's recorded contract must match the profile. An EMPTY collection takes
        the profile's when written to (the first vector store to write decides); a used one never
        changes. Searches only compare (the API's database role can't change collections)."""
        if self._checked:
            return
        cid = self.db.collection_id(conn)
        row = conn.execute(
            "SELECT distance_metric, dimensions FROM rag.collections WHERE id = %s", (cid,)
        ).fetchone()
        options = {"index_type": self.p.index_type, "m": self.p.hnsw_m, "ef_construction": self.p.ef_construction,
                   "quantization": self.p.quantization, "vector_type": self.p.vector_type}  # fmt: skip
        used = conn.execute("""SELECT EXISTS (SELECT 1 FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
                               WHERE d.collection_id = %s AND c.embedding IS NOT NULL)""", (cid,)).fetchone()  # fmt: skip
        if row is not None and not (used and used[0]):
            if not claim:
                return  # empty: nothing to compare yet (checked again on the next search)
            conn.execute("UPDATE rag.collections SET distance_metric = %s, dimensions = %s, index_options = %s::jsonb "
                         "WHERE id = %s", (self.p.metric, self.p.dimensions, json.dumps(options), cid))  # fmt: skip
        elif row is not None:
            check_contract(f"pgvector collection {self.p.collection!r}", self.contract(),
                           {"metric": row[0], "dimensions": int(row[1])})  # fmt: skip
        if self.p.create_index and (ddl := pg_index_ddl(self.p, concurrently=False)):
            conn.execute(ddl)
        self._checked = True

    def index_ddl(self) -> str | None:
        p = self.p
        if (p.metric, p.index_type, p.hnsw_m, p.ef_construction, p.quantization, p.vector_type) == (
            "cosine", "hnsw", 16, 64, "none", "halfvec"):  # fmt: skip
            return "-- nothing to add: Step 11's migration created chunks_embedding_hnsw (halfvec_cosine_ops, m 16, ef_construction 64)"
        return pg_index_ddl(p)

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        if any(len(v) != self.p.dimensions for v in vectors):
            raise ValueError(
                f"vectors must have {self.p.dimensions} dimensions (the collection's contract)"
            )
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")  # ingestion writes for every tenant
            self._check(conn, claim=True)
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

    def _settings(self, conn: Any) -> None:
        """Per-query knobs, local to this transaction (a pooled connection never keeps them)."""
        version = self.db.pgvector_version(conn)
        if self.p.metric == "l1" and version < (0, 7):
            raise RuntimeError("the l1 metric needs pgvector >= 0.7")
        if self.p.index_type == "ivfflat":
            conn.execute(f"SET LOCAL ivfflat.probes = {int(self.p.probes)}")
            if version >= (0, 8) and self.p.iterative_scan != "off":
                conn.execute("SET LOCAL ivfflat.iterative_scan = relaxed_order")
        else:
            conn.execute(f"SET LOCAL hnsw.ef_search = {int(self.p.ef_search)}")
            if version >= (0, 8) and self.p.iterative_scan != "off":
                conn.execute(f"SET LOCAL hnsw.iterative_scan = {self.p.iterative_scan}")

    def search(self, vector: Sequence[float], principal: Principal, k: int,
                filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        vt, dims = self.p.vector_type, int(self.p.dimensions)
        op, _, score = PG_OPS[self.p.metric]
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")  # the contract is about the whole collection, every tenant
            self._check(conn)
            self._settings(conn)
            _tenant(conn, principal.tenant)  # the database itself shows only this tenant's rows
            params = _access_params(principal, self.db.collection_id(conn))
            params |= {"q": self._vec(vector), "k": k}
            where = f"c.embedding IS NOT NULL AND {ACCESS_SQL}{_filters_sql(filters, params)}"
            dist = f"c.embedding {op} %(q)s::{vt}"
            if self.p.quantization == "binary":
                # 1. nearest 1-bit codes (hamming), oversampled; 2. re-scored with the full vectors
                params["k_candidates"] = max(k, int(k * self.p.oversample))
                sql = f"""SELECT {OUTER}, {score.format(d=f"s.emb {op} %(q)s::{vt}")} AS score FROM (
                            SELECT {SELECT_CHUNK}, c.embedding AS emb
                            FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id WHERE {where}
                            ORDER BY binary_quantize(c.embedding)::bit({dims}) <~> binary_quantize(%(q)s::{vt})
                            LIMIT %(k_candidates)s) s
                          ORDER BY s.emb {op} %(q)s::{vt} LIMIT %(k)s"""
            else:
                # flat: "+ 0" makes the ORDER BY unusable for an index, so the scan is exact
                order = f"({dist}) + 0" if self.p.index_type == "flat" else dist
                sql = f"""SELECT {SELECT_CHUNK}, {score.format(d=dist)} AS score
                            FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
                            WHERE {where} ORDER BY {order} LIMIT %(k)s"""
            rows = conn.execute(sql, params).fetchall()
        hits = [
            ScoredChunk(_row_to_chunk(r[:-1]), float(r[-1]), {"dense": float(r[-1])}) for r in rows
        ]
        # relaxed iterative scans may return rows slightly out of order: best first, always
        return sorted(hits, key=lambda h: -h.score)

    def count(self) -> int:
        with self.db.pool.connection() as conn, conn.transaction():
            _tenant(conn, "*")
            row = conn.execute("""SELECT count(*) FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
                            WHERE d.collection_id = %s AND c.embedding IS NOT NULL""",
                            (self.db.collection_id(conn),)).fetchone()  # fmt: skip
        return int(row[0]) if row else 0


@register("vector_store", "pgvector", params=PgVectorParams, requires=("postgres",),
            summary="Postgres + pgvector on Step 11's tables; metric cosine/dot/l2/l1, hnsw/ivfflat/flat, binary quantization; permissions joined in SQL")  # fmt: skip
def _pgvector(p: PgVectorParams, c: Container) -> PgVectorStore:
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
                filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
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
