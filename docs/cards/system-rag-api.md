# rag-api (the company knowledge search and answer service)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `system:rag-api` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-13 (every 180 days) |

## Summary

The platform's front door: authenticates people (Step 17), asks the policy what they may read (Step 18), searches with hybrid retrieval and reranking (Step 32), answers with citations or says "I don't know" (Step 33), checks questions, documents and answers with guards (Step 34), runs the architecture its profile chooses (Step 35, `standard` by default), and records who received what, including every guard verdict (Step 23).

## Intended use

- Finding documents and passages relevant to a work question
- Answering work questions from those documents, with a citation after every claim
- Follow-up questions within one signed-in session (memory expires after a day)

## Out of scope

- Decisions about people, or advice presented as authoritative legal, medical or financial advice
- Access to documents the policy doesn't allow, by any route

## Purpose

Help employees find information, and answers with sources, in company documents they are allowed to read.

## Users

Employees, signed in through Keycloak; machine clients with service accounts.

## Human oversight

Results and answers show their source documents, so people can check every claim and decide what to do; thumbs up/down go to /v1/feedback and online evaluation (Step 37). Guards block with a fixed message and audit the reason. The platform team can roll back prompts (Step 24), models (Step 7) and releases (canary abort, git revert) and switch the service off; every access is audited.

## Risk assessment

Believed to be limited-risk under the EU AI Act (an assistant over internal documents, not used for decisions about people): users must be told they are using AI. Re-assess before any HR, credit or similar use. Confirm with your legal team; this is not legal advice.

## Known limitations

- Answers can still be wrong: a citation shows where a claim came from, not that it is right, and the groundedness guard only flags answers whose words and numbers are not in the documents
- The guards are pattern-based: rephrased, translated or story-wrapped injection attempts are known gaps (examples/eval/guards.yaml) until a model-based judge or guard service is added
- Only as good as the documents it may read: outdated or conflicting documents give outdated or conflicting answers, and a question the documents don't cover gets "I don't know"
- Offline evaluations use the shipped handbook questions; quality on your own documents must be measured with your own golden set and online evaluation
- Architectures other than `standard` (corrective, self-reflective, adaptive, agentic, graph, sql) cost more model calls and latency; evaluate one with `rag eval-answers` before switching to it

## Lineage

Built from:

- dataset:company-chunks
- dataset:company-documents
- model:embedder
- model:qwen-fast
- model:qwen-quality
- model:reranker
- prompt:query-instruction
- prompt:rag-answer

Affects if changed:

- dataset:audit-log (input)
- dataset:llm-traces (input)

## Approvals

- 2026-10-13 · you
