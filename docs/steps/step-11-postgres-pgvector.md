# Step 11 · Postgres + pgvector: the document and vector store

*Step 11 of 38 · Phase C · Data stores*

## At a glance

| | |
|---|---|
| **Goal** | Run the platform's main database: PostgreSQL with the pgvector extension. It stores documents, chunks, metadata, access-control lists and their vectors in one place, with least-privilege roles, versioned schema migrations, an HNSW vector index, keyword search, tuning and backups. |
| **Time** | About 2 hours. |
| **You'll end up with** | A `rag-db` service (pgvector image pinned by digest, localhost-only port, tuned, health-checked); four database roles with different powers; a first migration creating `collections`, `documents` and `chunks`; a demo that embeds documents through the gateway and searches them with access filters; a tested backup/restore; and ADR-0011. |
| **New words** | Relational database, schema, table, row, column, extension, role, privilege, migration, primary/foreign key, index, B-tree, GIN, HNSW, IVFFlat, approximate nearest neighbour (ANN), recall, `halfvec`, distance operator, `EXPLAIN`, full-text search, `tsvector`, iterative scan, `shared_buffers`, `maintenance_work_mem`, `pg_dump`. |

## The big idea

> **ANALOGY · A LIBRARY WITH ONE CATALOGUE FOR EVERYTHING**
> A good library keeps the books (documents), their pages (chunks), the catalogue cards (title, author, date, who
> may borrow it), the subject-map coordinates from Step 8 (vectors), and the word index at the back (keyword
> search) all under one roof, with one lending desk checking who's allowed what.
>
> PostgreSQL is that building. pgvector adds the "coordinate shelves", so the same database that knows a document
> is confidential and belongs to HR can also find the passages closest in meaning to a question, in one query.

## What we're doing

1. Add four database passwords to the encrypted secrets.
2. Run `rag-db` (pgvector image) in Compose: pinned, localhost-only, tuned, with `pg_stat_statements`.
3. Create roles on first start: superuser (admin only), `rag_migrator` (changes the structure), `rag_app` (reads
   and writes rows), `rag_readonly` (reads only).
4. Install dbmate and write the first migration: tables for `collections` (the embedding contract), `documents`
   (with ACLs) and `chunks` (with `halfvec` embeddings, an HNSW index and keyword search).
5. Load a few documents through the gateway and run semantic search with an access filter; read the query plan.
6. Learn the filtering pitfall and pgvector's fix (iterative scans).
7. Back up and restore, then record ADR-0011.

## Why we're doing this

> **WHY THIS MATTERS**
> A RAG answer is only as trustworthy as what was retrieved, and whether the user was allowed to see it. Keeping
> text, metadata, permissions and vectors in one transactional database means a document's permissions can never
> drift away from its vectors, deletions remove everything at once, and one SQL query can combine "similar
> meaning" with "this user may see it, it's current, it's from HR".

| Need | How Postgres + pgvector meets it |
|---|---|
| Store documents, chunks and metadata reliably | Mature, transactional, crash-safe relational database |
| Semantic search | pgvector types (`vector`, `halfvec`, `sparsevec`, `bit`), distance operators, HNSW/IVFFlat indexes |
| Permission-aware retrieval | ACL columns filtered in the same query as the vector search |
| Keyword search for hybrid retrieval (Step 32) | Built-in full-text search (`tsvector` + GIN index) |
| Every index tied to its embedding contract | A `collections` table recording model, revision, dims, instruction |
| Controlled, reviewable schema changes | Versioned migrations (dbmate), run by a dedicated role |
| Least privilege | Separate roles for admin, migrations, app and read-only |
| Recoverability | `pg_dump` backups with a tested restore |

> **IN A COMPANY**
> "Just use Postgres" is a common, defensible architecture choice for RAG up to millions of chunks: one system to
> secure, back up, monitor and audit, familiar to every DBA. Managed equivalents exist on every cloud (Amazon
> RDS/Aurora, Azure Database for PostgreSQL, Cloud SQL/AlloyDB) with pgvector available. Dedicated vector
> databases (Step 12) earn their place at larger scale or for specialised features, and you'll compare them with
> real numbers.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Relational database / table / row / column | Data stored in tables; each row is a record (one chunk), each column a field (its text, its vector). |
| Schema | A named folder of tables inside a database (we use `rag`); also "the structure" of the tables. |
| Extension | An add-on that teaches Postgres new tricks. `vector` (pgvector) adds vector types and indexes. |
| Role / privilege | A database identity / what it's allowed to do (read, write, create tables). |
| Migration | A versioned, reviewable script that changes the database structure, applied in order and recorded. |
| Primary key / foreign key | A row's unique ID / a column pointing to another table's row (a chunk → its document). |
| Index | A lookup structure that makes searches fast. B-tree for exact values, GIN for arrays/JSON/words, HNSW for vectors. |
| ANN (approximate nearest neighbour) | Finding nearly the closest vectors very fast, instead of exactly the closest by checking every one. |
| Recall | Of the truly closest results, the share the fast (approximate) search actually returned. |
| `halfvec` | Vectors stored at half precision (2 bytes per number instead of 4). Half the storage, negligible quality loss for embeddings. |
| Distance operators | `<=>` cosine distance, `<#>` negative inner product, `<->` Euclidean (L2), `<+>` L1. |
| Full-text search / `tsvector` | Postgres's built-in keyword search: words normalised to stems and indexed with GIN. |
| `EXPLAIN` | Asks Postgres how it will run a query, e.g. whether it uses an index. |

### Who may do what

*(Guide Figure 33, "Four roles from most to least powerful".)*

| | `postgres` | `rag_migrator` | `rag_app` | `rag_readonly` |
|---|---|---|---|---|
| **What it is** | superuser | schema owner | application | read-only |
| **Can** | everything, incl. roles and extensions | `CREATE` / `ALTER` / `DROP` tables, indexes | `SELECT` · `INSERT` · `UPDATE` · `DELETE` rows | `SELECT` only |
| **Used by** | admin only, via `docker compose exec` | only `just db-migrate` | RAG services | evals · analytics |

More power on the left, less power (and used more often) on the right. The more powerful a role, the less often
it's used and the fewer places know its password.

### The tables

*(Guide Figure 34, "The first schema".)*

| `rag.collections` | `rag.documents` | `rag.chunks` |
|---|---|---|
| `id` | `id` | `id` |
| `name` | `collection_id` → collections | `document_id` → documents |
| `embedding_model` | `source_uri` | `chunk_index` |
| `embedding_revision` | `content_sha256` | `content` text |
| `dimensions` | `acl_groups text[]` | `token_count` |
| `query_instruction` | `classification` | `embedding halfvec(1024)` |
| `max_chunk_tokens` | `metadata jsonb` | `content_tsv tsvector` |
| *the embedding contract (Step 8)* | `version` · `deleted_at` — *who may see it (enforced in Step 18)* | *HNSW (meaning) + GIN (keywords)* |

One collection has many documents; one document has many chunks. A collection records the embedding contract;
documents carry ownership, access groups and classification; chunks carry text, a half-precision embedding with an
HNSW index, and a keyword-search column.

### How HNSW finds neighbours fast

*(Guide Figure 35.)* HNSW is a layered "small world" graph. **Layer 2** has few nodes and long jumps, **layer 1**
more, and **layer 0** holds every vector with short links. A search starts at the sparse top layer, takes long jumps
toward the query, then refines layer by layer, visiting a tiny fraction of all vectors before it reports the nearest
neighbours. Three settings trade recall for speed and memory:

| Setting | What it controls | Turn it up and… |
|---|---|---|
| `m = 16` | Links per node | Better recall, more memory |
| `ef_construction = 64` | Effort while building | Better graph, slower build |
| `hnsw.ef_search = 40` | Effort per query | Better recall, slower query |

> **EXACT VS APPROXIMATE SEARCH**
> Without an index, Postgres compares the question's vector with every stored vector: perfectly accurate, but slow
> on large tables. HNSW visits only a small, smart subset, so it's much faster, but it can occasionally miss a true
> neighbour. You'll measure that recall in Step 32. For a few thousand rows, exact search is fine and Postgres may
> simply choose it.

## How to do it

All commands run on the Mac, from the project folder (`~/dev/rag-platform`, the root of this repository):

```bash
cd ~/dev/rag-platform
git switch -c feat/rag-db
```

### 1 · Secrets for the database roles

`POSTGRES_PASSWORD` (generated in Step 6) becomes the superuser password. Add three more:

```bash
for i in 1 2 3; do openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-32; echo; done   # letters/digits only: URL-safe
just secrets-edit
#   RAG_DB_MIGRATOR_PASSWORD=<1st>
#   RAG_DB_APP_PASSWORD=<2nd>
#   RAG_DB_READONLY_PASSWORD=<3rd>
```

Letters and digits only, because the passwords go inside database URLs, where `/`, `+` and `=` would need
escaping. On a new machine, `just secrets-init` (`scripts/new-dev-secrets.sh`) now generates all three for you, and
`.env.example` lists their names.

### 2 · The role-creation script (runs once, on first start)

The official image runs scripts in `/docker-entrypoint-initdb.d/` only when the data volume is empty. That makes it
the place for one-time bootstrap (roles, extension, schema), never for later changes.

The script is [`infra/config/rag-db/init/01-roles.sh`](../../infra/config/rag-db/init/01-roles.sh). It runs `psql`
as the superuser with `ON_ERROR_STOP=1` and passes the three role passwords as psql variables read from the secret
files (`-v migrator_pw="$(cat /run/secrets/rag_db_migrator_password)"` and so on). Then it:

- creates the extensions `vector` and `pg_stat_statements` (both need the superuser);
- creates the roles `rag_migrator`, `rag_app` and `rag_readonly` with `LOGIN PASSWORD :'migrator_pw'` etc.
  `:'var'` makes psql quote the value safely: no SQL injection, and the password is never echoed;
- locks the database down (`REVOKE ALL ON DATABASE rag FROM PUBLIC`, `REVOKE CREATE ON SCHEMA public FROM PUBLIC`)
  and grants only `CONNECT` to the three roles;
- creates the schema `rag` owned by `rag_migrator` and grants `USAGE` on it to `rag_app` and `rag_readonly`;
- sets default privileges (below) so every future table is readable/writable by `rag_app` and readable by
  `rag_readonly`, and its sequences usable by `rag_app`;
- sets per-role defaults: `search_path = rag, public` for all three, `statement_timeout = '30s'` for `rag_app`
  ("no query may run forever"), `120s` and `default_transaction_read_only = on` for `rag_readonly`.

The SQL is in a quoted heredoc (`<<'SQL'`), so the shell never expands anything inside it.

> **IN PLAIN ENGLISH · DEFAULT PRIVILEGES**
> `ALTER DEFAULT PRIVILEGES` is a standing instruction: "every table `rag_migrator` creates from now on is
> automatically readable and writable by `rag_app`, and readable by `rag_readonly`." Without it, each new table would
> need manual grants, and forgotten grants are a classic cause of production errors.

### 3 · Add rag-db to Compose

Pick a pgvector image matching Postgres 17 (e.g. `pgvector/pgvector:0.8.7-pg17`; check Docker Hub for the current
`0.8.x-pg17` tag) and pin its digest:

```bash
docker buildx imagetools inspect pgvector/pgvector:0.8.7-pg17 | head -5
```

The `rag-db` service in [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml):

| Setting | Value | Why |
|---|---|---|
| `image` | `pgvector/pgvector:0.8.7-pg17@sha256:ac08…a75d` | Postgres 17 + pgvector 0.8.7, pinned by digest |
| `environment` | `POSTGRES_DB: rag`, `POSTGRES_USER: postgres`, `POSTGRES_PASSWORD_FILE: /run/secrets/rag_db_superuser_password` | The superuser password comes from a file, never an env var |
| `secrets` | the four `rag_db_*_password` secrets | Read by the init script |
| `volumes` | `rag-db-data:/var/lib/postgresql/data`, `../config/rag-db/init:/docker-entrypoint-initdb.d:ro` | Named volume for data; read-only init scripts |
| `shared_buffers=1GB` | | Postgres's own cache (~25% of the container's memory) |
| `effective_cache_size=3GB` | | Hint: total memory available for caching |
| `maintenance_work_mem=1GB` | | HNSW builds are much faster when the graph fits here |
| `work_mem=32MB` | | Per sort/hash operation |
| `max_connections=100` | | |
| `shared_preload_libraries=pg_stat_statements` | | Per-query statistics for Step 20 |
| `log_min_duration_statement=500` | | Log any query slower than 500 ms |
| `password_encryption=scram-sha-256` | | Modern password hashing |
| `shm_size` | `1g` | Parallel index builds need shared memory (Docker's default is 64 MB) |
| `ports` | `"127.0.0.1:5432:5432"` | Localhost only: for migrations and admin tools on your Mac |
| `healthcheck` | `pg_isready -U postgres -d rag` every 10 s, 5 s timeout, 10 retries | |
| `restart` / `security_opt` / limits | `unless-stopped`, `no-new-privileges:true`, 4 GB / 4 CPUs | Same hardening as every service |

The file also declares the `rag-db-data` volume and four secrets, each read from an environment variable that
`sops exec-env` supplies when you run `just up`:

```yaml
secrets:
  rag_db_superuser_password: { environment: POSTGRES_PASSWORD }
  rag_db_migrator_password:  { environment: RAG_DB_MIGRATOR_PASSWORD }
  rag_db_app_password:       { environment: RAG_DB_APP_PASSWORD }
  rag_db_readonly_password:  { environment: RAG_DB_READONLY_PASSWORD }
```

Start it and check:

```bash
chmod +x infra/config/rag-db/init/01-roles.sh
just up && just ps                                   # rag-db healthy
just logs rag-db                                     # look for the init script running, then "ready to accept connections"
docker compose -f infra/compose/compose.yaml exec rag-db psql -U postgres -d rag -c '\du'   # the four roles
docker compose -f infra/compose/compose.yaml exec rag-db psql -U postgres -d rag -c '\dx'   # vector, pg_stat_statements
```

> **WATCH OUT · CHANGED THE INIT SCRIPT? IT WON'T RE-RUN**
> Init scripts only run against an empty volume. During setup, if you need to start over: `just down`, then
> `docker volume rm rag-platform_rag-db-data`, then `just up`. That deletes all data, which is fine now and never
> acceptable later. After today, every change goes through migrations.

### 4 · Migrations with dbmate

[`bootstrap/Brewfile`](../../bootstrap/Brewfile) gains:

```ruby
# ---- Database migrations (Step 11) ----
brew "dbmate"               # simple, language-agnostic SQL migrations (up/down), single binary
```

The [`justfile`](../../justfile) gains a database URL for the migrator and two recipes:

```make
rag_db_url    := "postgres://rag_migrator:$RAG_DB_MIGRATOR_PASSWORD@127.0.0.1:5432/rag?sslmode=disable&search_path=rag,public"

# Database migrations:   just db-migrate new create_core_tables | up | status | rollback
db-migrate *args="status":
    sops exec-env secrets/dev.enc.env 'DATABASE_URL="{{rag_db_url}}" dbmate --migrations-dir infra/db/rag/migrations --no-dump-schema {{args}}'

# Admin SQL shell (superuser, inside the container: no password on your Mac)
db-psql:
    docker compose -f infra/compose/compose.yaml exec rag-db psql -U postgres -d rag
```

The `$RAG_DB_MIGRATOR_PASSWORD` in the URL is expanded by the shell that `sops exec-env` starts, so the password
only exists in memory for that one command. dbmate keeps its record of applied migrations in
`rag.schema_migrations` (the first schema in `search_path`).

```bash
just bootstrap
just db-migrate new create_core_tables     # creates infra/db/rag/migrations/<timestamp>_create_core_tables.sql
```

Fill in the generated file. Here it is
[`infra/db/rag/migrations/20261012202941_create_core_tables.sql`](../../infra/db/rag/migrations/20261012202941_create_core_tables.sql).
Under `-- migrate:up` it creates:

- **`rag.collections`**: one index built under one embedding contract (Step 8): `name` (unique),
  `embedding_model`, `embedding_revision`, `dimensions` (checked to be 32–4000), `normalized` (default true),
  `query_instruction`, `max_chunk_tokens` (> 0), `created_at`.
- **`rag.documents`**: `collection_id` (foreign key, `ON DELETE CASCADE`), `source_uri` (where it came from),
  `title`, `content_sha256` (to detect unchanged documents, dedup in Step 31), `acl_groups text[]` (groups allowed
  to see it, enforced in Step 18), `classification` (one of `public`, `internal`, `confidential`, `restricted`;
  default `internal`), `metadata jsonb`, `version`, `created_at`, `updated_at`, `deleted_at` (soft delete; hard
  delete flows come in Step 36), and `UNIQUE (collection_id, source_uri, version)`.
- **`rag.chunks`**: `document_id` (foreign key, cascade), `chunk_index`, `content`, `token_count` (> 0),
  `embedding halfvec(1024) NOT NULL` (half the storage of `vector(1024)`), `content_tsv` generated as
  `to_tsvector('english', content)` and stored, `metadata`, `created_at`, and `UNIQUE (document_id, chunk_index)`.

And the indexes:

```sql
-- Vector index: cosine distance on half-precision vectors
CREATE INDEX chunks_embedding_hnsw ON rag.chunks
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);
-- Keyword index for hybrid search (Step 32)
CREATE INDEX chunks_content_tsv ON rag.chunks USING gin (content_tsv);
-- Filters
CREATE INDEX chunks_document_id   ON rag.chunks USING btree (document_id);
CREATE INDEX documents_acl_groups ON rag.documents USING gin (acl_groups);
CREATE INDEX documents_metadata   ON rag.documents USING gin (metadata jsonb_path_ops);
CREATE INDEX documents_live       ON rag.documents (collection_id) WHERE deleted_at IS NULL;
```

Under `-- migrate:down` it drops `chunks`, `documents` and `collections`, children first.

```bash
just db-migrate up
just db-migrate status        # [X] <timestamp>_create_core_tables.sql
```

> **WHY `HALFVEC(1024)`, AND WHY IS THE DIMENSION FIXED?**
> A column's vector size is part of its type, which enforces the embedding contract in the database itself: a
> 768-number vector can't be inserted by mistake. `halfvec` stores each number in 2 bytes, so 1M chunks need about
> 2 GB of vectors instead of 4 GB. A collection with different dimensions would need its own table or column: that's
> the re-index cost from Step 8, made concrete.

> **COSINE VS INNER PRODUCT**
> Our embeddings are normalised (length 1), so cosine distance (`<=>`) and negative inner product (`<#>`) rank
> results identically, and inner product is slightly cheaper. We use cosine because it stays correct even if an
> un-normalised vector ever slips in. It's a deliberate safety-over-speed choice you can revisit in Step 32.

### 5 · Load documents through the gateway and search them

[`scripts/pg_demo.py`](../../scripts/pg_demo.py) connects to `rag` as **`rag_app`** and talks to the gateway with
the ingestion key (`INGESTION_GATEWAY_KEY`, Step 10) using the OpenAI SDK, `model="embedder"`. It:

1. looks for a collection called `demo`; if it doesn't exist, creates it with the embedding contract
   (`Qwen/Qwen3-Embedding-0.6B`, revision from `EMBED_REVISION`, 1024 dimensions, the query instruction,
   1024 max chunk tokens);
2. embeds four documents in one batch and stores each as a document plus one chunk, with its access groups and
   classification:

   | Title | Access groups | Classification |
   |---|---|---|
   | Remote work policy | `all-staff` | internal |
   | Parking | `all-staff` | internal |
   | Salary bands 2026 | `hr` | confidential |
   | Exec offsite ("…covers the 2027 hybrid-work strategy") | `executives` | restricted |

3. embeds the question *"What is the plan for hybrid work?"* (with the query instruction, Step 8) and runs, for two
   different users, one query that combines meaning and permission:

   ```sql
   SELECT d.title, d.classification, round((1 - (c.embedding <=> %(q)s))::numeric, 3) AS similarity
   FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
   WHERE d.deleted_at IS NULL AND d.acl_groups && %(groups)s     -- && = "the arrays overlap"
   ORDER BY c.embedding <=> %(q)s LIMIT 3
   ```

```bash
just with-secrets uv run --with "psycopg[binary]" --with pgvector --with openai scripts/pg_demo.py
```

> **WHAT TO NOTICE**
> The same question returns different results for different users. An ordinary employee never sees the restricted
> executive document, even though it's the closest match in meaning, because the permission filter is part of the
> retrieval query itself. This is the foundation of permission-aware RAG (Step 32). Step 18 will make the groups
> come from the user's real sign-in, not a hard-coded list.
>
> Notice too that the script connects as `rag_app`, which can read and write rows but can't drop a table. Try
> `DROP TABLE rag.chunks;` while connected as `rag_app`: it fails with a permission error.

### 6 · Read the query plan, and avoid the filtering trap

```bash
just db-psql
```

```sql
SET search_path = rag, public;
-- With only 4 rows, Postgres rightly prefers a plain scan. Force the index to see it in the plan:
SET enable_seqscan = off;
EXPLAIN (ANALYZE, COSTS OFF)
SELECT id FROM chunks ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1) LIMIT 3;
-- look for: "Index Scan using chunks_embedding_hnsw"
RESET enable_seqscan;

SHOW hnsw.ef_search;                         -- 40 by default: the per-query search effort
SET hnsw.iterative_scan = relaxed_order;     -- keep scanning when filters remove results (pgvector 0.8+)
SELECT query, calls, round(mean_exec_time::numeric, 2) AS ms
FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 5;     -- slowest queries
\q
```

*(Guide Figure 36.)* **Default: filter AFTER the index scan.** The index returns its top 40 by similarity; the ACL
filter keeps 2. You asked for 5 → you get 2 (silent recall loss). **Iterative scan (pgvector 0.8+).** The index keeps
scanning until enough rows pass the filter: `SET hnsw.iterative_scan = relaxed_order`.

> **WATCH OUT · THE FILTERING TRAP MATTERS MOST FOR PERMISSIONS**
> When a user may only see a small fraction of the documents, an approximate search might return its top 40
> candidates, the permission filter removes 38, and the user gets 2 results instead of 5. No error, just worse
> answers. The remedies are iterative scans (`hnsw.iterative_scan`), larger `ef_search`, partial indexes per tenant,
> or separate collections per tenant. You'll measure them in Step 32.

### 7 · Backup and restore: prove it works

Two more recipes in the [`justfile`](../../justfile):

```make
# Logical backup of the RAG database (custom format, compressed) into backups/ (gitignored)
db-backup:
    mkdir -p backups
    docker compose -f infra/compose/compose.yaml exec -T rag-db pg_dump -U postgres -d rag -Fc > backups/rag-$(date +%Y%m%d-%H%M%S).dump
    ls -lh backups | tail -3

# Restore the latest backup into a scratch database and count rows (proves the backup is usable)
db-restore-test:
    docker compose -f infra/compose/compose.yaml exec -T rag-db psql -U postgres -c "DROP DATABASE IF EXISTS rag_restore_test" -c "CREATE DATABASE rag_restore_test"
    cat "$(ls -t backups/rag-*.dump | head -1)" | docker compose -f infra/compose/compose.yaml exec -T rag-db pg_restore -U postgres -d rag_restore_test --no-owner
    docker compose -f infra/compose/compose.yaml exec -T rag-db psql -U postgres -d rag_restore_test -c "SELECT count(*) AS chunks FROM rag.chunks"
    docker compose -f infra/compose/compose.yaml exec -T rag-db psql -U postgres -c "DROP DATABASE rag_restore_test"
```

`-T` turns off the pseudo-terminal so the binary dump streams cleanly through the pipe. `-Fc` is the compressed
custom format that `pg_restore` reads; `--no-owner` restores without trying to recreate object owners.

```bash
echo "backups/" >> .gitignore          # done in this repository
just db-backup && just db-restore-test # expect: chunks = 4
```

> **A BACKUP YOU HAVEN'T RESTORED IS A HOPE, NOT A BACKUP**
> Many real data-loss incidents involve backups that silently failed or couldn't be restored. Testing the restore
> every time you test the backup is the habit; the Capstone adds schedules, retention, off-machine copies and
> recovery-time targets.

### 8 · Record the decision: ADR-0011, then merge

```bash
just adr "Use Postgres with pgvector as the primary document and vector store"
```

[`docs/adr/0011-use-postgres-with-pgvector-as-the-primary-document-and-vector-store.md`](../adr/0011-use-postgres-with-pgvector-as-the-primary-document-and-vector-store.md)
records the context (documents, chunks, metadata, ACLs and vectors must stay consistent; thousands to low millions
of chunks), the decision (the schema, the four roles, dbmate only, localhost port, tested backups), the alternatives
(a dedicated vector DB only, OpenSearch only, SQLite + sqlite-vec, ORM migrations with Alembic), the consequences,
and when to revisit (over ~10M chunks, p95 vector latency misses targets, or multi-node sharding is needed).

```bash
git add -A
git commit -m "feat(db): pgvector rag-db with least-privilege roles, migrations, HNSW and backups"
git push -u origin feat/rag-db
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **One source of truth:** text, metadata, permissions and vectors stay consistent in one transaction. Delete a
  document and its chunks and vectors go with it.
- **Permission-aware search in a single query,** combining meaning, access groups, classification and freshness.
- **Hybrid-ready:** vectors (HNSW) and keywords (full-text GIN) side by side, ready for Step 32.
- **Least privilege and safe change:** separate roles, timeouts, and reviewed migrations with a recorded history.
- **Efficient:** `halfvec` halves vector storage; HNSW gives fast approximate search, tunable per query.
- **Operable:** mature backup, monitoring (`pg_stat_statements`) and cloud-managed options.

## Drawbacks and risks

- **Filtered ANN pitfalls.** Selective filters can silently reduce results. Use iterative scans and measure.
- **Memory-hungry index builds.** HNSW builds on large tables need `maintenance_work_mem`, shared memory and time.
  Build after bulk loads where possible.
- **Single node.** No built-in sharding or high availability in this setup (replication and DR in the Capstone).
- **Fixed dimensions per column.** A different embedding size needs a new column or table (the planned re-index).
- **Init scripts run once.** Easy to forget; all later changes must be migrations.
- **Superuser power.** The `postgres` password unlocks everything. Use it only via `docker compose exec`, never in
  apps.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Postgres + pgvector (our choice) | Relational database with vector types and indexes | You want one system for documents, metadata, ACLs and vectors |
| Qdrant / Milvus / Weaviate | Purpose-built vector databases | Very large vector counts, advanced vector features, separate scaling (Step 12) |
| OpenSearch / Elasticsearch | Search engines with keyword and vector search | Keyword-heavy search, analyzers, aggregations (Step 13) |
| VectorChord / pgvectorscale | Postgres extensions with alternative vector indexes for larger scale | Postgres at very large scale |
| LanceDB / sqlite-vec / DuckDB VSS | Embedded, file-based vector storage | Notebooks, edge/offline apps (Step 36) |
| Managed Postgres (RDS/Aurora, Azure, Cloud SQL/AlloyDB, Supabase, Neon) | The same Postgres + pgvector, run for you | Production in the cloud (Step 37) |
| Migration tools: Alembic, Flyway, Liquibase, Atlas, sqitch | Other ways to version schema changes | Python/ORM-centred teams (Alembic), Java shops (Flyway/Liquibase), declarative schemas (Atlas) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| RAG up to a few million chunks with permissions and metadata | Postgres + pgvector (this step) |
| Hundreds of millions of vectors, or heavy multi-tenant vector search | Dedicated vector DB (Qdrant/Milvus) with Postgres as the system of record |
| Mostly keyword search with analytics | OpenSearch (Step 13), possibly fed from Postgres |
| Strict tenant isolation | Separate schemas, databases or collections per tenant, plus row-level security (Step 36) |
| Edge/offline single-user app | sqlite-vec / LanceDB (Step 36) |

## Common mistakes

- **Connecting apps as the superuser.** One bug or injection can drop everything. Use `rag_app`.
- **Changing tables by hand in psql.** The change isn't recorded, reviewed or reproducible. Use a migration.
- **Forgetting `ALTER DEFAULT PRIVILEGES`,** so new tables are invisible to the app role.
- **Mixing embeddings from different models or dimensions in one column** (the column type now blocks different
  dimensions, but not a different model of the same size; record the collection's contract).
- **Building HNSW with tiny `maintenance_work_mem` / `shm_size`.** Builds become extremely slow or fail.
- **Assuming filtered vector search returns `LIMIT` rows.** Check counts; use iterative scans.
- **Publishing port 5432 on all interfaces, or committing backups** (they contain all your data).
- **Never testing a restore.**

## Done when

- [ ] `rag-db` runs healthy, pinned by digest, published only on `127.0.0.1:5432`.
- [ ] `\du` shows `rag_migrator`, `rag_app` and `rag_readonly`; `\dx` shows `vector` and `pg_stat_statements`.
- [ ] `just db-migrate status` shows the core-tables migration applied.
- [ ] `pg_demo.py` loads 4 documents via the gateway, and different groups get different results.
- [ ] As `rag_app`, `DROP TABLE` fails with a permission error.
- [ ] `EXPLAIN` shows `Index Scan using chunks_embedding_hnsw` (with seq scans disabled).
- [ ] You can explain the filtering trap and what `hnsw.iterative_scan` does.
- [ ] `just db-backup && just db-restore-test` prints `chunks = 4`, and `backups/` is gitignored.
- [ ] ADR-0011 and all files are merged through a PR.

## Recap

> **RECAP**
> The platform has its system of record: PostgreSQL with pgvector, holding collections (embedding contracts),
> documents (with access groups and classification) and chunks (text, half-precision vectors with an HNSW index,
> keyword index). Four roles enforce least privilege, dbmate migrations version every change, and backups are
> proven by restore. You've seen permission-aware semantic search in one query, read a query plan, and learned the
> filtered-ANN trap. Next, Qdrant (Step 12), a dedicated vector database to compare against.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/compose/compose.yaml` (changed) | Adds the digest-pinned, tuned, localhost-only `rag-db` (pgvector 0.8.7 on Postgres 17) with healthcheck, hardening and limits, the `rag-db-data` volume and the four role-password secrets. |
| `infra/config/rag-db/init/01-roles.sh` | One-time bootstrap on an empty volume: extensions, the `rag` schema, the three least-privilege roles, default privileges and per-role defaults. |
| `infra/db/rag/migrations/20261012202941_create_core_tables.sql` | The first dbmate migration: `collections`, `documents`, `chunks` with HNSW, GIN and filter indexes, and the down migration. |
| `scripts/pg_demo.py` | Loads four documents embedded through the gateway and shows permission-aware semantic search as `rag_app`. |
| `justfile` (changed) | `rag_db_url` and the `db-migrate`, `db-psql`, `db-backup` and `db-restore-test` recipes. |
| `bootstrap/Brewfile` (changed) | Adds `dbmate`. |
| `scripts/new-dev-secrets.sh` (changed) | Also generates `RAG_DB_MIGRATOR_PASSWORD`, `RAG_DB_APP_PASSWORD` and `RAG_DB_READONLY_PASSWORD`. |
| `.env.example` (changed) | Documents the three new role-password names. |
| `.gitignore` (changed) | Ignores `backups/` (backups hold all your data). |
| `pyproject.toml`, `uv.lock` (changed) | `psycopg[binary]` and `pgvector` as dev dependencies, so strict mypy and the tests can check the demo. |
| `tests/test_rag_db.py` | Checks the service, tuning, secrets, init-script grants, migration, recipes and gitignore; with a live database, runs the demo against a fake embedder and proves the role boundaries. |
| `docs/adr/0011-use-postgres-with-pgvector-as-the-primary-document-and-vector-store.md` | ADR-0011: the decision, alternatives, consequences and when to revisit. |
| `docs/adr/README.md` (changed) | ADR-0011 added to the index. |
| `docs/steps/step-11-postgres-pgvector.md` | This write-up. |
| `docs/steps/README.md`, `docs/glossary.md`, `CHANGELOG.md` (changed) | Step index row, the new glossary terms, and the changelog entry. |

## Notes for this repository

- **`search_path=rag,public` instead of `search_path=rag`.** The guide's `rag_db_url` ends in `search_path=rag`.
  Running the migration with that URL fails with `type "halfvec" does not exist`, because the `vector` extension
  (and its `halfvec` type) is installed in the `public` schema, and a `search_path` in the URL replaces the role's
  default `rag, public`. Adding `public` fixes it; dbmate still keeps `schema_migrations` in `rag` (the first entry).
- **The image digest is real.** The guide leaves `<digest>`; Docker Hub returned
  `sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d` for `pgvector/pgvector:0.8.7-pg17` (the
  multi-platform index, published 2026-10-01), which `compose.yaml` pins.
- **Migration timestamp.** The migration file was generated with `dbmate new create_core_tables`, so its name has a
  real timestamp (`20261012202941`) in place of the guide's `<timestamp>`.
- **`pg_demo.py` tweaks for strict mypy and ruff.** The guide's code, formatted by ruff, with one small helper
  (`returned_id`) that turns `cur.fetchone()` from "a row or `None`" into an `int` and fails loudly otherwise.
  Behaviour and output are unchanged.
- **The secrets generator** now creates the three role passwords for new machines (letters and digits only, the
  same `rand` the other passwords use); the guide's `openssl` + `just secrets-edit` route is still the way to add
  them to an existing `secrets/dev.enc.env`. No real values are committed: only names in `.env.example`.
- **Faithful formatting fixes.** Line wraps from the PDF inside the init script, Compose file, justfile and SQL were
  rejoined, and columns re-aligned; no statement was changed.
- **What was validated here (Linux container, Docker, no Mac, no model servers).** `docker compose config` resolves
  the file. The real `rag-db` was started from the pinned image with test passwords: the init script ran
  (`CREATE EXTENSION` ×2, `CREATE ROLE` ×3, `CREATE SCHEMA`, default privileges), the service became healthy,
  `\du` showed the three roles, `\dx` showed `vector 0.8.7` and `pg_stat_statements`, `SHOW shared_buffers` gave
  `1GB`, and `docker port` showed only `127.0.0.1:5432`. dbmate 2.36.0 ran `just db-migrate up / status / rollback /
  up` through the recipe (with a stand-in for `sops exec-env`). `pg_demo.py` ran against the real database with a
  fake gateway returning deterministic bag-of-words embeddings: the all-staff user got only the two internal
  documents, the executive got "Exec offsite" first. As `rag_app`, `DROP TABLE rag.chunks` failed with "must be
  owner of table chunks"; as `rag_readonly`, `DELETE` failed in a read-only transaction. `EXPLAIN` showed
  `Index Scan using chunks_embedding_hnsw`, `hnsw.ef_search` was 40 and `hnsw.iterative_scan = relaxed_order` was
  accepted, and `pg_stat_statements` listed the slowest queries. `just db-backup && just db-restore-test` printed
  `chunks = 4`. The live tests in `tests/test_rag_db.py` passed against that database; without one they skip.
  The real embeddings through the gateway (and therefore the real similarity scores) must be run on the Mac.
