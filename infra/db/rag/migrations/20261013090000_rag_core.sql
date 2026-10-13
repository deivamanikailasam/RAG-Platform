-- migrate:up
-- Step 31: what the RAG core (libs/rag-core) needs on top of Step 11's tables.

-- Tenants: every document belongs to one; every query is limited to one (Step 18 decides which)
ALTER TABLE rag.documents ADD COLUMN tenant text NOT NULL DEFAULT 'default';
CREATE INDEX documents_tenant ON rag.documents (tenant) WHERE deleted_at IS NULL;

-- A stable chunk key (same document + position + text = same key): re-ingesting is idempotent,
-- and Qdrant/OpenSearch copies use the same key, so all stores agree on what a chunk is.
-- Unique per document: the same source may be in two collections (e.g. during a re-index).
ALTER TABLE rag.chunks
    ADD COLUMN chunk_key       text,
    ADD COLUMN embed_text      text,    -- what was embedded (text + title/section/context), Step 31
    ADD COLUMN parent_key      text,    -- parent-child chunking: the larger passage
    ADD COLUMN embedding_model text;    -- vectors of different models must never be compared
UPDATE rag.chunks SET chunk_key = id::text WHERE chunk_key IS NULL;
ALTER TABLE rag.chunks ALTER COLUMN chunk_key SET NOT NULL;
ALTER TABLE rag.chunks ADD CONSTRAINT chunks_chunk_key UNIQUE (document_id, chunk_key);

-- Keyword-only stores (postgres-fts without pgvector search) write rows without a vector
ALTER TABLE rag.chunks ALTER COLUMN embedding DROP NOT NULL;

-- Full-text search over what was embedded when there is one (title and section help keywords too)
ALTER TABLE rag.chunks DROP COLUMN content_tsv;
ALTER TABLE rag.chunks ADD COLUMN content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(embed_text, content))) STORED;
CREATE INDEX chunks_content_tsv ON rag.chunks USING gin (content_tsv);

-- Which source was ingested with which pipeline: unchanged sources are skipped (Step 31)
CREATE TABLE rag.ingest_manifest (
    collection      text        NOT NULL,
    source_uri      text        NOT NULL,
    content_sha256  text        NOT NULL,
    pipeline_hash   text        NOT NULL,   -- chunker + enrichers + embedder settings
    chunk_count     int         NOT NULL,
    status          text        NOT NULL CHECK (status IN ('indexed', 'failed', 'skipped')),
    detail          text        NOT NULL DEFAULT '',
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection, source_uri)
);

-- migrate:down
DROP TABLE rag.ingest_manifest;
ALTER TABLE rag.chunks DROP COLUMN content_tsv;
ALTER TABLE rag.chunks ADD COLUMN content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
CREATE INDEX chunks_content_tsv ON rag.chunks USING gin (content_tsv);
DELETE FROM rag.chunks WHERE embedding IS NULL;
ALTER TABLE rag.chunks ALTER COLUMN embedding SET NOT NULL;
ALTER TABLE rag.chunks DROP CONSTRAINT chunks_chunk_key;
ALTER TABLE rag.chunks DROP COLUMN chunk_key, DROP COLUMN embed_text, DROP COLUMN parent_key, DROP COLUMN embedding_model;
DROP INDEX rag.documents_tenant;
ALTER TABLE rag.documents DROP COLUMN tenant;
