# ADR-0011: Use Postgres with pgvector as the primary document and vector store

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
RAG needs documents, chunks, metadata, ACLs and vectors kept consistent, filtered together, deleted
together, backed up and audited. Scale for this lab is thousands to low millions of chunks.

## Decision
A dedicated rag-db (pgvector/pgvector 0.8.x on Postgres 17, digest-pinned) stores collections
(embedding contract), documents (ACL groups, classification, versions, soft delete) and chunks
(halfvec(1024) embeddings with HNSW cosine index; generated tsvector with GIN). Roles: postgres
(admin via exec only), rag_migrator (DDL via dbmate), rag_app (DML, 30 s timeout), rag_readonly.
Schema changes only via dbmate migrations. Port bound to 127.0.0.1. pg_dump backups with restore test.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Dedicated vector DB only (Qdrant, Milvus, Weaviate) | Vector features, scale | Second source of truth for ACLs/metadata | Evaluated as a complement in Step 12 |
| OpenSearch only | Strong keyword + vector | Weaker relational modelling, transactions | Used for search (Step 13), not as system of record |
| SQLite + sqlite-vec | Tiny, embedded | Not multi-user/server-grade | Used for the edge project (21) |
| ORM migrations (Alembic) | Python-native | Ties schema to one language/ORM | dbmate keeps plain, reviewable SQL |

## Consequences
+ One transactional source of truth; permission filters in the same query as similarity.
+ Familiar operations (backup, monitoring, roles) and cloud-managed equivalents.
- Filtered ANN needs care (iterative scans, ef_search) for selective ACLs.
- Very large scale or heavy vector workloads may need a dedicated engine (measure in Projects 1, 17).

## Revisit when
Corpus exceeds ~10M chunks, p95 vector latency misses targets, or multi-node sharding is required.
