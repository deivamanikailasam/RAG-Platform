# ADR-0015: Use Valkey for cache, queues and locks

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
The platform needs millisecond storage for LLM response caching, crash-safe ingestion job queues,
distributed locks and (later) session memory and shared rate-limit counters.

## Decision
Run Valkey 9.1.x (BSD, Linux Foundation; digest-pinned) as service valkey on 127.0.0.1:6379, with an
ACL built in tmpfs from SOPS secrets: default user off; admin; litellm (all keys, no @dangerous);
rag_app (rag:* keys only, no @dangerous/@admin). maxmemory 512 MB with volatile-lru (cache keys always
have TTLs; queues/locks never evicted), AOF everysec + RDB snapshots. LiteLLM exact-match response
cache with 10-minute TTL. Ingestion uses Streams + consumer groups, XAUTOCLAIM recovery, a 3-try
dead-letter stream, idempotent jobs, and SET NX PX locks released by token.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Redis Open Source 8.x | Original project; built-in query engine and vector sets | Tri-licence incl. AGPL/SSPL; governance by one vendor | Valkey's BSD licence is simpler to approve |
| Separate cache and queue instances | Clean eviction policies | More services and memory | volatile-lru suffices locally; split in production |
| RabbitMQ / Kafka / Redpanda for jobs | Richer messaging guarantees | Heavier to run | Streams enough now; Kafka/Redpanda for CDC (Step 36) |
| Postgres-based queue (SKIP LOCKED) | No new service | Adds write load to system of record | Keep the database for records |

## Consequences
+ Millisecond cache hits; crash-safe queues; safe per-document locks; least-privilege users.
+ Redis-protocol compatible: works with every Redis client and with managed Valkey offerings.
- Shared instance mixes cache and durable data (mitigated by volatile-lru + TTL discipline).
- Cache keys must respect permission boundaries (application responsibility).

## Revisit when
Load requires separate cache/queue instances, or vector/semantic caching needs a search module.
