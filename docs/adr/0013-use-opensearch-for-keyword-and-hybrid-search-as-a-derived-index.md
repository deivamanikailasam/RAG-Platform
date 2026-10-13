# ADR-0013: Use OpenSearch for keyword and hybrid search as a derived index

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Vector search is weak on exact codes, names, acronyms and rare terms; keyword search is weak on
paraphrases. Hybrid retrieval is the robust default. Company jargon needs synonyms and stemming.

## Decision
Run OpenSearch 3.x (single node, digest-pinned) with the security plugin and TLS (demo certs in dev
only), admin password from SOPS, heap 2 GB, port 9200 on 127.0.0.1. Users: rag_search (read) and
rag_indexer (write) on rag-chunks*. Index rag-chunks-v1 (alias rag-chunks): stemmed text fields,
query-time synonym_graph, keyword ACL/tenant fields, Lucene HNSW knn_vector (1024, cosine).
Search pipeline rag-hybrid: min-max normalisation, weights 0.3 keyword / 0.7 vector (to be tuned).
Data flows one way from Postgres; every query carries tenant + ACL filters.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Postgres full-text only | No new service | Weaker analyzers, BM25-style ranking needs extensions | Kept for simple cases; compared in Step 32 |
| Elasticsearch | Very mature, rich features | Licence considerations; similar capability | OpenSearch is Apache-2.0 and maps to AWS |
| Qdrant sparse vectors (BM25/SPLADE) | One engine for hybrid | Fewer analyzers, no aggregations | Explored in Step 32 |
| Vespa / Typesense / Meilisearch | Strong in niches | Smaller enterprise footprint | Not needed now |

## Consequences
+ Robust retrieval across exact and semantic queries; explainable keyword scores.
+ Enterprise-standard search skills and a direct path to Amazon OpenSearch Service.
- Heaviest service so far (~4 GB); JVM tuning and upgrades to manage.
- Demo TLS certificates must be replaced outside development.

## Revisit when
Step 32 evaluation shows hybrid via another engine is as good, or memory pressure requires
consolidation.
