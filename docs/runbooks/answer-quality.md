# Runbook: answer quality alerts (warning)

Covers RagGuardBlocksSpike, RagAbstentionSpike, RagThumbsDownHigh, RagAnswerLatencyHigh and
RagScheduledJobFailed (infra/config/prometheus/rules/rag-answers.yml, Step 37).

**Check first (10 minutes)**
1. Did something just change? `git log --since="6 hours ago" -- deploy/envs prompts rag.yaml`
   and the Argo CD history of `rag-api-<env>`. A new release, prompt label or model is the usual cause.
2. Grafana → *RAG platform · overview*: which outcome moved, and in which `service_version`?
   If only the canary's version moved, Argo Rollouts is already handling it (see canary.md).
3. Per release, with feedback joined: `rag online-eval --dsn-file /run/bao/audit_reader_dsn --since-hours 6`
   (or `kubectl -n rag logs job/<latest rag-online-eval>`). `--queue review.jsonl` lists the answers
   to look at.
4. Open a few of those answer ids in Langfuse/Tempo (the trace id is the answer id, Steps 21-22).

**By alert**
- *Blocks spike*: `rag_guard_verdicts_total` by `guard`: one guard, or all? One guard after a
  release = a threshold or prompt change; many guards with normal releases = an attack campaign.
  Check the audit log for a few actors (`details->'guards'`), rate-limit or block them at the gateway.
- *Abstentions spike*: search is failing quietly. `rag search "<a known question>" --group …` in the
  pod; check the embedder model in the gateway, the last ingestion run, and `rag eval-search`.
- *Thumbs down*: read the reasons (`rag_feedback_total` by `reason`). "outdated" → ingestion or
  retention; "wrong" → retrieval or prompt; "unsafe" → treat as an incident (Step 34's playbook).
- *Latency*: gateway first (Step 10 dashboards), then the reranker, then the database.
- *Job failed*: `kubectl -n rag logs job/<name>`; rerun with `kubectl create job --from=cronjob/<name> …`.

**Fix**
- Roll back by reverting the promotion commit (`git revert`), through a pull request: Argo CD does the rest.
- Turn the reviewed answers into labelled questions (examples/eval/*.yaml) so CI catches it next time.

**Close**
- The rate is back near its daily level; the alert resolves by itself.
- Record the cause and the new evaluation cases in the incident log.
