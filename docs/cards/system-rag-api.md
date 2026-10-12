# rag-api (the company knowledge search service)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `system:rag-api` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-12 (every 180 days) |

## Summary

The platform's front door: authenticates people (Step 17), asks the policy what they may read (Step 18), searches, records who received what (Step 23), and, from Step 32, answers.

## Intended use

- Finding documents and passages relevant to a work question

## Out of scope

- Decisions about people, or advice presented as authoritative legal, medical or financial advice
- Access to documents the policy doesn't allow, by any route

## Purpose

Help employees find information in company documents they are allowed to read.

## Users

Employees, signed in through Keycloak; machine clients with service accounts.

## Human oversight

Results show their source documents; people decide what to do with them. The platform team can roll back prompts (Step 24) and models (Step 7) and switch the service off; every access is audited.

## Risk assessment

Believed to be limited-risk under the EU AI Act (an assistant over internal documents, not used for decisions about people): users must be told they are using AI. Re-assess before any HR, credit or similar use. Confirm with your legal team; this is not legal advice.

## Known limitations

- Search only; answers arrive in Step 32

## Lineage

Built from:

- dataset:company-chunks
- dataset:company-documents
- model:embedder
- prompt:query-instruction

Affects if changed:

- dataset:audit-log (input)
- dataset:llm-traces (input)

## Approvals

- 2026-10-12 · you
