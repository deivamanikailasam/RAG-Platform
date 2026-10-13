# Runbook: RagSearchErrorBudgetFastBurn (critical) / RagSearchErrorBudgetSlowBurn (warning)

**What it means:** searches are failing fast enough to spend the search error budget early.
The objective is 99% of searches succeeding over 28 days, so 1% may fail.
- **Fast burn (page):** more than 14.4% of searches failed over the last hour AND the last 5 minutes.
  At this rate the whole 28-day budget is gone in about 2 days. Users are hurting now.
- **Slow burn (ticket):** more than 6% failed over the last 6 hours AND the last 30 minutes.
  The budget is gone in about 5 days. Fix it during working hours.

A "failed" search is one that raised an error or returned 5xx (`outcome="error"`). Denied requests
(401/403) are not searches and do not count.

**Check first (5 minutes)**
1. Grafana → *RAG platform · overview* → "Searches per second by outcome": when did `error` start rising?
   Is it all searches, or a share of them?
2. Grafana → "Scrape targets": is a dependency down? `opa`, `postgres-rag` and `keycloak` matter most.
3. `just ps`: is any container restarting or unhealthy?
4. The errors themselves: `docker compose -f infra/compose/compose.yaml logs --since 30m rag-api | grep -E '"level": ?"ERROR"'`.
   Each line carries a `trace_id`; from Step 21 you can open the trace in Grafana.

**Likely causes**
- OPA down or unreachable: rag-api fails closed with 503 ("Policy engine unavailable").
- rag-db down, out of connections, or a slow query hitting `statement_timeout` (30 s for `rag_app`).
- The embedder (TEI, native on the Mac) or the LiteLLM gateway is down: the query can't be embedded.
- Keycloak's signing keys can't be fetched (503 "Identity provider unavailable").
- A bad deploy of rag-api.

**Fix**
- Restart or repair the failing dependency (`just up`, `just models-health`, `just health`).
- Roll back the last rag-api change if the errors started with a deploy (`git revert`, `just api-up`).

**Close**
- The 5-minute error ratio falls below the threshold; the fast-burn alert resolves within minutes,
  the slow-burn one within about 30 minutes.
- Note how much budget was spent (the "Error budget left" panel). If it is below 25%, prioritise
  reliability work over features until it recovers.
