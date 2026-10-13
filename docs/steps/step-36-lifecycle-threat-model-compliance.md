# Step 36 · Data lifecycle, threat model and compliance

*Step 36 of 38 · Phase I · Production & reuse*

## At a glance

| | |
|---|---|
| **Goal** | Make everything the platform holds manageable for its whole life (permissions that change, documents that expire, people who ask to be forgotten, models that get replaced, databases that fail) and make its safety case reviewable: who could attack it, how, what stops them, the proof, and how that maps to the frameworks your reviewers use. |
| **How, in one sentence** | rag-core gains access changes in place (every store, graph, manifest and cache at once), retention, erasure and blue/green re-indexing commands that dry-run by default; Postgres gains row-level security per tenant; backups come with a restore drill; and a risk register as code links 19 threats to 25 controls, to the tests that prove them, and to NIST AI RMF, ISO/IEC 42001, the EU AI Act and the Australian Privacy Principles, checked in CI. |
| **Time** | About 4 hours. |
| **You'll end up with** | `update_access` in every store (pgvector, Postgres FTS, Qdrant, OpenSearch, memory) with a new conformance check, and `rag reacl` · `rag retention`, `rag erase-source` (every object version), `rag erase-subject` (conversations, cached answers, where a person is mentioned) and `rag reindex` · a migration: the manifest remembers access and metadata; row-level security isolates tenants inside Postgres · `scripts/backup.py` and `just db-backup` / `just db-restore-test`, proven against a real database · `docs/compliance/risk-register.yaml`, `scripts/compliance.py`, generated threat model and controls documents, a C4 model as code, and a CI check · 18 new tests; ADR-0036. |
| **New words** | data lifecycle, retention, right to erasure, legal hold, revocation, row-level security (RLS), blue/green re-index, soak period, backup receipt, restore drill, RPO and RTO, threat model, STRIDE, residual risk, control, evidence, control mapping, C4 model. |

## The big idea

> **ANALOGY · A RECORDS OFFICE WITH A FIRE INSPECTOR**
> A good records office does more than file things. When a file's security level changes, every copy gets the
> new stamp today, not at the next reorganisation. Files are destroyed on schedule, and when someone asks to
> be forgotten, the office finds every place their name appears. When the filing system is reorganised, a new
> room is set up from the originals, checked, and only then do people move over. Copies are kept off-site, and
> once a year someone actually restores from them.
>
> And then the fire inspector visits: "What could go wrong here? What stops it? Show me." The office hands over
> a register: each risk, the measure that treats it, and the evidence (the drill log, the inspection certificate).
> That register is this step's last part.

### What happens to a document over its life (Figure 112)

```
  ingest              change              access change          retention            erasure
  parsed, redacted,   replaced, not       every store, graph,    rules by URI;        all object versions,
  indexed; manifest   appended; cache     manifest, cache:       dry run, then        chunks, sessions,
  keeps access        epoch +1            at once (reacl)        --apply              cached answers

  Every step is a report (dry run by default) and an event: rag-api's audit log or the job's output
  records what was done, when, by whom.
  Backups: a dump + checksum + row counts; the restore drill proves they can be used.
  The audit log is kept by design (pseudonymous ids only).
```

Ingestion records a document's access in the manifest; changes replace it and reset cached answers; access
changes reach every store, the graph, the manifest and the cache at once; retention removes what has outlived its
rule; erasure removes every copy, including every object version. Each action is a dry-run-by-default report.

## What we're doing

1. Change access in place, everywhere at once, so revocation is immediate.
2. Isolate tenants inside the database with row-level security.
3. Retention, erasure and re-indexing as commands with dry runs and reports.
4. Backups with a receipt and a restore drill.
5. A threat model (STRIDE + safety), controls, evidence and framework mapping, as one validated file.
6. C4 diagrams of the platform, as code.

## Why we're doing this

> **WHY THIS MATTERS**
> Most RAG incidents in the real world aren't clever attacks. They are lifecycle failures:
>
> - **Revocation lag:** HR restricts a document at 9 am; the vector index still serves it at 5 pm because the
>   next full sync is tonight.
> - **Zombie data:** the 2021 policy is still answering questions in 2026; a deleted file survives as an old
>   object version, a cached answer and a chunk in a second index.
> - **Erasure gaps:** a person asks to be forgotten; their name is gone from the source system but not from
>   conversation memory, the answer cache or the index.
> - **Re-index outages:** a new embedding model means rebuilding everything, and search is broken (or silently
>   worse) for a day.
> - **Untested backups:** the dump runs nightly; nobody has ever restored one.
> - **Unreviewable safety:** the security review asks "what are your threats and how do you know your controls
>   work?", and the answer is a slide.

| Need | How this step meets it |
|---|---|
| Revocation that doesn't wait | `update_access` in every store + graph + manifest; cache epoch bumped; `rag reacl` |
| Tenants can't see each other, even with a query bug | Postgres row-level security keyed by a per-transaction setting; nothing set = nothing returned |
| Data doesn't outlive its purpose | Retention rules by URI pattern, measured from the last ingestion, dry run then `--apply` |
| Right to erasure | Every store, the manifest, every S3 object version; a person's conversations; all cached answers; a list of documents that mention them |
| Change models without downtime | `rag reindex` from the originals into a new collection, compare, switch by pull request, roll back by revert |
| Recoverable | `pg_dump` with a checksum + row-count receipt; a drill that restores and compares |
| Reviewable safety | Risk register: threats → controls → evidence (tests that CI runs) → framework references, validated in CI |

> **IN A COMPANY**
> These are the questions a privacy officer, a security reviewer and an internal auditor will ask before a RAG
> system goes live: What personal data does it hold and for how long? How do you delete it? How fast does a
> permission change take effect? Can tenants see each other? When did you last restore a backup? Show me your
> threat model and how each control is tested. After this step each has an answer that points at a command, a
> file or a passing test, not at a promise.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Data lifecycle** | Everything that happens to data from creation to deletion: changes, access changes, copies, archiving, destruction. |
| **Retention, legal hold** | How long something may be kept; a hold suspends deletion while a dispute or investigation is open. |
| **Right to erasure** | A person's right (GDPR Art. 17; under the APPs, destruction or de-identification of information no longer needed, APP 11.2) to have their data removed. |
| **Revocation** | Taking access away. It must reach every copy, or it hasn't happened. |
| **Row-level security (RLS)** | Rules inside the database that decide which rows a query may see, whatever the query says. |
| **Blue/green re-index** | Building a new index beside the live one, checking it, then switching; the old one stays until the switch is proven. |
| **RPO / RTO** | Recovery point objective: how much data you can afford to lose. Recovery time objective: how long you can afford to be down. |
| **Restore drill** | Actually restoring a backup into a scratch database and checking it, on a schedule. |
| **Threat model, STRIDE** | A structured list of what could go wrong. STRIDE: Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege. |
| **Control, evidence, residual risk** | A measure that treats a threat; the proof it works; the risk that remains. |
| **Control mapping** | Showing which framework requirements each control helps meet. |
| **C4 model** | Architecture diagrams at four zoom levels: context, containers, components, code. |

> **IN PLAIN ENGLISH**
> Until now the platform was good at *putting things in* and *finding them*. This step is about everything
> that happens afterwards: a document's permissions change, it becomes outdated, someone asks to be forgotten,
> the embedding model is replaced, the database dies. And then it is about proving — to people whose job is to
> doubt you — that the whole thing is safe, with a list that points at real tests.

## How to do it

### 1 · Access changes, everywhere at once

Every store learns to change a document's access **without re-parsing or re-embedding**. Each one does it in its
own way, but the method has the same name and contract everywhere: `update_access(document_uri, access) -> int`
(the number of chunks that changed).

- **pgvector / Postgres FTS** (`libs/rag-core/src/rag_core/components/pgstore.py`): access lives on the one
  `rag.documents` row (Step 11); chunks join to it, so one `UPDATE … RETURNING id` changes every chunk at once.
  The query counts the chunks of the updated document in the same statement:

  ```python
  def _update_access(db: PgConnection, document_uri: str, access: Access) -> int:
      """New permissions on the document row: every chunk follows at once (they join to it)."""
      with db.pool.connection() as conn, conn.transaction():
          _tenant(conn, "*")
          row = conn.execute("""WITH d AS (UPDATE rag.documents SET classification = %s, acl_groups = %s, tenant = %s,
                                  updated_at = now() WHERE collection_id = %s AND source_uri = %s RETURNING id)
                                  SELECT count(*) FROM rag.chunks WHERE document_id IN (SELECT id FROM d)""", …)
      return int(row[0]) if row else 0
  ```

- **Qdrant** (`components/qdrant.py`): count the document's points, then overwrite three payload fields
  (`tenant_id`, `classification`, `acl_groups`) on every point matching `source_uri` with
  `POST /points/payload?wait=true`. The vectors are untouched.
- **OpenSearch** (`components/opensearch.py`, for both the BM25 index and the k-NN store):
  `_update_by_query` with a *painless* script whose values are **parameters**
  (`params.t`, `params.c`, `params.g`), never string-built into the script. `refresh=true` makes the change
  visible to the next search; `conflicts=proceed` doesn't stop on a concurrent write.
- **Memory stores** (`components/basics.py`): replace the chunk's `access` in place.

The ingestion pipeline (`libs/rag-core/src/rag_core/ingest.py`) applies it to every store, the graph, the
manifest and the cache:

```python
def update_access(self, uri: str, access: Access) -> int:
    """Permissions changed at the source (Step 36): every store, the graph and the manifest get
    the new access now, without re-parsing or re-embedding. Revocation shouldn't wait."""
    n = 0
    for store in (self.vectors, self.keywords):
        if store is not None:
            if not hasattr(store, "update_access"):
                raise NotImplementedError(f"{type(store).__name__} can't change access in place: re-ingest instead")
            n = max(n, store.update_access(uri, access))
    # graph store (Step 35): its copies of the chunks get the new access too
    # manifest: remembers the new access (a re-index uses it)
    # cache: invalidated: cached answers may rest on what was just revoked
    self.on_event({"event": "rag.access", "uri": uri, "chunks": n, "classification": access.classification})
    return n
```

A new conformance check, `check_access_update` in `libs/rag-core/src/rag_core/testing/conformance.py`, makes it
part of the contract for **any** store a project writes. It indexes the five sample chunks, then:

1. Bob (engineering, internal) can't find the confidential salary document;
2. the salary document is re-labelled `internal` for `eng` → Bob now finds it ("grant not applied" otherwise),
   and Alice (HR) no longer does ("old access still applies" otherwise);
3. the leave policy is re-labelled `restricted` for `executives` → Alice (no `restricted` clearance) must
   not find it ("LEAK: revocation not applied").

> **WHY IN PLACE, NOT RE-INGEST**
> Re-ingesting means fetching, parsing, chunking and embedding again: minutes to hours for a big document set,
> and in the meantime the old access applies. Access lives in one row per document in Postgres (chunks join to
> it), and as payload fields in Qdrant and OpenSearch, so it can change in seconds. Wire your source system's
> permission-change events (a webhook, or change data capture) to `rag reacl`, and revocation lag becomes
> seconds.

### 2 · Tenants isolated inside the database

The migration `infra/db/rag/migrations/20261014000000_lifecycle_and_tenants.sql` does two things:

1. **The manifest remembers each source's access and metadata** (`access` and `source_metadata` jsonb columns
   on `rag.ingest_manifest`), so retention, erasure and a re-index can rebuild a source from its original
   without asking the source system again. `ManifestEntry` gains `access` and `metadata`, and ingestion fills
   them.
2. **Row-level security** on `rag.documents` and `rag.chunks`:

   ```sql
   ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON rag.documents
       USING (current_setting('rag.tenant', true) IN (tenant, '*'))
       WITH CHECK (current_setting('rag.tenant', true) IN (tenant, '*'));

   ALTER TABLE rag.chunks ENABLE ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON rag.chunks
       USING (EXISTS (SELECT 1 FROM rag.documents d WHERE d.id = document_id))   -- documents' RLS applies inside
       WITH CHECK (EXISTS (SELECT 1 FROM rag.documents d WHERE d.id = document_id));
   ```

   Chunks have no tenant column of their own: the policy says "a chunk is visible if its document is", and
   because the documents' policy applies inside that sub-query, chunks follow their document automatically.

Every Postgres transaction in rag-core now starts by saying which tenant it works for:

```python
def _tenant(conn: Any, tenant: str) -> None:
    """Row-level security (Step 36 migration): the database only shows rows of this tenant ('*' for
    ingestion and maintenance, which work across tenants). Local to the current transaction."""
    conn.execute("SELECT set_config('rag.tenant', %s, true)", (tenant,))
```

Searches set the person's tenant; writes, deletes, access changes and counts set `*`. The full-text search now
runs inside an explicit transaction too, so the setting covers it.

> **READING ROW-LEVEL SECURITY**
>
> - **Defence in depth, not the main lock:** every query already filters by tenant (Step 31). RLS is for the day
>   someone writes a query that forgets. With RLS, that query returns nothing instead of everyone's data.
> - `set_config(…, true)` lasts for the current transaction only, so a pooled connection can't carry one
>   tenant's setting into another's request.
> - `'*'` is for ingestion and maintenance jobs, which legitimately work across tenants. They run under their own
>   identity (Step 37 gives the worker its own login), and the audit log records them.
> - Superusers and table owners bypass RLS. That's why the migration owner (`rag_migrator`) isn't used at
>   runtime, and why the test uses a plain role.
> - The Step 11 search in rag-api (`legacy` backend) now sets the tenant too, so it keeps working.

In this repository the same one-line `set_config` was also added to the earlier demo and sync scripts that read
the tables (`scripts/pg_demo.py`, `scripts/qdrant_sync.py`, `scripts/os_demo.py`, `scripts/s3_demo.py`). They
are maintenance tools, so they set `*` for the whole session (`false` instead of `true`).

Apply the migration on your Mac as before:

```bash
just db-migrate up
uv run rag config validate --profile local
```

### 3 · Retention, erasure and re-indexing

All of it lives in one module, `libs/rag-core/src/rag_core/lifecycle.py`. Every function returns a
`LifecycleReport` (an action name, whether it was applied, and one item per thing touched) whose `summary()`
reads either "…done" or "…would be done (dry run; add --apply)".

**Retention.** A YAML file of rules (`examples/retention.yaml`):

```yaml
version: 1
rules:
  - {match: "*/tickets/*", keep_days: 365, reason: "Support tickets: 1 year (records schedule HR-12)"}
  - {match: "*/chat-exports/*", keep_days: 90, reason: "Chat exports: 90 days (privacy notice v3)"}
  - {match: "*annual-leave-2021*", keep_days: 30, reason: "Superseded policy: remove after replacement"}
default_keep_days: null   # anything else is kept until its source deletes it
```

`apply_retention` walks the manifest. The **first** rule whose glob matches the source URI decides; age is
measured from the manifest's `updated_at`, the last time the source was indexed. A document that keeps changing
at the source keeps being re-ingested and is therefore kept; one that was superseded and forgotten expires. Each
expired source is reported with its age, rule and reason; with `apply=True` it is deleted from every store
(`IngestionPipeline.delete`).

**Erasure of a source.** `erase_source` removes a document from every store, the graph, the manifest and the
cache, and for an `s3://` original lists and deletes **every object version and delete marker** for exactly that
key (Step 14's bucket keeps versions, so deleting the latest isn't deleting). A file called `letter.md.bak` next
to it is not touched.

**Erasure of a person.** `erase_subject(container, subject, identifiers)`:

- deletes the person's conversations (`memory.forget_subject`), or counts them in a dry run;
- invalidates every cached answer (any answer may quote them) by starting a new cache epoch;
- **lists** the documents that mention them, by the exact identifier or by the pseudonym Step 31 would have
  written for it, searching across every tenant and group (`search_all` on stores that support it). Changing a
  source document is its owner's decision, so the list goes to them.

Conversation memory had to learn to find all of one person's sessions. `ValkeyMemory` keys now start with a hash
of the person:

```python
def _person(self, principal: Principal) -> str:
    return hashlib.sha256(f"{principal.tenant}:{principal.subject}".encode()).hexdigest()[:24]

def _key(self, principal: Principal, session_id: str) -> str:
    # person first, so erasure can find every session of one person (Step 36); both hashed,
    # so the keys say nothing about who or what
    return f"{self.p.prefix}{self._person(principal)}:{hashlib.sha256(session_id.encode()).hexdigest()[:24]}"
```

`count_subject` and `forget_subject` scan `rag:memory:<person-hash>:*`. The in-memory store got the same two
methods.

**Access changes.** `change_access(pipeline, uri, access)` wraps `IngestionPipeline.update_access` in a report.
It always acts (there is nothing to preview: the new access is the point).

**Re-indexing (blue/green).** `reindex(source, target)` lists what the source profile's manifest holds and, with
`apply=True`, re-ingests each source **from its original** into the target profile (new embedder, new chunker,
new collection) with the access recorded in the manifest. Failures are reported per source, not fatal.

> **READING THE LIFECYCLE COMMANDS**
>
> - Dry run by default: every command first says what it would do. `--apply` does it. Scheduled jobs (Step 37)
>   run with `--apply`; people investigating don't.
> - Retention measures from the last ingestion, so a document that keeps changing at its source is kept; one that
>   was superseded and forgotten expires.
> - Erasure of a source deletes every object version and delete marker: Step 14's bucket keeps versions, so
>   deleting the latest isn't deleting.
> - Erasure of a person deletes their conversations, invalidates every cached answer, and lists the documents that
>   mention them (by exact text, or by the pseudonym Step 31 gave it). Changing a source document is its owner's
>   decision, so the list goes to them. If ingestion masked the identifier, there's nothing left to find: that's
>   the point of masking.
> - Re-indexing rebuilds from the originals with each source's recorded access, so a new embedding model or
>   chunker gets a clean, comparable collection.
> - The audit log isn't erased: it holds pseudonymous ids, not names or text, and its integrity is the point
>   (Step 23). Record that exception in your privacy documentation.

See it all on the sample handbook, in one process (offline profile, nothing outside the process touched):

```bash
uv run python examples/lifecycle_demo.py
```

```
== retention (dry run)
   uri=annual-leave-2021.md   age_days=40.0   keep_days=30   rule=*annual-leave-2021*   reason=Superseded policy: remove after replacement
   retention: 1 item(s) would be done (dry run; add --apply)

== retention (apply)
   uri=annual-leave-2021.md   age_days=40.0   keep_days=30   rule=*annual-leave-2021*   reason=Superseded policy: remove after replacement   chunks_deleted=2
   retention: 1 item(s) done

== before: Staff may work from home up to three days a week, agreed with their ma

== change access
   uri=remote-work.md   chunks=2   access={'classification': 'confidential', 'groups': ['hr'], 'tenant': 'default'}
   change-access: 1 item(s) done
== after:  You may work up to 10 paid keeping-in-touch days during parental leave

== erase subject (dry run)
   what=conversations   subject=ann   sessions=1
   what=cached answers   action=all invalidated (new epoch)
   what=documents mentioning the person   documents=[]   action=listed for their owners (not deleted automatically)
   erase-subject: 3 item(s) would be done (dry run; add --apply)

== erase subject (apply)
   …the same three items…
   erase-subject: 3 item(s) done
```

> **READING THE OUTPUT**
>
> - Retention found the superseded 2021 leave policy (40 days since ingestion, rule: 30) and removed its two
>   chunks.
> - After the access change, the remote-work policy no longer reaches this person's answer: the extractive
>   fallback grabbed the next-best sentence from another document, which is exactly the weak-context case Step
>   35's corrective architecture handles.
> - Erasure found one conversation for this person and invalidated the cache; no document mentions
>   `security@example.com` by pseudonym because the offline profile masks emails at ingestion.

The same operations from the command line, against a real profile (dry runs; add `--apply` to act):

```bash
uv run rag retention --rules examples/retention.yaml --profile local
uv run rag erase-source s3://rag-raw-docs/hr/letter-0412.pdf --profile local
uv run rag erase-subject --subject 8f1c…-sub --identifier jane.doe@example.com --profile local
uv run rag reacl s3://rag-raw-docs/policies/remote-work.md --group hr --classification confidential --profile local
uv run rag reindex --profile local --to local-v2          # a profile with the new embedder/collection
```

Every command takes `--json` for machine-readable reports (what a scheduled job records). `erase-subject` also
accepts `--email` as a synonym of `--identifier`, and `--tenant` for the person's tenant.

### 4 · Re-indexing without downtime

```
 blue: collection v1           rag reindex --apply           green: collection v2       compare
 serving every query    ──▶    from the ORIGINALS in S3, ──▶  embedder B, chunker B  ──▶ eval-search and
 embedder A, chunker A         with each source's access     not serving yet            eval-answers, both
                                                                    │
                                          switch: one-line pull request
                                          profile collection: v1 → v2 (or a Qdrant alias)

 Rollback = revert the pull request (v1 is still there). Delete v1 only after the agreed soak period.
```

*Figure 113. Blue/green re-indexing.* The live collection keeps serving while `rag reindex` rebuilds a new one
from the originals with each source's access. Both are compared with the same evaluations; the switch is a
one-line pull request, and rolling back is reverting it.

`rag.yaml` now has the profile for the new collection:

```yaml
local-v2:
  extends: local
  embedder:
    use: cached
    inner: {use: gateway, model: embedder-v2, dimensions: 1024, base_url: "http://litellm:4000/v1",
            api_key_file: /run/bao/rag_api_gateway_key, query_prompt: query-instruction, prompts_dir: /app/prompts}
  vector_store: {use: pgvector, dsn_env: null, credentials_file: /run/bao/rag_db.json, collection: default_v2}
  keyword_index: {use: postgres-fts, dsn_env: null, credentials_file: /run/bao/rag_db.json, collection: default_v2}
  manifest: {use: postgres, dsn_env: null, credentials_file: /run/bao/rag_db.json, collection: default_v2}
```

Rebuild, compare, switch:

```bash
uv run rag reindex --profile local --to local-v2 --apply
uv run rag eval-search examples/eval/handbook.yaml --profile local --no-ingest > v1.txt
uv run rag eval-search examples/eval/handbook.yaml --profile local-v2 --no-ingest > v2.txt
# better on your own questions? open a pull request changing RAG_API_RAG_PROFILE to local-v2
```

> **TIP**
> The *soak period* is how long you keep v1 after switching: long enough to see real traffic, feedback and
> alerts on v2 (a week is common). Until it ends, rolling back is a revert and costs nothing.

### 5 · Backups and restore drills

`scripts/backup.py` has two commands:

```bash
backup.py backup       --dsn-env RAG_BACKUP_DSN --out backups/rag-<date>.dump [--s3 s3://bucket/prefix/]
backup.py restore-test --dump backups/rag-<date>.dump --admin-dsn-env RAG_RESTORE_ADMIN_DSN
```

- **backup** counts the rows of the tables that matter (`rag.collections`, `rag.documents`, `rag.chunks`,
  `rag.ingest_manifest`; with `rag.tenant = '*'` so RLS doesn't hide any), runs
  `pg_dump --format=custom --no-owner --no-privileges`, and writes a JSON **receipt** next to the dump: file
  name, SHA-256, size, row counts, time. With `--s3` both files go to object storage, where Object Lock (Step 14)
  keeps them immutable for the retention period.
- **restore-test** checks the dump's checksum against the receipt, creates a throwaway database
  `restore_check_<timestamp>`, `pg_restore`s into it, counts the rows, compares them with the receipt, and drops
  the database again (`WITH (FORCE)`), whatever happened. It prints `"ok": true` or the list of problems and exits
  1 on any problem.

The options take the **name** of an environment variable holding the DSN, never the DSN itself, so passwords don't
appear in shell history or process lists. The justfile recipes (they replace Step 11's first versions):

```just
# Backups (Step 36): a dump plus a receipt (checksum, row counts); a drill restores it and compares
db-backup out="backups/rag-$(date +%Y%m%d-%H%M).dump":
    sops exec-env secrets/dev.enc.env 'uv run python scripts/backup.py backup --dsn-env RAG_BACKUP_DSN --out {{out}}'

db-restore-test dump:
    sops exec-env secrets/dev.enc.env 'uv run python scripts/backup.py restore-test --dump {{dump}} --admin-dsn-env RAG_RESTORE_ADMIN_DSN'
```

On your Mac (`pg_dump`/`pg_restore` come from Homebrew's `libpq`):

```bash
just db-backup
just db-restore-test backups/rag-20261014-0930.dump      # → "ok": true
```

| Store | What a loss costs | Backup | Suggested RPO / RTO (local) |
|---|---|---|---|
| Postgres `rag` | Chunks can be rebuilt from originals; the manifest and access decisions are cheaper to restore | Nightly `db-backup`; weekly drill | 24 h / 2 h |
| Postgres `audit` | Can't be rebuilt; the evidence | Step 23's anchors to locked object storage + nightly dump | 0 (anchored) / 4 h |
| Object storage | The originals: everything else derives from them | Versioning + Object Lock (Step 14); replicate in production | 0 / 4 h |
| Qdrant, OpenSearch | Derived indexes | Rebuild with `rag reindex` (or snapshots) | n/a / hours |
| Valkey | Queue, memory, cache: short-lived | AOF (Step 15); losing it loses conversations, not documents | minutes / minutes |

> **FILL IN YOUR OWN NUMBERS**
> The RPO/RTO column is a starting point for a local platform. Production numbers are a business decision (how
> much lost work and downtime is acceptable), and Step 37 turns them into managed backups with point-in-time
> recovery.

### 6 · The threat model and control mapping, as code

`docs/compliance/risk-register.yaml` is one file with two lists:

- **25 controls**, each with an id (`C-AUTH`, `C-RLS`, `C-LIFECYCLE`, …), a title, a description, the steps that
  built it, the **evidence** (a file, or `file::test_name` for one test), and **framework references** under four
  keys: `nist` (NIST AI RMF 1.0 subcategories, e.g. `MEASURE 2.7`), `iso42001` (ISO/IEC 42001:2023 Annex A
  controls, e.g. `A.6.2.5`), `eu_ai_act` (articles, e.g. `Art. 15`) and `app` (Australian Privacy Principles,
  e.g. `APP 11`).
- **19 threats**, each with an id, a category (the six STRIDE categories plus *Safety*), the component, the
  threat in one sentence, the controls that treat it, and the residual risk (Low / Medium).

A control looks like this:

```yaml
- id: C-RLS
  title: Tenant isolation by row-level security
  description: The database itself returns only the tenant set for the transaction; nothing set means nothing returned.
  steps: [36]
  evidence: [libs/rag-core/tests/test_lifecycle.py::test_row_level_security_isolates_tenants]
  frameworks: {nist: [MEASURE 2.7], iso42001: [A.6.2.5], eu_ai_act: [Art. 15], app: [APP 11]}
```

and a threat like this:

```yaml
- {id: T11, category: Information disclosure, component: multi-tenant data,
   threat: "A query bug returns another tenant's data.", controls: [C-RLS, C-STORE-ACL], residual: Low}
```

`scripts/compliance.py check` validates it: ids are unique; every threat has controls that exist; every control
has evidence, every evidence file exists and **every named test exists in it** (a regex for `def <name>`); every
framework reference is one the script knows (a typo like "Art 51" or a non-existent "MEASURE 2.14" fails); every
control treats at least one threat. `compliance.py docs` renders two Markdown files from it:
`docs/security/threat-model.md` (threats grouped by category) and `docs/compliance/controls.md` (controls with
their evidence, then one table per framework: reference → controls). `docs --check` fails if they are out of date.

```just
compliance-check:
    uv run python scripts/compliance.py check
    uv run python scripts/compliance.py docs --check

compliance-docs:
    uv run python scripts/compliance.py docs
```

`ci-config` now runs `just compliance-check`, so a renamed test, a deleted file or a hand-edited generated document
fails CI.

```
$ just compliance-check
19 threats, 25 controls, 0 problem(s)
```

The threat model it generates:

| Id | Category | Component | Threat | Controls | Residual |
|---|---|---|---|---|---|
| T01 | Spoofing | rag-api | A stolen or forged token is used to call the API. | C-AUTH, C-SECRETS | Low |
| T02 | Spoofing | conversation memory | Someone reads another person's conversation by guessing a session id. | C-SESSION | Low |
| T03 | Tampering | ingestion | A poisoned document plants instructions for the model (indirect prompt injection). | C-INJECTION, C-GROUND, C-AUDIT | Medium |
| T04 | Tampering | audit log | An administrator rewrites the audit history. | C-AUDIT | Low |
| T05 | Tampering | build and deploy | A malicious dependency or image reaches production. | C-SUPPLY, C-DEPLOY | Medium |
| T06 | Tampering | prompts | A prompt, model or dataset is changed without review and alters behaviour. | C-PROMPTS, C-EVAL, C-CARDS | Low |
| T07 | Repudiation | rag-api | A user denies receiving an answer, or an operator denies a change. | C-AUDIT, C-DEPLOY | Low |
| T08 | Information disclosure | retrieval | An answer reveals a document the person may not see. | C-AUTHZ, C-STORE-ACL, C-CACHE | Low |
| T09 | Information disclosure | stores, logs and traces | Personal data ends up in indexes, caches, logs or traces. | C-PII, C-AUDIT, C-OBSERVE, C-LIFECYCLE | Medium |
| T10 | Information disclosure | model output | The model reveals its system prompt, a secret or personal data. | C-INJECTION, C-OUTPUT | Medium |
| T11 | Information disclosure | multi-tenant data | A query bug returns another tenant's data. | C-RLS, C-STORE-ACL | Low |
| T12 | Information disclosure | model providers | Questions and documents are sent to a model provider abroad. | C-LIMITS, C-PII | Medium |
| T13 | Denial of service | rag-api | Huge inputs, runaway agents or SQL, or cost abuse exhaust capacity or budget. | C-LIMITS, C-OBSERVE | Medium |
| T14 | Denial of service | dependencies | A model, reranker or store outage takes answers down. | C-RESILIENCE, C-BACKUP, C-OBSERVE | Medium |
| T15 | Elevation of privilege | SQL RAG | Generated SQL writes data or reads tables beyond the person's access. | C-LIMITS, C-AUTHZ | Low |
| T16 | Elevation of privilege | model | A jailbreak makes the assistant ignore its rules or scope. | C-INJECTION, C-OVERSIGHT | Medium |
| T17 | Elevation of privilege | platform | A compromised pod uses broad database or network access. | C-SECRETS, C-DEPLOY, C-RLS | Low |
| T18 | Safety | answers | A confident wrong answer is acted on (hallucination, outdated document). | C-GROUND, C-EVAL, C-FEEDBACK, C-OVERSIGHT, C-LIFECYCLE | Medium |
| T19 | Safety | answers | People don't realise they're dealing with AI, or can't check where an answer came from. | C-TRANSPARENCY, C-CARDS | Low |

The control mapping (generated per framework in `docs/compliance/controls.md`; combined here):

| Control | NIST AI RMF | ISO/IEC 42001 | EU AI Act | APP |
|---|---|---|---|---|
| C-AUTH Short-lived signed tokens, checked on every request | MEASURE 2.7 | A.6.2.5 | Art. 15 | APP 11 |
| C-AUTHZ Policy-as-code authorisation with pre-filter and post-check | MEASURE 2.7 | A.9.2 | Art. 15 | APP 6, APP 11 |
| C-STORE-ACL Access enforced inside every store, proven by one conformance kit | MEASURE 2.7 | A.6.2.4 | Art. 15 | APP 11 |
| C-RLS Tenant isolation by row-level security | MEASURE 2.7 | A.6.2.5 | Art. 15 | APP 11 |
| C-SESSION Conversations belong to one person and expire | MEASURE 2.10 | A.7.2 | Art. 10 | APP 11 |
| C-CACHE Answer caches keyed by who can see what, reset by every change | MEASURE 2.7 | A.6.2.4 | Art. 15 | APP 11 |
| C-PII Personal data redacted before indexing and in questions and answers | MEASURE 2.10 | A.7.4, A.7.6 | Art. 10 | APP 3, APP 6, APP 11 |
| C-INJECTION Prompt-injection and jailbreak guards, measured in CI | MEASURE 2.7, MEASURE 2.6 | A.6.2.4 | Art. 15 | APP 11 |
| C-OUTPUT Output guards for secrets, personal data and toxicity | MEASURE 2.6, MEASURE 2.10 | A.6.2.4 | Art. 15 | APP 11 |
| C-GROUND Grounded answers with checked citations and honest abstention | MEASURE 2.5, MEASURE 2.9 | A.6.2.4 | Art. 13, Art. 15 | APP 10 |
| C-AUDIT Tamper-evident audit log of every search and answer, without text | MEASURE 2.8 | A.6.2.8 | Art. 12 | APP 1 |
| C-EVAL Evaluation gates on every change | MEASURE 2.3, MEASURE 2.5, MEASURE 2.13 | A.6.2.4 | Art. 9, Art. 15 | APP 10 |
| C-PROMPTS Versioned, locked, reviewed prompts | MEASURE 2.8 | A.6.2.3, A.6.2.7 | Art. 11 | APP 1 |
| C-CARDS Model, dataset and system cards with lineage | GOVERN 1.6, MEASURE 2.8 | A.6.2.7, A.7.5, A.8.2 | Art. 11, Art. 13 | APP 1 |
| C-SECRETS Dynamic, short-lived secrets from files, never config or env in containers | MEASURE 2.7 | A.6.2.5 | Art. 15 | APP 11 |
| C-SUPPLY Pinned, scanned, signed supply chain | GOVERN 6.1, MEASURE 2.7 | A.10.3 | Art. 15 | APP 11 |
| C-DEPLOY Deploy and roll back by pull request, guarded by admission policies | MANAGE 2.4 | A.6.2.5 | Art. 15 | APP 11 |
| C-OBSERVE Traces, metrics and alerts without personal text | MEASURE 2.4, MANAGE 4.1 | A.6.2.6 | Art. 12 | APP 11 |
| C-FEEDBACK User feedback tied to each answer | MANAGE 4.1, MEASURE 2.4 | A.6.2.6, A.8.3 | Art. 14 | APP 13 |
| C-LIFECYCLE Retention, erasure and immediate revocation | MEASURE 2.10, MANAGE 2.4 | A.7.2, A.7.5 | Art. 10 | APP 11, APP 12, APP 13 |
| C-BACKUP Backups with restore drills | MEASURE 2.7 | A.6.2.6 | Art. 15 | APP 11 |
| C-LIMITS Limits on cost and blast radius | MEASURE 2.7 | A.6.2.4 | Art. 15 | APP 11 |
| C-RESILIENCE Degrade, don't fail | MEASURE 2.7 | A.6.2.6 | Art. 15 | – |
| C-TRANSPARENCY People know they're using AI, see sources, and can't be misled by refusals | MEASURE 2.8, MEASURE 2.9 | A.8.2 | Art. 13, Art. 50 | APP 1, APP 5 |
| C-OVERSIGHT Human oversight and escalation | MANAGE 2.4, MANAGE 4.3 | A.9.2, A.9.4 | Art. 14 | APP 1 |

> **WHAT THIS MAPPING IS, AND ISN'T**
> It shows where each control contributes to a framework requirement; it is not legal advice and not a
> certification. Whether an obligation applies depends on what you build:
>
> - **EU AI Act:** most of Articles 9–15 apply to high-risk systems (Annex III includes AI used in employment and
>   access to essential services). A general policy assistant is usually not high-risk, but Article 50's
>   transparency duty (telling people they're dealing with AI) applies more widely. In June 2026 the EU
>   institutions reached a provisional agreement to move the Annex III high-risk deadline from 2 August 2026 to
>   2 December 2027; check its final status before relying on either date.
> - **Australian Privacy Principles:** from 10 December 2026, APP 1.7–1.9 require privacy policies to describe
>   the kinds of personal information used, and the kinds of decisions made, by computer programs that make or
>   substantially assist decisions significantly affecting individuals. If a project uses RAG answers that way,
>   its privacy policy needs updating.
> - **ISO/IEC 42001** is a certifiable management-system standard: the controls here are evidence, but
>   certification also needs the management system around them (policy, roles, risk assessment, internal audit).
> - **NIST AI RMF** is voluntary guidance; the categories cited are where these controls fit its MEASURE and
>   MANAGE functions.

The register is the platform's; each project copies it and adds its own threats (its data, its users, its
decisions) and controls. The document access policy that the dataset cards link to,
[`docs/security/access-policy.md`](../security/access-policy.md), was written in this step too: classifications,
groups and clearance, tenants, the six enforcement points, how access changes (`rag reacl`), retention and
deletion, and the review rules.

### 7 · C4 diagrams

**Level 1, context (Figure 114).** People and the systems the RAG platform depends on:

```
   Employee                       Document owner                    Platform operator
   asks questions, reads          publishes documents,              runs, monitors and audits
   cited answers                  sets their access
        │ HTTPS + token                                                   │ dashboards, audit
        ▼                                                                 ▼
                        RAG platform
          answers from permitted documents, with citations; records everything
        │ verify tokens               │ pull documents                   │ embed, rerank, generate
        ▼                             ▼                                  ▼
   Identity provider            Document sources                  Model providers
   Keycloak / company IdP       wikis, shares, tickets            local MLX/TEI or hosted APIs
```

**Level 2, containers (Figure 115).** The services inside the platform and what each is for:

```
 RAG PLATFORM (CONTAINERS)
 rag-api                     OPA                       Postgres                           Object storage
 search · answers · feedback who may do / see what     chunks (pgvector, FTS, RLS), audit originals (versioned), backups

 ingestion-worker            LLM gateway               Valkey                             Observability
 parse · redact · chunk ·    LiteLLM: routing, budgets queue · memory · cache             OTel · Prometheus · Tempo · Loki
 embed
                             OpenBao                   Qdrant / OpenSearch                Langfuse
                             dynamic logins, keys      optional engines                   LLM traces (masked)

 rag-api → OPA, Postgres, Valkey, gateway, engines, OpenBao (agent). worker → Valkey, gateway, Postgres, object storage.
 Every container: signed image by digest, non-root, resource limits, network policy, secrets from OpenBao files (Steps 27–29).
```

The same model is kept as code in `docs/architecture/workspace.dsl` (Structurizr DSL): three people, three
external systems, the RAG platform with ten containers, and every relationship with its protocol. Render it with:

```bash
docker run --rm -p 8080:8080 -v "$PWD/docs/architecture:/usr/local/structurizr" structurizr/lite
# then open http://localhost:8080 (or paste the file into https://structurizr.com/dsl)
```

> **TIP**
> Diagrams as code are reviewed in pull requests like everything else. When a container is added (Step 37's
> scheduled jobs, for example), the same pull request updates `workspace.dsl`, and the diagram can't drift.

### 8 · Test it

| Test file | What it proves |
|---|---|
| `libs/rag-core/tests/test_lifecycle.py` (10 tests) | Memory stores change access in place (the conformance check); OpenSearch sends a parameterised `_update_by_query`; a revocation reaches search, answers, the cache, the graph and the manifest at once; retention reports, then deletes, exactly what outlived its rule; erasure of an S3 source deletes v1, v2 and the delete marker but not `letter.md.bak`, and every copy; erasure of a person removes only their conversations, starts a new cache epoch and finds a document by the pseudonym of an email address across tenants and groups; Valkey memory forgets one person and its keys say nothing about who; re-indexing rebuilds 17 sources with the same access (the restricted document stays restricted); the CLI; row-level security as a non-superuser against the real migrations |
| `libs/rag-core/tests/test_stores.py` (2 new) | `check_access_update` on real Postgres (pgvector and full-text) and a real Qdrant |
| `tests/test_backup.py` (3 tests) | A backup restores with matching row counts; a one-byte change is caught by the checksum; dump and receipt upload together |
| `tests/test_compliance.py` (3 tests) | The real register is valid and its documents are current; seven kinds of mistake are caught; every threat category is covered |

```bash
just audit-test            # everything, with a throwaway Postgres (pgvector) for the live tests
just compliance-check
```

The Postgres tests use a small helper, `rag_core.testing.postgres.apply_migrations(dsn, dimensions=64)`, that
creates the extension and schema and applies every migration's up section (what dbmate does), shrinking the
vector size for the offline embedder. `test_stores.py` now uses it too.

> **WHAT THE TESTS PROVE**
>
> - Access changes work in memory, Postgres (vector and keyword) and Qdrant against the real services, and
>   OpenSearch sends a parameterised update; a revocation reaches search, answers, the cache, the graph and the
>   manifest at once.
> - Retention reports, then deletes, exactly what outlived its rule.
> - Erasure deletes every object version and every copy of a source; a person's conversations (and only theirs),
>   in memory and in Valkey, whose keys say nothing about who; and finds a document by the pseudonym of an email
>   address across tenants and groups.
> - Re-indexing rebuilds from originals with the same access (the restricted document stays restricted).
> - Row-level security returns nothing to a query that sets no tenant and only the right tenant's rows otherwise,
>   as a non-superuser against the real migrations.
> - Backups restore with matching row counts; a one-byte change is caught; dump and receipt upload together.
> - The risk register is valid, its documents are current, and seven kinds of mistakes are caught.

### 9 · Record the decision

`docs/adr/0036-lifecycle-tenant-isolation-and-a-risk-register-as-code.md` records it: stores implement
`update_access` applied everywhere by the pipeline and enforced by a conformance check; retention, erasure and
re-indexing dry-run by default; the manifest records access; Postgres RLS by a per-transaction tenant setting;
backups with receipts and drills; the risk register validated and rendered in CI. Alternatives rejected:
re-ingesting on every access change (slow, old access applies meanwhile), a database per tenant (now; kept for
regulated tenants), a GRC tool as the register (evidence drifts from code; export to one if needed), backups
without drills. Consequences: lifecycle jobs need their own identity and schedule (Step 37), retention rules
need an owner, and legal holds aren't modelled yet. Revisit when tenants need contractual isolation, a GRC
platform becomes the system of record, or sources can publish change events.

## Benefits

- Immediate revocation across every copy of a document.
- Tenant isolation that survives a buggy query.
- Deletion that is complete (versions, chunks, sessions, caches) and reported.
- Model upgrades without downtime, with a comparison before and a rollback after.
- Backups you've actually restored.
- A safety case reviewers can check, tied to tests that run on every change.

## Drawbacks and risks

- **Dry-run-by-default needs discipline:** a job left in dry-run mode does nothing. Step 37's scheduled jobs pass
  `--apply` and alert on failures.
- **Erasure can't reach what others copied** (an answer pasted into an email). Say so in the privacy notice.
- **Pseudonyms are findable only with the key, and masked data isn't findable at all:** choose deliberately per
  data type.
- **RLS adds a setting to every transaction** and a way to get "no rows" by forgetting it; tests catch that, but
  it surprises people.
- **A risk register goes stale if nobody owns it;** the CI check catches broken evidence, not new threats.
- **Legal holds are not implemented here;** a project with litigation exposure must add them before running
  retention with `--apply`.

> **WATCH OUT**
> "No rows" is RLS working as designed, not a bug in your data. If a new script or service suddenly finds an
> empty table, check that its transaction runs `SELECT set_config('rag.tenant', …, true)` first — and that it
> isn't connecting as the table owner, which would hide the problem in development and leak in production.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Change data capture (Debezium, source webhooks) | Source systems publish every change, including permission changes | Sources can emit events; feed them to `rag enqueue` and `rag reacl` |
| Relationship-based access (OpenFGA, SpiceDB) | Permissions as a graph, checked at query time | Permissions are complex and change constantly (Step 18's alternative) |
| Database per tenant / cluster per tenant | Physical isolation | Contracts or regulators require it |
| pgBackRest / Barman / WAL-G | Continuous archiving and point-in-time recovery for Postgres | Production RPO under a day |
| CloudNativePG / managed Postgres backups | Backups and PITR operated for you | Kubernetes or cloud production (Step 37) |
| OWASP Threat Dragon / Microsoft Threat Modeling Tool / IriusRisk | Diagram-driven threat modelling tools | Teams that prefer a visual tool; export into the register |
| OWASP Top 10 for LLM Applications, MITRE ATLAS | AI-specific threat catalogues | Checking the register for missing AI threats |
| GRC platforms (Vanta, Drata, OneTrust, ServiceNow GRC) | Control libraries, evidence collection, audits | An organisation-wide compliance programme |
| Structurizr / C4-PlantUML / Mermaid C4 | Architecture diagrams as code | Keeping diagrams next to the code they describe |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| One organisation, a few departments | Groups and classifications (Step 18) + RLS by tenant "default" |
| SaaS with many customer organisations | Tenant per customer + RLS; per-tenant collections for the largest |
| Regulated customers demanding separation | Database or cluster per tenant |
| Sources with frequent permission changes | CDC or webhooks → `rag reacl`; measure revocation lag |
| Personal data in documents | Pseudonymise at ingestion; erasure lists by pseudonym; short memory TTL |
| Changing embedding model | `rag reindex` into a new collection, compare, switch by PR |

## Common mistakes

- "We'll pick up permission changes in the nightly sync."
- Deleting the latest object version and calling it erased.
- Forgetting caches and conversation memory in erasure.
- Re-indexing in place, so search is half old, half new until it finishes.
- Backups never restored.
- Threat models written once, never linked to tests, never updated.
- Claiming compliance from a mapping table.

## Done when

- [ ] `uv run python examples/lifecycle_demo.py` shows retention, revocation and erasure working
- [ ] The migration is applied; `rag config validate --profile local` passes; legacy and core search still answer
- [ ] With the platform up: `just db-backup` writes a dump and receipt; `just db-restore-test <dump>` says `"ok": true`
- [ ] `just compliance-check` passes; you've read the threat model and agreed the residual risks with someone who owns them
- [ ] Your privacy notice states memory TTL, retention rules, how erasure works, and the audit-log exception
- [ ] `just audit-test` passes
- [ ] ADR-0036 is committed

## Recap

> **RECAP**
> The platform can now manage what it holds, and show why it's safe:
>
> - access changes in place, everywhere at once; tenants isolated inside Postgres
> - retention, erasure and re-indexing as dry-run-first commands with reports
> - backups with restore drills
> - 19 threats, 25 controls, evidence that CI checks, mapped to NIST AI RMF, ISO/IEC 42001, the EU AI Act and the
>   APPs
> - C4 diagrams kept as code
>
> Next, Step 37: production environments: staging and production overlays, promotion gates fed by evaluation and
> SLOs, high availability, disaster recovery, cloud service mapping, online evaluation from feedback, scheduled
> lifecycle jobs and canary releases.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-core/src/rag_core/lifecycle.py` | Retention rules and `apply_retention`, `erase_source` (every S3 version), `erase_subject`, `change_access`, blue/green `reindex`, `LifecycleReport` |
| `libs/rag-core/src/rag_core/ingest.py` (changed) | `IngestionPipeline.update_access` (every store, the graph, the manifest, the cache); the manifest records each source's access and metadata |
| `libs/rag-core/src/rag_core/components/pgstore.py` (changed) | `_tenant` (RLS setting) at the start of every transaction; `update_access` for pgvector and Postgres FTS; `search_all` for the erasure job; the manifest reads and writes `access` and `source_metadata` and keeps the entry's `updated_at` |
| `libs/rag-core/src/rag_core/components/qdrant.py`, `opensearch.py` (changed) | `update_access` by payload overwrite / parameterised `_update_by_query`; OpenSearch `search_all` |
| `libs/rag-core/src/rag_core/components/basics.py` (changed) | `update_access` on the memory vector store and BM25 index; `search_all` on the BM25 index |
| `libs/rag-core/src/rag_core/components/conversation.py` (changed) | Valkey memory keys start with a hash of the person; `count_subject` / `forget_subject` on both memories |
| `libs/rag-core/src/rag_core/components/queues.py` (changed) | `ManifestEntry.access` and `.metadata` |
| `libs/rag-core/src/rag_core/testing/conformance.py` (changed) | `check_access_update`: the new store contract |
| `libs/rag-core/src/rag_core/testing/postgres.py` | `apply_migrations` / `pgvector_version`: a throwaway Postgres with the real migrations, for tests |
| `libs/rag-core/src/rag_core/cli.py` (changed) | `rag retention`, `erase-source`, `erase-subject`, `reacl`, `reindex` (dry run by default, `--apply`, `--json`) |
| `infra/db/rag/migrations/20261014000000_lifecycle_and_tenants.sql` | Manifest `access` / `source_metadata` columns; row-level security on documents and chunks |
| `services/rag-api/src/rag_api/search.py` (changed) | The legacy search sets the tenant for RLS |
| `scripts/pg_demo.py`, `qdrant_sync.py`, `os_demo.py`, `s3_demo.py` (changed) | Maintenance scripts set `rag.tenant = '*'` for their session |
| `rag.yaml` (changed) | The `local-v2` profile (new embedder, collection `default_v2`) for blue/green re-indexing |
| `examples/retention.yaml` | Example retention rules |
| `examples/lifecycle_demo.py` | Retention, revocation and erasure on the sample handbook, offline |
| `scripts/backup.py` | Backups with a checksum + row-count receipt (optionally to S3) and restore drills |
| `justfile` (changed) | New `db-backup` / `db-restore-test` (replacing Step 11's), `compliance-check` (run by `ci-config`), `compliance-docs` |
| `scripts/new-dev-secrets.sh`, `.env.example` (changed) | `RAG_BACKUP_DSN` and `RAG_RESTORE_ADMIN_DSN` |
| `docs/compliance/risk-register.yaml` | 19 threats, 25 controls, evidence and framework references |
| `scripts/compliance.py` | Validates the register and renders the threat model and controls documents |
| `docs/security/threat-model.md`, `docs/compliance/controls.md` | Generated from the register (don't edit) |
| `docs/security/access-policy.md` | The platform's document access policy (linked from the dataset cards since Step 25) |
| `docs/architecture/workspace.dsl` | The C4 model (context and containers) as Structurizr DSL |
| `libs/rag-core/tests/test_lifecycle.py`, `tests/test_backup.py`, `tests/test_compliance.py`; `libs/rag-core/tests/test_stores.py` (changed) | The 18 new tests |
| `pyproject.toml` (changed) | `examples/**` may print (ruff `T20`) |
| `docs/adr/0036-lifecycle-tenant-isolation-and-a-risk-register-as-code.md` | ADR-0036 |
| `docs/glossary.md`, `docs/adr/README.md`, `docs/steps/README.md`, `CHANGELOG.md` (changed) | New terms, indexes, changelog |

## Notes for this repository

- **Example bucket:** the chapter's examples use `s3://rag-originals/…`, a bucket nothing creates. Step 14's
  `scripts/s3_setup.py` creates `rag-raw-docs` for originals, and the `rag-ingest` / `rag-reader` identities may
  only touch that bucket, so the commands, docstrings and tests here use `s3://rag-raw-docs/…`
  (`tests/test_object_storage.py` checks that every example names a bucket that exists).
- **Code reconstructed from the PDF.** Indentation and line wraps were rebuilt and `ruff format` re-wrapped a
  few long lines. The guide shows only the new methods of the stores, the pipeline and the memory; where the rest
  had to follow, it was written here to match: `_tenant` is called in *every* rag-core Postgres transaction
  (searches with the person's tenant; writes, deletes, access changes and counts with `*`), the Postgres
  manifest reads and writes the new columns, ingestion records each source's access and metadata in the manifest,
  `InMemoryMemory` got `count_subject` / `forget_subject`, the memory BM25 index, Postgres FTS and OpenSearch got
  the `search_all` the erasure job uses, and the five CLI commands were written from the guide's examples.
- **`rag_core.testing.postgres` is new.** The guide's tests import `apply_migrations` from it without showing
  it; it does what `test_stores.py`'s fixture did (extension, schema, every migration's up section, smaller
  vectors, `vector` instead of `halfvec` on old pgvector), and that fixture now uses it.
- **The RLS test role has a password.** The guide creates `rls_app` without one; `just audit-test` runs Postgres
  with password authentication (Step 28), so the test gives the throwaway role a password.
- **Two tests beyond the guide's listings.** The guide counts 18 new tests and says access changes are proven on
  Postgres and Qdrant against the real services, but its listings show 16; the other two,
  `test_postgres_stores_change_access_in_place` and `test_qdrant_changes_access_in_place`, were added to
  `test_stores.py` with the existing live-service fixtures.
- **Masked identifiers aren't searched for in erasure.** The guide's `erase_subject` adds whatever the PII
  redactor turns an identifier into. With `strategy: mask` that is `[EMAIL]`, the same for everyone, which would
  list every document that had any email in it (and `remove` yields an empty string, which matches everything).
  Only pseudonyms are added here, which matches the guide's own explanation ("if ingestion masked the identifier,
  there's nothing left to find").
- **The Postgres manifest keeps the entry's `updated_at`** (`to_timestamp(…)`) instead of `now()`, as the memory
  manifest already did. Otherwise an access change would restart the retention clock, and retention is defined
  as "from the last ingestion".
- **Threat T09's component is quoted.** In the guide's YAML `component: stores, logs and traces` sits unquoted
  inside a flow mapping, so YAML reads the component as `stores` plus a stray key (the guide's rendered table
  indeed shows only "stores"). It is quoted here, so the table says "stores, logs and traces".
- **Backup credentials.** `RAG_BACKUP_DSN` uses `rag_migrator` (the table owner: RLS doesn't hide rows from it,
  and it can read everything it dumps) and `RAG_RESTORE_ADMIN_DSN` the container's `postgres` admin (the drill
  creates and drops a database). Both are generated by `scripts/new-dev-secrets.sh` into the encrypted
  `secrets/dev.enc.env` and documented in `.env.example`; no real value is committed. An existing secrets file
  needs the two lines added with `just secrets-edit`.
- **`docs/security/access-policy.md` was missing.** Step 25's dataset card links to it but no step's text
  defines it; it was written here as the platform's document access policy, consistent with Step 10's gateway
  policy format and Step 18's `policies/rag/authz/data.json`.
- **What was validated here.** ruff, ruff format, strict mypy, `just --list`, `bash -n` on the secrets script;
  the full pytest suite with a throwaway pgvector Postgres (`mirror.gcr.io/pgvector/pgvector:0.8.1-pg16`, so the
  container's `pg_dump` 16 matches the server) and the pinned `qdrant` binary, so the RLS, backup, Postgres and
  Qdrant access-change tests ran for real; `examples/lifecycle_demo.py` (output above); `compliance.py check`
  and `docs --check`; `rag retention` / `rag reacl` on the offline profile; `rag config validate` for every
  profile including `local-v2`. `just db-backup` / `just db-restore-test` against the Compose platform, the
  `--profile local` commands and rendering `workspace.dsl` with Structurizr need the running platform (and
  Docker Hub for Structurizr) and were not run here.
