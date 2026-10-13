-- migrate:up

-- A collection = one index built under ONE embedding contract (Step 8)
CREATE TABLE rag.collections (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                text        NOT NULL UNIQUE,
    embedding_model     text        NOT NULL,
    embedding_revision  text        NOT NULL,
    dimensions          int         NOT NULL CHECK (dimensions BETWEEN 32 AND 4000),
    normalized          boolean     NOT NULL DEFAULT true,
    query_instruction   text        NOT NULL,
    max_chunk_tokens    int         NOT NULL CHECK (max_chunk_tokens > 0),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rag.documents (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    collection_id   bigint      NOT NULL REFERENCES rag.collections (id) ON DELETE CASCADE,
    source_uri      text        NOT NULL,                -- where it came from
    title           text,
    content_sha256  text        NOT NULL,                -- detect unchanged documents (dedup, Step 31)
    acl_groups      text[]      NOT NULL DEFAULT '{}',   -- groups allowed to see it (enforced Step 18)
    classification  text        NOT NULL DEFAULT 'internal'
                    CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    metadata        jsonb       NOT NULL DEFAULT '{}',
    version         int         NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,                         -- soft delete; hard delete flows come in Step 36
    UNIQUE (collection_id, source_uri, version)
);

CREATE TABLE rag.chunks (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  bigint        NOT NULL REFERENCES rag.documents (id) ON DELETE CASCADE,
    chunk_index  int           NOT NULL,
    content      text          NOT NULL,
    token_count  int           NOT NULL CHECK (token_count > 0),
    embedding    halfvec(1024) NOT NULL,                 -- half precision: half the storage of vector(1024)
    content_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata     jsonb         NOT NULL DEFAULT '{}',
    created_at   timestamptz   NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

-- Vector index: cosine distance on half-precision vectors
CREATE INDEX chunks_embedding_hnsw ON rag.chunks
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);
-- Keyword index for hybrid search (Step 32)
CREATE INDEX chunks_content_tsv ON rag.chunks USING gin (content_tsv);
-- Filters
CREATE INDEX chunks_document_id   ON rag.chunks USING btree (document_id);
CREATE INDEX documents_acl_groups ON rag.documents USING gin (acl_groups);
CREATE INDEX documents_metadata   ON rag.documents USING gin (metadata jsonb_path_ops);
CREATE INDEX documents_live       ON rag.documents (collection_id) WHERE deleted_at IS NULL;

-- migrate:down
DROP TABLE rag.chunks;
DROP TABLE rag.documents;
DROP TABLE rag.collections;
