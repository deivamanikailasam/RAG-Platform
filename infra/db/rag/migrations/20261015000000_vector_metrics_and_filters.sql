-- migrate:up
-- Extension 01: switchable similarity metrics and general metadata filters.

-- 1. The embedding contract gains the distance metric and the vector index settings. A collection
--    is searched with the metric it was built for: rag-core's pgvector store compares its
--    `metric` setting with this column and refuses to search on a mismatch (cosine scores on a
--    collection tuned for inner product are silently wrong, never an error, so we make it one).
ALTER TABLE rag.collections
    ADD COLUMN distance_metric text  NOT NULL DEFAULT 'cosine'
        CHECK (distance_metric IN ('cosine', 'dot', 'l2', 'l1')),
    ADD COLUMN index_options   jsonb NOT NULL DEFAULT '{}'::jsonb;   -- {"index_type": "hnsw", "m": 16, …}

-- 2. Dates in chunk metadata are compared as timestamps ("updated after 2025-01-01"). A value
--    that isn't a valid date is simply no match (NULL), never an error that fails the search.
--    STABLE, not IMMUTABLE: a date without a time zone uses the session's (UTC in our containers).
CREATE FUNCTION rag.safe_timestamptz(value text) RETURNS timestamptz
    LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
BEGIN
    RETURN value::timestamptz;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$;

-- The HNSW index of Step 11 uses halfvec_cosine_ops. A collection that uses another metric needs
-- an index with that metric's operator class, or its searches fall back to an exact scan
-- (correct, but slow on large collections). It is created per project, by a migration of its own:
-- `rag index ddl --profile <p>` prints the exact statement for the profile's settings, e.g.
--   CREATE INDEX CONCURRENTLY chunks_embedding_hnsw_ip ON rag.chunks
--       USING hnsw (embedding halfvec_ip_ops) WITH (m = 16, ef_construction = 64);
-- (one extra index per metric in use: every index costs disk space and slows down every write).

-- migrate:down
DROP FUNCTION rag.safe_timestamptz(text);
ALTER TABLE rag.collections DROP COLUMN index_options, DROP COLUMN distance_metric;
