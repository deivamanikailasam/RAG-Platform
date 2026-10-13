-- migrate:up
-- Step 36: what the data lifecycle and multi-tenancy need.

-- 1. The manifest remembers each source's access and metadata, so retention, erasure and a
--    re-index can rebuild it from the original without asking the source system again.
ALTER TABLE rag.ingest_manifest
    ADD COLUMN access          jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

-- 2. Row-level security: defence in depth for tenants. Every query already filters by tenant
--    (Step 31); with RLS, a query that FORGETS to still sees only the tenant set for its
--    transaction (SELECT set_config('rag.tenant', '<tenant>', true)). Nothing set = no rows.
--    '*' is for ingestion and maintenance, which work across tenants. The table owner
--    (rag_migrator) isn't subject to it, so migrations keep working; rag_app and rag_readonly are.
ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rag.documents
    USING (current_setting('rag.tenant', true) IN (tenant, '*'))
    WITH CHECK (current_setting('rag.tenant', true) IN (tenant, '*'));

ALTER TABLE rag.chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rag.chunks
    USING (EXISTS (SELECT 1 FROM rag.documents d WHERE d.id = document_id))   -- documents' RLS applies inside
    WITH CHECK (EXISTS (SELECT 1 FROM rag.documents d WHERE d.id = document_id));

-- migrate:down
DROP POLICY tenant_isolation ON rag.chunks;
ALTER TABLE rag.chunks DISABLE ROW LEVEL SECURITY;
DROP POLICY tenant_isolation ON rag.documents;
ALTER TABLE rag.documents DISABLE ROW LEVEL SECURITY;
ALTER TABLE rag.ingest_manifest DROP COLUMN source_metadata, DROP COLUMN access;
