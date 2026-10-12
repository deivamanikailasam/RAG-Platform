# Runbook: audit log (Step 23)

The audit log records who received which documents, every refusal and every admin action.
rag-api **fails closed**: if it can't record an event, it refuses the request (503).

## Alert `RagAuditWriteFailing` (critical): searches are being refused

1. Is the audit database up? `just ps` (rag-db healthy?) and `just audit-psql -c 'select 1'`.
2. Can the writer connect? `just logs rag-api | grep -i audit`. Look for `permission denied`,
   `password authentication failed` (secret rotated in one place only?) or `too many connections`.
3. Is the lock queue stuck? As admin:
   `select pid, state, wait_event, now() - xact_start as age, query from pg_stat_activity where datname = 'audit';`
   A long-open transaction holding `audit.events` blocks every append. Find out what it is
   before terminating it.
4. Disk full? `docker compose exec rag-db df -h /var/lib/postgresql/data`.
5. Once fixed, searches recover by themselves (the pool reconnects). Confirm with one search and
   `just audit-verify`.

Do **not** switch fail-closed off to "get users working again" without the data owner's written
approval: every answer served in that window would be unaccounted for.

## `just audit-verify` reports problems, or `just audit-anchor` refuses ("ANCHOR REFUSED")

Treat this as a **security incident**, not a bug, until proven otherwise.

1. **Preserve evidence first.** Don't "repair" the chain, don't re-run anchors, don't restart
   the database. Take a fresh `pg_dump -d audit` to a safe place and note the time.
2. Save the verify report (it lists the first 50 problems).
3. Read the problems:
   - `database: row N was changed/deleted after it was anchored`: the database no longer matches
     the write-once archive. The archive copy is the trustworthy one.
   - `database: row N: contents changed` / `link broken` / `row N is missing`: rows changed
     since they were written, possibly not yet anchored.
   - `archive: … has 2 versions (replacement attempted)`: someone tried to overwrite an archived
     object. Find out who from the object store's access logs.
4. Who had superuser or `audit_migrator` access in that window? Check Keycloak admin events,
   shell history on the host, and the Postgres logs.
5. Escalate to the security lead and the data owner. Agree on what to restore and how, and
   record the decision as a new audit event and in the incident report.

## Routine

- `just audit-anchor` runs hourly; `just audit-verify` runs daily. Alert if either has not
  succeeded for 2 runs (Step 29 turns these into monitored Kubernetes CronJobs).
- `not_yet_anchored` in the verify report should stay below one hour of traffic.
