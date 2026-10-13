# bge-reranker-v2-m3 (reranker)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `model:reranker` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-12 (every 180 days) |
| **Task** | reranking |
| **Weights** | `BAAI/bge-reranker-v2-m3` @ `<40-char SHA` |
| **Licence** | [apache-2.0](https://huggingface.co/BAAI/bge-reranker-v2-m3), verified 2026-10-12 |
| **Fallback allowed** | no |

## Summary

A multilingual cross-encoder (built on bge-m3) that scores how well a passage answers a query, used to re-order the top search candidates (Step 8). Served by TEI.

## Intended use

- Re-ordering the top 20-100 retrieval candidates before they reach a prompt

## Out of scope

- Filtering for permissions (only the policy, Step 18, decides who may read what)
- Scores as calibrated probabilities across different queries

## Training data

Not disclosed in detail by the publisher beyond its bge-m3 origin.

## Data handling

Runs on the Mac (TEI); nothing leaves the machine.

## Risks

- A strong reranker can promote a confidently worded but outdated document

## Known limitations

- Cost grows with the number of candidates, so keep k small

## Evaluation

No results yet (Step 26).

## Lineage

Built from:

- (none)

Affects if changed:

- system:rag-api (input)
  - dataset:audit-log (input)
  - dataset:llm-traces (input)

## Approvals

- 2026-10-12 · you · Step 8
