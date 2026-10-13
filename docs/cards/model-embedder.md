# Qwen3-Embedding-0.6B (embedder)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `model:embedder` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-12 (every 180 days) |
| **Task** | embedding |
| **Weights** | `Qwen/Qwen3-Embedding-0.6B` @ `<40-char SHA` |
| **Licence** | [apache-2.0](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), verified 2026-10-12 |
| **Fallback allowed** | no |

## Summary

Turns text into 1024-number vectors for semantic search, served by TEI (Step 8). Every chunk in every index, and every query, goes through it, under the embedding contract in models.yaml.

## Intended use

- Embedding document chunks at indexing time
- Embedding queries, prefixed with the registered query instruction (prompt query-instruction)

## Out of scope

- Comparing vectors from a different embedding model or contract (another vector space)
- Classification or clustering decisions about people

## Training data

Built on the Qwen3 foundation models and trained on large-scale text pairs, per the publisher; supports 100+ languages. Datasets not disclosed in detail.

## Data handling

Runs on the Mac (TEI); text and vectors never leave the machine.

## Risks

- Changing the model, revision or contract silently breaks search unless everything is re-indexed

## Known limitations

- Queries without the task instruction retrieve noticeably worse (publisher reports 1-5%)
- Input beyond the chunk limit in the contract is truncated silently by the server

## Evaluation

No results yet (Step 26).

## Lineage

Built from:

- (none)

Affects if changed:

- dataset:company-chunks (input)
- prompt:query-instruction (runs on)
- system:rag-api (input)
  - dataset:audit-log (input)
  - dataset:llm-traces (input)

## Approvals

- 2026-10-12 · you · Step 8: embedding contract recorded
