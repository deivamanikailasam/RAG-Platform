# ADR-0031: Ingest through one replace-not-append pipeline, redacting before storing

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Each project would otherwise write its own parsing and chunking, with stale versions left in
indexes, personal data embedded, access rules applied unevenly across stores, and no record of
what was ingested with which settings.

## Decision
rag-core's IngestionPipeline: parse (by detected type) → normalise → redact PII (checksummed
regexes; mask/pseudonymise/remove; Presidio optional) → chunk (structure-aware by default; fixed,
recursive, sentence-window, semantic, parent-child available) → enrich (context header by default;
LLM context and questions available) → embed (gateway, batched, dimension-checked, cached) →
delete the source's old chunks → upsert into the profile's vector store and keyword index.
Access is copied to every chunk and enforced inside each store's query. A manifest skips unchanged
sources (content SHA-256 + pipeline hash). Jobs run on Valkey Streams with retries and a dead-letter
stream. Stores: pgvector + Postgres FTS (default), Qdrant, OpenSearch; all pass one conformance kit.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Unstructured.io / Docling as the only parser | Best layout and OCR | Heavy dependencies and models | Available as options |
| Fixed-size chunks only | Simple | Splits tables and sentences; worse retrieval | Structure-aware default, others selectable |
| Append-only indexing | Simple | Stale versions remain searchable | Replace on every change |
| Redact at query time | Index keeps full data | Personal data embedded and stored | Redact before storing |
| Kafka / RabbitMQ | Mature queues | Another service to run | Valkey Streams already in the platform |

## Consequences
+ Clean, current, access-labelled chunks in any store; re-runs are cheap.
- Embedded text differs from cited text (by design); evaluation must use the cited text.
- Regex PII misses names; projects with free-text personal data need Presidio or similar.

## Revisit when
Documents are mostly scanned (make Docling the default), a project needs per-field encryption, or
ingestion volume needs a dedicated stream processor.
