-- migrate:up
-- Extension 03: GraphRAG's entity graph in Postgres (`graph_store: postgres`), so it survives a
-- restart and every API replica sees the same graph. Until now the graph lived in memory only.

-- 1. The chunks the graph points at, with the SAME access columns as rag.documents: graph
--    search filters by them in SQL, exactly like vector and keyword search. A copy, not a join
--    to rag.chunks, so a graph can be built over any store (Qdrant, OpenSearch) too.
CREATE TABLE rag.graph_chunks (
    collection     text        NOT NULL,
    chunk_key      text        NOT NULL,           -- the chunk id every store agrees on (Step 31)
    document_uri   text        NOT NULL,
    chunk_index    int         NOT NULL,
    content        text        NOT NULL,
    metadata       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    classification text        NOT NULL CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    acl_groups     text[]      NOT NULL DEFAULT '{}',
    tenant         text        NOT NULL DEFAULT 'default',
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection, chunk_key)
);
CREATE INDEX graph_chunks_document ON rag.graph_chunks (collection, document_uri);

-- 2. Which entities each chunk mentions (normalised lower-case names) and their type.
CREATE TABLE rag.graph_mentions (
    collection  text NOT NULL,
    chunk_key   text NOT NULL,
    entity      text NOT NULL,
    entity_type text NOT NULL DEFAULT '',
    PRIMARY KEY (collection, chunk_key, entity),
    FOREIGN KEY (collection, chunk_key) REFERENCES rag.graph_chunks (collection, chunk_key) ON DELETE CASCADE
);
CREATE INDEX graph_mentions_entity ON rag.graph_mentions (collection, entity);

-- 3. Typed relations between entities, as stated in one chunk (the `llm-entities` enricher).
CREATE TABLE rag.graph_relations (
    collection text NOT NULL,
    chunk_key  text NOT NULL,
    source     text NOT NULL,
    relation   text NOT NULL,
    target     text NOT NULL,
    PRIMARY KEY (collection, chunk_key, source, relation, target),
    FOREIGN KEY (collection, chunk_key) REFERENCES rag.graph_chunks (collection, chunk_key) ON DELETE CASCADE
);

-- 4. Row-level security, as Step 36 set up for documents and chunks: each transaction sees only
--    the tenant it set (SELECT set_config('rag.tenant', '<tenant>', true)); '*' is ingestion.
ALTER TABLE rag.graph_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rag.graph_chunks
    USING (current_setting('rag.tenant', true) IN (tenant, '*'))
    WITH CHECK (current_setting('rag.tenant', true) IN (tenant, '*'));

ALTER TABLE rag.graph_mentions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rag.graph_mentions
    USING (EXISTS (SELECT 1 FROM rag.graph_chunks g WHERE g.collection = graph_mentions.collection
                   AND g.chunk_key = graph_mentions.chunk_key))
    WITH CHECK (EXISTS (SELECT 1 FROM rag.graph_chunks g WHERE g.collection = graph_mentions.collection
                        AND g.chunk_key = graph_mentions.chunk_key));

ALTER TABLE rag.graph_relations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rag.graph_relations
    USING (EXISTS (SELECT 1 FROM rag.graph_chunks g WHERE g.collection = graph_relations.collection
                   AND g.chunk_key = graph_relations.chunk_key))
    WITH CHECK (EXISTS (SELECT 1 FROM rag.graph_chunks g WHERE g.collection = graph_relations.collection
                        AND g.chunk_key = graph_relations.chunk_key));

-- migrate:down
DROP TABLE rag.graph_relations;
DROP TABLE rag.graph_mentions;
DROP TABLE rag.graph_chunks;
