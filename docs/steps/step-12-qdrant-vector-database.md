# Step 12 · Qdrant: a dedicated vector database

*Step 12 of 38 · Phase C · Data stores*

## At a glance

| | |
|---|---|
| **Goal** | Run Qdrant, a database built only for vector search, as a *derived, rebuildable index* of your Postgres data. Secure it with API keys and scoped tokens, design a production-style collection (named vectors, quantization, payload indexes, multitenancy, an alias), sync data into it, and compare it with pgvector. |
| **Time** | About 90 minutes. |
| **You'll end up with** | A `qdrant` service pinned to v1.19.x, authenticated, telemetry off, localhost-only; a versioned collection behind an alias (`rag_chunks`); a sync script copying chunks from Postgres without re-embedding; permission-filtered search that matches pgvector's results; a read-only JWT for apps, a snapshot, and ADR-0012. |
| **New words** | Dedicated vector database, collection, point, payload, payload index, named vectors, sparse vector, scalar quantization, rescoring, multitenancy, tenant, alias, blue/green, derived index, source of truth, snapshot, JWT, RBAC, telemetry. |

## The big idea

> **ANALOGY · THE MASTER LEDGER AND THE FAST LOOKUP COUNTER**
> A bank keeps one master ledger: the authoritative record of every account. It also runs fast service counters
> that hold copies of what tellers need, arranged for speed. If a counter's copy gets damaged, nobody panics: it's
> rebuilt from the ledger.
>
> Postgres is the ledger (Step 11). Qdrant is a fast counter: specialised for vector search with filters,
> compression and multi-customer separation, and always rebuildable from the ledger.

```text
  Postgres + pgvector                     sync job                         Qdrant
  SYSTEM OF RECORD          ───────────────────────────────────▶          DERIVED INDEX
  documents, ACLs, versions,   copies chunks + payload                    fast filtered vector search,
  chunks + embeddings          (no re-embedding)                          quantization, multitenancy
  authoritative, backed up                                                rebuildable from Postgres

                  ◀──── lost or corrupted? rebuild it from the source of truth ────

  Rule: the database that decides permissions and existence is Postgres. Qdrant only ever mirrors it.
```

*Figure 37 of the guide: Postgres stays the source of truth for documents, permissions and existence. A sync job
mirrors chunks and their metadata into Qdrant, which can be rebuilt at any time.*

## What we're doing

1. Add two Qdrant keys (admin and read-only) to the encrypted secrets.
2. Run `qdrant` in Compose: pinned, keys from secret files, telemetry off, localhost-only ports, limits, health
   check.
3. Design and create a collection: named dense + sparse vectors, `float16`, HNSW settings, `int8` quantization,
   payload indexes (including a tenant index), behind an alias.
4. Sync chunks from Postgres into Qdrant (reusing stored embeddings) and run the same permission-aware search as
   Step 11.
5. Mint a read-only, collection-scoped token for applications, and prove it can't write.
6. Take a snapshot, look at the dashboard, and write ADR-0012.

## Why we're doing this

> **WHY THIS MATTERS**
> pgvector is excellent as a system of record, but dedicated vector databases add features that matter at scale:
> compression with rescoring, per-tenant indexing, fast filtered search, horizontal scaling, and built-in hybrid
> queries. An expert must know both, know when each wins, and design them so they never disagree about
> permissions. Treating Qdrant as a derived index makes that guarantee structural rather than hopeful.

| Need | How Qdrant meets it |
|---|---|
| Fast vector search with filters on metadata | Payload indexes and filter-aware HNSW search |
| Lower memory per vector | Scalar / binary / product quantization, with rescoring for accuracy |
| Many tenants in one index | `is_tenant` payload index, per-tenant graphs, shard keys for big tenants |
| Dense + sparse (hybrid) retrieval in one query | Named vectors and the Query API with fusion (Step 32) |
| Zero-downtime re-indexing when the embedding contract changes | Aliases switched atomically between versioned collections |
| Least-privilege access per application | Admin key, read-only key, and JWT tokens scoped to collections |
| Recovery | Rebuild from Postgres, or restore a snapshot |

> **IN A COMPANY**
> A common production pattern is "Postgres (or another database) as the source of truth, a search or vector
> engine as a derived index", kept in sync by a pipeline (later with change data capture, Step 36). It keeps
> compliance-critical facts (who may see what, what's deleted) in one authoritative place, while search scales
> separately. Interviewers often probe exactly this: "What happens if your vector store and your database
> disagree?" Your answer: by design, the vector store is rebuilt from the database.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Collection | Qdrant's equivalent of a table: a set of points sharing vector settings. |
| Point | One stored item: an ID, one or more vectors, and a payload. Here, one chunk. |
| Payload | The JSON metadata stored with a point (tenant, access groups, title, text…). |
| Payload index | An index on a payload field so filters on it are fast. Without one, filtering scans. |
| Named vectors | Several vectors per point under different names, e.g. `dense` and `sparse`. |
| Sparse vector | A vector that's mostly zeros, stored as (position, value) pairs. Used for keyword-like retrieval (SPLADE, BM25-style), Step 32. |
| Scalar quantization (int8) | Storing each vector number as a 1-byte integer instead of 2–4 bytes: about 4× smaller and faster to scan. |
| Rescoring | After a fast search on compressed vectors, re-ranking the top candidates using the original vectors to recover accuracy. |
| Multitenancy / tenant | Serving many customers or departments from one system / one such customer, whose data must stay separate. |
| Alias | A stable name pointing at a real collection; it can be switched to another collection instantly. |
| Blue/green | Building the new version beside the old one, then switching traffic all at once, with the old one kept for rollback. |
| Derived index | A copy organised for fast lookup, always rebuildable from the source of truth. |
| Snapshot | A point-in-time backup file of a collection. |
| JWT / RBAC | A signed token carrying permissions / role-based access control: what each token may read or write. |
| Telemetry | Usage information a program sends to its makers. We switch it off, as with Homebrew in Step 1. |

> **IN PLAIN ENGLISH · A DEDICATED VECTOR DATABASE**
> Postgres is a general-purpose database that *learned* vector search through an extension. Qdrant is the
> opposite: a database written (in Rust) for nothing *but* storing vectors and finding the nearest ones fast,
> with filters. Because that's all it does, it has extra tools for it: compression with rescoring, per-customer
> index layout, several vectors per item, and aliases for swapping whole indexes without downtime.

### The collection design

```text
collection rag_chunks_qwen3e06b_v1                                          ◀── alias rag_chunks

  one point (= one chunk)                              collection settings
  id              1234 (same as Postgres chunk id)     HNSW m=16, ef_construct=100
  vector dense    1024 × float16, cosine               int8 scalar quantization in RAM, rescored with
  vector sparse   reserved for hybrid (Project 2)        originals (≈4× less memory for search)
  payload         tenant_id · acl_groups ·             payload indexes (fast filters)
                  classification · document_id ·         tenant_id: keyword, is_tenant=true
                  source_uri · title · text              acl_groups, classification: keyword
                                                         document_id: integer
```

*Figure 38 of the guide: each point mirrors one Postgres chunk; vectors are float16 with int8 quantization for
search; payload fields used in filters are indexed, with the tenant field marked for per-tenant layout.*

What each design choice buys you, in plain words:

- **Named vectors (`dense`, `sparse`).** One point can carry several vectors. Today only `dense` (the 1024-number
  Qwen3 embedding from Step 8) is filled; the `sparse` slot is reserved so hybrid keyword + meaning search
  (Step 32) can be added later without rebuilding the collection's shape.
- **`float16` storage.** The same half-precision trick as `halfvec` in Step 11: half the disk and memory of
  `float32`, with no measurable loss for retrieval.
- **HNSW `m=16`, `ef_construct=100`.** The same "highway map" index as Step 11. `m` is how many neighbours each
  point links to; `ef_construct` is how hard the builder searches for good links (higher = better graph, slower
  build). Step 11's pgvector index used `ef_construction = 64`; Qdrant's default is 100.
- **`int8` scalar quantization, `always_ram=True`.** A compressed copy of every vector (1 byte per number) is kept
  in RAM and searched first; the full `float16` vectors can stay on disk. Search uses about 4× less memory.
- **Rescoring.** Compression blurs distances slightly, so the top candidates found with the compressed vectors are
  re-scored with the originals (`rescore=True` at query time) before the final order is decided.
- **Payload indexes.** Every field you filter on (`tenant_id`, `acl_groups`, `classification`, `document_id`) gets
  an index, so a filter is a quick lookup instead of a scan, and the HNSW search can be "filter-aware".
- **`is_tenant=True` on `tenant_id`.** Tells Qdrant that most queries filter on one tenant, so it lays out storage
  and graphs per tenant: each customer's search stays fast and separate.

### Versioned collection + alias = blue/green re-indexing

```text
                     today            rag_chunks_…_v1   live (old embedding contract)
  apps query  ──▶  alias: rag_chunks
                     after switch     rag_chunks_…_v2   building in background

  Blue/green re-index: 1. build v2 with new model  2. evaluate v1 vs v2  3. switch alias (atomic)
                       4. keep v1 for rollback      5. delete v1 later
```

*Figure 39 of the guide: applications always query the alias. When the embedding contract changes, a new versioned
collection is built and evaluated, then the alias is switched atomically, with the old one kept for rollback.*

> **WHY THE VERSION IS IN THE NAME**
> The collection name records which embedding contract built it (`qwen3e06b_v1`). Applications only ever use the
> alias `rag_chunks`. When you change the embedder in a later project, you build `…_v2` beside it, compare them with
> the evaluation harness, then flip the alias in one atomic step. That's the zero-downtime blue/green re-index
> promised in Step 8.

### Keys, tokens and who may do what

| Credential | Who holds it | What it can do |
|---|---|---|
| `QDRANT_API_KEY` (admin) | You, the setup script, the sync job | Everything: create/delete collections, write points, take snapshots, and *sign* JWTs |
| `QDRANT_READ_ONLY_API_KEY` | You, for quick checks | Read every collection, change nothing |
| A JWT signed with the admin key | Applications that only search | Exactly what the token says (here: read one collection), until it expires |

> **TOKENS VS KEYS**
> A key is long-lived and all-or-nothing. A token carries its own permissions and expiry, so a leaked token is
> limited in scope and dies on its own. Qdrant can also make tokens revocable through a `value_exists` claim tied
> to a point you can delete. Changing the admin key invalidates every token at once: your emergency brake.

## How to do it

All commands run on the Mac from the project folder (`~/dev/rag-platform`, the root of this repository). Start a
feature branch:

```bash
cd ~/dev/rag-platform
git switch -c feat/qdrant
```

### 1 · Keys

Generate two long random keys and add them to the encrypted secrets file (Step 6):

```bash
openssl rand -hex 32; openssl rand -hex 32
just secrets-edit
#      QDRANT_API_KEY=<1st>                     admin: create/delete collections, write, mint tokens
#      QDRANT_READ_ONLY_API_KEY=<2nd>           read-only, for quick checks
```

On a new machine you don't need to do this by hand: `just secrets-init` (`scripts/new-dev-secrets.sh`) now
generates both keys with `openssl rand -hex 32`, and `.env.example` lists their names.

> **TIP**
> The admin key is also the *signing secret* for JWTs (step 5). A 32-byte random value (64 hex characters) is the
> right size for HMAC-SHA256 signatures; never use a short, memorable key.

### 2 · Add Qdrant to Compose

Use the current stable release (at the time of writing v1.19.2, from Qdrant's GitHub releases) and pin its digest:

```bash
docker buildx imagetools inspect qdrant/qdrant:v1.19.2 | head -5
```

The service in [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml) (added below `rag-db`):

```yaml
services:
  qdrant:
    image: qdrant/qdrant:v1.19.2@sha256:b7b0444c4c351c970b98e90a6f89c2ee4287c65b44e52b4cb503fa5b2aa927ad
    # Keys come from secret FILES and are exported only inside the container process.
    entrypoint: ["/bin/sh", "-c"]
    command:
      - >
        export QDRANT__SERVICE__API_KEY="$$(cat /run/secrets/qdrant_api_key)"
        QDRANT__SERVICE__READ_ONLY_API_KEY="$$(cat /run/secrets/qdrant_read_only_api_key)" &&
        exec /qdrant/entrypoint.sh
    environment:
      QDRANT__TELEMETRY_DISABLED: "true"        # don't send usage reports (same habit as Step 1)
      QDRANT__SERVICE__JWT_RBAC: "true"         # allow scoped tokens signed with the admin key
      QDRANT__LOG_LEVEL: INFO
    secrets: [qdrant_api_key, qdrant_read_only_api_key]
    volumes:
      - qdrant-data:/qdrant/storage
      - qdrant-snapshots:/qdrant/snapshots
    ports:
      - "127.0.0.1:6333:6333"                   # REST API + web dashboard
      - "127.0.0.1:6334:6334"                   # gRPC API
      # 6335 (cluster-internal, unauthenticated) is deliberately NOT published
    healthcheck:
      test: ["CMD-SHELL", "bash -c ':> /dev/tcp/127.0.0.1/6333' || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 10
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 2g, cpus: "2" }

volumes:
  qdrant-data:
  qdrant-snapshots:

secrets:
  qdrant_api_key:            { environment: QDRANT_API_KEY }
  qdrant_read_only_api_key:  { environment: QDRANT_READ_ONLY_API_KEY }
```

What each part does:

- **The wrapper `command`.** Qdrant reads its keys from environment variables (`QDRANT__SERVICE__API_KEY`, the
  double underscores map to `service.api_key` in its config). Putting them under `environment:` would expose them
  in `docker inspect`; instead, as with LiteLLM in Step 9, a tiny shell reads the secret *files* and exports them
  only inside the container process, then `exec`s the image's own start script `/qdrant/entrypoint.sh`. (`$$` is
  Compose's escape for a literal `$`.)
- **`QDRANT__TELEMETRY_DISABLED`.** Qdrant sends anonymous usage reports by default; we decide not to, the same
  habit as `HOMEBREW_NO_ANALYTICS` in Step 1.
- **`QDRANT__SERVICE__JWT_RBAC`.** Turns on scoped tokens signed with the admin key (step 5).
- **Ports.** Only on `127.0.0.1`. 6333 is the REST API and the web dashboard; 6334 is gRPC (faster binary protocol,
  used by clients with `prefer_grpc=True`). 6335 is for traffic between cluster nodes and is never published.
- **The healthcheck** opens a TCP connection to 6333 with bash's `/dev/tcp` (the image has no `curl`), so Docker
  knows when Qdrant is accepting connections without needing a key.
- **Two volumes**: `qdrant-data` holds collections and HNSW graphs (rebuildable from Postgres); `qdrant-snapshots`
  holds snapshot files.
- **Hardening and limits** as for every service: restart policy, `no-new-privileges`, 2 GB memory and 2 CPUs.

> **QDRANT IS OPEN BY DEFAULT**
> Qdrant's own documentation warns that self-deployed instances are not secure by default: no key, no encryption.
> Here, keys are mandatory and ports are localhost-only. Locally, traffic is unencrypted; in production you'd enable
> TLS, because an API key sent over plain HTTP can be read on the network. Port 6335 (cluster traffic between
> nodes) has no authentication at all, so it must never be exposed.

> **IF THE WRAPPER OR HEALTHCHECK DOESN'T FIT YOUR IMAGE VERSION**
> The image's start script lives at `/qdrant/entrypoint.sh` in current releases. Check with
> `docker run --rm --entrypoint ls qdrant/qdrant:v1.19.2 /qdrant`. If the image has no bash for the healthcheck,
> remove the healthcheck and rely on `just qdrant-health`.

Add a health recipe to the [`justfile`](../../justfile):

```make
# Qdrant checks (admin key from secrets)
qdrant-health:
    sops exec-env secrets/dev.enc.env 'curl -sf -H "api-key: $QDRANT_API_KEY" http://127.0.0.1:6333/collections | jq -c .'
```

Start it and prove the key is required:

```bash
just up && just ps
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:6333/collections   # 401: no key, rejected
just qdrant-health                                                            # {"result":{"collections":[]},…}
```

> **WATCH OUT**
> `just qdrant-health` uses *single* quotes around the command, so `$QDRANT_API_KEY` is expanded by the shell that
> `sops exec-env` starts (where the secret exists), not by your own shell or by `just`.

### 3 · Create the collection, behind an alias

[`scripts/qdrant_setup.py`](../../scripts/qdrant_setup.py):

```python
#!/usr/bin/env python3
"""Create the versioned chunks collection, its payload indexes and the stable alias.

Run: just with-secrets uv run --with qdrant-client scripts/qdrant_setup.py
"""

import os

from qdrant_client import QdrantClient, models

VERSIONED = "rag_chunks_qwen3e06b_v1"  # model + contract version in the name
ALIAS = "rag_chunks"  # what applications use

client = QdrantClient(
    url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"),
    api_key=os.environ["QDRANT_API_KEY"],
    prefer_grpc=False,
)

if not client.collection_exists(VERSIONED):
    client.create_collection(
        collection_name=VERSIONED,
        vectors_config={
            "dense": models.VectorParams(
                size=1024, distance=models.Distance.COSINE, datatype=models.Datatype.FLOAT16
            )
        },
        sparse_vectors_config={"sparse": models.SparseVectorParams()},  # for hybrid search, Step 32
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, always_ram=True)
        ),
    )
    indexes = {
        "tenant_id": models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True),
        "acl_groups": models.PayloadSchemaType.KEYWORD,
        "classification": models.PayloadSchemaType.KEYWORD,
        "document_id": models.PayloadSchemaType.INTEGER,
    }
    for field, schema in indexes.items():
        client.create_payload_index(VERSIONED, field_name=field, field_schema=schema)
    print("created", VERSIONED)

client.update_collection_aliases(change_aliases_operations=[
    models.CreateAliasOperation(create_alias=models.CreateAlias(collection_name=VERSIONED, alias_name=ALIAS))])
print("alias", ALIAS, "->", VERSIONED)
print(client.get_collection(VERSIONED).config.params)
```

```bash
just with-secrets uv run --with qdrant-client scripts/qdrant_setup.py
```

The script is safe to re-run: it only creates the collection if it doesn't exist, and re-creating an existing alias
just points it at the same collection again. It prints the stored parameters so you can check the `float16`
`dense` vector and the `sparse` slot.

> **TIP**
> The client prints `UserWarning: Api key is used with an insecure connection.` That's Qdrant reminding you that
> the key travels over plain HTTP. Fine on `127.0.0.1`; in production you'd use `https://` (TLS).

### 4 · Sync from Postgres and search with permissions

The embeddings already live in Postgres, so the sync copies them. Nothing is re-embedded, and both stores hold
identical vectors.

[`scripts/qdrant_sync.py`](../../scripts/qdrant_sync.py):

```python
#!/usr/bin/env python3
"""Mirror live chunks from Postgres (source of truth) into Qdrant, then run a permission-aware search.

Run: just with-secrets uv run --with qdrant-client --with "psycopg[binary]" --with pgvector --with openai \
         scripts/qdrant_sync.py
"""

import os

import psycopg
from openai import OpenAI
from pgvector.psycopg import register_vector
from qdrant_client import QdrantClient, models

ALIAS = "rag_chunks"
TENANT = "acme"  # single tenant for now; Step 31 adds real tenants
INSTRUCTION = ("Instruct: Given an employee question, retrieve passages from company "
               "documents that answer it\nQuery:")

qd = QdrantClient(url="http://127.0.0.1:6333", api_key=os.environ["QDRANT_API_KEY"])
dsn = f"postgresql://rag_readonly:{os.environ['RAG_DB_READONLY_PASSWORD']}@127.0.0.1:5432/rag"

points = []
with psycopg.connect(dsn) as conn:
    register_vector(conn)
    rows = conn.execute("""
        SELECT c.id, c.embedding, c.content, d.id, d.title, d.source_uri, d.acl_groups, d.classification
        FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
        WHERE d.deleted_at IS NULL""").fetchall()
for cid, emb, text, did, title, uri, acl, cls in rows:
    points.append(models.PointStruct(
        id=cid,  # same id as Postgres: easy to reconcile
        vector={"dense": emb.to_list()},
        payload={"tenant_id": TENANT, "document_id": did, "title": title, "source_uri": uri,
                 "acl_groups": acl, "classification": cls, "text": text}))
qd.upsert(collection_name=ALIAS, points=points, wait=True)
print("synced", len(points), "points; Qdrant count =", qd.count(ALIAS, exact=True).count)

gw = OpenAI(base_url="http://127.0.0.1:4000/v1", api_key=os.environ["RAG_API_GATEWAY_KEY"])
question = "What is the plan for hybrid work?"
qvec = gw.embeddings.create(model="embedder", input=[INSTRUCTION + question]).data[0].embedding

for groups in (["all-staff"], ["all-staff", "executives"]):
    hits = qd.query_points(
        collection_name=ALIAS, query=qvec, using="dense", limit=3, with_payload=True,
        query_filter=models.Filter(must=[
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=TENANT)),
            models.FieldCondition(key="acl_groups", match=models.MatchAny(any=groups)),
        ]),
        search_params=models.SearchParams(hnsw_ef=64,
                                          quantization=models.QuantizationSearchParams(rescore=True)),
    ).points
    print(f"\nuser in {groups}:")
    for h in hits:
        print(f"    {h.score:.3f}  [{h.payload['classification']}]  {h.payload['title']}")
```

(The committed file is the same code, formatted by ruff, with the small changes listed in *Notes for this
repository*.)

```bash
just with-secrets uv run --with qdrant-client --with "psycopg[binary]" --with pgvector --with openai scripts/qdrant_sync.py
```

How it works, line by line:

- It reads every chunk of every **live** document (`deleted_at IS NULL`) together with the document's title, URI,
  access groups and classification, connecting as `rag_readonly`.
- Each chunk becomes a **point with the same id** as its Postgres row, the stored `halfvec` embedding as its
  `dense` vector, and the document metadata as **payload**. `upsert` inserts new points and overwrites existing ones
  with the same id, so running the sync twice gives the same result.
- It writes through the **alias** `rag_chunks`, so it always fills whichever collection is live.
- It embeds the question once through the gateway (with the query instruction from Step 8, using the RAG API's
  virtual key from Step 10) and searches with two filters that **must** both match: the tenant, and *any* of the
  user's groups (`MatchAny` is Qdrant's version of Postgres's `&&` array overlap).
- `hnsw_ef=64` is how wide the search looks (like `hnsw.ef_search` in Step 11), and `rescore=True` re-scores the
  candidates with the original vectors after the fast int8 pass.

> **WHAT TO COMPARE**
> Put this output beside Step 11's `pg_demo.py` output. The same documents should come back in the same order, with
> near-identical scores (Qdrant reports cosine similarity; Step 11 printed `1 − distance`, which is the same thing).
> The executive document again appears only for the user in `executives`. Two engines, one source of truth, one
> answer: that's the consistency you designed for.

> **THE SYNC CONNECTS AS RAG_READONLY**
> The sync job only reads Postgres, so it uses the read-only role from Step 11. If it ever had a bug, it couldn't
> damage the source of truth. Note also that deleted documents (`deleted_at IS NOT NULL`) are skipped, but points
> already in Qdrant from before a deletion would remain. A real sync must also delete stale points. That's the
> change-data-capture work in Step 36, and a reason a full rebuild must always be possible.

### 5 · A read-only, collection-scoped token for applications

Applications that only search shouldn't hold the admin key. With `JWT_RBAC` on, you can mint tokens signed with the
admin key that allow only specific access.

[`scripts/qdrant_token.py`](../../scripts/qdrant_token.py):

```python
#!/usr/bin/env python3
"""Mint a short-lived, read-only Qdrant token for one collection, and prove it can't write.

Run: just with-secrets uv run --with qdrant-client --with pyjwt scripts/qdrant_token.py
"""

import os
import time

import jwt
from qdrant_client import QdrantClient, models

COLLECTION = "rag_chunks_qwen3e06b_v1"  # scope tokens to the real collection name
token = jwt.encode({"access": [{"collection": COLLECTION, "access": "r"}],
                    "exp": int(time.time()) + 3600},  # valid for one hour
                   os.environ["QDRANT_API_KEY"], algorithm="HS256")

app = QdrantClient(url="http://127.0.0.1:6333", api_key=token)
print("read  :", app.count(COLLECTION, exact=True).count, "points")
try:
    app.upsert(COLLECTION, points=[models.PointStruct(id=999999, vector={"dense": [0.0] * 1024}, payload={})])
    print("write : ALLOWED (unexpected!)")
except Exception as e:  # we expect a permission error here
    print("write : rejected ->", type(e).__name__)
```

```bash
just with-secrets uv run --with qdrant-client --with pyjwt scripts/qdrant_token.py
# read  : 4 points
# write : rejected -> UnexpectedResponse        (HTTP 403 Forbidden)
```

The token is a small signed JSON document: `access` says "read (`r`) the collection `rag_chunks_qwen3e06b_v1`",
and `exp` says "invalid after one hour". Qdrant checks the HMAC-SHA256 signature with its admin key, so nobody can
forge or widen a token without that key. The app passes the token exactly where a key would go (`api_key=`).

> **IN PLAIN ENGLISH · WHY THE TOKEN NAMES THE REAL COLLECTION**
> Tokens are scoped to the versioned collection name, not the alias. When you flip the alias to `…_v2`, you mint
> new tokens for `…_v2`; old tokens keep pointing at exactly what they were allowed to read.

### 6 · Snapshot, dashboard, decision

Add a snapshot recipe to the [`justfile`](../../justfile):

```make
# Create a Qdrant snapshot of the live collection (stored in the qdrant-snapshots volume)
qdrant-snapshot:
    sops exec-env secrets/dev.enc.env 'curl -sf -X POST -H "api-key: $QDRANT_API_KEY" http://127.0.0.1:6333/collections/rag_chunks_qwen3e06b_v1/snapshots | jq -c .result'
```

```bash
just qdrant-snapshot
open http://127.0.0.1:6333/dashboard   # paste the admin key to log in; browse points and payloads
```

The snapshot command prints the file name, size and checksum; the file lands in the `qdrant-snapshots` volume. In
the dashboard you can open the collection, look at its points and payloads, and run test searches.

> **TWO WAYS TO RECOVER**
> A Qdrant snapshot restores quickly. A re-sync from Postgres always works, even if every snapshot is lost. Keeping
> both, and knowing how long each takes, is the start of the recovery planning in the Capstone (RPO/RTO).

Record the decision:

```bash
just adr "Use Qdrant as a derived vector index alongside Postgres"
```

The result is
[`docs/adr/0012-use-qdrant-as-a-derived-vector-index-alongside-postgres.md`](../adr/0012-use-qdrant-as-a-derived-vector-index-alongside-postgres.md):
Postgres + pgvector stays the system of record (ADR-0011); Qdrant v1.19.x (digest-pinned) runs with SOPS keys,
JWT RBAC on, telemetry off and localhost-only ports; it is a *derived* index, named by embedding contract and used
through the alias; points mirror Postgres ids and payloads, written only by the read-only sync, never by apps; apps
get read-only, collection-scoped, expiring JWTs. Alternatives considered: pgvector only, Milvus, Weaviate, and
Qdrant as the source of truth (rejected: it breaks the single-source rule). Revisit when the comparative
benchmarks (Projects 1, 17) show one engine is enough, or scale requires clustering.

Commit, push and merge through a pull request:

```bash
git add -A
git commit -m "feat(qdrant): secured Qdrant as derived vector index with alias, quantization and scoped tokens"
git push -u origin feat/qdrant
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Vector-specialist features:** int8 quantization with rescoring, per-tenant layout, filter-aware HNSW, built-in
  hybrid queries.
- **Zero-downtime re-indexing:** versioned collections behind an alias make embedding-model upgrades a switch, not
  an outage.
- **Least privilege for apps:** expiring, read-only, collection-scoped tokens, with the admin key never in app
  config.
- **Consistency by design:** Postgres decides; Qdrant mirrors. Disagreement is fixed by rebuilding, not by debating
  which is right.
- **Two recovery paths:** snapshots and full re-sync.
- **Interview-ready:** you can explain, with working code, when and why to add a dedicated vector database.

## Drawbacks and risks

- **Sync complexity.** Updates and deletions must reach Qdrant reliably. Until CDC (Step 36), a full rebuild is the
  safe fallback.
- **Eventual consistency.** Between a change in Postgres and the next sync, Qdrant may be briefly out of date, which
  matters for permission revocations. Revocations must propagate fast, or be checked against Postgres at query time
  (Step 36).
- **More to operate:** another service to secure, monitor, back up and upgrade.
- **Memory.** HNSW graphs and quantized vectors live in RAM; size with care on a shared-memory Mac.
- **Unencrypted locally.** Fine on localhost; production needs TLS.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Qdrant (our choice) | Rust vector database: filters, quantization, multitenancy, hybrid query API | Self-hosted vector search with strong filtering and multitenancy |
| pgvector only | Vectors inside Postgres | Moderate scale; you want one system |
| Milvus / Zilliz | Distributed vector database; GPU indexes | Billions of vectors, large clusters |
| Weaviate | Vector database with modules (vectorizers, hybrid) | You want built-in modules and GraphQL-style APIs |
| OpenSearch / Elasticsearch k-NN | Vectors inside a search engine | Keyword search is primary (Step 13) |
| LanceDB / Chroma | Embedded or lightweight vector stores | Prototypes, notebooks, desktop/edge apps |
| Managed (Qdrant Cloud, Pinecone, Vertex Vector Search, Azure AI Search) | Hosted vector search | Cloud deployments, no ops team (Step 37) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Up to a few million chunks, one team | pgvector alone may be enough. Measure before adding Qdrant |
| Many tenants with strict separation and varied sizes | Qdrant with `is_tenant` indexing; shard keys for big tenants |
| Frequent embedding-model upgrades | Versioned collections + aliases (any engine with aliases) |
| Memory-constrained, large corpora | Quantization (int8/binary) with rescoring |
| Very large scale, many nodes | Milvus or a Qdrant cluster |
| Compliance-heavy permissions | Keep permissions authoritative in Postgres; vector store as a derived index |

## Common mistakes

- **Running Qdrant without an API key, or publishing its ports on all interfaces** (it's open by default).
- **Letting applications write to the derived index,** so it drifts from the source of truth and can't be safely
  rebuilt.
- **Forgetting payload indexes,** so filtered searches scan everything and slow down as data grows.
- **Pointing apps at a versioned collection name instead of the alias,** so re-indexing then requires app changes.
- **Skipping rescoring with quantization,** losing accuracy for a small speed gain.
- **Syncing upserts but not deletions,** so deleted or revoked documents remain searchable.
- **Giving apps the admin key** instead of scoped, expiring tokens.
- **Leaving telemetry on** without deciding to.

## Done when

- [ ] `qdrant` runs pinned at v1.19.x, `QDRANT__TELEMETRY_DISABLED=true`, ports only on `127.0.0.1` (6335 not
      published).
- [ ] A request without a key gets 401; `just qdrant-health` works with the key.
- [ ] `rag_chunks_qwen3e06b_v1` exists with float16 dense vectors, sparse slot, int8 quantization and four payload
      indexes; alias `rag_chunks` points to it.
- [ ] `qdrant_sync.py` mirrors all live chunks (counts match Postgres) and returns the same permission-filtered
      results as Step 11.
- [ ] The read-only JWT can read but cannot write.
- [ ] A snapshot exists, and you've browsed points in the dashboard.
- [ ] ADR-0012 and all files are merged through a PR.

You can check most of this at once with the tests: `just with-secrets uv run pytest tests/test_qdrant.py -v`
(the live tests run when Qdrant, and for the sync comparison rag-db, are up).

## Recap

> **RECAP**
> Qdrant now runs as a secured, derived vector index: authenticated, telemetry off, localhost-only, with a
> production-style collection (float16 vectors, int8 quantization with rescoring, indexed payloads, tenant-aware
> layout, sparse slot for hybrid) behind an alias for zero-downtime re-indexing. Data flows one way, from Postgres,
> so permissions and deletions have a single source of truth. Apps get read-only, expiring tokens. Next, OpenSearch
> (Step 13) for keyword search and analyzers, the third leg of hybrid retrieval.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/compose/compose.yaml` (changed) | Adds the `qdrant` service (v1.19.2 pinned by tag and digest, keys from secret files via a wrapper, telemetry off, JWT RBAC on, 6333/6334 on 127.0.0.1 only, healthcheck, hardening, limits), the `qdrant-data` / `qdrant-snapshots` volumes and the two key secrets. |
| `scripts/qdrant_setup.py` | Creates the versioned collection `rag_chunks_qwen3e06b_v1` (dense float16 + sparse slot, HNSW, int8 quantization, four payload indexes with a tenant index) and points the alias `rag_chunks` at it. |
| `scripts/qdrant_sync.py` | Mirrors live chunks from Postgres (as `rag_readonly`, reusing stored embeddings) into Qdrant and runs the permission-filtered search with rescoring. |
| `scripts/qdrant_token.py` | Mints a one-hour, read-only JWT scoped to the collection and proves it can read but not write. |
| `justfile` (changed) | `qdrant-health` and `qdrant-snapshot` recipes, using the admin key from SOPS. |
| `scripts/new-dev-secrets.sh` (changed) | Also generates `QDRANT_API_KEY` and `QDRANT_READ_ONLY_API_KEY` (64 hex characters each). |
| `.env.example` (changed) | Documents the two new key names. |
| `pyproject.toml`, `uv.lock` (changed) | `qdrant-client` and `pyjwt` as dev dependencies, so strict mypy and the tests can check the scripts. |
| `tests/test_qdrant.py` | Checks the Compose service, secrets, recipes and script design; with a live Qdrant, checks 401/403, telemetry and RBAC, the collection design and alias, the token's limits, and (with rag-db) that the sync mirrors every chunk and agrees with pgvector. |
| `docs/adr/0012-use-qdrant-as-a-derived-vector-index-alongside-postgres.md` | ADR-0012: the decision, alternatives, consequences and when to revisit. |
| `docs/adr/README.md` (changed) | ADR-0012 added to the index. |
| `docs/steps/step-12-qdrant-vector-database.md` | This write-up. |
| `docs/steps/README.md`, `docs/glossary.md`, `CHANGELOG.md` (changed) | Step index row, the new glossary terms, and the changelog entry. |

## Notes for this repository

- **The image digest is real.** The guide leaves `<digest>`. The multi-platform index digest of
  `qdrant/qdrant:v1.19.2` is `sha256:b7b0444c4c351c970b98e90a6f89c2ee4287c65b44e52b4cb503fa5b2aa927ad` (read here
  through Google's Docker Hub mirror, `mirror.gcr.io/qdrant/qdrant:v1.19.2`, because Docker Hub rate-limited this
  container); `compose.yaml` pins it. Confirm on your Mac with
  `docker buildx imagetools inspect qdrant/qdrant:v1.19.2 | head -5`.
- **Small script changes for strict mypy, ruff and testing.** The scripts are the guide's code formatted by ruff,
  with these differences, none of which change behaviour with the defaults:
  - The Qdrant URL is read from `QDRANT_URL` (default `http://127.0.0.1:6333`) in all three scripts, and the
    gateway URL in `qdrant_sync.py` from `LLM_GATEWAY_URL` (default `http://127.0.0.1:4000`), the same override
    `pg_demo.py` already has. The tests use it to point the sync at a fake embedder.
  - `qdrant_sync.py` reads `h.payload or {}` before indexing it, because the client types `payload` as "a dict or
    `None`".
  - `qdrant_setup.py` annotates the `indexes` dict with its value types for mypy.
  - `qdrant_token.py`'s `except Exception` comment drops the guide's `# noqa: BLE001`, because that ruff rule is not
    enabled here and ruff reports an unused `noqa` (RUF100) as an error.
- **The secrets generator** now creates both Qdrant keys for new machines with `openssl rand -hex 32`; the guide's
  `openssl` + `just secrets-edit` route is still the way to add them to an existing `secrets/dev.enc.env`. No real
  values are committed: only names in `.env.example`.
- **Faithful formatting fixes.** Line wraps from the PDF inside the Compose file, justfile recipes and Python were
  rejoined and indentation reconstructed; no statement was changed beyond the notes above.
- **What was validated here (Linux container, Docker, no Mac, no model servers, no SOPS key).** The real
  `qdrant/qdrant:v1.19.2` image (from the mirror, same digest) was started with this Compose file and test keys,
  together with `rag-db`: the container became **healthy** with the bash `/dev/tcp` healthcheck, the wrapper found
  `/qdrant/entrypoint.sh`, the log said `Telemetry reporting disabled`, `docker inspect` showed no key in the
  environment, and only `127.0.0.1:6333-6334` were published. `GET /collections` returned **401** without a key and
  with a wrong key, **200** with the admin or read-only key, and the read-only key got **403** (`Global manage
  access is required`) when trying to create a collection; `/telemetry` reported `version 1.19.2, jwt_rbac: true`.
  `qdrant_setup.py` created the collection and alias (and is idempotent on re-run); the stored config had
  `float16` 1024-d cosine `dense`, the `sparse` slot, HNSW 16/100, int8 quantization with `always_ram`, and the four
  payload indexes with `is_tenant`. After applying the Step 11 migration and loading `pg_demo.py`'s four documents
  through a fake gateway (deterministic bag-of-words embeddings), `qdrant_sync.py` synced 4 points (Qdrant count 4)
  and returned the **same documents in the same order with scores within 0.01 of pgvector's**; the all-staff user
  never saw "Exec offsite", and the executive got it first. `qdrant_token.py` printed `read : 4 points` and
  `write : rejected -> UnexpectedResponse`. The snapshot request (the `qdrant-snapshot` recipe's `curl`) returned a
  snapshot name, size and checksum. All of this is automated in `tests/test_qdrant.py` (16 tests passed live;
  without the services the live ones skip). The containers and volumes were removed afterwards. Not run here: the
  real embeddings through the gateway and the dashboard in a browser, which need the Mac.
