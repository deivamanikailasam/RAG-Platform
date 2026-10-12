# LLM traces in Langfuse

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `dataset:llm-traces` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-12 (every 90 days) |
| **Role** | operational |
| **Highest classification** | internal |
| **Personal data** | yes |
| **Retention** | 30 days, enforced by the nightly retention job (Step 22). |

## Summary

Per-request records of what was asked and retrieved, for debugging and evaluation (Step 22).

## Where it lives

- Self-hosted Langfuse (ClickHouse, Postgres, the langfuse bucket), Step 22

## Provenance

Written by rag-api's Langfuse client for every search.

## Personal data

Questions (masked for e-mails, tokens and keys, but free text can still contain names) and the pseudonymous user id (sub). Titles of confidential and restricted documents are withheld.

## Legal basis

Legitimate interest in operating and improving the service, limited to 30 days.

## Deletion

The retention job; individual traces can be deleted by trace id or user id via the API.

## Access

Langfuse login, few named people, sign-up disabled.

## Known limitations

- Masking is pattern-based; unusual personal data passes through

## Lineage

Built from:

- dataset:company-chunks
- dataset:company-documents
- model:embedder
- prompt:query-instruction
- system:rag-api

Affects if changed:

- (nothing)

## Approvals

- 2026-10-12 · you
