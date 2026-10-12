# Golden retrieval cases per persona

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `dataset:retrieval-golden` |
| **Status** | approved |
| **Owner** | rag-quality |
| **Last reviewed** | 2026-10-12 (every 180 days) |
| **Role** | evaluation |
| **Highest classification** | internal |
| **Personal data** | no |
| **Retention** | Versioned in git. |

## Summary

Questions asked AS a given persona, with the documents they should receive and the documents they must never receive. Measures search quality and the access policy together (Step 26).

## Where it lives

- evals/datasets/retrieval-golden/ (v1.jsonl, hash pinned in dataset.yaml)

## Provenance

Written by people who know the documents and the access rules (Step 18).

## Personal data

None.

## Legal basis

Not applicable.

## Deletion

Remove the case in a new dataset version.

## Access

Repository readers.

## Known limitations

- Personas are synthetic; real group memberships are messier
- Relevance labels are binary (relevant or not)

## Lineage

Built from:

- dataset:company-documents

Affects if changed:

- (nothing)

## Approvals

- 2026-10-12 · you · Step 26: v1
