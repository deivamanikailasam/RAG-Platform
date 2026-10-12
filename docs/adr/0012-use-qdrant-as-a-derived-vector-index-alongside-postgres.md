# ADR-0012: Use Qdrant as a derived vector index alongside Postgres

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Postgres + pgvector is the system of record (ADR-0011). Later projects need features where a
dedicated engine helps: quantization with rescoring, per-tenant indexing, hybrid dense+sparse
queries, aliases for blue/green re-indexing, and independent scaling. Two stores must never
disagree about permissions or existence.

## Decision
Run Qdrant v1.19.x (digest-pinned) with admin and read-only keys from SOPS, JWT RBAC enabled,
telemetry disabled, ports 6333/6334 on 127.0.0.1 only (6335 unpublished). Qdrant is a DERIVED index:
collections are named by embedding contract (rag_chunks_qwen3e06b_v1) and accessed via the alias
rag_chunks; points mirror Postgres chunk ids and payloads, synced by a read-only job, never written
by applications. Apps get read-only, collection-scoped, expiring JWTs.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| pgvector only | One system | Fewer vector-specific features at scale | Kept as system of record; compare in Projects 1/17 |
| Milvus | Very large scale, GPU indexes | Heavier to operate locally (several components) | Qdrant simpler for a single node |
| Weaviate | Built-in modules, hybrid | Larger footprint, different model | Qdrant fits the derived-index pattern well |
| Qdrant as source of truth | Fewer moving parts | Permissions and deletions in two places | Breaks the single-source rule |

## Consequences
+ Vector-specific features and blue/green re-indexing without touching the source of truth.
+ Rebuildable at any time; consistency is structural.
- A sync pipeline to maintain (deletes, updates). CDC in Step 36.
- Another service, keys and snapshots to manage.

## Revisit when
Comparative benchmarks (Projects 1, 17) show one engine is enough, or scale requires clustering.
