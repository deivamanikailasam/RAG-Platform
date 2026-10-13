# ADR-0039: Switchable similarity metrics, pushed-down metadata filters, more fusion, a result cache and multi-retriever search

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Steps 11-13 and 32 fixed several search decisions: cosine similarity everywhere, metadata filters
limited to equality, three fusion methods, no cache in front of search, and one retriever per
profile. Projects need other embedding models (some trained for inner product or L2), "only these
documents" conditions (department, type, dates, language, tags), filters hidden in questions,
multi-index setups and cheaper repeated searches. Two risks shape the design: a metric that doesn't
match the index ranks badly *without any error*, and a filter that could replace (instead of narrow)
the permission filter would be a data leak.

## Decision
We will:
1. Give every vector store a `metric` (cosine, dot, l2, l1 where supported), index settings
   (`index_type` hnsw/flat/ivfflat, `hnsw_m`, `ef_construction`, `ef_search`) and quantization where
   the store supports it safely with rescoring (pgvector binary, Qdrant scalar/binary). Every store
   reports scores with one convention (higher = more similar; distances as 1 / (1 + d)). Each store
   checks the index's recorded metric and size against the profile and refuses a mismatch
   (`ContractError`); pgvector records them in `rag.collections` (new migration).
2. Carry a typed filter expression in `Query.filters` (eq, ne, in, nin, gt/gte/lt/lte, range, exists,
   and/or/not; ISO dates; limits on size), validate it once, and have each store compile it into its
   own query (SQL with bound parameters, Qdrant payload filter, OpenSearch bool filter, Python), always
   ANDed with the access filter. The same conformance check (`check_metadata_filters`) runs on every
   store, live. A `self-query` transformer extracts filters from the question against a declared
   schema (rules offline; an LLM whose output is checked against the schema), with a fallback when
   the extracted filter finds nothing.
3. Add `relative-score`, `combsum`, `combmnz` and `borda` fusion; a `search_cache` slot keyed by
   access fingerprint, question, conversation, filter, k, settings and an index epoch bumped by every
   ingestion change; an `ensemble` retriever (N retrievers in parallel, fused with per-member weights);
   and a `router` retriever (rules or LLM) that sends a question to a named collection, profile or
   retriever. Members and routes share every slot they don't change (`Overlay`).

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Keep cosine only | Simplest; right for this platform's model | Wrong for dot/L2-trained models, silently | Switchable, with a contract check |
| One HNSW index per metric in the migration | Every metric fast out of the box | Triples index storage and write cost for metrics nobody uses | Per-project index from `rag index ddl` (or `create_index` in dev) |
| Post-filter results in Python | One implementation | Returns fewer than k; transfers data the person may not need | Pushed down into each store; Python only for the in-memory reference |
| Free-form filters in each store's own syntax | Full engine power | Not portable; injection risk; unreviewable | One small, validated language compiled per store |
| A framework's self-query/router (LangChain, LlamaIndex) | Ready-made | Their abstractions; unchecked LLM filters | Our contracts; LLM output checked against the schema, rules as fallback |
| Cache keyed by question only | Higher hit rate | Crosses access boundaries; stale after ingestion | Access fingerprint + filter + epoch in the key |

## Consequences
+ A project can adopt any embedding model's native metric, tune recall/latency/memory per store, and
  filter by any metadata it ingests, with the same behaviour on every store.
+ Mismatched indexes fail loudly; filters can never widen access (tested on every store).
- More settings to understand and evaluate; a non-cosine metric needs a project migration for its
  index; selective filters on approximate indexes need tuning (`ef_search`, iterative scans, payload
  indexes).
- Self-query and routing can guess wrong; they are measured, logged in the trace and fall back.
- The in-process result cache isn't invalidated by ingestion in other pods (readiness warns; use Valkey).

## Revisit when
A store gains native hybrid fusion or filtering that measurably beats ours; sparse/learned retrievers
join the ensemble; or projects need per-field operators we don't support (full-text inside metadata,
geo filters).
