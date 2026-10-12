# Golden questions and answers for rag-answer

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `dataset:rag-answer-golden` |
| **Status** | approved |
| **Owner** | rag-quality |
| **Last reviewed** | 2026-10-12 (every 180 days) |
| **Role** | evaluation |
| **Highest classification** | internal |
| **Personal data** | no |
| **Retention** | Versioned in git for as long as the prompts it evaluates exist. |

## Summary

Questions with FIXED documents, reference answers, cases that must be refused and prompt-injection attempts. Scores prompt and model versions independently of retrieval (Step 26).

## Where it lives

- evals/datasets/rag-answer-golden/ (v1.jsonl, hash pinned in dataset.yaml)

## Provenance

Written by people who know the documents; passages copied from the source documents; injection cases written deliberately. No real user questions.

## Personal data

None.

## Legal basis

Not applicable.

## Deletion

Remove the case in a new dataset version; re-run the affected evaluations.

## Access

Repository readers.

## Known limitations

- Eight cases is a smoke test, not a benchmark; grow it from real failures (Step 37)
- Built on the four demo documents; your own corpus needs its own cases

## Lineage

Built from:

- dataset:company-documents

Affects if changed:

- (nothing)

## Approvals

- 2026-10-12 · you · Step 26: v1
