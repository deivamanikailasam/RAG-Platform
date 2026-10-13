# Company document chunks and vectors (the search indexes)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `dataset:company-chunks` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-12 (every 90 days) |
| **Role** | derived |
| **Highest classification** | restricted |
| **Personal data** | yes |
| **Retention** | As long as the source document exists; rebuilt, never edited by hand. |

## Summary

Documents split into chunks, each with a 1024-number vector and keyword index entries. What search actually reads. Rebuildable at any time from company-documents.

## Where it lives

- Postgres rag.chunks (pgvector, Step 11)
- Qdrant alias rag_chunks (Step 12)
- OpenSearch alias rag-chunks (Step 13)

## Provenance

Chunked and embedded by the ingestion worker (Step 32) under the embedding contract stored with each collection (Step 8/11).

## Personal data

Whatever personal data the source documents contain, as text and as vectors.

## Legal basis

Same as company-documents (derived for the same purpose).

## Deletion

Removed with the source document (Step 36); a full re-index also removes leftovers.

## Access

Only through rag-api and the policy; no person queries the indexes directly in production.

## Known limitations

- Vectors can leak the gist of their text; treat them with the same classification as the text
- Three stores must stay in step; a partial re-index leaves them inconsistent

## Lineage

Built from:

- dataset:company-documents
- model:embedder

Affects if changed:

- system:rag-api (input)
  - dataset:audit-log (input)
  - dataset:llm-traces (input)

## Approvals

- 2026-10-12 · you
