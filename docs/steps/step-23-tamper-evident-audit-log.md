# Step 23 · A tamper-evident audit log

*Step 23 of 38 · Phase F · Audit & governance*

## At a glance

| | |
|---|---|
| **Goal** | Keep a record of **who did what, when, and with what result** that nobody can quietly change: not a hacker inside rag-api, not the database owner, and not even a database superuser. |
| **How, in one sentence** | Every event carries a fingerprint of the event before it (a **hash chain**), the table refuses changes, rag-api may only **add** events, and every hour the newest fingerprint is copied into **write-once storage** (Step 14's object-locked bucket), where nobody can touch it. |
| **Time** | About 2.5 hours. |
| **You'll end up with** | A separate `audit` database on rag-db with three roles: `audit_writer` (rag-api: may only append), `audit_reader` (jobs and auditors: read only), `audit_migrator` (owns the schema) · an append-only `audit.events` table with a SHA-256 hash chain, a single entry point `audit.append()`, and `audit.verify()` that finds the first broken link · rag-api recording every search (which document ids went to whom), every refusal and every admin action, and **failing closed**: no record, no data · `just audit-anchor` (hourly) and `just audit-verify` (daily), which copy the chain to the object-locked bucket and prove that database and archive still agree · an alert, `RagAuditWriteFailing`, and a runbook · 32 new tests in the guide (72 in its count), including real tampering attacks against a real Postgres · ADR-0023. |
| **New words** | audit log, tamper-evident vs tamper-proof, hash function, SHA-256, hash chain, genesis, head, append-only, trigger, `SECURITY DEFINER`, search-path hijacking, table lock, anchoring, manifest, WORM, delete marker, fail closed, break-glass, pseudonymous, crypto-shredding, transparency log, Merkle tree, RFC 3161 timestamp. |

## The big idea

> **ANALOGY · THE NOTARY'S LEDGER AND THE BANK VAULT**
> Picture a notary's ledger with numbered pages. At the bottom of each page, the notary presses a wax seal
> whose pattern is made from everything on that page **plus the seal of the page before**. Change a single
> word on page 2 and its seal no longer fits. Re-make page 2's seal to hide it, and page 3's seal (made from
> the old page 2 seal) no longer fits. To hide one change, you'd have to re-make every seal after it.
>
> A determined forger with the whole book and plenty of time could do that. So every hour, the notary
> photocopies the newest pages and their seals and drops them into a **bank vault** that nobody can open or
> empty until a set date, not even the notary. Now a forger would also have to break into the vault.
>
> In this step:
> - the ledger is the `audit.events` table
> - the seal is a SHA-256 hash
> - the vault is the object-locked bucket from Step 14

```text
 Each row carries the previous row's fingerprint. Row 1 starts from 32 zero bytes (the genesis).

   row 1                      row 2                      row 3                        row 4
   alice · search · allowed   alice · search · allowed   alice · admin:ping · denied  dana · admin:ping · allowed
   prev_hash  000000…   ┌──>  prev_hash  666299…   ┌──>  prev_hash  3c79b2…     ┌──>  prev_hash  9be189…
   hash = sha256(       │     hash = sha256(       │     hash = sha256(         │     hash = sha256(
     prev + row) 666299…┘       prev + row) 3c79b2…┘       prev + row) 9be189… ─┘       prev + row) 5157d7…

 Change anything in row 2 (one id, one letter)…
 …and its recomputed fingerprint no longer equals its stored hash: "contents changed", caught at row 2.
 Recompute row 2's hash to hide it, and row 3's prev_hash no longer matches: "link broken", caught at row 3.
```

*Figure 72. A hash chain. Each row stores the previous row's hash and its own hash, computed from the
previous hash plus its own contents. Editing a row breaks its own hash; hiding that by recomputing it breaks
the next row's link.*

## What we're doing

1. Create a **separate audit database** and three least-privilege roles (a one-time bootstrap script).
2. Write the **migration**: the `audit.events` table, the hash-chain function `audit.append()`, the checker
   `audit.verify()` and a trigger that refuses every change.
3. Make **rag-api record** searches, refusals and admin actions, and **fail closed** when it can't.
4. **Test it against a real Postgres**, including the attacks: edited rows, deleted rows, full rewrites, roles
   overstepping, concurrent writers, database restarts.
5. **Anchor** the chain hourly in the write-once bucket, and **verify** database and archive against each other.
6. Add an **alert and a runbook**, then record **ADR-0023**.

## Why we're doing this

> **WHY THIS MATTERS**
> Logs answer "what went wrong?". An audit log answers a different question: **"who saw what, and can you
> prove it?"**
>
> For a RAG platform that question comes up constantly:
> - a document turns out to have been mis-classified: who received it while it was wrong?
> - an employee leaves under a cloud: what did they search for and read in their last month?
> - a customer or regulator asks for evidence that only authorised people accessed their data
>
> Ordinary logs can't answer this well. They're sampled, rotated after days, mixed with debug noise, and
> anyone with server access can edit them. An audit log is the opposite: **complete** for the events it
> covers, **kept for years**, **minimal** in content, and **tamper-evident**: if it's changed, you can tell.

| Need | How this step meets it |
|---|---|
| A record of every data access | rag-api records each search with the ids of the documents returned, and each refusal and admin action |
| Nothing handed out without a record | Fail closed: if the event can't be stored, the request gets a 503 and no documents |
| The application can't cover its tracks | rag-api's role can only call `audit.append()`: no read, no update, no delete |
| Rows can't be edited or deleted | An append-only trigger refuses `UPDATE`, `DELETE` and `TRUNCATE`, even for the table's owner |
| Any change is detectable | A SHA-256 hash chain, checked by `audit.verify()` |
| Even a superuser can't rewrite history unnoticed | Hourly anchors in an object-locked bucket; `just audit-verify` compares |
| No new privacy problem | Only pseudonymous ids, actions, outcomes and document ids. Never names, questions or content |
| Link to everything else | The trace id, so one event opens the full request in Tempo, Loki and Langfuse |

> **IN A COMPANY**
> Audit logging is required, by name, by almost every security standard and regulation a platform like this
> meets:
> - **ISO/IEC 27001:2022**, control A.8.15 *Logging*: logs of user activities must be produced, kept and
>   protected from tampering.
> - **SOC 2**: auditors test that access to sensitive data is logged and that the logs are protected.
> - **PCI DSS v4**, requirement 10: log all access to cardholder data and protect audit logs from modification.
> - **HIPAA** §164.312(b), audit controls, for health data.
> - **The EU AI Act**, Article 12, record-keeping: high-risk AI systems must automatically log events over
>   their lifetime.
> - **GDPR's accountability principle**: you must be able to show who processed personal data and why.
>
> In a review, you'll be asked four questions: *What do you record? Who can change it? How would you know if
> someone did? How long do you keep it?* This step gives a precise answer to each.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Audit log** | A permanent, minimal record of security-relevant actions: who, what, when, result. Not for debugging. |
| **Tamper-evident vs tamper-proof** | *Evident*: changes can't be hidden. *Proof*: changes are impossible. Nothing digital is truly tamper-proof against its own administrators; evident is the realistic, honest goal. |
| **Hash function, SHA-256** | Turns any data into a fixed 32-byte "fingerprint". The same input always gives the same fingerprint; changing one bit changes it completely; you can't work backwards or find two inputs with the same one. |
| **Hash chain** | Each record's hash includes the previous record's hash, so records are linked like a chain. |
| **Genesis** | The starting point of the chain: here, 32 zero bytes as the "previous hash" of row 1. |
| **Head** | The newest hash. It summarises the entire chain up to that point. |
| **Append-only** | Rows may be added, never changed or removed. |
| **Trigger** | Code the database runs automatically before or after a change; here, to refuse it. |
| **`SECURITY DEFINER`** | A database function that runs with the rights of its *owner*, not its caller. Lets rag-api append without having any table rights. |
| **Search-path hijacking** | Tricking a privileged function into calling an attacker's look-alike object. Prevented by fixing the function's `search_path`. |
| **Anchoring** | Copying the head (and the events) somewhere the database's administrators can't change, so a rewrite becomes visible. |
| **Manifest** | A small file describing one archived batch: first and last row, head hash, previous head, checksum. |
| **WORM / object lock** | Write Once, Read Many. The storage refuses deletes and overwrites until a retention date (Step 14). |
| **Delete marker** | In a versioned bucket, "delete" without a version id only hides the object behind a marker; the data remains. |
| **Fail closed** | When a safety check can't run, refuse rather than carry on without it. |
| **Break-glass** | Emergency super-powers (the superuser), used rarely, deliberately and visibly. |
| **Crypto-shredding** | Making data unreadable by destroying a key or a lookup, instead of deleting it. Used to reconcile "never delete" with "right to erasure". |
| **Transparency log, Merkle tree** | Public append-only logs (Certificate Transparency, Sigstore Rekor) built on hash trees, which allow small proofs that an entry is included. |
| **RFC 3161 timestamp** | A signed statement from a timestamping authority that some hash existed at a given time. |

> **IN PLAIN ENGLISH · TAMPER-EVIDENT, NOT TAMPER-PROOF**
> Whoever runs a computer can, in the end, change what's on it. So the honest promise isn't "nobody can
> change the log"; it's "nobody can change the log **without it showing**". Every design choice in this step
> serves that promise.

### What goes in, and what never does

An audit log is kept for years and read by auditors, security staff and sometimes lawyers. If it held
questions or document text, it would become the biggest copy of sensitive data in the company. So it records
**facts about the access, not the content**.

| Field | Example | Why |
|---|---|---|
| `seq` | `5` | Position in the chain; no gaps allowed |
| `occurred_at` | `2026-10-12T10:56:10.381952Z` | When, from the database clock |
| `actor` | `8f1c0000-…` (the token's `sub`) | Who, as a stable pseudonymous id. Never a name or email |
| `client_id` | `rag-cli` | Which application acted for them |
| `action` | `search`, `admin:ping` | The same action names as the policy (Step 18) |
| `outcome` | `allowed`, `denied`, `error` | What happened |
| `resource` | `documents` | What was acted on |
| `details` | `{"returned_ids": [1, 7], "k": 5, "query_chars": 28}` | Small facts: document ids (not titles), counts, refusal reasons |
| `trace_id` | `0b280632…` | Opens the full request in Tempo, Loki and Langfuse |
| `prev_hash`, `hash` | 32 bytes each | The chain |

> **NAMES ARE LOOKED UP, NOT STORED**
> To answer "what did Alice read?", an investigator finds Alice's `sub` in Keycloak, then searches the audit
> log for it. If Alice later invokes her right to erasure, her Keycloak account is deleted and the audit rows
> become anonymous **without changing a single byte of the chain**. That's crypto-shredding by lookup: the
> chain stays intact, and so does her privacy. Document ids work the same way: the titles live in
> `rag.documents`, under its own access rules.

### Who can do what

| Role | append | read | verify | UPDATE / DELETE | switch off triggers |
|---|:---:|:---:|:---:|:---:|:---:|
| `audit_writer` (rag-api) | yes | no | no | no | no |
| `audit_reader` (anchor & verify jobs, auditors) | no | yes | yes | no | no |
| `audit_migrator` (owns the tables, runs migrations) | – | yes | yes | refused by the trigger, even for the owner | **yes** |
| superuser `postgres` (break-glass admin) | – | yes | yes | **yes** | **yes** |

*Figure 73. The audit roles. rag-api can only append; jobs and auditors can only read and verify; the owner
can't change rows because of the trigger, but could switch it off; the superuser can do anything. Hence
anchoring outside the database.*

Being honest about the last two rows is the heart of good audit design. The trigger stops accidents and
ordinary roles, but the table's owner can switch triggers off, and a superuser can do anything.
Tamper-evidence is about making sure that **even they can't do it unnoticed**.

### Anchoring: a copy nobody can change

```text
  RAG-DB · DATABASE audit                                   S3 · rag-audit-archive (OBJECT LOCK)

   row 1  666299…                                          segments/000…001-000…005
   row 2  3c79b2…                                            the rows themselves (JSONL, gzip)
   row 3  9be189…  ── new rows ──>  just audit-anchor  ──>   a full, independent copy
   row 4  5157d7…                   hourly · audit_reader  manifests/000…005.json
   row 5  a441d0…                   re-checks, then copies   from 1 · to 5
                                                             head_hash a441d0…
   hash chain (catches edits)                                prev_head_hash 000000…
   head = newest hash                                      no one can delete or overwrite until the date

  just audit-verify: does the database still match the archive? A superuser who rewrites the whole chain
  produces a perfect-looking chain, but row by row it no longer matches the locked copy: caught.
```

*Figure 74. Anchoring. Every hour, the anchor job checks the new rows and copies them, with a manifest
holding the head hash, into the object-locked bucket. The verify job compares database and archive row by
row; a rewritten chain no longer matches.*

The archive does two jobs at once:
- **Evidence**: a rewrite in the database no longer matches the locked copy.
- **Backup**: the segments are a complete copy of the log, checkable with nothing but Python, even if the
  database is gone.

> **WATCH OUT · WHAT TAMPER-EVIDENT DOES NOT COVER**
> - **The newest hour.** Events written since the last anchor are protected only by the chain and the
>   trigger. Someone with superuser rights could delete or rewrite them before the next anchor. Anchor more
>   often if that window matters to you.
> - **Events that were never written.** The log records what rag-api reports. A compromised rag-api could
>   simply not report something. Defences live elsewhere: Keycloak's own login events (Step 16), the gateway's
>   request logs (Step 10), and database statement auditing (pgaudit) if you need it.
> - **Who wrote it.** A valid chain proves nothing was *changed*, not that the original entry was *true*.

### Fail closed

```text
 token ──> policy ──────> search + post-check ──> audit.append ──> 200 + results
 Step 17   Step 18        Steps 11, 18            this step
              │                                       │
            deny                                 can't store it
              │                                       │
     403 + 'denied' event                     503 · no documents
     best effort: nothing is handed out       fail closed

 The event (who, which document ids, trace id) is committed BEFORE the answer leaves. No record, no data.
```

*Figure 75. Where the audit write sits in a request. It happens after the policy and the search, before the
response. If it can't be stored, the request ends with 503 and no documents. A refusal is still a 403; its
event is best effort.*

For a refusal we record the event on a **best-effort** basis: nothing is handed out, so turning a 403 into a
503 would help nobody. The lost event is counted and logged.

## How to do it

On the Mac, in the project folder (the guide works on a feature branch):

```bash
cd ~/dev/rag-platform
git switch -c feat/audit-log
```

### 1 · Secrets

Three database passwords and two object-store identities (four values):

```bash
for i in 1 2 3 4 5 6 7; do openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-32; echo; done   # letters/digits only
just secrets-edit
#   AUDIT_DB_MIGRATOR_PASSWORD=<1st>
#   AUDIT_DB_WRITER_PASSWORD=<2nd>
#   AUDIT_DB_READER_PASSWORD=<3rd>
#   S3_AUDIT_ANCHOR_ACCESS_KEY=<4th>   S3_AUDIT_ANCHOR_SECRET_KEY=<5th>
#   S3_AUDIT_READER_ACCESS_KEY=<6th>   S3_AUDIT_READER_SECRET_KEY=<7th>
```

The seven names are in `.env.example` and in `scripts/new-dev-secrets.sh`, as in earlier steps, so a fresh
machine generates them automatically.

### 2 · A separate database, three roles

**Why a separate database, not just a schema in `rag`?** Postgres permissions start at the database: a role
that can't `CONNECT` can't even see what's inside. None of the `rag_*` roles from Step 11, not even
`rag_migrator`, can connect to `audit`.

The bootstrap lives in [`infra/config/rag-db/init/02-audit.sh`](../../infra/config/rag-db/init/02-audit.sh).
It creates the three roles (none a superuser), the `audit` database owned by `audit_migrator`, removes
`PUBLIC`'s right to connect, sets per-role timeouts, creates the `audit` schema and fixes each role's
`search_path`.

> **READING THE BOOTSTRAP**
> - `CREATE DATABASE audit OWNER audit_migrator`: the migrator owns it, so migrations never need the superuser.
> - `REVOKE ALL ON DATABASE audit FROM PUBLIC`: by default every role may connect to every database. Not this one.
> - `ALTER DEFAULT PRIVILEGES … REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`: a surprising Postgres default is
>   that every role may run every new function. For a schema whose main function writes the audit log, that's
>   switched off; each function is granted explicitly.
> - `statement_timeout = '5s'` for the writer: an audit write is tiny. If it takes longer, something is wrong,
>   and rag-api should fail fast rather than hang.
> - `SECRETS_DIR`: defaults to `/run/secrets` (Docker secrets); the tests point it at a temporary folder.

rag-db gets the three password files (in [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml)):

```yaml
rag-db:
  secrets: [rag_db_superuser_password, rag_db_migrator_password, rag_db_app_password, rag_db_readonly_password,
            rag_db_metrics_password,
            audit_db_migrator_password, audit_db_writer_password, audit_db_reader_password]

secrets:
  audit_db_migrator_password: { environment: AUDIT_DB_MIGRATOR_PASSWORD }
  audit_db_writer_password:   { environment: AUDIT_DB_WRITER_PASSWORD }
  audit_db_reader_password:   { environment: AUDIT_DB_READER_PASSWORD }
```

Init scripts in the mounted folder run automatically only on an **empty** volume. Your rag-db volume already
exists, so run the script once by hand. The `justfile` gains:

```text
audit_db_url := "postgres://audit_migrator:$AUDIT_DB_MIGRATOR_PASSWORD@127.0.0.1:5432/audit?sslmode=disable"

audit-bootstrap:          # one-time, on an EXISTING rag-db volume
audit-migrate *args="status":   # dbmate with --migrations-table audit.schema_migrations
audit-psql *args:         # superuser SQL shell on the audit database (break-glass: inside the container only)
```

```bash
just up                          # recreates rag-db with the new secrets mounted
just audit-bootstrap             # CREATE ROLE ×3, CREATE DATABASE, CREATE SCHEMA …
just audit-psql -c '\du audit_*' # the three roles
```

### 3 · The migration: table, chain, checker, guard

```bash
just audit-migrate new create_audit_log   # creates infra/db/audit/migrations/<timestamp>_create_audit_log.sql
```

The committed migration is
[`infra/db/audit/migrations/20261012090000_create_audit_log.sql`](../../infra/db/audit/migrations/20261012090000_create_audit_log.sql).
It creates:

- **`audit.events`** — the columns from the table above, with `CHECK`s on `outcome` and on both hashes being
  32 bytes, a `UNIQUE` hash, and two indexes: `(actor, occurred_at)` for "what did X do in March?" and
  `(trace_id)` for "which event is this trace?".
- **`audit.event_body(e)`** — the exact text that gets hashed: a JSON object of every field except the hashes,
  with the time in UTC and microseconds.
- **`audit.append(...)`** — the *only* way in: validates, locks, links, hashes and inserts; returns `seq`.
- **`audit.verify(p_from, p_to)`** — recomputes the chain and reports the first broken link.
- **`audit.forbid_change()`** and the **`events_append_only`** statement trigger.
- **Grants**: writer → `append`; reader → `SELECT`, `verify` and `event_body`. Nothing else.
- **`migrate:down`** that raises an error.

> **READING THE MIGRATION, PART 1: THE CHAIN**
> - `event_body(e)` builds the exact text that gets hashed: a JSON object of every field except the hashes.
>   Its time is formatted in UTC with microseconds, so the same row produces the same text on any machine, in
>   any session time zone (a test checks this).
> - `sha256(prev_hash || body)`: the new row's fingerprint covers its own contents and the previous
>   fingerprint. That one line is the whole chain.
> - `LOCK TABLE … IN EXCLUSIVE MODE`: only one append at a time. Without it, two simultaneous appends could
>   both read row 41 as "the latest" and both create a row 42 pointing at it: a **fork**. The lock allows
>   readers (verify, anchor) to carry on. It's released at commit, after about a millisecond.
> - `clock_timestamp()`, after the lock: the real time at that moment, so times always increase with `seq`.
>   (`now()` would give the transaction's start time instead.)
> - Validation: the actor, action and trace id must look right, and `details` is capped at 8 KB. An audit log
>   full of junk is as useless as none, and size limits stop it being used to smuggle content in.

> **READING THE MIGRATION, PART 2: THE GUARDS**
> - `SECURITY DEFINER`: `append()` runs with its owner's rights. `audit_writer` needs no rights on the table
>   at all, only `EXECUTE` on this one function. Everything it writes goes through the validation above.
> - `SET search_path = pg_catalog, pg_temp`: a classic attack on `SECURITY DEFINER` functions is to create a
>   look-alike function (say, a fake `sha256`) in a schema the caller controls, so the privileged function calls
>   it. Fixing the search path, with `pg_temp` last, and writing `audit.events` in full, closes that hole. This
>   is the PostgreSQL documentation's own advice.
> - The trigger refuses `UPDATE`, `DELETE` and `TRUNCATE` for everyone, including the owner. It's a
>   `FOR EACH STATEMENT` trigger, so it fires even if no row matches.
> - `REVOKE … FROM PUBLIC`, then exact grants: writer → `append`; reader → `SELECT`, `verify` and
>   `event_body`. Nothing else.
> - `migrate:down` raises an error. An audit log is never rolled back. Mistakes are fixed with a new,
>   forward migration.

> **READING THE MIGRATION, PART 3: VERIFY()**
> It walks the rows in order, recomputing each hash, and stops at the first problem with one of three messages:
> - `row N is missing`: a gap in the numbers (a deleted row)
> - `link broken`: this row's `prev_hash` isn't the previous row's hash (a row before it was changed and re-hashed)
> - `contents changed`: this row's stored hash doesn't match its contents (this row was edited)
>
> It runs as one statement, so it sees a consistent snapshot even while rag-api keeps appending.

```bash
just audit-migrate up
just audit-migrate status   # [X] 20261012090000_create_audit_log.sql
```

### 4 · Try it by hand

```bash
just audit-psql
```

```sql
SET ROLE audit_writer;
SELECT audit.append('8f1c0000-alice', 'rag-cli', 'search', 'allowed', 'documents', '{"returned_ids": [1, 2]}');
--   1
SELECT * FROM audit.events;
--   ERROR: permission denied for table events          ← the writer can't even read
RESET ROLE; SET ROLE audit_reader;
SELECT seq, actor, action, encode(prev_hash, 'hex') AS prev, encode(hash, 'hex') AS hash FROM audit.events;
SELECT * FROM audit.verify();
--   ok | checked | first_bad_seq | problem
--   t  |       1 |               |
RESET ROLE; SET ROLE audit_migrator;
UPDATE audit.events SET actor = 'someone-else';
--   ERROR: audit.events is append-only: UPDATE is not allowed   ← even the owner
RESET ROLE;
```

`SET ROLE` works here because you're the superuser: exactly the break-glass power the anchors exist to keep honest.

### 5 · rag-api: record, or refuse

```bash
uv add --package rag-api "psycopg-pool>=3.2"
```

[`services/rag-api/src/rag_api/audit.py`](../../services/rag-api/src/rag_api/audit.py) defines the
`AuditEvent` dataclass, the `AuditUnavailable` error, the `AuditLog` protocol, `current_trace_id()` and
`PgAuditLog`, which calls `SELECT audit.append(...)` over a small connection pool.

> **READING AUDIT.PY**
> - `AuditLog` protocol: the API depends on "something that can `record()`", so tests use a fake and
>   production uses `PgAuditLog`.
> - A small pool (1–4 connections), **autocommit**: each event is committed the instant `append()` returns.
>   No half-finished transactions holding the chain's lock.
> - `timeout=2.0`: the longest a request waits for a working connection. Then it fails, and the API answers
>   503 fast instead of hanging.
> - `check=ConnectionPool.check_connection`: before lending out a connection, the pool checks it's still alive
>   (one tiny round trip). Without it, after a database restart the pool lends out dead connections and
>   requests fail needlessly. The tests for this step caught exactly that, and a test now guards it.
> - `AuditUnavailable` carries only the error's *type*, never connection details.
> - `current_trace_id()`: the request's trace id (Step 19), so an auditor can jump from an event to the full request.

[`settings.py`](../../services/rag-api/src/rag_api/settings.py) gains `audit_db_host` (default `rag-db`),
`audit_db_port` (5432) and `audit_db_password` (secret file `/run/secrets/rag_api_audit_db_password`).

[`main.py`](../../services/rag-api/src/rag_api/main.py) gains `get_audit()`, the counter
`rag.audit.write_failures`, the helpers `audit_event()`, `record_or_refuse()` and `record_best_effort()`, a
`denied` event inside `authorize()`, the `search` event after the post-check, and an `admin:ping` event.

> **READING THE CHANGES TO MAIN.PY**
> - `record_or_refuse()` is for anything that hands out data or changes something: searches and admin
>   actions. If the event can't be stored, the request ends with 503 "Audit log unavailable", and the
>   documents are never sent.
> - `record_best_effort()` is for refusals (inside `authorize`). A refusal hands out nothing, so a failed write
>   is counted and logged, and the answer stays 403.
> - **Position in the search**: after the policy post-check (so the ids are exactly what the user will
>   receive) and before the `return`. Recording after sending would make "fail closed" impossible.
> - `details` holds the returned ids, how many were dropped by the post-check, `k`, and the question's
>   *length*. Never the question.
> - `rag.audit.write_failures`, started at 0 for both outcomes (the Step 20 lesson), feeds the new alert. A
>   failed search also counts as a search error, so the search SLO (Step 20) sees it too.
> - **Not recorded**: requests with a bad or missing token (401). There's no verified identity to record;
>   failed sign-ins are Keycloak's events (Step 16).

Compose gives rag-api the writer password and the host:

```yaml
rag-api:
  environment:
    RAG_API_AUDIT_DB_HOST: rag-db
  secrets:
    - rag_api_audit_db_password   # -> /run/secrets/rag_api_audit_db_password

secrets:
  rag_api_audit_db_password: { environment: AUDIT_DB_WRITER_PASSWORD }
```

### 6 · Test it

**Unit tests** use a `FakeAudit` (in
[`services/rag-api/tests/conftest.py`](../../services/rag-api/tests/conftest.py)) that stores events in a list
and can be switched "down". [`services/rag-api/tests/test_audit.py`](../../services/rag-api/tests/test_audit.py)
has six tests: a search is recorded with the returned ids and nothing sensitive (not the question, the
username, an e-mail address or a title); a refusal is recorded with its reason; an admin action is recorded;
no audit, no data (503); an audit outage doesn't turn a 403 into a 503; a bad token isn't an audit event.

**Database tests** need a real Postgres, because the guarantees live in SQL: roles, triggers, locks and
hashes. They use a throwaway container on port 55432 and run the **real bootstrap script and the real dbmate
migration**, exactly as production does. The script needs `psql` on your Mac, so the Brewfile gains:

```ruby
# ---- Audit log tests (Step 23) ----
brew "libpq"   # psql and pg_isready without a full Postgres server (keg-only: /opt/homebrew/opt/libpq/bin)
```

[`tests/conftest.py`](../../tests/conftest.py) provides the `audit_db` fixture (drop and recreate the
`audit` database and roles, run `02-audit.sh` with password files, run `dbmate up` as the migrator), the
`chain` fixture (empty the table as superuser with triggers off), and the helpers `append()`, `tamper()` and
`REWRITE_FROM_2` (the strongest attack: change a row, then recompute every later hash).

[`tests/test_audit_db.py`](../../tests/test_audit_db.py) has 17 tests: the chain, every role's limits, the
trigger (×3), validation, time zones, 8 concurrent writers producing 200 gap-free rows, the four attacks, the
refused rollback, and rag-api's real `PgAuditLog`, including surviving a database restart and failing within
2 seconds when the database is down.

> **THE ATTACKS THE TESTS RUN**
> The tampering tests act as a superuser who sets `session_replication_role = replica`, a real Postgres
> setting (meant for replication tools) that skips ordinary triggers. So the trigger is no obstacle, and only
> the chain and the anchors remain. Four attacks:
> - **Edit one row**: caught at that row (`contents changed`).
> - **Edit and re-hash one row**: caught at the next row (`link broken`).
> - **Delete a row in the middle**: caught (`row 2 is missing`).
> - **Rewrite everything after the edit, or chop off the newest rows**: `verify()` says ok. The test asserts
>   that on purpose, to document the limit. The anchor tests in step 7 catch both.

The `justfile` gains `audit-test`, which starts the same pinned image as rag-db
(`pgvector/pgvector:0.8.7-pg17@sha256:…`) with `POSTGRES_HOST_AUTH_METHOD=trust` on `127.0.0.1:55432`, waits
with `pg_isready -h 127.0.0.1`, runs the whole suite with `AUDIT_TEST_ADMIN_DSN` set, and stops (deletes) the
container on exit.

> **TIP · WHY TRUST AUTHENTICATION IS OK HERE**
> `trust` authentication is acceptable only because the container listens on `127.0.0.1`, holds nothing, and
> is deleted when the tests end. `pg_isready -h 127.0.0.1` waits for the real server: during first start, the
> image runs a temporary one that only listens on a local socket.

```bash
just check        # the database tests skip without AUDIT_TEST_ADMIN_DSN
just audit-test   # everything, including the database and anchor tests
```

> **WHAT YOU SHOULD SEE**
> In the guide's count, 72 passed: 40 from before, 6 rag-api tests, 17 database tests and 9 anchor tests
> (next section). This repository has many more tests (configuration tests from every step); see "Notes for
> this repository".

### 7 · Anchor the chain in the write-once bucket

Two new object-store identities, scoped to the archive bucket. The anchor job can write; the verifier and
auditors can only read (added to the `s3.json` the object store builds at start-up, plus four secrets):

```json
{"name": "audit-anchor", "credentials": [{"accessKey": "$$(cat /run/secrets/s3_audit_anchor_access_key)", "secretKey": "$$(cat /run/secrets/s3_audit_anchor_secret_key)"}],
 "actions": ["Read:rag-audit-archive", "Write:rag-audit-archive", "List:rag-audit-archive"]},
{"name": "audit-reader", "credentials": [{"accessKey": "$$(cat /run/secrets/s3_audit_reader_access_key)", "secretKey": "$$(cat /run/secrets/s3_audit_reader_secret_key)"}],
 "actions": ["Read:rag-audit-archive", "List:rag-audit-archive"]}
```

The anchor and verify commands live in one script,
[`scripts/audit_chain.py`](../../scripts/audit_chain.py). Both connect to Postgres as `audit_reader`:
**anchoring never needs write access to the database**. Objects go under
`audit/segments/<first>-<last>.jsonl.gz` (the rows: `seq`, `prev_hash`, `hash` and the exact hashed `body`)
and `audit/manifests/<last>.json` (zero-padded numbers, so alphabetical order is chain order).

> **READING THE ANCHOR**
> 1. Read the manifests already in the bucket. The last one says where the archive ends and what its head hash was.
> 2. Check the database still agrees with that head. If row 5's hash no longer equals the archived head,
>    someone rewrote history: refuse, and say so loudly. Anchoring over a rewritten chain would *launder* it.
> 3. Check the new rows twice: with the database's own `verify()` (including the link to the archived head)
>    and again in Python, independently. Don't let one piece of code grade its own work.
> 4. Upload the segment, then the manifest. Each key must not exist yet; after writing, the job confirms the
>    store actually locked it. A misconfigured bucket without object lock makes the job fail rather than give
>    false comfort.
> 5. One consistent snapshot: steps 2–3 run in one `REPEATABLE READ READ ONLY` transaction, so rows arriving
>    meanwhile wait for the next run.

> **READING THE VERIFY**
> It never stops at the first problem; it collects them all (up to 50) and exits with code 1 if there are any:
> - the database chain on its own (`audit.verify()`)
> - each manifest continues the previous one (`from_seq`, `prev_head_hash`)
> - each segment matches its manifest's checksum and is a valid chain ending at the manifest's head
> - every archived row is still in the database, unchanged, which is what catches rewrites and deletions
> - object-store tricks: it always reads the **oldest version** of each key, and reports extra versions
>   (someone stacked a fake on top) and delete markers (someone tried to hide one). Object lock protects the
>   original version, but in a versioned bucket a new version can still be added, and a plain "delete" adds a
>   marker that hides the key from normal listings. So the script lists versions, not current objects.

The tests use **moto**, a faithful in-process imitation of S3 that supports object lock, together with the
real Postgres:

```bash
uv add --dev "boto3>=1.40" "moto[s3]>=5.1"
```

[`tests/test_audit_chain.py`](../../tests/test_audit_chain.py) has nine tests: incremental anchoring with
chained manifests and locked objects; archived objects can't be deleted; verify passes on a clean log (and
reports what's not yet anchored); a full rewrite is caught by the anchor and the anchor job refuses to
continue; deleting the newest rows is caught; stacking a fake manifest version on top is caught; hiding a
manifest with a delete marker is caught (and the rows it covers are still checked); the anchor refuses a
bucket without object lock; and the archive alone is checkable with nothing but Python.

Two `justfile` recipes run the script with the reader DSN:

```text
audit_reader_dsn := "postgres://audit_reader:$AUDIT_DB_READER_PASSWORD@127.0.0.1:5432/audit"

audit-anchor:   # copy new audit events + head hash to the write-once bucket. Hourly.
audit-verify:   # check database chain, archive, and that they agree. Daily. Exit 1 = problems.
```

And two cron entries (`crontab -e`; a reference copy is in
[`bootstrap/home/crontab`](../../bootstrap/home/crontab)):

```text
5 * * * *   cd ~/dev/rag-platform && just audit-anchor >> ~/Library/Logs/audit-anchor.log 2>&1
30 4 * * *  cd ~/dev/rag-platform && just audit-verify >> ~/Library/Logs/audit-verify.log 2>&1
```

> **WATCH OUT · DEVELOPMENT VS PRODUCTION RETENTION**
> Step 14 set the bucket's default retention to **GOVERNANCE, 1 day**, so you can clean up while learning.
> Governance mode can be bypassed by an identity with special permission. For real evidence use
> **COMPLIANCE** mode with your required retention (often 1–7 years): then nobody, including the storage
> administrator, can delete the objects early. That's deliberate and permanent until the date, so agree the
> period with whoever owns compliance before switching.

### 8 · Alert and runbook

[`infra/config/prometheus/rules/security.yml`](../../infra/config/prometheus/rules/security.yml) gains:

```yaml
# rag-api couldn't store audit events (Step 23). It fails closed, so searches are being REFUSED
# with 503 right now. Fix the audit database first; the runbook says how.
- alert: RagAuditWriteFailing
  expr: sum(increase(rag_audit_write_failures_total[5m])) > 0
  labels: { severity: critical, service: rag-api }
  annotations:
    summary: "Audit events cannot be stored: rag-api is refusing requests until they can"
    runbook: docs/runbooks/audit-log.md
```

[`infra/config/prometheus/tests/rules_test.yml`](../../infra/config/prometheus/tests/rules_test.yml) gains
case 8: the audit database is unreachable for a few minutes (failures jump 0 → 4 → 9), so no alert at 2 m, a
page at 5 m, and silence again at 13 m once the counter stops rising.

```bash
just alerts-test   # SUCCESS
```

The runbook [`docs/runbooks/audit-log.md`](../runbooks/audit-log.md) covers: the alert (is the database up,
can the writer connect, is the lock queue stuck, is the disk full, then confirm with one search and
`just audit-verify`; never switch fail-closed off without the data owner's written approval); a failed
verify or a refused anchor (a **security incident**: preserve evidence first with `pg_dump`, save the report,
read the problems, find who had superuser or `audit_migrator` access, escalate); and the routine (hourly
anchor, daily verify, `not_yet_anchored` below one hour of traffic).

> **WATCH OUT · A FAILED VERIFY IS AN INCIDENT, NOT A BUG**
> The runbook's first instruction is *preserve evidence*: dump the database before touching anything. The
> instinct to "fix the chain" destroys exactly what an investigation needs.

### 9 · Try it end to end

```bash
just api-up && just api-demo   # alice searches; alice tries an admin action; dana (admin) pings
just audit-psql -c "SELECT seq, actor, action, outcome, details FROM audit.events ORDER BY seq"
just audit-anchor && just audit-verify
```

The guide shows a full run: rag-api with the real OPA policy and the real audit database, then a database
restart, an outage, and finally a superuser attack. Shortened:

```text
== requests
  alice search      -> 200 ['Remote work policy']
  alice admin:ping  -> 403 action admin:ping requires role rag-admin
  dana  admin:ping  -> 200 {'status': 'ok', 'admin': 'dana'}
== database restart: every audit connection is killed
  alice search      -> 200 (the pool tests connections before lending them)
== outage: audit_writer can't connect
  alice search      -> 503 {'detail': 'Audit log unavailable'}   (2.0s)
  alice admin:ping  -> 403 (refusal stays a 403)
  after recovery    -> 200
== anchor & verify (CLI) against S3 with object lock
$ just audit-anchor   (exit 0)   {"version": 1, "from_seq": 1, "to_seq": 6, "rows": 6, "head_hash": "a441d0…", …}
$ just audit-anchor   (exit 0)   {"anchored": 0, "reason": "no new events"}
$ just audit-verify   (exit 0)   {"ok": true, "database_rows": 6, …, "problems": []}
== attack: superuser edits row 2 and recomputes every later hash
  verify() inside the database: (True, 6, None, None)
$ just audit-verify   (exit 1)   "problems": ["database: row 2 was changed after it was anchored", … row 6 …]
$ just audit-anchor   (exit 2)
ANCHOR REFUSED: row 6 no longer matches the anchored head hash: the database chain was rewritten.
Run `just audit-verify` and investigate.
```

> **WHAT TO NOTICE**
> - Refusals are recorded with the policy's reason, and admin actions too.
> - A database restart is invisible to users: the pool tests each connection before lending it out.
> - During the outage, searches get 503 within 2 seconds and no documents. The refusal stays a 403.
> - The superuser's rewrite fools the database's own check (`verify()` says ok), but `just audit-verify` names
>   every changed row, and `just audit-anchor` refuses to continue.
> - Speed, measured on a modest test machine: about 1,300 appends per second with one writer, ~0.8 ms each,
>   and still ~1,500 per second with 8 writers queueing for the lock; `verify()` checks about 80,000 rows per
>   second. The single-writer lock is not a bottleneck at this platform's scale.

### 10 · Record the decision

```bash
just adr "Use a hash-chained audit log anchored in write-once storage"
```

[ADR-0023](../adr/0023-use-a-hash-chained-audit-log-anchored-in-write-once-storage.md) records the context,
the decision, the alternatives (plain table + app logs, pgaudit only, immudb, Trillian/Tessera/Rekor, Amazon
QLDB, SIEM with WORM storage), the consequences and when to revisit. Then, in the guide:

```bash
git add -A
git commit -m "feat(audit): hash-chained append-only audit log, fail-closed recording and anchoring in object-locked storage"
git push -u origin feat/audit-log
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- Answers "who saw what?" precisely: every search's returned document ids, per pseudonymous user, with a
  link to the full trace.
- Nothing handed out without a record: fail closed, tested.
- rag-api can't cover its tracks: it may only append.
- Changes are detectable at three levels: the trigger refuses them, the chain exposes edits, the anchors
  expose rewrites.
- No new privacy problem: ids, actions and outcomes only; names stay in Keycloak, content in its own stores.
- A full independent copy in write-once storage, checkable with nothing but Python.
- Plain Postgres and S3: no new database product to learn, run or back up.

## Drawbacks and risks

- **Availability is coupled**: if the audit database is down, searches are refused. That's deliberate, but
  it means the audit database needs the same care (backups, monitoring) as the main one.
- **Serialised writes**: one append at a time. At ~1,300 per second it's ample here; very high volumes need
  batching or several chains.
- **The unanchored window**: up to an hour of events is protected only by the chain and the trigger.
- **Only reported events**: a compromised rag-api could skip recording. Keep Keycloak's events and the
  gateway logs as independent witnesses.
- **The log grows forever** while rows can't be deleted. Plan, later, monthly partitions that are archived
  (already anchored) and detached under a documented, recorded procedure.
- **Jobs must actually run**: a silently failing anchor job widens the window unnoticed. Monitor it (Step 29
  makes it a monitored CronJob).

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **Postgres hash chain + object-lock anchors (our choice)** | Tamper-evident log in the database you already run, with an external proof | One platform, moderate volume, self-hosted |
| **pgaudit** | Postgres extension that logs every statement (or chosen ones) to the server log | You must audit database access itself, including admins; complements this step |
| **immudb** | An open-source database built to be verifiable (Merkle trees, client-side proofs) | Many applications need verifiable storage; you'll run a dedicated system |
| **Trillian / Tessera, Sigstore Rekor** | Merkle-tree transparency logs with small inclusion and consistency proofs | Third parties must verify entries without trusting you (supply chain, certificates) |
| **Signed checkpoints, RFC 3161 timestamps** | Sign the head with a key, or have a timestamp authority sign it | You must prove *when* a head existed, to outsiders, in court |
| **SQL Server / Azure SQL ledger tables, Oracle blockchain tables** | Built-in tamper-evident tables in commercial databases | You're already on that database |
| **SIEM with WORM storage (Splunk, Elastic, Sentinel)** | Central security log platform with immutable retention | The company has a security operations centre; ship anchored segments there |
| **Cloud audit services (AWS CloudTrail Lake, GCP Cloud Audit Logs)** | Provider-managed, immutable logs of cloud API calls | Auditing the cloud control plane; not your app's business events |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Self-hosted RAG platform, one team | This step: Postgres chain + object-lock anchors |
| Regulators may challenge timestamps | Add RFC 3161 timestamps or signed checkpoints to each manifest |
| Database administrators are themselves in scope | Add pgaudit, ship its logs off the host, and keep anchoring |
| Many services must write audit events | A small audit service owning the database; services send events to it |
| Very high volume (thousands per second) | Batch events per transaction, or one chain per partition/tenant, anchored together |
| Outside parties must verify without trusting you | A transparency log (Merkle tree) with published checkpoints |
| Company-wide security monitoring exists | Keep this as the source of truth; forward anchored segments to the SIEM |

## Common mistakes

- Putting the question, document text or names in the audit log, creating the largest copy of sensitive data
  in the company, kept for years.
- Letting the application `UPDATE` / `DELETE` / `SELECT` audit rows, so a compromised app can erase its tracks.
- A `SECURITY DEFINER` function without a fixed `search_path`, open to look-alike-function hijacking.
- Forgetting that `EXECUTE` on functions is granted to `PUBLIC` by default.
- No lock around "read latest hash, insert next row", so concurrent writers fork the chain.
- Hashing text that depends on the session (time zone, locale, key order), so verification fails on another machine.
- Believing a hash chain alone stops administrators: anyone who can write the table can rebuild the chain.
  Anchor it outside.
- Logging after responding, which makes fail closed impossible; or failing open "just this once".
- Reading only the latest object version, or listing only current objects, so a stacked fake or a delete
  marker goes unnoticed.
- Compliance-mode retention on day one, by accident: it can't be undone until the date passes.
- "Fixing" a broken chain during an incident, destroying the evidence.

## Done when

- [ ] `just audit-psql -c '\du audit_*'` shows the three roles; `just audit-migrate status` shows the migration applied
- [ ] As `audit_writer` you can append but not read; as `audit_migrator` an `UPDATE` is refused with "append-only"
- [ ] A search through rag-api creates an `allowed` event with `returned_ids` and a trace id; a refused admin ping creates a `denied` event
- [ ] With the audit database unreachable, searches return 503 and no documents; `RagAuditWriteFailing` is tested with promtool
- [ ] `just check` passes with the database tests skipped, and `just audit-test` passes them all (guide: 47 passed / 25 skipped, and 72 passed)
- [ ] `just audit-anchor` writes a segment and a manifest to `rag-audit-archive` with object lock; `just audit-verify` reports `"ok": true`
- [ ] The anchor and verify jobs are scheduled; the runbook is in `docs/runbooks/audit-log.md`
- [ ] ADR-0023 is merged through a PR

## Recap

> **RECAP**
> The platform now keeps a notary's ledger of who did what:
> - **minimal**: pseudonymous ids, actions, outcomes, document ids and a trace id, nothing more
> - **append-only**: rag-api can only add; nobody can edit through normal means, not even the owner
> - **chained**: every row seals the one before, so any edit is detectable
> - **anchored**: every hour, the chain goes into a vault nobody can change, so even a superuser's rewrite is caught
> - **fail closed**: no record, no data
>
> Next, Step 24, a prompt registry: prompts become versioned, reviewed artefacts with an owner and a history,
> rather than strings scattered through the code.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/config/rag-db/init/02-audit.sh` | One-time bootstrap: the `audit` database, its schema and the three audit roles, passwords from secret files. |
| `infra/db/audit/migrations/20261012090000_create_audit_log.sql` | The append-only, hash-chained `audit.events` table, `append()`, `verify()`, `event_body()`, the guard trigger, exact grants, and a refusing down migration. |
| `infra/compose/compose.yaml` (changed) | Audit passwords mounted into rag-db; rag-api gets `RAG_API_AUDIT_DB_HOST` and the writer password; the object store gets the `audit-anchor` and `audit-reader` identities; seven new top-level secrets. |
| `justfile` (changed) | `audit-bootstrap`, `audit-migrate`, `audit-psql`, `audit-test`, `audit-anchor`, `audit-verify`. |
| `bootstrap/Brewfile` (changed) | `libpq` for `psql` and `pg_isready` on the Mac. |
| `bootstrap/home/crontab` | Reference copy of the hourly anchor and daily verify cron entries. |
| `.env.example`, `scripts/new-dev-secrets.sh` (changed) | The seven new secret names, documented and generated. |
| `services/rag-api/src/rag_api/audit.py` | `AuditEvent`, `AuditLog`, `AuditUnavailable`, `current_trace_id()` and the pooled `PgAuditLog` writer. |
| `services/rag-api/src/rag_api/settings.py` (changed) | Audit database host, port and password settings. |
| `services/rag-api/src/rag_api/main.py` (changed) | Records searches, refusals and admin actions; fails closed with 503; the `rag.audit.write_failures` counter. |
| `services/rag-api/pyproject.toml`, `uv.lock` (changed) | `psycopg-pool` for rag-api. |
| `services/rag-api/tests/conftest.py` (changed) | `FakeAudit` and the `audit` fixture wired into the test client. |
| `services/rag-api/tests/test_audit.py` | Six tests: what's recorded, what never is, and fail-closed behaviour. |
| `services/rag-api/tests/test_service.py` (changed) | Settings tests include the audit password. |
| `tests/__init__.py` | Makes the root `tests/` a package so tests can import shared helpers from `.conftest`. |
| `tests/conftest.py` | The throwaway-Postgres fixtures, `append()`, `tamper()` and the full-rewrite attack. |
| `tests/test_audit_db.py` | 17 database tests: chain, roles, trigger, validation, time zones, concurrency, attacks, rollback, `PgAuditLog`. |
| `scripts/audit_chain.py` | The `anchor` and `verify` commands against the object-locked bucket. |
| `tests/test_audit_chain.py` | Nine anchor/verify tests with moto's object-locked S3 and the real Postgres. |
| `pyproject.toml`, `uv.lock` (changed) | `moto[s3]` dev dependency. |
| `infra/config/prometheus/rules/security.yml` (changed) | The `RagAuditWriteFailing` alert. |
| `infra/config/prometheus/tests/rules_test.yml` (changed) | Unit test case 8 for the new alert. |
| `docs/runbooks/audit-log.md` | What to do when audit writes fail or verification reports problems. |
| `docs/adr/0023-use-a-hash-chained-audit-log-anchored-in-write-once-storage.md` | ADR-0023 (and its row in `docs/adr/README.md`). |
| `tests/test_audit_config.py` | Static checks (no services) that the audit wiring stays in place. |
| `tests/test_object_storage.py`, `tests/test_rag_db.py`, `tests/test_rag_api.py`, `tests/test_monitoring.py` (changed) | Earlier steps' config tests updated for the new identities, secrets and alert. |

## Notes for this repository

- **Secrets.** No real values are committed. The seven new names are in `.env.example`, and
  `scripts/new-dev-secrets.sh` generates them (letters/digits, `rand`) into the SOPS-encrypted
  `secrets/dev.enc.env`. The test passwords in `tests/conftest.py` belong to a throwaway container only.
- **Cron.** The guide adds the two cron lines with `crontab -e` on the Mac, outside the repository; they're
  kept as a reference copy in `bootstrap/home/crontab` and are not installed automatically.
- **`tests/__init__.py`.** The guide's root tests import helpers with `from .conftest import …`. With
  pytest's `--import-mode=importlib` that only works when `tests/` is a package, so an empty
  `tests/__init__.py` was added. In `services/rag-api/tests`, which isn't a package, `test_audit.py` follows
  the convention of the earlier steps there: `bearer()` is defined locally and the fake types are imported for
  type checking only.
- **Small typing adjustments** for strict mypy, behaviour unchanged: the pool attribute is annotated
  (`ConnectionPool[psycopg.Connection[Any]]`), the port is read with `int(str(...))` in two tests, and the
  `type: ignore` comments mypy reported as unused were dropped.
- **Brewfile, image digest.** `libpq` was appended as in the guide. The guide's `audit-test` recipe shows the
  image as `@sha256:<digest>`; it uses the same digest as rag-db (Step 11).
- **Extra tests.** Besides the guide's 32 new tests, `tests/test_audit_config.py` adds six static checks, and
  four earlier config tests were updated (new object-store identities, rag-db and rag-api secrets, the new
  critical alert and the eighth promtool case). The guide's counts ("47 passed, 25 skipped" / "72 passed")
  don't apply to this repository, which has config tests from every step.
- **`psycopg-pool`** resolved to 3.3.3; **moto** to 5.x. `boto3` was already a dev dependency (`>=1.43.0`), so
  only `moto[s3]>=5.1` was added.
- **Validated here (Linux container, Docker):**
  - The real `02-audit.sh` and the real migration (dbmate 2.36) ran against `pgvector/pgvector:0.8.7-pg17`
    (the pinned digest) on `127.0.0.1:55432`; the by-hand session above gave the same results (writer appends,
    reader verifies `t | 1`, the owner's `UPDATE` is refused as append-only).
  - The full suite with `AUDIT_TEST_ADMIN_DSN` set (what `just audit-test` runs): **333 passed**, the remaining
    skips being other live services; without it: 308 passed. All 17 database tests, 9 anchor tests and 6
    rag-api audit tests pass. ruff and strict mypy are clean.
  - `just alerts-test` with the real promtool/amtool images: rules check, unit tests (including case 8) and
    the Alertmanager config all report SUCCESS. `docker compose config` accepts the Compose file.
  - End to end against a **real SeaweedFS 4.45** with an object-locked `rag-audit-archive` and the two scoped
    identities: `audit_chain.py anchor` wrote the segment and manifest (exit 0), a second run reported
    `no new events`, `verify` reported `"ok": true`; after the superuser rewrite from row 2, the database's own
    `verify()` still said `(True, 6, None, None)` while `audit_chain.py verify` listed rows 2–6 as changed
    (exit 1) and `anchor` printed `ANCHOR REFUSED: row 6 no longer matches the anchored head hash…` (exit 2),
    exactly as in the guide. The `audit-reader` identity was refused (`AccessDenied`) when it tried to write.
  - Not done here: the macOS-only parts (Homebrew, `crontab`) and the `just api-up && just api-demo` run with
    Keycloak and the rebuilt rag-api image. The test containers were removed afterwards.
