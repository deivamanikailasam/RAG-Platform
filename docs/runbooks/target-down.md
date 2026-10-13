# Runbook: TargetDown (warning)

**What it means:** Prometheus has failed to scrape a target (`job`, `instance` in the alert) for 2 minutes.
Either the component is down, or Prometheus can't reach or authenticate to it. While it lasts, that
component's metrics and alerts are blind.

**Check first (5 minutes)**
1. Prometheus → *Status* → *Targets* (http://localhost:9090/targets): the error text says why.
   - `connection refused` / `no such host`: the container is not running. `just ps`.
   - `401 Unauthorized`: the token or key is wrong (OPA: `OPA_METRICS_TOKEN`; Qdrant: `QDRANT_READ_ONLY_API_KEY`).
   - `context deadline exceeded`: it is running but too slow to answer.
2. Logs of the component: `just logs <service>`.

**Likely causes**
- The service was stopped or crashed (OPA stopped means searches fail with 503 too).
- `tei`: the native embedder/reranker on the Mac isn't running. Normal when you stopped it; start it with
  `just search-models-up`.
- A secret was changed in SOPS but the stack wasn't restarted with `just up`.
- `postgres-rag`: the `rag_metrics` role is missing on an older database. Create it as in Step 20.

**Fix**
- Start or repair the component (`just up`); fix the credential and restart both sides.

**Close**
- The target shows UP again; the alert resolves on the next evaluation.
