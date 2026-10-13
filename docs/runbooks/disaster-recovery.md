# Runbook: disaster recovery (Step 37)

| What failed | What happens by itself | What you do | Data lost (RPO) | Time (RTO) |
|---|---|---|---|---|
| One rag-api / worker pod or node | Kubernetes replaces it; other replicas serve | nothing | none | seconds |
| Postgres primary (pod, node or zone) | CloudNativePG promotes a synchronous replica, moves `rag-db-rw` | check `kubectl cnpg status rag-db -n rag-data` | none (synchronous commit) | ~1 min |
| A whole zone | pods reschedule in the other two zones; Postgres fails over | watch capacity; HPA adds pods | none | minutes |
| Bad data (a wrong delete, a bad migration) | nothing: replicas copy the mistake | point-in-time restore into a NEW cluster, then switch | to the second before the mistake | 1-2 h per 100 GB |
| The region or the cluster | nothing | rebuild: new cluster, Argo CD root.yaml, restore from the backup bucket | WAL archived up to the loss (seconds-minutes) | hours |
| Qdrant / OpenSearch (if used) | derived data | `rag reindex` from the originals (Step 36) | none | hours |
| Valkey (cache, memory, queue) | cache and memory are disposable; queue jobs re-sent by sources | restart; re-enqueue from the manifest if needed | conversations, cached answers | minutes |

**Point-in-time restore (the drill and the real thing are the same steps)**
1. Find the time just BEFORE the mistake (audit log, Step 23: `occurred_at` of the bad action).
2. `just dr-drill "2026-10-13 08:59:00+00"` creates `rag-db-drill` from deploy/data/drills/restore-cluster.yaml
   with that target, waits for it, and compares row counts with production.
3. Real recovery: check the restored data, then point the `rag-db` Service (deploy/components/managed-deps)
   at `rag-db-drill-rw.rag-data.svc.cluster.local` through a pull request, or copy the affected rows back.
4. Run `rag eval-search` against it before switching: an index restored is an index to prove.

**Drill monthly.** The drill writes its timings into the incident log: RTO is measured, not guessed.
Never restore over the production cluster: always next to it, then switch.

**Region loss (rebuild).** Backups live in a bucket in ANOTHER region with Object Lock (Step 14).
New cluster → `kubectl apply -f deploy/argocd/envs/prod/root.yaml` → Argo CD installs everything →
the data project's Cluster bootstraps with `recovery` from the bucket instead of `initdb` (edit
deploy/data/envs/prod in the pull request). Practise this once a year.
