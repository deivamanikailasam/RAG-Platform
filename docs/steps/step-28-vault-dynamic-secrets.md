# Step 28 · Vault: secrets issued on demand, short-lived and audited

*Step 28 of 38 · Phase G · Quality & delivery*

## At a glance

| | |
|---|---|
| **Goal** | rag-api stops using long-lived database passwords. Instead, it gets a database login made just for it, valid for an hour, renewed while needed, replaced automatically, cancellable in one command, and recorded every time it's handed out. |
| **How, in one sentence** | OpenBao (the open-source fork of HashiCorp Vault) runs beside the platform. Its database engine creates short-lived Postgres users on request, a small OpenBao Agent next to rag-api logs in with AppRole and keeps the current login in a file in memory, and rag-api reads that file for every new connection. |
| **Time** | About 3 hours. |
| **You'll end up with** | an OpenBao server (one node, raft storage, sealed with 3 key shares, an audit log, Prometheus metrics), configured entirely from files in git by `scripts/vault_setup.py` · dynamic credentials for `rag-api`, `audit-writer` and `rag-readonly`; the bootstrap admin passwords rotated away so only OpenBao knows them · policies for rag-api, the evaluation harness, a person (developer) and the administrator; the root token revoked after setup · an agent sidecar, a single-use wrapped secret ID, and rag-api changes (`CredentialsFile`) that pick up new logins without restarting · SOPS kept for the few bootstrap secrets (unseal keys, the first passwords), `just vault-*` recipes, two new alerts and a runbook · 30 new tests (220 in the guide's count), most of them against a real OpenBao and a real Postgres · ADR-0028. |
| **New words** | secrets manager, Vault, OpenBao, seal/unseal, Shamir's secret sharing, root token, secrets engine, KV v2, database secrets engine, dynamic secret, lease, TTL (default, max), renew, revoke, auth method, AppRole (role ID, secret ID), response wrapping, policy, token, OpenBao Agent, auto-auth, template, audit device, HMAC, rotate-root, break-glass. |

## The big idea

> **ANALOGY · THE HOTEL KEY CARD**
> An old-fashioned office gives each employee a metal key. It works on every door, forever. Lose it and someone
> has to change the locks for everybody. Copy it and nobody will ever know.
>
> A hotel works differently. At the front desk you show who you are, and you get a key card:
> - it opens your room only
> - it stops working at check-out time, by itself
> - if you lose it, the desk cancels that one card in seconds; the lock doesn't change
> - the desk keeps a record of every card it issued, to whom, when
>
> Until now, rag-api had metal keys: passwords in files that never expire and are shared by every copy of the
> service. In this step, OpenBao is the front desk, each database login it creates is a key card, and the agent is
> the guest who goes back to the desk before the card expires.

The same database access, handed out two ways (Figure 88 in the guide):

| | Before: a password in a file | After: a login issued on demand |
|---|---|---|
| **Who uses it** | every rag-api instance, the same one | one agent: its own user, `v-approle-rag-api-…` |
| **How long it lives** | months (until someone rotates it) | 1 hour, renewed while needed (max 24 h) |
| **If it leaks** | valid everywhere until rotated by hand | revoke one lease: user dropped, sessions ended |
| **Rotating it** | change SOPS + Postgres + restart, together | automatic: a new pair before the old one expires |
| **Who used it when** | can't tell instances (or an attacker) apart | every issue in OpenBao's audit log |

Same database, same privileges (each user is a member of `rag_app`): only **how** the login is handed out changes.

## What we're doing

1. Run OpenBao next to the platform: one node, encrypted storage, an audit log, metrics.
2. Initialise it once (the unlock key shares go straight into a SOPS file) and unseal it.
3. Describe everything it should do in files in git: policies, database connections and roles, logins. One script
   applies them, again and again, safely.
4. Give Postgres one admin login per database for OpenBao, then let OpenBao rotate those passwords so only it
   knows them.
5. Add the agent beside rag-api, delivering its first secret through a single-use wrapper.
6. Teach rag-api to read changing credentials, then cut over and switch the old passwords off.
7. Test it against a real OpenBao and Postgres, add alerts and a runbook, and record ADR-0028.

## Why we're doing this

> **WHY THIS MATTERS**
> A password that never changes is only as safe as every place it has ever been: SOPS files, environment
> variables, a developer's terminal history, a backup, a log line printed by mistake. Three problems remain even
> with SOPS (Step 6):
> - **Leaks stay valid.** If `rag_app`'s password leaks, it works until someone notices and rotates it by hand, in
>   several places at once. Most teams rotate rarely, because rotating hurts.
> - **Everyone is the same user.** Every rag-api instance (and an attacker using a stolen password) logs in as
>   `rag_app`. Postgres logs can't tell them apart.
> - **No record of who had it.** SOPS tells you who can decrypt the file, not who used the password, when.
>
> Short-lived, per-client credentials turn all three around: a leaked login expires within the hour (or the minute
> you revoke it), every login name is unique, and every issue is logged.

| Need | How this step meets it |
|---|---|
| A leaked database password must stop working quickly | Logins live 1 hour, renewed only while the agent is alive; `bao lease revoke` drops the user now |
| Know which client used the database | Each login is a unique Postgres user (`v-approle-rag-api-…`) |
| Know who received which secret, when | OpenBao's audit device logs every request; values appear only as HMACs |
| No human knows the database admin passwords | `rotate-root` right after setup: only OpenBao knows them |
| Least privilege for machines and people | One policy per client; rag-api can read 3 paths and nothing else |
| Recover from a mistake | Static passwords stay available for rollback (`just vault-cutover-undo`) until you remove them |
| Configuration reviewable like code | Policies, roles and settings are files in git, applied by one idempotent script |

> **IN A COMPANY**
> Secrets management is a standard control:
> - OWASP's Secrets Management Cheat Sheet recommends a central secrets manager, short-lived (ideally dynamic)
>   secrets, automatic rotation and auditing.
> - PCI DSS 4.0 (8.3, 8.6) and ISO 27001 (A.5.17, A.8.5) require protecting and regularly changing authentication
>   secrets, including those of system accounts.
> - SOC 2 auditors ask: how are service credentials stored, rotated and revoked, and who can see them?
>
> Large companies run HashiCorp Vault Enterprise, OpenBao, or a cloud service (AWS Secrets Manager, Azure Key Vault,
> Google Secret Manager), often with workload identity (Kubernetes service accounts, cloud IAM roles) instead of
> AppRole. The ideas in this step carry over directly: policies, leases, dynamic database users, an agent or
> sidecar, and audit logs.

> **WHY OPENBAO, NOT HASHICORP VAULT?**
> Vault was open source (MPL 2.0) until August 2023, when HashiCorp moved it to the Business Source License 1.1,
> which restricts some uses and isn't an open-source licence (IBM has since bought HashiCorp). OpenBao is the
> community fork from the last open version, run under the Linux Foundation and still MPL 2.0. Its API, policies
> and concepts are Vault's; the binary is called `bao` instead of `vault`. Step 27's licence policy already refuses
> BUSL-1.1 dependencies, so OpenBao is also the consistent choice. Everything in this chapter works almost word for
> word with Vault (`vault` instead of `bao`).

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Secrets manager** | A server whose job is to store secrets and hand them out to the right clients, with an audit trail. |
| **Vault / OpenBao** | The best-known secrets manager, and its open-source fork. We say "Vault" for the idea, OpenBao for the product. |
| **Seal / unseal** | OpenBao's data on disk is encrypted. After every start it's *sealed* (can't read its own data) until enough key shares are entered. |
| **Shamir's secret sharing** | Splitting a key into N shares so that any K of them rebuild it, and fewer reveal nothing. We use 3 shares, any 2. |
| **Root token** | An all-powerful login created at initialisation. Used once for setup, then revoked. |
| **Secrets engine** | A plug-in that produces secrets: **KV v2** stores fixed values (with versions); the **database engine** creates logins. |
| **Dynamic secret** | A secret created on request, for one client, with an expiry. It didn't exist before you asked. |
| **Lease, TTL** | Every dynamic secret comes with a lease: an ID and a time to live. Default TTL 1 h; it can be renewed up to the max TTL. |
| **Revoke** | End a lease early. For a database login: end its sessions and drop the user. |
| **Auth method, token** | How a client proves who it is (AppRole, userpass, OIDC, Kubernetes…). Success gives a token with policies attached. |
| **AppRole: role ID, secret ID** | A login for machines. The role ID says which role (like a username, not secret); the secret ID is the password. |
| **Response wrapping** | OpenBao hands out a secret inside a single-use envelope (a wrapping token). If someone opened it first, the real recipient finds out. |
| **Policy** | A list of paths and what a token may do with them. Anything not listed is denied. |
| **OpenBao Agent** | A helper process next to an application: logs in (auto-auth), renews, and writes secrets into files (templates). |
| **Audit device** | Where OpenBao records every request and response. Secret values are replaced by HMACs (keyed hashes). |
| **rotate-root** | OpenBao changes the password of its own database admin login, so no person knows it any more. |
| **Break-glass** | A documented emergency procedure (here: `bao operator generate-root` with 2 key shares). |

### How rag-api gets a database login (Figure 89)

```
 you: just vault-agent-start
   role ID + a WRAPPED secret ID (works once)
            │ 1
            ▼
 rag-api-agent ── 2 login (AppRole) ──►  OpenBao  (sealed until 2 of 3 key shares unlock it)
 (OpenBao Agent)                          ├─ policy rag-api: may read 2 creds paths + 1 secret
   logs in, renews,  ◄── 3 token, creds ──┤─ database engine ── creates / drops ──► Postgres (rag-db)
   re-fetches,                            │    CREATE ROLE … IN ROLE rag_app          v-approle-rag-api-x7Q…
   writes files                           ├─ kv secret/rag-api: gateway key, OPA token   VALID UNTIL +1 h
            │ 4 writes                    └─ audit device: every request; secrets HMAC'd member of rag_app
            ▼                                                                        ▲
 /run/bao (tmpfs, 0400, user 10001):                                                 │ 5 connects as v-…
   rag_db.json · audit_db.json · rag_api_gateway_key · rag_api_opa_token ──► rag-api reads /run/bao/rag_db.json
                                                                              for EVERY new connection;
                                                                              never holds an OpenBao token
```

You hand the agent a single-use wrapped secret ID (1). The agent logs in with AppRole (2) and gets a token limited
by the `rag-api` policy, then requests credentials (3). OpenBao's database engine creates a Postgres user that is a
member of `rag_app` and expires in an hour. The agent writes the login into in-memory files (4), and rag-api reads
them for every new connection (5). Every request is in the audit log.

**The important property:** rag-api never talks to OpenBao and never holds an OpenBao token. It only reads files.
If rag-api is compromised, the attacker gets one database login that expires within the hour, not the keys to the
safe.

### A login's life (Figure 90)

One rag-api database login over a day (real values: token 1 h, renewed up to 24 h):

- The lease is **renewed every hour**. Each renewal also moves the Postgres `VALID UNTIL` an hour on, so Postgres
  accepts the login only while OpenBao keeps the lease alive.
- **Before the maximum TTL**, the agent fetches a **new pair** (user 2). Then the old lease ends: its sessions are
  terminated and the user is dropped (`DROP ROLE`).
- **Leaked?** `bao lease revoke <lease>`: the same clean-up happens *now*, not at the 24 h mark.
- **OpenBao gone for good?** `VALID UNTIL` is a second lock: Postgres refuses the login on its own.

### Locked even on disk (Figure 91)

OpenBao's storage is encrypted and the key to it is **not stored anywhere**. Any 2 of the 3 key shares rebuild the
unseal key in memory after each start (Shamir's secret sharing); a restart means sealed again, so a stolen disk or
backup is useless without 2 shares. The root token is used once for setup, then revoked; a new one needs 2 shares
(break-glass). Day to day, *you* use an admin login (1 h, can't read secret values) and *machines* use AppRole,
one policy each.

## How to do it

On your Mac, in the project folder:

```bash
cd ~/dev/rag-platform
git switch -c feat/vault
```

### 1 · Pin the bao binary

One binary is the server, the agent and the command-line client. It is added to Step 27's tool manifest
(`ci/tools.yaml`) so CI and your Mac use the same, verified version:

```yaml
  bao:  # OpenBao (Step 28): server, CLI and agent in one binary. MPL-2.0.
    version: 2.7.1
    member: bao  # the file to take out of the archive
    linux-amd64:
      url: https://github.com/openbao/openbao/releases/download/v2.7.1/openbao_2.7.1_linux_amd64.tar.gz
      sha256: 0e2f1ce10d124e03112b50dd2fbec6b78003783253bc3a91587938f39d1e2243
    darwin-arm64:
      url: https://github.com/openbao/openbao/releases/download/v2.7.1/openbao_2.7.1_darwin_arm64.tar.gz
      sha256: 15625b5f69aee5bb4578b4e76e856a2141647342b0f8e5969a8875b44e0fbf91
```

```bash
just tools bao && bao version          # OpenBao v2.7.1
```

The hashes come from the release's own `checksums.txt`. `tests/test_ci_tools.py` now expects nine tools.

### 2 · The server's configuration

`infra/config/openbao/server.hcl` describes one OpenBao node:

- `storage "raft"` at `/openbao/file`, node `bao-1`.
- `listener "tcp"` on `0.0.0.0:8200` with `tls_disable = true` and `unauthenticated_metrics_access = true`.
- `api_addr` / `cluster_addr` on `http://openbao:8200` / `:8201`.
- `disable_mlock = true`, `ui = false`, `log_level = "info"`.
- `telemetry { prometheus_retention_time = "24h", disable_hostname = true }`.
- `audit "file" "file"` writing `/openbao/logs/audit.log` with mode `0600`.

> **READING THE SERVER CONFIGURATION**
> - `storage "raft"`: OpenBao's built-in storage. One node now; more nodes later give high availability without an
>   external database. Everything written there is encrypted by OpenBao.
> - `tls_disable`: plain HTTP is acceptable only because the port is reachable on the internal Docker network and on
>   127.0.0.1 of your Mac. Anywhere else, TLS. Step 29 revisits this in the cluster.
> - `disable_mlock`: mlock would pin memory so secrets never reach swap, but raft memory-maps its database file and
>   mlock would pin all of it; OpenBao's own docs recommend switching it off with raft. The trade-off: memory could
>   in principle be swapped to disk. On a Mac the Docker VM's disk lives on your drive, so keep FileVault on.
> - `telemetry`: metrics for Prometheus at `/v1/sys/metrics`, readable without a token. They contain counts and
>   states, never secret values (tested).
> - `audit "file"`: declared in the file, not created through the API. OpenBao 2.x refuses to create audit devices
>   through the API, so a stolen admin token can't add or redirect one. The guide's authors found this out the
>   honest way: the first version of the setup script tried, and got `cannot enable audit device via API`. If no
>   audit device can write, OpenBao refuses requests: an unrecorded secret is never handed out.

Two services are added to `infra/compose/compose.yaml`:

- **`openbao`**: the server, started with `entrypoint: ["bao", "server", "-config=/openbao/config/server.hcl"]`,
  `init: true`, `ulimits: { core: 0 }`, port `127.0.0.1:8200:8200` only, `server.hcl` mounted read-only, volumes
  `openbao-data` (raft storage) and `openbao-logs` (audit log), `read_only: true`, `tmpfs: [/tmp]`,
  `cap_drop: [ALL]`, `no-new-privileges`, a healthcheck on `/v1/sys/health`, 1 CPU / 512 MB, `restart:
  unless-stopped`.
- **`rag-api-agent`**: the same image in agent mode (`bao agent -config=/openbao/config/agent.hcl`), running as
  `user: "10001:10001"` (rag-api's user), mounting `agent-rag-api.hcl` read-only, `../../.bao/rag-api` as
  `/openbao/bootstrap` and the in-memory volume `rag-api-bao` as `/openbao/out`; healthy when
  `/openbao/out/rag_db.json` is non-empty; 0.25 CPU / 64 MB; `restart: "no"`.

rag-api gains `RAG_API_DB_CREDENTIALS_FILE: /run/bao/rag_db.json`,
`RAG_API_AUDIT_DB_CREDENTIALS_FILE: /run/bao/audit_db.json`, the volume `rag-api-bao:/run/bao:ro` and a
`depends_on` on `rag-api-agent` being healthy. rag-db gains one more secret, `vault_admin_pg_password`, for the new
init script. New volumes: `openbao-data`, `openbao-logs`, and `rag-api-bao` as a tmpfs
(`uid=10001,gid=10001,mode=0700,size=1m`). New Compose secret: `vault_admin_pg_password` from
`VAULT_ADMIN_PG_PASSWORD` (bootstrap only; rotated by OpenBao).

> **READING THE SERVICES**
> - `entrypoint: bao server …`: we skip the image's start-up script (it's meant for `-dev` mode and changes file
>   ownership). `init: true` replaces its signal handling (and passes SIGHUP on, which reopens the audit log);
>   `ulimits: core: 0` replaces its "no core dumps" rule. A core dump is a copy of memory on disk, with secrets in it.
> - Volumes: `/openbao/file` and `/openbao/logs` already belong to the image's `openbao` user, so Docker gives the new
>   volumes the same owner. Everything else is read-only.
> - Healthcheck: `/v1/sys/health` answers 200 only when OpenBao is unsealed and active. A sealed server shows as
>   unhealthy, which is exactly what you want to notice.
> - `rag-api-agent` runs as user 10001, the same user as rag-api, so the files it writes (`0400`: owner read-only)
>   can be read by rag-api and nobody else.
> - `rag-api-bao` is a tmpfs volume: in memory only, never written to disk, gone when stopped. Only these two
>   containers mount it.
> - `../../.bao/rag-api` is where you put the agent's role ID and single-use secret ID (git-ignored). On Docker
>   Desktop and OrbStack, bind mounts are writable by the container user; on a Linux host, `chown 10001` that folder.
> - `restart: "no"` for the agent: its secret ID works once, so a restarted agent couldn't log in anyway.
>   `just vault-up` starts it properly (below).

Prometheus (Step 20) scrapes OpenBao (`infra/config/prometheus/prometheus.yml`):

```yaml
  - job_name: openbao                         # Step 28: sealed?, leases, audit failures (metrics hold no secrets)
    metrics_path: /v1/sys/metrics
    params: { format: [prometheus] }
    static_configs: [{ targets: ["openbao:8200"] }]
```

### 3 · Initialise and unseal (once, then after every restart)

```bash
docker compose -f infra/compose/compose.yaml up -d openbao
bao status
```

```text
Initialized     false
Sealed          true
Version         2.7.1
Storage Type    raft
```

Initialising creates the encryption key, splits the unlock key into 3 shares (any 2 unlock it) and creates the root
token. These are the only secrets that can't live in OpenBao itself, so they go where your bootstrap secrets
already live: SOPS (Step 6). The `vault-init` recipe pipes them straight into an encrypted file; they never touch
the disk in clear text. The justfile's new "Vault: OpenBao (Step 28)" section exports
`BAO_ADDR` (default `http://127.0.0.1:8200`) and names `bao_init_file := "secrets/openbao-init.enc.json"`:

```bash
just vault-init
# wrote secrets/openbao-init.enc.json: commit it. Next: just vault-unseal && just vault-setup-first
head -c 300 secrets/openbao-init.enc.json      # "unseal_keys_b64": ["ENC[AES256_GCM,data:…", …

just vault-unseal
# sops decrypt secrets/openbao-init.enc.json | uv run python scripts/vault_setup.py unseal
# unsealed
```

> **THE UNSEAL KEYS ARE THE CROWN JEWELS**
> Whoever has 2 shares and a copy of the data volume has every secret. Here, all 3 shares sit in one SOPS file
> encrypted to your age key, which is fine for one person on one Mac. In a team, give each share to a different
> person (each encrypted to their own key), so no single person can unseal alone. Back up your age key (Step 6)
> separately from the volume backups. Lose all of them and the data is gone for good: there is no reset.

After any restart of OpenBao or your Mac, OpenBao is sealed again (that's the point). `just vault-up` unseals it and
restarts the agent; the `OpenBaoSealed` alert (section 9) reminds you.

### 4 · The database side: a login for OpenBao

OpenBao needs a Postgres login that may create and drop users, and nothing more. **One per database**, because each
connection's password is rotated separately (the guide's first version shared one login, and rotating it for `rag`
broke `audit`: caught on the first live run).

`infra/config/rag-db/init/03-openbao.sh` (runs automatically on an empty volume, after `01-roles.sh` and
`02-audit.sh`) creates `vault_admin_rag` and `vault_admin_audit` with `LOGIN CREATEROLE` and the bootstrap
password from the `vault_admin_pg_password` secret file, then:

```sql
GRANT rag_app, rag_readonly TO vault_admin_rag   WITH ADMIN OPTION;
GRANT audit_writer          TO vault_admin_audit WITH ADMIN OPTION;
GRANT pg_signal_backend TO vault_admin_rag, vault_admin_audit;   -- revoking a lease ends that user's sessions
GRANT CONNECT ON DATABASE rag   TO vault_admin_rag;
GRANT CONNECT ON DATABASE audit TO vault_admin_audit;
ALTER ROLE vault_admin_rag   SET statement_timeout = '10s';
ALTER ROLE vault_admin_audit SET statement_timeout = '10s';
```

> **READING THE BOOTSTRAP**
> - `CREATEROLE`, not superuser: since Postgres 16, a CREATEROLE user can only give out memberships of roles it
>   holds `WITH ADMIN OPTION`. So `vault_admin_rag` can create users that are members of `rag_app` or `rag_readonly`,
>   but never a member of `audit_writer`, never a superuser.
> - `pg_signal_backend`: needed to end a revoked user's open sessions (`pg_terminate_backend`). It can't signal
>   superuser sessions.
> - Groups stay as they are: `rag_app`, `rag_readonly` and `audit_writer` keep their privileges from Steps 11 and 23.
>   Each short-lived user is created `IN ROLE` one of them and inherits everything. No privilege is defined twice.

If your rag-db volume already exists:

```bash
sops secrets/dev.enc.env      # add VAULT_ADMIN_PG_PASSWORD (a bootstrap value, rotated in a minute) and BAO_ADMIN_PASSWORD
just vault-db-bootstrap
```

(New machines get both values from `just secrets-init`; they are in `scripts/new-dev-secrets.sh` and `.env.example`.)

### 5 · Everything else as code

Who may do what is written in policies, one file per client, in `infra/config/openbao/policies/`:

| Policy | May do |
|---|---|
| `rag-api.hcl` | `read` on `database/creds/rag-api`, `database/creds/audit-writer`, `secret/data/rag-api`. Nothing else. |
| `rag-evals.hcl` | The evaluation harness (Step 26): `read` on `database/creds/rag-readonly` and `secret/data/rag-evals`. |
| `developer.hcl` | A person: a short-lived read-only database login (`database/creds/rag-readonly`) when they need to look at data. |
| `platform-admin.hcl` | Day-to-day administration instead of the root token: engines and auth methods (`sys/mounts/*`, `sys/auth/*`), see audit devices (`sys/audit`), policies, lease lookup/revoke, database connections, roles and `rotate-root`, AppRoles and userpass users, and **write-only** secrets (`secret/data/*`: create/update; `secret/metadata/*`: read/list/delete). **Not** `database/creds/*`. |

> **READING THE POLICIES**
> - Deny by default: a token can do exactly what its policies list. rag-api's token gets 403 on every other path
>   (tested on four of them).
> - `capabilities`: `read`, `create`, `update`, `delete`, `list`; `sudo` for a few protected system paths.
> - The admin policy is honest about itself: whoever can write policies could grant themselves anything. It doesn't
>   pretend to stop a malicious admin; it removes the root token from daily use, ties every action to a named login,
>   and avoids accidentally reading secret values. It can write `secret/data/*` but not read it back. It cannot
>   seal/unseal, change audit devices (they live in `server.hcl`) or generate a root token.
> - `bao policy fmt` is the canonical format; `just vault-check` (part of `ci-config`) fails if a file isn't formatted.

Then **one script applies the whole desired state**: `scripts/vault_setup.py`. It talks to OpenBao's HTTP API
directly (`BAO_ADDR`, `BAO_TOKEN`), so every call is visible and testable. The desired state is three dataclass
tuples at the top of the file:

- `CONNECTIONS`: `rag-db` → database `rag`, admin `vault_admin_rag`, allowed roles `rag-api`, `rag-readonly`;
  `audit-db` → database `audit`, admin `vault_admin_audit`, allowed role `audit-writer`.
- `ROLES`: `rag-api` (member of `rag_app`, 1 h / 24 h, `search_path = rag, public`, `statement_timeout = '30s'`),
  `rag-readonly` (member of `rag_readonly`, 1 h / 8 h, `statement_timeout = '120s'`,
  `default_transaction_read_only = on`), `audit-writer` (member of `audit_writer`, 1 h / 24 h,
  `search_path = audit`, `statement_timeout = '5s'`).
- `APPROLES`: `rag-api` (policy `rag-api`), `rag-evals` (policy `rag-evals`, token max TTL 4 h); tokens 1 h,
  renewable to 24 h; secret IDs live 30 days (720 h) and are bound to CIDRs.

`setup()` then, in order: (1) refuses to continue unless the `file/` audit device exists; (2) mounts KV v2 at
`secret/` and the database engine, and enables `approle` and `userpass` auth, if missing; (3) writes every policy
file; (4) creates each database connection **once** with the bootstrap password and immediately calls
`database/rotate-root/<name>`, while later runs update the connection without a password; (5) writes the database
roles with their creation statements (`CREATE ROLE "{{name}}" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL
'{{expiration}}' IN ROLE <group>;` plus one `ALTER ROLE "{{name}}" SET …;` per setting) and revocation statements
(`pg_terminate_backend` for the user's sessions, then `DROP ROLE IF EXISTS`); (6) writes the AppRoles; (7) creates
or updates the `admin` userpass login (policies `platform-admin` + `developer`, 1 h, max 8 h) when
`BAO_ADMIN_PASSWORD` is set. Other subcommands: `put` (KV v2 write; values from **environment variable names**),
`role-id`, `secret-id` (wrapped, 10-minute TTL), `creds` (a 0600 JSON file, prints only the lease), `unseal`
(keys on stdin).

> **READING THE SETUP SCRIPT**
> - Converges, safely re-runnable: it creates what's missing and overwrites what's described (policies, roles,
>   logins). Run it after every change to these files, like a migration.
> - Refuses to configure a server without an audit device (tested): secrets must never be handed out unrecorded.
> - The database connections are created once with the bootstrap password, then `rotate-root` changes it to a random
>   value only OpenBao knows. Re-runs never resend a password; updating a connection without one keeps the rotated
>   password working (tested).
> - `creation_statements`: `{{name}}`, `{{password}}` and `{{expiration}}` are filled in by OpenBao. `VALID UNTIL`
>   makes Postgres itself refuse the login after expiry, a second lock in case OpenBao is ever lost. Renewals move it
>   forward (tested).
> - `ALTER ROLE … SET`: per-role settings (`search_path`, `statement_timeout`, read-only) are **not** inherited from a
>   group role, so each new user gets them explicitly (tested: `SHOW statement_timeout` says `30s`).
> - `REVOCATION`: end the user's sessions, then drop it.
> - AppRole settings: tokens live 1 h, renewable to 24 h; secret IDs are bound to the Docker network's addresses
>   (`secret_id_bound_cidrs`, default `172.16.0.0/12,127.0.0.1/32` via `BAO_APPROLE_CIDRS`), so a stolen one is
>   useless from elsewhere.
> - Values never on a command line: `put` takes environment variable names (`gateway_key=RAG_API_GATEWAY_KEY`) and
>   reads the values from your SOPS environment; `unseal` reads the keys from a pipe. Command lines end up in shell
>   history and process lists.
> - `creds` writes a person's short-lived login to a 0600 file and prints only the lease, never the password.

```bash
just vault-setup-first          # with the root token from the SOPS file
just vault-revoke-root          # retire it
```

```text
$ just vault-setup-first
ok: audit device present
ok: kv-v2 at secret/
ok: database engine
ok: approle auth
ok: userpass auth
ok: 4 policies
ok: connection rag-db (root password rotated)
ok: connection audit-db (root password rotated)
ok: 3 database roles
ok: 2 approles
ok: admin login

$ just vault-revoke-root
Success! Revoked token (if it existed)
root token revoked (the copy in secrets/openbao-init.enc.json is now useless)
```

From now on you work with your own login:

```bash
just vault-login
just vault-put rag-api gateway_key=RAG_API_GATEWAY_KEY opa_token=RAG_API_OPA_TOKEN
just vault-setup                # after any change to the policy files or the script
```

```text
$ just vault-put rag-api gateway_key=RAG_API_GATEWAY_KEY opa_token=RAG_API_OPA_TOKEN
secret/rag-api: version 1 (gateway_key, opa_token)

$ just vault-setup
ok: audit device present
ok: 4 policies
ok: 3 database roles
ok: 2 approles
ok: admin login
```

A person who needs to look at the data gets a read-only login that expires on its own:

```bash
just vault-creds rag-readonly
# .bao/rag-readonly.json: valid for 60 min (revoke early: bao lease revoke database/creds/rag-readonly/1V26…)
psql "postgres://$(jq -r .username .bao/rag-readonly.json):…@127.0.0.1:5432/rag" -c 'select current_user, …'
#  v-userpass-rag-read-nyIAq41oeN0qF5HLTlNl-1791810577 | 2026-10-13 01:09:42+11 | t
#  … and an INSERT fails: cannot execute INSERT in a read-only transaction
```

The evaluation harness (Step 26) uses the same file:
`RAG_DB_READONLY_CREDENTIALS_FILE=.bao/rag-readonly.json just evals run retrieval`.

### 6 · The agent

`infra/config/openbao/agent-rag-api.hcl`:

- `vault { address = "http://openbao:8200" }`.
- `auto_auth` with `method "approle"`: `role_id_file_path = "/openbao/bootstrap/role_id"` (not secret: *which*
  role), `secret_id_file_path = "/openbao/bootstrap/secret_id"` (a **wrapping token**, not the secret itself),
  `secret_id_response_wrapping_path = "auth/approle/role/rag-api/secret-id"` (unwrap it: works exactly once),
  `remove_secret_id_file_after_reading = true`.
- `template_config { exit_on_retry_failure = true }`: can't fetch secrets? stop: rag-api must not run on stale ones.
- Four `template` blocks, each `perms = "0400"` and `error_on_missing_key = true`: `database/creds/rag-api` →
  `rag_db.json` and `database/creds/audit-writer` → `audit_db.json` (both as `{{ .Data | toJSON }}`), and
  `secret/data/rag-api`'s `gateway_key` / `opa_token` → `rag_api_gateway_key` / `rag_api_opa_token`.

> **READING THE AGENT CONFIGURATION**
> - `auto_auth` with AppRole: the agent logs in, renews its token, and logs in again when the token reaches its
>   maximum age.
> - The secret ID arrives wrapped: `just vault-agent-start` asks for a secret ID inside a single-use envelope valid
>   for 10 minutes. The agent opens it, then deletes the file. If someone opened the envelope first, the agent's
>   unwrap fails loudly and it renders nothing (tested): you learn about the theft instead of sharing access with the
>   thief.
> - After that, the secret ID lives only in the agent's memory. It logs in again on its own after its token expires,
>   with the file long gone (tested). The flip side: a restarted agent can't log in; that's why `restart: "no"` and
>   `just vault-agent-start`.
> - Templates: the database logins are written as JSON (`{"username": …, "password": …}`); the static secrets as one
>   file each, named the way rag-api's settings read secret files (Step 17). `error_on_missing_key` refuses to write
>   an empty secret. Files are replaced in one step (written aside, then renamed), so rag-api never reads half a file.
> - `exit_on_retry_failure`: if the agent can't get secrets, it stops instead of leaving rag-api on stale ones.

```bash
just vault-agent-start
```

```text
$ ls -l /run/bao                          # inside rag-api
-r-------- 1 10001 10001 99 Oct 13 00:09 audit_db.json
-r-------- 1 10001 10001  7 Oct 13 00:09 rag_api_gateway_key
-r-------- 1 10001 10001  7 Oct 13 00:09 rag_api_opa_token
-r-------- 1 10001 10001 98 Oct 13 00:09 rag_db.json

$ ls .bao/rag-api                          # the secret ID was read once and deleted
role_id
```

The agent's log shows `authenticating`, `authentication successful, sending token to sinks`, `starting renewal
process` and one `rendered "(dynamic)" => "/openbao/out/…"` line per file.

### 7 · rag-api reads changing credentials

Until now, rag-api read its database password once at start-up. A login that changes every so often needs a
different shape: **ask for the current pair every time a connection is opened.**

`libs/rag-common/src/rag_common/secrets.py` provides:

- `Credentials`: a protocol, "a callable that returns `(username, password)`".
- `StaticCredentials(username, password)`: the old fixed pair, for rollback and tests; its `repr` hides the password.
- `CredentialsFile(path)`: reads `{"username", "password"}` from a JSON file, again whenever the file changes, and
  raises `CredentialsUnavailable` (whose message never contains a secret) when the file is missing or malformed.

> **READING CREDENTIALSFILE**
> - Cheap when nothing changed: one `stat()` per new connection; the file is re-read only when its inode,
>   modification time or size changed.
> - Inode, not just time: two writes in the same clock tick with the same size would look unchanged by time alone;
>   the agent's rename gives the new file a new inode (tested).
> - Errors never contain the file's content, which may be a password (tested with five broken files).
> - `StaticCredentials` keeps the old way working, for rollback and for tests, and hides the password in its `repr`.

`services/rag-api/src/rag_api/settings.py` now reads secret files from **two** folders,
`secrets_dir=["/run/secrets", "/run/bao"]`, and has `db_credentials_file` / `audit_db_credentials_file` next to the
now optional `db_password` / `audit_db_password`. A validator requires one of each pair, and `db_credentials()` /
`audit_db_credentials()` return a `CredentialsFile` when the file is set (it wins) or a `StaticCredentials`
otherwise.

> **READING THE SETTINGS**
> - Two secret folders: `/run/secrets` (Docker secrets from SOPS) and `/run/bao` (the agent's files). When a file is
>   in both, `/run/bao` wins (tested), which makes the cut-over gradual: add the agent first, remove the Docker
>   secrets later.
> - Either a credentials file or a password, never neither (tested): a missing setting fails at start-up, not on the
>   first search.

The two places that open database connections change only slightly:

- `search.py` (`PgSearch`): stores `s.db_host` and `s.db_credentials()`, and calls the credentials for **every**
  search: `user_name, password = self._credentials()` then
  `psycopg.connect(host=…, dbname="rag", user=user_name, password=password, application_name="rag-api")`.
- `audit.py` (`PgAuditLog`): takes `credentials: Credentials` instead of a password, and gives the pool a
  **function** for its connection arguments (`kwargs=connect_kwargs`), called for each new connection, plus
  `max_lifetime=1800`.
- `main.py`: `PgAuditLog(host=…, port=…, credentials=s.audit_db_credentials())`.

> **WHY THIS SURVIVES A ROTATION**
> - `psycopg_pool` accepts a function for connection arguments (since 3.3, so the requirement is now
>   `psycopg-pool>=3.3`), called for each new connection. So a new login is used the moment the agent writes it.
> - Old connections: when the old lease ends, OpenBao terminates its sessions. Step 23 already gave the pool
>   `check_connection`, so a killed connection is noticed and replaced before it's lent out. The live test watches
>   exactly that: a write, a rotation, the old user dropped, two more writes succeeding.
> - `max_lifetime=1800`: connections are recycled every 30 minutes anyway, well inside the 1-hour login.

Step 26's evaluation harness (`scripts/evals.py`) accepts the same file (`RAG_DB_READONLY_CREDENTIALS_FILE`) instead
of `RAG_DB_READONLY_PASSWORD`.

### 8 · Cut over, and keep a way back

`infra/config/rag-db/vault-cutover.sql` switches the shared group roles' logins off (`ALTER ROLE rag_app NOLOGIN;`,
the same for `rag_readonly` and `audit_writer`). They keep all their privileges: every short-lived user is created
`IN ROLE` one of them. `just vault-cutover` runs it; `just vault-cutover-undo` runs the same file with `NOLOGIN`
turned back into `LOGIN`.

The order matters; each step can be checked before the next:

1. `just vault-agent-start`, and the Compose changes for rag-api (credentials files, `/run/bao`). rag-api now uses
   `v-approle-…` users; the old passwords still exist but aren't used.
2. Check: in Postgres, `select usename, count(*) from pg_stat_activity group by 1` shows `v-approle-rag-api-…`, not
   `rag_app`. A search works; `just audit-verify` is clean.
3. `just vault-cutover`: the shared roles can no longer log in.
4. After a quiet week, remove the four old Docker secrets from rag-api and their values from SOPS.

```text
                       rolname                       |     rolvaliduntil      |  member_of
-----------------------------------------------------+------------------------+--------------
 v-approle-audit-wr-JpZbwXB0N2vJaehyXHZb-1791810578  | 2026-10-13 01:09:43+11 | audit_writer
 v-approle-rag-api-mEv3xiftzKveRUKScGQ1-1791810578   | 2026-10-13 01:09:43+11 | rag_app
 v-userpass-rag-read-nyIAq41oeN0qF5HLTlNl-1791810577 | 2026-10-13 01:09:42+11 | rag_readonly
```

**Rollback**, at any point before step 4: `just vault-cutover-undo`, put the two `*_PASSWORD` secrets back, remove
the `*_CREDENTIALS_FILE` variables, restart rag-api. A few minutes.

### 9 · Alerts and a runbook

Two alerts are added to `infra/config/prometheus/rules/security.yml`:

```yaml
      - alert: OpenBaoSealed
        expr: max(vault_core_unsealed) < 1
        for: 2m
        labels: { severity: critical, service: openbao }
        annotations:
          summary: "OpenBao is sealed: run just vault-up before credentials expire"
          runbook: docs/runbooks/openbao.md
      - alert: OpenBaoAuditFailing
        expr: sum(increase(vault_audit_log_request_failure[5m])) > 0
        labels: { severity: critical, service: openbao }
        annotations:
          summary: "OpenBao cannot write its audit log and is refusing requests"
          runbook: docs/runbooks/openbao.md
```

The metric names still start with `vault_` (OpenBao kept them for compatibility). The `max()` isn't decoration:
after unsealing, the metrics endpoint still reports the old series `vault_core_unsealed{cluster=""} 0` next to the
new `…{cluster="vault-cluster-…"} 1`, and a plain `vault_core_unsealed == 0` would have alerted for a day. Two new
unit tests in `infra/config/prometheus/tests/rules_test.yml` cover both alerts, including that stale series
(`promtool test rules`: SUCCESS).

The runbook `docs/runbooks/openbao.md` covers: `OpenBaoSealed` (or any restart: `just vault-status`,
`just vault-up`, check; never re-initialise a server that holds data), `OpenBaoAuditFailing` (disk full? rotate the
log with a rename and SIGHUP, archive it, never remove the audit stanza), rag-api failing to log in with a
`v-approle-…` user (agent restarted, wrapping token already used = security incident, policy changed, OpenBao
down; rollback), a possibly leaked secret (revoke a lease or a prefix, rotate a static secret at its source, destroy
a secret ID accessor, change the admin password; `sys/audit-hash` to find a value in the log), and break-glass
(`bao operator generate-root` with 2 shares, then revoke and record).

### 10 · What OpenBao records

Every request and response is one JSON line in `/openbao/logs/audit.log`. The agent fetching rag-api's login,
shortened:

```json
{
  "time": "2026-10-12T13:09:38.743740253Z",
  "type": "response",
  "auth": {
    "client_token": "hmac-sha256:d5491ee4…",
    "display_name": "approle",
    "policies": ["default", "rag-api"],
    "metadata": { "role_name": "rag-api" }
  },
  "request": { "operation": "read", "path": "database/creds/rag-api", "remote_address": "127.0.0.1" },
  "response": {
    "secret": { "lease_id": "database/creds/rag-api/Y62BJ4GXPO6RVhKlH6WRl4n2" },
    "data": { "password": "hmac-sha256:99bc0119…", "username": "hmac-sha256:99c095e1…" }
  }
}
```

You can see who (the AppRole `rag-api`, from which address), what (`read database/creds/rag-api`), and which lease,
but not the username or password: both are `hmac-sha256:…`. If a password turns up somewhere it shouldn't,
`bao write sys/audit-hash/file input=<the password>` gives its HMAC, and a search of the log tells you exactly when
and to whom it was issued.

This is a second audit trail beside Step 23's: Step 23 records what *users* did in the platform; this one records
what *machines and administrators* did with *secrets*.

### 11 · Test it, for real

Every test that matters runs against a real OpenBao started from the real `server.hcl`, configured by the real
setup script, against the throwaway Postgres from Step 23, with the real agent configuration. Only paths and ports
are swapped (`real_config()` fails the test if a replaced string disappears from the file).

`tests/test_vault.py` (16 tests; needs `bao` on PATH and `AUDIT_TEST_ADMIN_DSN`, skips otherwise):

- **The setup script**: converges and never needs the bootstrap password again (the old password now fails for
  both admin logins); refuses a server without an audit device; refuses a first run without the bootstrap password.
- **Dynamic credentials**: a `rag-api` login works in the `rag` database with `statement_timeout = 30s`, can do DML
  but not DDL, isn't a superuser or CREATEROLE, and has `VALID UNTIL` about an hour ahead; renewing the lease moves
  `VALID UNTIL`; `rag-readonly` can read but not write; `audit-writer` can call `audit.append()` but not read events,
  and can't even connect to `rag`; revoking a lease ends the open session and drops the user.
- **Who may do what**: rag-api's AppRole token reads its 3 paths and gets 403 on four others; a wrapped secret ID
  unwraps exactly once; the admin login writes secrets but can't read them (or rag-api's creds), can get a read-only
  login, and can re-run setup; the audit log holds HMACs, not values; the metrics need no token and hold no secrets;
  a sealed server answers 503.
- **The agent**: writes 0400 files, deletes its secret ID, rotates the login (tokens shortened to 6 s / 12 s) while
  `PgAuditLog` keeps writing through the rotation; and refuses to render anything with an already-used secret ID
  (`wrapping token is not valid or does not exist`).

`libs/rag-common/tests/test_secrets.py` (10 tests: reading the pair, picking up a new pair immediately, not re-reading
an unchanged file, five broken files failing without leaking content, a missing file, `StaticCredentials`' `repr`)
and `services/rag-api/tests/test_settings.py` (4 tests: static passwords still work, OpenBao files win, a login is
required, `/run/bao` overrides `/run/secrets`).

> **THE TEST DATABASE NOW CHECKS PASSWORDS**
> Step 23's throwaway Postgres used `trust` authentication: any password works. That would make half of these tests
> meaningless ("the old password stops working" passes trivially). The test database now has a real password,
> `test-admin`, in `just audit-test` (`POSTGRES_PASSWORD=test-admin`,
> `AUDIT_TEST_ADMIN_DSN=postgres://postgres:test-admin@127.0.0.1:55432/postgres`) and in CI's `checks` job, which
> also installs `bao` with the pinned tools (`scripts/ci_tools.py opa regal dbmate bao`).

```bash
just audit-test          # 220 passed in the guide's count
just ci                  # including just vault-check
```

> **WHAT YOU SHOULD SEE**
> 220 passed: 190 from before (three Step 23 tests now pass `StaticCredentials`), 16 against a live OpenBao, 10
> `CredentialsFile` tests and 4 settings tests. Beyond the tests, the whole command-line flow in this chapter (init,
> unseal, setup, revoke root, login, put, creds, agent, unseal after a restart) ran against a scratch server.
> `just ci`'s static, policy and supply-chain parts are green (gitleaks, actionlint, zizmor, licences, Trivy).

### 12 · Record the decision

```bash
just adr "Issue database credentials dynamically from OpenBao"
```

`docs/adr/0028-issue-database-credentials-dynamically-from-openbao.md` records the context (long-lived shared
passwords, no usage audit), the decision (everything above), the alternatives (HashiCorp Vault, SOPS only, Infisical
/ Doppler / 1Password, cloud secret managers, Kubernetes Secrets + External Secrets Operator, Postgres IAM/OIDC
authentication), the consequences (per-client, expiring, revocable, audited logins and no human-known admin
passwords; but a new critical service, manual unsealing, and a fresh secret ID after every agent restart) and when to
revisit (Kubernetes in Step 29, more than one node, managed Postgres with IAM authentication).

```bash
git add -A
git commit -m "feat(secrets): OpenBao with dynamic database credentials, AppRole agent and audit"
git push -u origin feat/vault
gh pr create --fill && gh pr checks --watch
gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Leaks have a short life**: a stolen database login expires within the hour, or the minute you revoke it.
- **Every client is distinguishable**: each login is a unique Postgres user, visible in `pg_stat_activity` and the
  database logs.
- **Full record**: who received which secret, when, from where, in OpenBao's audit log, without the values
  themselves.
- **Rotation without pain**: new logins arrive before the old ones expire; rag-api doesn't restart.
- **Smaller blast radius**: rag-api holds no OpenBao token; its policy reaches three paths. Admin passwords are known
  only to OpenBao.
- **Everything reviewable**: policies, roles and settings are code, applied by one script, checked in CI.

## Drawbacks and risks

- **A new critical service.** Sealed or down means no new logins. Existing ones last up to an hour, so there's time,
  but someone must act (`just vault-up`, the `OpenBaoSealed` alert).
- **Manual unsealing.** After every restart. Cloud setups use auto-unseal with a KMS; on a Mac there's no KMS to lean
  on.
- **Agent restarts need you.** The single-use secret ID is safer but means `just vault-agent-start` after any
  restart. The alternative (a reusable secret ID on disk) trades safety for convenience.
- **More moving parts to understand**: leases, tokens, policies, wrapping. Mistakes in policies fail closed (403),
  which is the safer direction, but still an outage.
- **The unseal shares are the crown jewels.** Lost: data gone. Leaked with a volume copy: everything readable.
- **Not every secret moves**: the Langfuse key and the SOPS bootstrap values stay in SOPS for now.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **OpenBao** (our choice) | Open-source Vault: dynamic secrets, policies, audit, agent | You want Vault's model without the BUSL licence |
| **HashiCorp Vault / HCP Vault** | The original, self-hosted or as a managed service | Your company already runs it or needs Enterprise features (namespaces, replication, HSM) |
| **AWS Secrets Manager / Azure Key Vault / Google Secret Manager** | Cloud-managed secret stores, tied to cloud IAM | You run in that cloud; rotation via cloud functions |
| **SOPS (Step 6) only** | Encrypted files in git | Small, static secrets; no server to run |
| **Infisical, Doppler, 1Password Secrets Automation** | Hosted or self-hosted secret stores with good UIs | Mainly static secrets, teams wanting a UI |
| **External Secrets Operator / Secrets Store CSI** | Bring secrets from a store into Kubernetes | In Kubernetes (Step 29), on top of a store like OpenBao |
| **Passwordless database auth (IAM, OIDC, mTLS client certs)** | No password at all; identity proves access | Managed databases that support it; certificates from OpenBao's PKI engine |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| One person, one Mac (this guide) | This step: OpenBao, manual unseal, AppRole agent, SOPS for bootstrap |
| Small team | Same, with the 3 unseal shares held by 3 people, an OIDC login (Keycloak) for humans, backups of the raft snapshots |
| Kubernetes (Step 29) | OpenBao in the cluster, Kubernetes auth instead of AppRole, agent injector or CSI driver, auto-unseal via a cloud KMS |
| All-in on one cloud | That cloud's secret manager plus IAM database authentication where possible |
| Regulated environment | HSM- or KMS-backed unseal, audit logs shipped to append-only storage (like Step 23's archive), per-team namespaces, periodic access reviews |

## Common mistakes

- Using the root token day to day, or leaving it unrevoked after setup.
- Unseal keys next to the data (same disk, same backup), or all shares with one person in a team.
- A superuser as OpenBao's database login. `CREATEROLE` with `ADMIN OPTION` on specific groups is enough.
- Forgetting that role settings aren't inherited: dynamic users without `statement_timeout` or the read-only flag.
- No `VALID UNTIL`: if OpenBao is lost, its users live forever.
- Reading the database password once at start-up, then failing an hour later.
- Secret IDs in environment variables, images or git; unwrapped secret IDs passed around.
- Running without an audit device, or "fixing" a full audit disk by removing it.
- `tls_disable` outside a private network.
- Policies with `path "*"` "to get it working".
- Switching the old passwords off before checking that every client uses the new logins.

## Done when

- [ ] `just tools bao` installs OpenBao 2.7.1; `bao status` shows `Sealed false` after `just vault-unseal`
- [ ] `secrets/openbao-init.enc.json` is committed (encrypted); the root token is revoked
- [ ] `just vault-setup` runs clean with your admin login and changes nothing on a second run
- [ ] `just vault-creds rag-readonly` gives a login that reads but can't write and expires in an hour
- [ ] `rag-api-agent` is healthy; `pg_stat_activity` shows `v-approle-rag-api-…` users, not `rag_app`
- [ ] `just vault-cutover` done; a search works; `just audit-verify` is clean
- [ ] Prometheus shows the `openbao` target up; `OpenBaoSealed` fires when you seal it on purpose
      (`bao operator seal`), and clears after `just vault-up`
- [ ] `just audit-test` shows 220 passed; `just ci` (with `vault-check`) passes
- [ ] ADR-0028 is merged

## Recap

> **RECAP**
> The platform has a front desk for secrets:
> - OpenBao stores secrets encrypted, opens only with 2 of 3 key shares, and writes down every request
> - database logins are issued on demand: a unique user per client, valid for an hour, renewed while needed, replaced
>   automatically, cancelled in one command
> - rag-api never sees OpenBao: an agent logs in with a single-use, wrapped secret ID and keeps fresh logins in
>   memory-only files, which rag-api reads for every new connection
> - no standing master keys: the database admin passwords were rotated away, the root token revoked; people use a
>   limited login, machines a policy each
> - tested for real: 30 new tests against a live OpenBao and Postgres, including a rotation while the audit log keeps
>   writing
>
> Next, the final step, Step 29: Kubernetes and GitOps with Argo CD: the whole platform declared as code, deployed by
> GitOps, with signed images verified before they run, and Kubernetes identities replacing AppRole.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `ci/tools.yaml` | Adds `bao` 2.7.1 (Linux and macOS archives, SHA-256 from the release's `checksums.txt`). |
| `infra/config/openbao/server.hcl` | The OpenBao server: raft storage, plain HTTP on the private network, metrics, file audit device. |
| `infra/config/openbao/agent-rag-api.hcl` | rag-api's agent: AppRole auto-auth with a wrapped single-use secret ID, four 0400 templates. |
| `infra/config/openbao/policies/rag-api.hcl` | rag-api may read its two creds paths and its KV secret, nothing else. |
| `infra/config/openbao/policies/rag-evals.hcl` | The evaluation harness: read-only database login and its own KV secret. |
| `infra/config/openbao/policies/developer.hcl` | A person: a short-lived read-only database login. |
| `infra/config/openbao/policies/platform-admin.hcl` | Day-to-day administration without the root token; writes secrets but can't read them. |
| `infra/compose/compose.yaml` | The `openbao` and `rag-api-agent` services, rag-api's credentials files and `/run/bao` volume, rag-db's bootstrap secret, three volumes and one secret. |
| `infra/config/rag-db/init/03-openbao.sh` | Creates `vault_admin_rag` / `vault_admin_audit` (CREATEROLE, ADMIN OPTION on the group roles only). |
| `infra/config/rag-db/vault-cutover.sql` | Switches the shared group roles' logins off (undo: the same file with LOGIN). |
| `infra/config/prometheus/prometheus.yml` | The `openbao` scrape job (`/v1/sys/metrics?format=prometheus`, no token). |
| `infra/config/prometheus/rules/security.yml` | `OpenBaoSealed` and `OpenBaoAuditFailing` (both critical). |
| `infra/config/prometheus/tests/rules_test.yml` | Unit tests for both alerts, including the stale `cluster=""` series. |
| `scripts/vault_setup.py` | OpenBao configuration as code plus unseal, put, role-id, wrapped secret-id and creds. |
| `libs/rag-common/src/rag_common/secrets.py` | `Credentials`, `StaticCredentials`, `CredentialsFile`, `CredentialsUnavailable`. |
| `services/rag-api/src/rag_api/settings.py` | Secrets from `/run/secrets` and `/run/bao`; credentials file or password for each database. |
| `services/rag-api/src/rag_api/search.py` | Asks for the current login on every connection. |
| `services/rag-api/src/rag_api/audit.py` | The pool calls the credentials for each new connection; connections recycled every 30 minutes. |
| `services/rag-api/src/rag_api/main.py` | Builds `PgAuditLog` from `audit_db_credentials()`. |
| `services/rag-api/pyproject.toml`, `uv.lock` | `psycopg-pool>=3.3` (callable connection arguments). |
| `scripts/evals.py` | `RAG_DB_READONLY_CREDENTIALS_FILE` as an alternative to `RAG_DB_READONLY_PASSWORD`. |
| `justfile` | The `vault-*` recipes, `vault-check` in `ci-config`, a password-checked `audit-test`. |
| `.github/workflows/ci.yml` | Postgres service with a real password, the matching DSN, and `bao` among the pinned tools. |
| `.gitignore` | `.bao/` (the agent's role/secret ID and short-lived logins). |
| `.env.example`, `scripts/new-dev-secrets.sh` | `VAULT_ADMIN_PG_PASSWORD` and `BAO_ADMIN_PASSWORD`. |
| `secrets/README.md` | How `secrets/openbao-init.enc.json` is made, its (dummy) structure, and how to handle the shares. |
| `tests/test_vault.py` | 16 tests against a live OpenBao and Postgres (plus mocked setup checks). |
| `libs/rag-common/tests/test_secrets.py` | 10 `CredentialsFile` / `StaticCredentials` tests. |
| `services/rag-api/tests/test_settings.py` | 4 tests on where rag-api's logins come from. |
| `tests/test_ci_tools.py`, `tests/test_monitoring.py`, `tests/test_rag_api.py`, `tests/test_rag_db.py`, `tests/test_audit_db.py`, `tests/conftest.py`, `services/rag-api/tests/test_service.py` | Updated for the ninth tool, the new scrape job, alerts and rule tests, rag-api's new dependency, rag-db's new secret, `StaticCredentials` and per-connection credentials. |
| `docs/runbooks/openbao.md` | Sealed, audit failing, login failures, leaks, break-glass. |
| `docs/adr/0028-issue-database-credentials-dynamically-from-openbao.md` | ADR-0028 (and its row in `docs/adr/README.md`). |
| `docs/glossary.md` | The step's new terms. |
| `docs/steps/step-28-vault-dynamic-secrets.md` | This write-up (and its row in `docs/steps/README.md`). |

## Notes for this repository

- **No unseal keys or root token are committed.** `secrets/openbao-init.enc.json` can only be produced honestly by
  running `just vault-init` against your own server with your own age key, so it is not in the repository. Its
  structure (with dummy values) and the exact `sops` command are documented in `secrets/README.md`. The
  `secrets-encrypted` pre-commit hook would refuse a plaintext copy anyway.
- **Image source and digest.** The guide pulls `quay.io/openbao/openbao:2.7.1@sha256:<digest>`. quay.io was not
  reachable from the build container, so Compose uses the same release from Docker Hub (the guide notes it is "also on
  Docker Hub as `openbao/openbao`"), pinned by the digest verified there:
  `openbao/openbao:2.7.1@sha256:6d2b93856e3fcf7b18ad855a0b51eaba474dc8b79cf554379ea32034797d2acf`.
- **Gradual cut-over kept in Compose.** The guide's Compose excerpt shows rag-api's final state with only the Langfuse
  secret and a comment listing the four to remove "after the cut-over". This repository keeps the four Docker secrets
  for now (with that comment), because removing them is step 4 of the cut-over, done after a quiet week. With both
  present, `/run/bao` wins and the `*_CREDENTIALS_FILE` variables take precedence over the passwords.
- **`just vault-secret-id`.** `scripts/vault_setup.py`'s docstring mentions `just vault-secret-id rag-api`, which the
  guide's justfile excerpt doesn't define; a one-line recipe was added so the docstring is true.
- **`compose` variable.** The guide's justfile section re-declares `compose := "docker compose -f …"`; it already
  exists at the top of the justfile (Step 9), and `just` refuses duplicate variables, so it is reused.
- **`test_first_run_needs_the_bootstrap_password`** takes the live `env` fixture in the guide although it only uses a
  mock transport; here it runs without OpenBao (so it also runs when `bao` isn't installed) and additionally asserts
  that the script looked for the connection before refusing.
- **PgAuditLog signature.** The old `password=` / `user=` arguments are replaced by `credentials=`; the three Step 23
  tests pass `StaticCredentials("audit_writer", …)`, as the guide says.
- **Validation in this repository.** All 30 new tests passed against the real `bao` 2.7.1 binary and a
  password-checked `pgvector/pgvector:0.8.7-pg17` container (full suite: 485 passed). In addition, the Compose
  services themselves were run end to end in an isolated project: rag-db ran `03-openbao.sh` on a fresh volume,
  OpenBao initialised, unsealed through `vault_setup.py unseal`, `setup` produced exactly the output shown above,
  the agent rendered the four 0400 files as user 10001 and deleted its secret ID, `v-approle-…` users appeared with
  `VALID UNTIL` an hour ahead, the cut-over SQL and its undo ran, the root token was revoked and setup re-ran with
  the admin login. The stale `vault_core_unsealed{cluster=""} 0` series the guide describes appeared exactly as
  described. Everything was deleted afterwards. `just ci` passes, except that zizmor's *online* audits cannot reach
  the GitHub API from this sandbox (they fail on the unchanged workflows too); `zizmor --offline` reports no findings.
