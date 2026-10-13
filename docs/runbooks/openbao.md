# Runbook: OpenBao (Step 28)

OpenBao hands out short-lived database logins and stores the platform's other secrets.
When it is **sealed** or **down**, nothing new is handed out. Services keep working on the
credentials they already have until those expire (database logins: at most 1 hour after the
agent last renewed them). So you have time, but not all day.

## Alert `OpenBaoSealed` (critical), or after any restart of OpenBao or your Mac

1. `just vault-status`. `Sealed true` is expected after every restart: OpenBao never stores its
   own unlock key.
2. `just vault-up`: unseals with 2 of the 3 key shares from `secrets/openbao-init.enc.json`
   (decrypted in a pipe by SOPS), then gives rag-api's agent a new single-use secret ID.
3. Check: `just ps` shows `rag-api-agent` healthy; one search works.

If unsealing fails with "invalid key": the init file doesn't belong to this server's data
(restored from another machine?). Stop and find the right file; never re-initialise a server
that holds data: `bao operator init` refuses, and wiping the volume loses every stored secret.

## Alert `OpenBaoAuditFailing` (critical): OpenBao is refusing requests

OpenBao refuses to answer when it can't record the request. That is deliberate.

1. Disk full? `docker compose exec openbao df -h /openbao/logs`.
2. Rotate the log: rename it, then tell OpenBao to reopen (SIGHUP; `init: true` passes it on):
   `docker compose exec openbao mv /openbao/logs/audit.log /openbao/logs/audit-$(date +%F).log`
   and `docker compose kill -s HUP openbao`.
3. Copy the renamed file somewhere safe (`docker compose cp`, then the object store with
   retention, like Step 23's archive), then delete it from the volume. As soon as there is
   space again, requests are answered.
4. Never "fix" this by removing the audit stanza from `server.hcl`.

## rag-api can't reach the database ("password authentication failed" for a `v-approle-…` user)

1. `just logs rag-api-agent`. Typical causes:
   - the agent restarted (Docker, your Mac): its single-use secret ID is gone, so it can't log
     in again. Run `just vault-agent-start`.
   - `wrapping token is not valid or does not exist` right after `just vault-agent-start`:
     someone else unwrapped that secret ID first. Treat it as a security incident (below).
   - `permission denied`: a policy changed. `git log infra/config/openbao/policies`, then
     `just vault-setup`.
   - connection refused: OpenBao is down or sealed (above).
2. Roll back if needed (minutes): set `RAG_API_DB_PASSWORD` / `RAG_API_AUDIT_DB_PASSWORD` secrets
   again, remove the `*_CREDENTIALS_FILE` variables, `just vault-cutover-undo`, restart rag-api.

## A secret may have leaked

- **A database login** (`v-…` user): `bao lease revoke <lease_id>` (or
  `bao lease revoke -prefix database/creds/rag-api` for all of them). The user is dropped and its
  sessions are ended immediately. The agent fetches a new one.
- **A static secret** (gateway key, OPA token): rotate it at its source, then
  `just vault-put rag-api gateway_key=…` and `just vault-agent-start` (rag-api reads these at start).
  A KV write replaces the whole secret: put every rag-api value again (since Step 32 that includes
  `pii_hmac_key`, without which the agent renders nothing). Never rotate `pii_hmac_key` on its own:
  pseudonyms change with it, so it rotates only together with a full re-index (Step 36).
- **The secret ID or rag-api's token**: `bao write auth/approle/role/rag-api/secret-id-accessor/destroy
  secret_id_accessor=…` (accessors are in the audit log), then
  `bao lease revoke -prefix auth/approle/login`.
- **Your admin password**: change it in SOPS (`BAO_ADMIN_PASSWORD`) and run `just vault-setup`.

Who did what: every request is one JSON line in `/openbao/logs/audit.log`. Secret values appear
only as `hmac-sha256:…`. To check whether a value you hold was involved, hash it the same way:
`bao write sys/audit-hash/file input=<value>` and search the log for the result.

## Break glass: the admin login is lost

`bao operator generate-root` creates a new root token from 2 of the 3 key shares. Use it to fix
the admin login, then revoke it (`bao token revoke -self`) and record the event.
