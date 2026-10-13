# Step 13 · OpenSearch: keyword, analyzers and hybrid search

*Step 13 of 38 · Phase C · Data stores*

## At a glance

| | |
|---|---|
| **Goal** | Add OpenSearch, a search engine that excels at keyword search (BM25, analyzers, synonyms), as another *derived index* fed from Postgres. Secure it with its security plugin and least-privilege users, give it vector search too, and run your first *hybrid search* that fuses keyword and vector scores. |
| **Time** | About 2 hours. |
| **You'll end up with** | An `opensearch` service (3.x, single node, TLS, admin password from secrets, localhost-only); `rag_search` (read-only) and `rag_indexer` users; a versioned index `rag-chunks-v1` behind the alias `rag-chunks`, with a custom analyzer and synonyms, keyword fields for filters, and a k-NN vector field; a hybrid search pipeline; a demo showing where keyword beats vector and vice versa; and ADR-0013. |
| **New words** | Search engine, inverted index, analyzer, tokenizer, token filter, stemming, synonyms, BM25, term frequency, inverse document frequency, mapping, shard, replica, JVM heap, security plugin, internal user, role mapping, k-NN plugin, Lucene engine, search pipeline, score normalisation, hybrid search, explain API. |

## The big idea

> **ANALOGY · THE INDEX AT THE BACK OF THE BOOK VS THE LIBRARIAN'S UNDERSTANDING**
> Vector search (Steps 8, 11, 12) is a librarian who understands meaning: ask about "working from my house" and
> they find the remote-work policy, even though those words never appear in it. But ask for "POL-117" and that
> librarian may hesitate: a code has little "meaning".
>
> The index at the back of a book is the opposite: it can't understand anything, but it finds exact words
> instantly and reliably. A search engine like OpenSearch is a super-powered back-of-book index, with rules for
> word variations ("Fridays" → "friday") and synonyms ("WFH" → "work from home").
>
> Hybrid search asks both and merges their answers. That's the usual production default.

```text
  Keyword search (BM25)            Vector search (embeddings)          Hybrid (both, fused)
  exact IDs: "POL-117"             paraphrases: "job from my house"    robust across all query types
  names, codes, error messages     different words, same meaning       the usual production default
  rare words, acronyms             other languages                     tune weights with evaluation
  "must contain this word"         vague or conversational questions   rerank the fused list (Step 8)
```

*Figure 40 of the guide: each retrieval style has queries it wins. Hybrid search combines them so no query type
falls through the cracks.*

## What we're doing

1. Generate strong passwords (admin, search, indexer) into the encrypted secrets.
2. Run `opensearch` in Compose: pinned 3.x, single node, memory-locked JVM heap, TLS and security plugin on,
   localhost-only.
3. Create least-privilege users and roles, a versioned index with a custom analyzer, synonyms, keyword filter
   fields and a k-NN vector field, behind an alias.
4. Add a hybrid search pipeline (min-max normalisation + weighted combination).
5. Add two documents to Postgres (the source of truth), sync everything into OpenSearch, then compare BM25,
   vector and hybrid results, with permission filters on all of them.
6. Use the explain API to see why a document scored as it did, and write ADR-0013.

## Why we're doing this

> **WHY THIS MATTERS**
> Real users type codes, product names, error messages, acronyms and exact phrases. Pure vector search is
> famously weak on these, and pure keyword search is weak on paraphrases. Benchmarks and production experience
> consistently show hybrid retrieval is more robust than either alone. OpenSearch also brings mature analyzers
> (stemming, synonyms, many languages), aggregations for analytics, and a widely used enterprise search platform
> you'll meet in real jobs.

| Need | How OpenSearch meets it |
|---|---|
| Exact matches: IDs, codes, names, rare terms | Inverted index with BM25 relevance scoring |
| Word variations and company jargon | Analyzers: tokenizers, lowercasing, stemming, synonyms |
| Meaning-based matches too | k-NN plugin with HNSW (Lucene engine) |
| Combine both fairly | Hybrid query + search pipeline with score normalisation |
| Permission filters in every query | Keyword fields (`acl_groups`, `tenant_id`) in filter clauses |
| Least privilege | Security plugin: TLS, internal users, roles, role mappings |
| Understand rankings | Explain API shows each score's ingredients |

> **IN A COMPANY**
> OpenSearch (and Elasticsearch, which it forked from) powers search in a huge number of enterprises. AWS offers
> it as Amazon OpenSearch Service. RAG teams often already have a search cluster, and the pragmatic architecture
> adds vectors and hybrid ranking to it rather than replacing it. Knowing analyzers, mappings, BM25 and hybrid
> pipelines is directly employable knowledge.

## Key ideas

### How keyword search works

```text
  "Staff may WFH on Fridays"
        │
        ▼
  tokenizer ──────────▶ lowercase ─────────▶ synonyms ─────────────────▶ stemmer
  split into words      WFH → wfh            wfh → work from home         fridays → friday

  terms stored: staff · may · work · from · home · friday

  Inverted index (like the index at the back of a book)
      friday   → doc 1, doc 5
      home     → doc 1, doc 6
      parking  → doc 2
      pol-117  → doc 5
```

*Figure 41 of the guide: an analyzer turns text into normalised terms (split, lowercase, synonyms, stemming), which
are stored in an inverted index mapping each term to the documents containing it.*

(The figure shows every stage on one string to explain the idea. In our index, synonyms run only on the *query*
side; see "Why different analyzers for indexing and searching?" below.)

| Term | Plain-English meaning |
|---|---|
| Inverted index | A map from each word to the documents containing it, like a book's index. |
| Analyzer | The recipe that turns text into searchable terms: a *tokenizer* (split into words) plus *token filters* (lowercase, synonyms, stemming). |
| Stemming | Reducing words to a common root ("Fridays", "friday" → "friday") so variations match. |
| Synonyms | Rules treating different terms as equivalent ("wfh" = "work from home" = "remote work"). |
| BM25 | The standard keyword relevance formula. A document scores higher when the query's words appear in it often (*term frequency*), when those words are rare across all documents (*inverse document frequency*), and when the document is short (length normalisation). Repeating a word gives diminishing returns. |
| Mapping | An index's schema: each field's type (`text`, `keyword`, `knn_vector` …) and analyzer. |
| `text` vs `keyword` fields | `text` is analysed for full-text search; `keyword` is stored exactly, for filters and IDs. |
| Shard / replica | An index is split into shards (pieces) and copied to replicas for scale and safety. Single node: 1 shard, 0 replicas. |
| JVM heap | OpenSearch runs on Java; the heap is its working memory. Typically about half the container's memory. |
| Security plugin | OpenSearch's built-in TLS, users, roles and permissions. |
| Internal user / role mapping | A user stored inside OpenSearch's security index / the link that gives a user (or backend role) a role's permissions. |
| k-NN plugin / Lucene engine | OpenSearch's vector search, here using Lucene's HNSW implementation. |
| Search pipeline | Processing steps applied to search results, e.g. normalising and combining scores for hybrid search. |
| Explain API | `"explain": true` on a search: OpenSearch returns the full arithmetic behind each score. |

> **IN PLAIN ENGLISH · WHY BM25 REWARDS RARE WORDS**
> If you search "POL-117 flights", the word "flights" appears in many travel documents, but "pol-117" appears in
> exactly one. BM25 gives the rare term much more weight, so the one document that actually mentions POL-117
> wins. That's exactly the behaviour embeddings struggle to reproduce.

A little more on BM25, in plain words. For each query word, BM25 asks three questions and multiplies the answers:

- **How rare is this word across the whole index?** (inverse document frequency, *idf*). A word in every
  document ("the", "policy") says almost nothing; a word in one document ("pol") is a strong signal.
- **How often does it appear in this document?** (term frequency, *tf*). More is better, but with diminishing
  returns: the 10th mention adds much less than the 2nd, so keyword stuffing doesn't win.
- **How long is this document?** A match in a short document counts for more than the same match buried in a long
  one.

The document's score is the sum over the query words. That is exactly what the explain output breaks down
(`sum of:` … `weight(text:pol in 4)` … `idf` … `tf` …).

### Hybrid search: combining apples and oranges

```text
                    ┌── BM25 match ────── scores like 2.1 … 11.7 ──┐
  question          │                                               │   normalise (min-max)        combine
  "WFH Fridays?" ───┤                                               ├─▶ both scaled to 0 … 1  ─▶  0.3 × keyword
                    │                                               │   different units →          + 0.7 × vector
                    └── k-NN (vector) ── scores like 0.61 … 0.83 ──┘   same scale

  A search pipeline does this inside OpenSearch. The weights are a starting point;
  Project 2 tunes them (and tries RRF) with evaluation.
```

*Figure 42 of the guide: BM25 and vector scores use different scales, so each list is normalised to 0–1 before a
weighted combination. A search pipeline does this inside OpenSearch.*

> **IN PLAIN ENGLISH · NORMALISATION**
> A BM25 score of 11.7 and a cosine score of 0.83 are in different units, like adding kilometres to kilograms.
> Min-max normalisation rescales each list so its best hit becomes 1 and its worst becomes 0. Only then can the
> two be mixed with weights (here 30 % keyword, 70 % meaning). Without this, raw BM25 numbers would simply swamp
> the vector scores.

### The index design

| Piece | Setting | Why |
|---|---|---|
| Index name / alias | `rag-chunks-v1` / `rag-chunks` | Applications always use the alias; a changed mapping is built as `-v2` and the alias switched (same blue/green idea as Qdrant in Step 12). |
| Shards / replicas | 1 / 0 | One node: more shards only add overhead, and a replica can't live on the same node. |
| `rag_index` analyzer | standard tokenizer → lowercase → English stemmer | How documents are stored: words split, lowercased and reduced to roots. |
| `rag_query` analyzer | standard tokenizer → lowercase → `rag_synonyms` (`synonym_graph`) → English stemmer | How questions are read: same as documents, plus synonym expansion. |
| Synonym rules | `wfh, work from home, remote work` and `pto, paid time off, annual leave` | Company jargon. Comma-separated = all equivalent. |
| `text`, `title` | `text` fields with both analyzers; `title.raw` is an exact `keyword` sub-field | Full-text search; the raw title supports exact sorting/aggregation. |
| `embedding` | `knn_vector`, dimension 1024, HNSW (Lucene), cosine, `m=16`, `ef_construction=100` | The same Qwen3 embedding contract as Steps 8, 11 and 12, copied from Postgres. |
| `tenant_id`, `acl_groups`, `classification`, `source_uri` | `keyword` | Exact values for filters: permission checks must never be "fuzzy". |
| `document_id` | `long` | Links each chunk back to its Postgres document. |

> **WHY DIFFERENT ANALYZERS FOR INDEXING AND SEARCHING?**
> Documents are indexed with plain stemming. Synonyms are applied only to the search side (`search_analyzer`).
> Updating the synonym list (say, new company jargon) then needs no re-indexing, and multi-word synonyms like
> "work from home" are handled correctly at query time by `synonym_graph`. This is the standard recommendation.

### Users and permissions

| User | Role permissions | Used by |
|---|---|---|
| `admin` | Everything (built in; password from `OPENSEARCH_ADMIN_PASSWORD`) | `os_setup.py` and `just os-health` only |
| `rag_search` | Cluster: `cluster_composite_ops_ro`; indices `rag-chunks*`: `read` | Anything that only searches (the demo's queries, `just os-count`, later the RAG API) |
| `rag_indexer` | Cluster: `cluster_composite_ops` (needed for `_bulk`); indices `rag-chunks*`: `crud`, `create_index`, `manage_aliases` | The sync job from Postgres |

Each user gets its own role and a *role mapping* (`users: [name]`) that connects the two. Neither can touch any
other index or the security configuration.

## How to do it

All commands run on the Mac from the project folder (`~/dev/rag-platform`, the root of this repository). Start a
feature branch:

```bash
cd ~/dev/rag-platform
git switch -c feat/opensearch
```

### 1 · Strong passwords

OpenSearch rejects weak passwords (minimum length, several character classes, an entropy check) and refuses to
start if the admin password is weak. Generate three that include upper, lower, digit and symbol:

```bash
for i in 1 2 3; do echo "$(openssl rand -base64 24 | tr -d '/+=\n')#9Qx"; done
just secrets-edit
#      OPENSEARCH_ADMIN_PASSWORD=<1st>
#      OPENSEARCH_SEARCH_PASSWORD=<2nd>
#      OPENSEARCH_INDEXER_PASSWORD=<3rd>
```

The random part gives the strength; the fixed `#9Qx` suffix just guarantees a symbol, a digit, and both cases are
present, which the password policy demands. On a new machine, `just secrets-init` (`scripts/new-dev-secrets.sh`)
now generates all three the same way, and `.env.example` lists their names.

### 2 · Add OpenSearch to Compose

Use the current 3.x release (3.8.0 at the time of writing; check OpenSearch's releases) and pin its digest. Then
confirm the image's start command, because the wrapper below must call it:

```bash
docker buildx imagetools inspect opensearchproject/opensearch:3.8.0 | head -5
docker image inspect opensearchproject/opensearch:3.8.0 --format 'entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}}'
```

For 3.8.0 this prints `entrypoint=["./opensearch-docker-entrypoint.sh"] cmd=["opensearch"]`, with the working
directory `/usr/share/opensearch`, so the full path is `/usr/share/opensearch/opensearch-docker-entrypoint.sh`.

The service added to `infra/compose/compose.yaml`:

```yaml
services:
  opensearch:
    image: opensearchproject/opensearch:3.8.0@sha256:fafe3fc3587088674669235575aa166228c48bdb940294a8cdbbc1da75236a40
    # Admin password from a secret FILE, exported only inside the process; then hand over to the
    # image's own entrypoint (adjust the path/args to what `docker image inspect` printed).
    entrypoint: ["/bin/bash", "-c"]
    command:
      - >
        export OPENSEARCH_INITIAL_ADMIN_PASSWORD="$$(cat /run/secrets/opensearch_admin_password)" &&
        exec /usr/share/opensearch/opensearch-docker-entrypoint.sh opensearch
    environment:
      discovery.type: single-node               # one node: no cluster discovery
      bootstrap.memory_lock: "true"             # keep the heap in RAM (no swapping)
      OPENSEARCH_JAVA_OPTS: "-Xms2g -Xmx2g"     # fixed 2 GB heap (half the container limit)
    secrets: [opensearch_admin_password]
    ulimits:
      memlock: { soft: -1, hard: -1 }
      nofile: { soft: 65536, hard: 65536 }
    volumes:
      - opensearch-data:/usr/share/opensearch/data
    ports:
      - "127.0.0.1:9200:9200"                   # REST API (HTTPS). 9600 (perf analyzer) not published
    healthcheck:
      # "up" = answers HTTPS at all (401 without credentials is fine), so no password in the healthcheck
      test: ["CMD-SHELL", "curl -sk -o /dev/null -w '%{http_code}' https://localhost:9200 | grep -qE '200|401'"]
      interval: 20s
      timeout: 10s
      retries: 15
      start_period: 60s
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 4g, cpus: "4" }

volumes:
  opensearch-data:

secrets:
  opensearch_admin_password: { environment: OPENSEARCH_ADMIN_PASSWORD }
```

What each part does, in plain words:

- **The wrapper `command`.** The image only reads the first-time admin password from the environment variable
  `OPENSEARCH_INITIAL_ADMIN_PASSWORD`. Putting it under `environment:` would expose it in `docker inspect`, so (as
  with LiteLLM and Qdrant) a small `bash -c` reads it from the secret *file* and exports it only inside the
  process, then `exec`s the image's own entrypoint. `$$` stops Compose from expanding it on your Mac.
- **`discovery.type: single-node`.** One node forms its own cluster; no searching the network for peers.
- **`bootstrap.memory_lock` + `memlock: -1`.** Lock the heap in RAM so the operating system never swaps it to disk
  (swapped heaps cause multi-second pauses).
- **`-Xms2g -Xmx2g`.** Minimum and maximum heap equal and fixed at 2 GB: half the 4 GB container limit, leaving the
  other half for the operating system's file cache, which Lucene relies on heavily.
- **`nofile: 65536`.** OpenSearch keeps many index files open at once.
- **Ports.** Only the HTTPS API, only on `127.0.0.1`. The performance-analyzer port 9600 isn't published.
- **Healthcheck.** Any HTTP answer (200, or 401 "credentials required") proves the node is up, so the check
  needs no password.

Start it and check:

```bash
just up && just ps                                    # OpenSearch takes ~1 minute to become healthy
just logs opensearch                                  # watch for "started"; Ctrl+C
curl -sk -o /dev/null -w "%{http_code}\n" https://127.0.0.1:9200                         # 401: credentials required
just with-secrets 'curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" https://127.0.0.1:9200 | jq .version.number'
```

> **WATCH OUT · DEMO CERTIFICATES ARE FOR DEVELOPMENT ONLY**
> With the security plugin's demo setup, OpenSearch generates self-signed TLS certificates, which is why `curl`
> needs `-k` (don't verify) and the Python client uses `verify_certs=False`. Traffic is encrypted, but the
> certificate proves nothing about identity. Production uses certificates from a real certificate authority,
> verified by every client (cert-manager on Kubernetes, Step 29).

> **TIP · IF IT WON'T START**
> - "vm.max_map_count too low": the Linux VM needs a higher limit. On OrbStack/Docker run
>   `docker run --rm --privileged alpine sysctl -w vm.max_map_count=262144`, then `just up` again. The setting
>   lasts until the VM restarts.
> - Password rejected: generate a stronger one, and delete the volume (`docker volume rm rag-platform_opensearch-data`)
>   so first-time setup runs again.
> - Entrypoint error: fix the path or arguments in `command:` to match `docker image inspect`.

### 3 · Users, index, alias and hybrid pipeline

`scripts/os_setup.py` does three things as `admin`, and is safe to re-run:

1. **Least-privilege roles and users.** For `rag_search` and `rag_indexer` it `PUT`s a role, an internal user
   (with the password from secrets) and a role mapping through the security plugin's REST API
   (`/_plugins/_security/api/...`).
2. **The index**, only if it doesn't exist yet: `rag-chunks-v1` with `knn: true`, 1 shard, 0 replicas, the
   `rag_synonyms` (`synonym_graph`) and `english_stemmer` filters, the `rag_index` and `rag_query` analyzers, the
   mapping from the table above, and the alias `rag-chunks`.
3. **The hybrid search pipeline** `rag-hybrid`: a `normalization-processor` (a *phase results* processor, so it
   runs between the query phase and the fetch phase, when both sub-queries' scores are known) with
   `min_max` normalisation and an `arithmetic_mean` combination weighted `[0.3, 0.7]` (keyword first, vector
   second, in the order the hybrid query lists them).

```bash
just with-secrets uv run --with opensearch-py scripts/os_setup.py
```

Expected output:

```text
users: rag_search (read), rag_indexer (write) on rag-chunks*
created rag-chunks-v1 with alias rag-chunks
pipeline rag-hybrid ready
```

You can watch the analyzers at work with the `_analyze` API:

```bash
just with-secrets 'curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" -H "Content-Type: application/json" \
  https://127.0.0.1:9200/rag-chunks-v1/_analyze -d "{\"analyzer\":\"rag_query\",\"text\":\"WFH on Fridays\"}" | jq -c "[.tokens[].token]"'
```

The query analyzer's tokens for `WFH on Fridays` include `wfh`, `work`, `from`, `home`, `remot` and `fridai`: the
synonym expansion plus English stemming (`remote` → `remot`, `fridays` → `fridai`; stems don't have to be real words, they
only have to be the same for every variation). The index analyzer turns `Staff may WFH on Fridays` into
`staff`, `mai`, `wfh`, `on`, `fridai`, with no synonyms.

### 4 · Add documents at the source, sync, and compare search styles

Following the source-of-truth rule from Step 12, new documents go into Postgres first. `scripts/os_demo.py` adds
two (a policy with a code, and an acronym-heavy note), syncs every live chunk into OpenSearch, then compares the
three search styles:

1. **Source of truth first.** As `rag_app`, it inserts "Travel policy POL-117" and "WFH requests" into the `demo`
   collection from Step 11 (skipping any whose `source_uri` already exists, so re-runs are safe), embedding each
   through the gateway with the *ingestion* virtual key.
2. **Sync** every live chunk (`deleted_at IS NULL`) into the alias as `rag_indexer`, with the Postgres chunk id as
   the OpenSearch `_id` and the stored embedding copied (never re-embedded), using `helpers.bulk(..., refresh=True)`
   so the documents are searchable immediately.
3. **Search** as the read-only `rag_search` user, with the permission filter (`tenant_id` = `acme` and
   `acl_groups` overlapping the user's groups) on every query: in the BM25 `bool` query's `filter`, inside the
   k-NN query's own `filter`, and therefore in both sub-queries of the `hybrid` query, which runs through the
   `rag-hybrid` pipeline. Questions are embedded with the query instruction and the *RAG API* virtual key.
4. **Explain** the top BM25 hit for "POL-117 business class".

```bash
just with-secrets uv run --with opensearch-py --with "psycopg[binary]" --with pgvector --with openai scripts/os_demo.py
```

The Step 11 demo collection must exist first (`scripts/pg_demo.py`), because the new documents join it.

> **TIP · WHAT TO LOOK FOR**
> - "POL-117 business class": BM25 nails the policy because "pol" and "117" are rare terms. Vector search may rank
>   it lower or mix in other travel or "class" content.
> - "Can I do my job from my house…": none of these words appear in the remote-work policy. BM25 struggles;
>   vector search finds it by meaning.
> - "WFH approval": the synonym rule expands "wfh" to "work from home / remote work", so BM25 matches both the WFH
>   note and the remote-work policy.
> - Hybrid puts a sensible answer at the top in all three cases. That robustness is the point.
> - Every query carried the permission filter, so restricted documents never appear for an all-staff user.

> **TIP · READ THE EXPLAIN OUTPUT**
> The explain result breaks a BM25 score into its parts: how often each term appears (tf), how rare it is across
> the index (idf), and the document-length adjustment. When search behaves unexpectedly in Step 32, explain is
> your first debugging tool.

```text
                         Postgres + pgvector
                         source of truth · permissions · deletions · versions
                                  │ one-way sync
               ┌──────────────────┴──────────────────┐
               ▼                                     ▼
            Qdrant                               OpenSearch
  vector specialist: quantization,     keywords, analyzers, hybrid, aggregations
  tenants

  Projects 1, 2 and 17 compare all three with the same questions and the evaluation harness.
```

*Figure 43 of the guide: the platform's three stores and their roles. Postgres stays the single source of truth;
Qdrant and OpenSearch are specialised, rebuildable mirrors compared side by side in later projects.*

### 5 · just recipes and the decision

Two recipes were added to the `justfile`:

```text
# OpenSearch: cluster health (admin) and index document counts
os-health:
    sops exec-env secrets/dev.enc.env 'curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" https://127.0.0.1:9200/_cluster/health | jq -c "{status, number_of_nodes, active_shards}"'

os-count:
    sops exec-env secrets/dev.enc.env 'curl -sk -u "rag_search:$OPENSEARCH_SEARCH_PASSWORD" https://127.0.0.1:9200/rag-chunks/_count | jq .count'
```

The single quotes matter: the password is expanded by the shell that `sops exec-env` starts, never by `just` or
your terminal history.

```bash
just os-health        # status "green" (or "yellow" is also normal on one node if replicas > 0)
just os-count         # should equal the live chunk count in Postgres
just adr "Use OpenSearch for keyword and hybrid search as a derived index"
```

The decision is recorded in
[ADR-0013](../adr/0013-use-opensearch-for-keyword-and-hybrid-search-as-a-derived-index.md): OpenSearch 3.x,
single node, digest-pinned, security plugin and TLS (demo certificates in development only), admin password from
SOPS, 2 GB heap, port 9200 on 127.0.0.1; `rag_search` (read) and `rag_indexer` (write) on `rag-chunks*`; the
analyzed index behind its alias; the `rag-hybrid` pipeline with 0.3/0.7 weights to be tuned; one-way data flow from
Postgres; tenant and ACL filters on every query. Alternatives considered: Postgres full-text only, Elasticsearch,
Qdrant sparse vectors, and Vespa / Typesense / Meilisearch.

Finish through a pull request, as in earlier steps:

```bash
git add -A
git commit -m "feat(opensearch): secured OpenSearch with analyzers, synonyms, k-NN and hybrid pipeline"
git push -u origin feat/opensearch
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Strong on exactly what vectors miss:** codes, IDs, names, acronyms and rare terms.
- **Language handling:** stemming and synonyms capture company jargon without re-embedding anything.
- **Hybrid in one request:** normalised, weighted fusion via a search pipeline, tunable later with evaluation.
- **Explainable ranking:** the explain API shows exactly why a document scored as it did.
- **Least privilege and TLS:** separate read and write users; encrypted traffic.
- **Career-relevant:** OpenSearch/Elasticsearch skills are widely used in enterprises and map directly to AWS.

## Drawbacks and risks

- **Heavy:** a JVM with a 2 GB heap inside a 4 GB container, the biggest service so far. Watch the VM memory cap
  from Step 3.
- **Operational depth:** heap sizing, shards, mappings and upgrades need care. Mapping changes usually mean
  re-indexing (versioned index + alias helps).
- **Score fusion is subtle:** min-max normalisation is sensitive to outliers and to how many results each side
  returns. Weights must be tuned with evaluation, not guessed (Step 32 also tries RRF).
- **Demo certificates:** convenient but insecure as an identity guarantee. Never use them outside development.
- **Another sync target:** deletions and updates must propagate (Step 36), same as Qdrant.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **OpenSearch (our choice)** | Open-source search engine: BM25, analyzers, k-NN, hybrid pipelines | Enterprise keyword + hybrid search, AWS alignment |
| Elasticsearch | The original engine OpenSearch forked from; similar features | Your company runs Elastic already |
| Postgres full-text (+ extensions such as ParadeDB/pg_search) | Keyword search inside Postgres | You want one database and moderate search needs |
| Qdrant / Weaviate sparse + dense | Hybrid inside a vector database | Vector-first systems with simple keyword needs |
| Vespa | Search + ranking engine with ML ranking built in | Large-scale, highly customised ranking |
| Typesense / Meilisearch | Lightweight, developer-friendly search | Small apps, instant search UIs |
| Managed (Amazon OpenSearch Service, Elastic Cloud, Azure AI Search, Vertex AI Search) | Hosted search with hybrid features | Cloud deployments (Step 37) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Users search with codes, IDs, product names | Hybrid with a strong keyword engine (this step) |
| Mostly conversational questions | Vector-first, plus hybrid as a safety net |
| Company already has Elastic/OpenSearch | Add vectors + hybrid to the existing cluster |
| Small corpus, minimal ops | Postgres full-text + pgvector, fused in SQL (Step 32) |
| Many languages | Per-language analyzers in OpenSearch, plus a multilingual embedder |

## Common mistakes

- **Using `text` fields for filters or IDs.** Analysed text doesn't match exactly. Use `keyword` fields.
- **Synonyms at index time,** so every synonym change needs a re-index. Prefer query-time `synonym_graph`.
- **Adding raw BM25 and vector scores without normalising them first.** BM25 swamps the result.
- **Forgetting the permission filter in one of the hybrid sub-queries.** Each sub-query must filter.
- **Heap larger than about half the container memory, or no memory lock,** leading to swapping and long GC pauses.
- **Disabling the security plugin "to make it easier".** It's open on the network and unencrypted.
- **Querying the versioned index name instead of the alias.**

## Done when

- [ ] `opensearch` runs pinned at 3.x, healthy, on 127.0.0.1:9200 only; unauthenticated requests get 401
- [ ] `rag_search` (read) and `rag_indexer` (write) exist; the demo uses each for its job
- [ ] `rag-chunks-v1` has the custom analyzers, synonyms, keyword ACL fields and a 1024-dimension Lucene HNSW
      vector field; alias `rag-chunks` points to it
- [ ] Pipeline `rag-hybrid` exists
- [ ] `os_demo.py` added two documents to Postgres and synced every live chunk; `just os-count` matches Postgres
- [ ] You saw BM25 win on "POL-117", vector win on the paraphrase, synonyms help "WFH", and hybrid handle all three
- [ ] You read an explain breakdown
- [ ] ADR-0013 and all files are merged through a PR

## Recap

> **RECAP**
> OpenSearch completes the retrieval trio:
> - **Postgres:** truth and permissions
> - **Qdrant:** vector specialist
> - **OpenSearch:** keywords, analyzers, synonyms and hybrid fusion
>
> You've seen concretely why hybrid retrieval is the production default: exact codes favour BM25, paraphrases
> favour vectors, and normalised fusion handles both, with permission filters on every path. Next, object storage
> (Step 14): an S3-compatible store for the original files every pipeline starts from.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/compose/compose.yaml` (changed) | New `opensearch` service (3.8.0 pinned by tag@digest, admin password from a secret file via a wrapper, single node, locked 2 GB heap, 4 GB limit, 127.0.0.1:9200 only, password-free healthcheck), the `opensearch-data` volume and the `opensearch_admin_password` secret. |
| `scripts/new-dev-secrets.sh` (changed) | Generates `OPENSEARCH_ADMIN_PASSWORD`, `OPENSEARCH_SEARCH_PASSWORD` and `OPENSEARCH_INDEXER_PASSWORD` in the guide's strong format for new machines. |
| `.env.example` (changed) | Lists the three OpenSearch password names (no values). |
| `justfile` (changed) | `just os-health` (cluster health as admin) and `just os-count` (document count as `rag_search`, through the alias). |
| `scripts/os_setup.py` | Creates the `rag_search` / `rag_indexer` roles, users and role mappings, the `rag-chunks-v1` index (analyzers, synonyms, keyword fields, Lucene HNSW vector) with alias `rag-chunks`, and the `rag-hybrid` search pipeline. Idempotent. |
| `scripts/os_demo.py` | Adds two documents to Postgres first, syncs all live chunks into OpenSearch as the indexer, compares BM25, vector and hybrid search with permission filters as the read-only user, and prints an explain breakdown. |
| `tests/test_opensearch.py` | Static checks of the Compose service, secrets, recipes and scripts; live checks (opt-in) of 401, the index/alias/pipeline design, the analyzers, least privilege, and the full demo against Postgres. |
| `pyproject.toml`, `uv.lock` (changed) | `opensearch-py` added to the dev group so mypy and the tests can check the scripts. |
| `docs/adr/0013-use-opensearch-for-keyword-and-hybrid-search-as-a-derived-index.md` | ADR-0013, plus its row in `docs/adr/README.md`. |
| `docs/steps/step-13-opensearch-keyword-hybrid-search.md` | This write-up, plus its row in `docs/steps/README.md`, the changelog entry and new glossary terms. |

## Notes for this repository

- **The image digest is real.** The guide leaves `<digest>`. The digest of `opensearchproject/opensearch:3.8.0`
  as pulled here is `sha256:fafe3fc3587088674669235575aa166228c48bdb940294a8cdbbc1da75236a40`, and
  `docker image inspect` confirmed the entrypoint `./opensearch-docker-entrypoint.sh` with `cmd ["opensearch"]`,
  matching the wrapper's `exec /usr/share/opensearch/opensearch-docker-entrypoint.sh opensearch`. Confirm the
  digest on your Mac with `docker buildx imagetools inspect opensearchproject/opensearch:3.8.0 | head -5` (Docker
  Hub rate-limited that call in this container).
- **Small script changes for strict mypy, ruff and testing.** The scripts are the guide's code formatted by ruff,
  with these differences, none of which change behaviour with the defaults:
  - `os_demo.py` reads the gateway URL from `LLM_GATEWAY_URL` (default `http://127.0.0.1:4000`), the same override
    `pg_demo.py` and `qdrant_sync.py` have; the tests use it to point the demo at a fake embedder.
  - `os_demo.py`'s `conn.execute(...).fetchone()[0]` calls go through a tiny `first()` helper that fails with a
    clear message if no row came back (e.g. the Step 11 demo collection wasn't loaded), because psycopg types
    `fetchone()` as "a row or `None`". Return types of `bm25`, `knn` and `show` are `dict[str, Any]` for mypy.
- **The secrets generator** now creates the three passwords for new machines with the guide's own formula
  (`openssl rand -base64 24 | tr -d '/+=\n'` followed by `#9Qx`); the `openssl` + `just secrets-edit` route is still
  the way to add them to an existing `secrets/dev.enc.env`. No real values are committed: only names in
  `.env.example`.
- **Faithful formatting fixes.** Line wraps from the PDF inside the Compose file, justfile recipes and Python were
  rejoined and indentation reconstructed; no statement was changed beyond the notes above.
- **What was validated here (Linux container, Docker, no Mac, no model servers, no SOPS key).** The real
  `opensearchproject/opensearch:3.8.0` image was started with this Compose file and test passwords, together with
  `rag-db`. The sandbox's own hard limits (open files 20000, locked memory 8 MB) are below the `ulimits` the
  Compose file asks for, so for this run only, a throwaway override file (not committed) removed the `ulimits`
  block; OpenSearch then logged "Unable to lock JVM Memory" (expected without the memlock limit) and otherwise
  started normally. On a Mac with OrbStack the committed `ulimits` apply as written. Results: the container became
  **healthy** with the password-free healthcheck, `docker inspect` showed no password in its environment, only
  `127.0.0.1:9200` was published, an unauthenticated request got **401**, and admin saw version **3.8.0**.
  `os_setup.py` created the users, the index, the alias and the pipeline, and re-running it was harmless. The
  `_analyze` API produced exactly the tokens shown above. `rag_search` could count but got **403** writing to
  `rag-chunks` or reading any other index; `rag_indexer` could write `rag-chunks` but got **403** creating another
  index or reading the security API. After applying the Step 11 migration and loading `pg_demo.py`'s four
  documents through a fake gateway (deterministic bag-of-words embeddings), `os_demo.py` added its two documents,
  synced **6 chunks**, and the `os-count` and `os-health` commands returned **6** (equal to Postgres's live chunk
  count) and `{"status":"green","number_of_nodes":1,...}`. BM25 put "Travel policy POL-117" first for
  "POL-117 business class" (hybrid kept it first), "WFH approval" matched both "WFH requests" and the "Remote work
  policy" through the synonym rule, no restricted or confidential document appeared on any path, and explain
  printed `sum of:` with `weight(text:pol in 4)` details. All of this is automated in `tests/test_opensearch.py`
  (18 tests passed live; without the services the live ones skip). The containers and volumes were removed
  afterwards. Not checked here: the paraphrase result ("job from my house" → remote-work policy), which needs the
  real Qwen3 embedder through the gateway on the Mac; the fake embedder only shares exact words.
