# Extension 01 · Retrieval maths, metadata filters, fusion, caching and routing

*Extension 01 · after the 38 guide steps · RAG core (search)*

## At a glance

| | |
|---|---|
| **Goal** | Make every remaining "how search decides" choice a switch in `rag.yaml`: how vector similarity is measured, which documents qualify (metadata filters, also pulled out of the question), how ranked lists are combined, whether a repeated search is answered from a cache, and which index a question goes to. |
| **How, in one sentence** | Every vector store gets a `metric` (cosine, dot, L2, L1), index settings and quantization, checked against what the index was built with; a typed filter expression travels with every query and each store translates it into its own language, always on top of the permission filter; four more fusion methods; a retrieval-result cache keyed by access and index epoch; and two new retrievers, `ensemble` and `router`, plus a `self-query` transformer. |
| **You'll end up with** | `metric` / `index_type` / `hnsw_m` / `ef_construction` / `ef_search` / quantization on `memory`, `pgvector`, `qdrant` and `opensearch-knn`, with an embedding-contract check and scores where higher = better on every store · `rag_core.filters`: eq, ne, in, nin, gt/gte/lt/lte, range, exists, and/or/not over chunk metadata and the source document, pushed down as SQL, a Qdrant payload filter, an OpenSearch bool filter, or Python · `rag search --filter`, `rag ask --filter`, `"filter"` in `/v1/search` and `/v1/answer` (validated, 422 on mistakes, documented in the OpenAPI schema) · query transformer `self-query` (rules offline, or an LLM checked against your schema) · fusion `relative-score`, `combsum`, `combmnz`, `borda` (next to `rrf`, `weighted`, `dbsf`) · slot `search_cache` (`memory`, `valkey`) · retrievers `ensemble` and `router` · `rag index ddl` · migration `20261015000000_vector_metrics_and_filters.sql` · conformance checks `check_metadata_filters` and `check_metrics`, run live on Postgres/pgvector, Qdrant and OpenSearch · ADR-0039. |
| **New words** | similarity metric, cosine similarity, inner (dot) product, Euclidean (L2) distance, Manhattan (L1) distance, score normalisation, HNSW `m` / `ef_construction` / `ef_search`, IVFFlat, flat (exact) index, scalar / binary quantization, oversampling and rescoring, iterative index scan, metadata filter, pre-filtering, self-query, relative score fusion, CombSUM, CombMNZ, Borda count, retrieval-result cache, ensemble retriever, query router. |

## In plain English

> **IN PLAIN ENGLISH**
> Search has four quiet decisions inside it that the first 38 steps made for you:
> 1. **How "close" two pieces of text are.** Every passage and every question becomes a list of
>    numbers (a vector). "Close" can mean *pointing the same way* (cosine), *pointing the same way and
>    being big* (dot product), or *being near each other* (L2, L1). The right one is the one your
>    embedding model was trained with: get it wrong and search still runs, but ranks badly, silently.
> 2. **Which documents count at all.** "Only HR documents, updated since January, in French."
>    That is not a question for the embedding (it doesn't know dates), it is a *filter*, and it must
>    be applied inside the database, together with the permission filter, never instead of it.
> 3. **How two ranked lists become one.** Vector search and keyword search each return a list. There
>    are several sensible ways to merge them; each favours something different.
> 4. **Where to look.** With one index per department, a question about payroll should go to HR's.
>
> This extension makes each of those a named, tested switch in `rag.yaml`, and adds two time-savers:
> a cache of search results, and a search that runs several retrievers at once.

> **ANALOGY · THE LIBRARIAN, AGAIN**
> Step 32's librarian rephrases your question, looks in the catalogue and the index, merges and
> tidies. Now give them:
> - **a ruler that matches the map** (the metric): distances on a map drawn in kilometres must be
>   measured in kilometres;
> - **the shelf labels** (filters): "only the HR shelf, only this year's binders", which they apply
>   *inside* the locked room's rules, not as a way around them;
> - **a rule for merging two shortlists** (fusion): count votes, add up marks, or reward agreement;
> - **a notebook of recent requests** (the cache), torn out whenever a book is added or withdrawn;
> - **a front desk** (the router) that sends you to the right branch library.

## What we're doing

1. Make the vector metric switchable on every vector store, with index tuning and quantization where
   the store supports them, a contract check, and comparable scores.
2. Add a typed metadata filter that every store applies in its own query language, on top of the
   permission filter; expose it in the SDK, the CLI and the API; and add `self-query`, which finds the
   filter hidden in a question.
3. Add four fusion methods and document how they differ; add a retrieval-result cache; add the
   `ensemble` retriever (N retrievers in parallel, fused).
4. Add the `router` retriever: one question, the right collection, profile or retriever.

## Why this matters

- **Wrong metric = quietly worse search.** A model trained for inner product, searched with cosine,
  returns plausible but wrong rankings; nothing errors. The contract check turns that into an error at
  start-up or first search.
- **Filters are the most common enterprise search request** ("only current policies", "only my
  region"). Applying them *after* search returns too few results; applying them *instead of* the
  permission filter would be a data leak. Here they are pushed down into each store and ANDed with
  access, and a conformance check proves it on every store.
- **Fusion choice changes results** as much as reranker choice on some corpora; now it is a one-word
  change that `rag eval-search` can compare.
- **The cache** saves an embedding call, two store round trips and the reranker (often the slowest
  step) on repeated searches, without ever crossing access boundaries or outliving a document change.
- **Multi-index setups** (one collection per department, per language, per embedding model) need a
  way to search one, several, or all of them at once.

## How it works

### 1. Similarity metrics, index settings and the embedding contract

```
                    profile says                      index was built with
 vector_store: {use: pgvector, metric: dot}    rag.collections.distance_metric = 'dot'
                         │                                  │
                         └──────────── compare ─────────────┘
                              equal: search · different: ContractError
                              (an EMPTY collection takes the profile's on its first write)
```

| Metric | Measures | Score reported (higher = better) | pgvector | Qdrant | OpenSearch |
|---|---|---|---|---|---|
| `cosine` (default) | Angle only | cosine similarity, −1…1 | `<=>`, `*_cosine_ops` | `Cosine` | `cosinesimil` |
| `dot` | Angle and length | the inner product | `<#>` (negative), `*_ip_ops` | `Dot` | `innerproduct` |
| `l2` | Straight-line distance | 1 / (1 + distance) | `<->`, `*_l2_ops` | `Euclid` | `l2` |
| `l1` | Sum of absolute differences | 1 / (1 + distance) | `<+>`, `*_l1_ops` (pgvector ≥ 0.7) | `Manhattan` | `l1`: `engine: nmslib` (2.x) or `index_type: flat` |

Every store returns the same number for the same pair of vectors: OpenSearch's own score formulas
((1 + cos) / 2, 1 / (1 + d²), …) and Qdrant's raw distances for Euclid/Manhattan are converted back.
`check_metrics` proves it live: four vectors chosen so that the metrics *disagree* must come back in
the exact order, with the exact scores, that plain arithmetic gives.

| Setting | Means | pgvector | Qdrant | OpenSearch |
|---|---|---|---|---|
| `index_type: hnsw` (default) | Approximate graph search: fast, ~99% recall | ✓ | ✓ | ✓ |
| `index_type: flat` | Exact, brute force: perfect recall, slow on big collections | `ORDER BY` that can't use an index | `exact: true` | `knn_score` script, no graph |
| `index_type: ivfflat` | Clusters (`lists`), searches `probes` of them | ✓ (not l1) | – | – |
| `hnsw_m` (16) | Links per node: recall vs memory | index DDL | `hnsw_config.m` | `method.parameters.m` |
| `ef_construction` (64/100) | Build-time candidates: graph quality vs build time | index DDL | `ef_construct` | `ef_construction` |
| `ef_search` (80/128/100) | Query-time candidates: recall vs latency | `hnsw.ef_search` | `hnsw_ef` (old name accepted) | `method_parameters.ef_search` |
| `quantization` | Smaller vectors in the index, re-scored with the originals | `binary` (+`oversample`); `vector_type: halfvec` is already 16-bit | `scalar` (int8), `binary` (+`oversampling`) | engine settings, not exposed |
| `iterative_scan` (pgvector ≥ 0.8) | Keep scanning until k rows pass the filters | `relaxed_order` (default) / `strict_order` / `off` | built in | built in (efficient filtering) |

**The contract check**, per store: pgvector compares the collection row (`distance_metric`,
`dimensions`, a new column from the migration); Qdrant reads the collection's vector `distance` and
`size`; OpenSearch reads the vector field's `space_type` and `dimension` from the mapping. A mismatch
raises `ContractError` naming both values and the fix ("change the profile, or `rag reindex` into a new
collection").

**Indexes for other metrics.** Step 11's HNSW index uses `halfvec_cosine_ops`. A dot-product (or
L2, L1, IVFFlat, binary) collection needs its own index or it falls back to an exact scan (correct,
slow). `rag index ddl --profile <p>` prints the statement for the profile's settings, for a project
migration; `create_index: true` creates it on first use in dev and tests.

### 2. Metadata filters

```
 /v1/search {"query": …, "filter": {"department": "hr", "updated": {"gte": "2025-01-01"}}}
        │ validated once (rag_core.filters.parse): unknown operator, bad date, bad field → 422
        ▼
 permission filter (tenant, classification, groups — from OPA)   AND   metadata filter
        │
        ├─ pgvector / postgres-fts: … WHERE <access SQL> AND ((c.metadata -> %(f0)s) @> %(f1)s::jsonb AND …)
        ├─ qdrant:      {"must": [<access conditions>, {"must": [{"key": "metadata.department", …}]}]}
        ├─ opensearch:  {"bool": {"filter": [<access terms>, {"bool": {"filter": [{"term": …}, {"range": …}]}}]}}
        └─ memory:      a Python test on each chunk (the reference the others are compared to)
```

| Write | Means |
|---|---|
| `{"department": "hr"}` | equal (for a list field such as `tags`: contains) |
| `{"department": ["hr", "it"]}` or `{"department": {"in": [...]}}` | any of |
| `{"doc_type": {"ne": "draft"}}`, `{"tags": {"nin": [...]}}` | not equal / none of (true when the field is missing) |
| `{"version": {"gte": 2}}`, `{"updated": {"lt": "2026-01-01"}}` | numbers, or ISO 8601 dates (a bare date = midnight UTC) |
| `{"updated": {"range": {"gte": "2025-01-01", "lt": "2026-01-01"}}}` | the same, as a range |
| `{"tags": {"exists": true}}` | has a value (not missing, null or an empty list) |
| `{"and": [...]}`, `{"or": [...]}`, `{"not": {...}}` | combine; several keys in one mapping are ANDed |
| `{"document": "s3://rag-raw-docs/hr/leave.pdf"}` | the source document itself |

Fields are chunk metadata: what the parser and chunker set (`title`, `section`, `language`), and any
scalar or list metadata you attach to the source at ingestion (`department`, `doc_type`, `tags`,
`updated`, `source`, …). Limits keep filters cheap: 64 conditions, 6 levels, 100 values per list.
In Postgres every value *and* field name is a bound parameter; dates go through
`rag.safe_timestamptz`, so a malformed date in the data is "no match", never a failed search.

**Self-query** finds the filter hidden in the question, against a schema you declare:

```
"HR policies updated after 2025"
   rules:  "hr" ∈ department.values · "policies" is a synonym of doc_type "policy" · "after 2025" → ≥ 2026-01-01
   filter: {"and": [{"department": "hr"}, {"doc_type": "policy"}, {"updated": {"gte": "2026-01-01"}}]}
   search: the question, with that filter AND the caller's filter AND the permission filter
   nothing found? search again without the self-query filter (fallback_on_empty) and say so in the trace
```

`mode: llm` asks the `llm` slot for the filter as JSON, then **checks it against the schema**:
undeclared fields, undeclared values or wrong types (an LLM that invents `classification: public`)
are rejected and the rules answer instead. A model failure never fails the search.

### 3. Fusion, the result cache and the ensemble

| Fusion | Each list becomes | Then | Rewards |
|---|---|---|---|
| `rrf` (default) | 1 / (k + rank) | sum | Being near the top anywhere; no tuning |
| `borda` | N, N−1, … points (N = longest list) | sum | Positions, with more weight in the middle than RRF |
| `weighted` | min-max to 0…1 | weighted sum | How *much* better a hit is |
| `relative-score` | min-max to 0…1 | `alpha` × dense + (1 − alpha) × keyword | Same maths as `weighted`, configured the Weaviate way |
| `dbsf` | scaled by mean ± 3 std devs | weighted sum | Lists whose score spreads differ; robust to one outlier |
| `combsum` | min-max (or `zscore`, `none`) | sum | Agreement and size |
| `combmnz` | as `combsum` | sum × number of lists that found it | Agreement, strongly (several similar retrievers voting) |

All accept `weights` per source (`dense`, `sparse`); the ensemble gives one weight per member.

**The result cache** (`search_cache` slot) stores the final hits of a search. Key = the person's
access fingerprint + the normalised question + the conversation + the canonical filter + k + the
search settings + the **index epoch**. Ingestion, deletion, `rag reacl` and `erase-subject` start a new
epoch (as they do for Step 33's answer cache). `memory` is per process; `valkey` shares entries *and*
the epoch between replicas.

**The ensemble** runs N retrievers in parallel, each optionally on changed slots (`slots: {vector_store:
…}`) or another profile, each with a weight, and fuses the lists with the `fusion` slot.

### 4. The router

```
 question ──▶ router ── rules: which route's keywords appear most? (ties: first declared)
                      └─ llm:   the model names a route from their descriptions (rules if it can't)
          ──▶ route "hr":  hybrid retriever, vector_store collection "hr", filter {department: hr}
          ──▶ (multi: every matching route, fused)
 trace: {"retriever": {"route": "hr", "how": "rules"}}
```

A route can change slots, use another profile of `rag.yaml`, choose another retriever, and add a
metadata filter. Unchanged slots (embedder, stores) are shared. The permission filter applies to
every route, always.

## How to switch it on

```yaml
profiles:
  my-project:
    extends: platform/local
    # 1 · the metric the embedding model was trained for, and the index to match
    vector_store: {use: pgvector, dsn_env: null, credentials_file: /run/bao/rag_db.json, collection: kb,
                   metric: dot, hnsw_m: 24, ef_construction: 128, ef_search: 100}
    #   Qdrant:      {use: qdrant, …, metric: dot, quantization: scalar, oversampling: 2.0,
    #                 metadata_indexes: {department: keyword, updated: datetime}}
    #   OpenSearch:  {use: opensearch-knn, …, metric: l2, engine: faiss, ef_search: 100}
    # 2 · filters found in the question
    query_transformer:
      use: self-query
      mode: rules                       # or llm (checked against the schema; rules if unusable)
      date_field: updated
      fields:
        department: {values: {hr: [human resources, people team], it: [tech support], finance: []}}
        doc_type:   {values: {policy: [policies], guide: [guides, how to], form: [forms]}}
        updated:    {type: date, aliases: [updated, changed, modified]}
    # 3 · fusion, cache, several retrievers
    fusion: {use: relative-score, alpha: 0.7}
    search_cache: {use: valkey, url_file: /run/bao/valkey_url, ttl_seconds: 600}
    retriever:
      use: ensemble
      members:
        - {name: current, retriever: {use: hybrid}}
        - {name: archive, retriever: {use: dense}, weight: 0.5,
           slots: {vector_store: {use: pgvector, dsn_env: null, credentials_file: /run/bao/rag_db.json, collection: kb_archive, metric: dot}}}
    # 4 · or: one index per department
    # retriever:
    #   use: router
    #   default: general
    #   routes:
    #     hr:      {keywords: [leave, payroll, parental], description: "HR policies",
    #               slots: {vector_store: {use: pgvector, collection: hr, …}}}
    #     it:      {keywords: [vpn, laptop, password], profile: it-helpdesk}
    #     general: {retriever: {use: hybrid}}
```

Filters at query time:

```bash
uv run rag search "How many leave days?" --profile offline --group hr \
    --filter department=hr --filter 'updated>=2025-01-01' --filter 'tags=leave,parental'
uv run rag search "…" --filter '{"or": [{"doc_type": "policy"}, {"tags": {"exists": true}}]}'
uv run rag ask "How many leave days?" --filter language=en
uv run rag index ddl --profile my-project      # the CREATE INDEX for a project migration
```

```python
app.search("How many leave days?", principal, filters={"department": "hr", "updated": {"gte": "2025-01-01"}})
```

```http
POST /v1/search  {"query": "How many leave days?", "k": 5, "filter": {"department": "hr"}}
POST /v1/answer  {"question": "How many leave days?", "filter": {"language": "en"}}
```

Attach the metadata at ingestion (`rag_core.ingest.load_source(uri, access, metadata={...})`, or the
source system's connector): string, number, boolean and list-of-scalar values reach every chunk.

## When to use which

| Situation | Choose |
|---|---|
| Your embedding model's card says "cosine" or "normalised" (most text models, this platform's Qwen3-Embedding) | `metric: cosine` (default) |
| The model card says "dot product" / "maximum inner product", vectors not normalised | `metric: dot` |
| Image or older models trained with Euclidean distance | `metric: l2` |
| You need L1 specifically | pgvector or Qdrant; OpenSearch only `index_type: flat` (3.x) |
| < ~50k chunks, or a recall-critical audit | `index_type: flat` (exact) |
| Recall too low on filtered searches | raise `ef_search`; pgvector ≥ 0.8 keeps `iterative_scan` on |
| Memory pressure in Qdrant | `quantization: scalar` (≈4× smaller, tiny loss) before `binary` (≈32×, needs rescoring) |
| "Only X documents" known by the caller | `filter` in the request (or `--filter`) |
| Users write the conditions into their questions | `self-query` (`rules` for known vocabulary; `llm` for free wording) |
| Mixing vector and keyword lists, no labelled data | `rrf` |
| You've measured one side deserves more | `relative-score` (one `alpha`) or `weighted` |
| Several similar retrievers that should vote | `combmnz` |
| Score spreads differ wildly between lists | `dbsf` |
| The same searches repeat (help desk, dashboards) | `search_cache: valkey` |
| A second collection, model or index to search too | `ensemble` |
| Separate indexes per department / language / product | `router` (`rules` with keywords; `llm` with descriptions) |

## Trade-offs

- **Metric:** no metric is "better"; only the model's training metric is right. Changing it means a
  re-index (the contract check enforces this).
- **HNSW knobs:** higher `m` and `ef_construction` = better recall, more memory and slower ingestion;
  higher `ef_search` = better recall, slower queries. Measure with `rag eval-search` before and after.
- **Quantization:** smaller and faster, slightly less accurate; rescoring wins most of it back at the
  cost of reading the full vectors of `oversample × k` candidates.
- **Filters:** a very selective filter on an approximate index can return fewer than k results;
  pgvector's iterative scan, Qdrant's filterable HNSW and OpenSearch's efficient filtering mitigate it.
  Index the fields you filter on (Qdrant `metadata_indexes`; OpenSearch keyword mapping).
- **Self-query:** rules are predictable but only know your vocabulary; an LLM understands paraphrases
  but costs a call and can misread; both can guess wrong, hence `fallback_on_empty`.
- **Cache:** faster repeated searches; stale for up to `ttl_seconds` only if a change bypassed the
  ingestion pipeline (e.g. a manual SQL edit). In-process `memory` isn't invalidated by a worker in
  another pod (readiness warns).
- **Ensemble / router:** more searches per question (latency = the slowest member); each member or
  route is one more thing to evaluate.

## Common mistakes

> **WATCH OUT**
> - **Switching `metric` on an existing collection** expecting a re-rank: you get `ContractError`.
>   Re-index into a new collection (`rag reindex`), compare, switch by PR.
> - **Choosing `dot` for normalised embeddings** "for speed": the ranking is the same as cosine; the
>   scores change scale, so every `min-score` threshold must be re-tuned.
> - **One threshold for two metrics.** A cosine 0.6 and an L2 score 0.6 mean different things.
> - **Filtering on a field you never stored.** `{"department": "hr"}` finds nothing if ingestion never
>   attached `department`; check with `rag search --json` (metadata is in every hit).
> - **Dates as "01/02/2025".** Use ISO 8601 (`2025-02-01`); anything else is rejected by the parser and
>   never matches in the stores.
> - **Expecting a filter to grant access.** It can only narrow: `{"document": "<restricted doc>"}`
>   returns nothing to someone without access (tested on every store).
> - **Step 13's index and exact filters:** its metadata strings are dynamically mapped as text; set
>   `keyword_suffix: ".keyword"` on the OpenSearch components (or recreate the index with
>   `create_if_missing`'s mapping, which maps them as keywords).
> - **An LLM self-query without a schema review:** declare only fields you're happy users filter on.

## What was added to the repo

| Where | What |
|---|---|
| `libs/rag-core/src/rag_core/similarity.py` | Metrics, score convention, `VectorIndexParams`, `ContractError`, `check_contract` |
| `libs/rag-core/src/rag_core/filters.py` | The filter language: parse/validate, Python matcher, SQL, Qdrant and OpenSearch compilers, `combine`, `canonical` |
| `components/basics.py` | `memory` vector store with `metric`; both memory stores use the new filters |
| `components/pgstore.py` | `PgVectorParams` (metric, index type, HNSW/IVFFlat knobs, binary quantization, iterative scan, `create_index`), contract check, `index_ddl()`; filters in SQL for pgvector and postgres-fts |
| `components/qdrant.py` | metric, HNSW config, flat, scalar/binary quantization, `metadata_indexes`, contract check, score conversion; payload filters |
| `components/opensearch.py` | `OpenSearchKnnParams` (metric, engine, HNSW knobs, flat), `create_if_missing` mapping, contract check, score conversion; bool filters; `keyword_suffix` |
| `components/retrieval.py` | fusion `relative-score`, `combsum`, `combmnz`, `borda`; per-list weights; `chain` passes filters on |
| `components/selfquery.py` | `self-query` transformer |
| `components/multiretrieval.py` | `ensemble` and `router` retrievers |
| `components/searchcache.py` | `search_cache` slot: `memory`, `valkey` |
| `registry.py` | the `search_cache` slot; `Overlay` (a profile with some slots changed) |
| `search.py`, `answer.py`, `ingest.py`, `lifecycle.py`, `conversation.py` | filter validation, self-query and fallback, result cache, trace; answer-cache key includes the filter; epochs bumped on every change |
| `cli.py` | `rag search --filter`, `rag ask --filter`, `rag index ddl` |
| `testing/conformance.py` | `check_metadata_filters`, `check_metrics` |
| `services/rag-api` | `filter` in `/v1/search` and `/v1/answer` (validated, documented); legacy SQL backend applies it too; filter *field names* in the audit event |
| `infra/db/rag/migrations/20261015000000_vector_metrics_and_filters.sql` | `rag.collections.distance_metric`, `index_options`; `rag.safe_timestamptz` |
| Tests | `test_filters.py`, `test_retrieval_ext.py`, new live tests in `test_stores.py` (pgvector, postgres-fts, Qdrant, OpenSearch: every filter case, every metric, contract mismatches, quantization, index types), rag-api filter tests |
| Docs | this page, ADR-0039, handbook sections 8, 9, 11, 16, 20, glossary, catalogue |

Live tests run when `RAG_TEST_PGVECTOR_DSN`, `RAG_TEST_QDRANT_URL` (or `qdrant` on PATH) and
`RAG_TEST_OPENSEARCH_URL` point at throwaway servers, e.g.:

```bash
docker run -d --name t-pg -e POSTGRES_PASSWORD=pw -p 55433:5432 pgvector/pgvector:0.8.7-pg17
docker run -d --name t-qd -e QDRANT__SERVICE__API_KEY=test-admin-key -p 56333:6333 qdrant/qdrant:v1.19.2
docker run -d --name t-os -e discovery.type=single-node -e DISABLE_SECURITY_PLUGIN=true \
    -e DISABLE_INSTALL_DEMO_CONFIG=true -p 59200:9200 opensearchproject/opensearch:3.8.0
RAG_TEST_PGVECTOR_DSN=postgres://postgres:pw@127.0.0.1:55433/postgres RAG_TEST_QDRANT_URL=http://127.0.0.1:56333 \
RAG_TEST_OPENSEARCH_URL=http://127.0.0.1:59200 uv run pytest libs/rag-core/tests/test_stores.py
```
