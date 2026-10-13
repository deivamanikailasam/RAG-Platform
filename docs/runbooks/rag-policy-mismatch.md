# Runbook: RagPolicyQueryMismatch (critical)

**What it means:** a search query returned a document that the policy's post-check then refused.
The post-check worked, so nothing was shown to the user, but the SQL filter and the OPA policy disagree.
Until fixed, some users may get fewer results than they should, and one safety layer is gone.

**Check first (5 minutes)**
1. Grafana → *RAG platform · overview* → "Policy/query mismatches": when did it start?
2. Did a policy change just merge? `git log --since="2 hours ago" -- policies/`
3. Did a migration or the search query change? `git log --since="2 hours ago" -- services/rag-api infra/db`
4. Find the request: `docker compose -f infra/compose/compose.yaml logs rag-api | grep "query/policy mismatch"`.
   The log line has the `trace_id`; the dropped document ids and the user's `sub` are in the message.

**Likely causes**
- A new classification or group mapping in `policies/rag/authz/data.json` not reflected in the query.
- A document whose `classification` or `acl_groups` were changed outside the normal ingestion path.

**Fix**
- Revert the offending change (policy or query), or correct the document's access fields.
- Add a test reproducing it: a Rego test in `authz_test.rego` and/or a case in `test_opa_live.py`.

**Close**
- The counter stops increasing; the alert resolves within 15 minutes.
- Record what happened in the incident log (Step 23 audit trail).
