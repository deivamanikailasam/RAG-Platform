# Runbook: RagSearchSlow (warning)

**What it means:** the 95th-percentile search time has been above the 2-second objective for 10 minutes.
One search in twenty is taking longer than users were promised. Searches still work.

**Check first (5 minutes)**
1. Grafana → *RAG platform · overview* → "Search latency percentiles": is only p95/p99 high, or the median too?
   A high median means everything is slow; only the tail means some searches are.
2. Grafana → "HTTP p95 by route": is only `/v1/search` slow, or every endpoint?
3. Traffic: "Searches per second". A sudden jump can saturate the embedder or the database.
4. Database: `just db-psql`, then
   `SELECT calls, mean_exec_time, query FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 5;`
5. The embedder: `just health`; TEI metrics are scraped as job `tei`.

**Likely causes**
- The embedder (TEI) is saturated or the Mac is under memory pressure (models swapping).
- A missing or unused index: the HNSW index on `rag.chunks` was dropped or a filter stopped using it.
- OPA slow to answer (large data or a policy change with an expensive rule).
- Noisy neighbours: other containers using the CPU (`docker stats`).

**Fix**
- Reduce load or restart the saturated component; check `just models-health`.
- Restore the index or roll back the query/policy change.
- If the objective is consistently wrong for real usage, revisit it (Step 37), don't just mute the alert.

**Close**
- p95 back under 2 s; the alert resolves after the 5-minute window recovers.

> Remember the bucket pitfall (Step 20): if p95 reads exactly ~4.75 s while searches feel fast, check
> that `rag_search_duration_seconds_bucket` has edges in seconds (0.025 … 30), not the SDK's millisecond defaults.
