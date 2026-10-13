# ADR-0022: Use self-hosted Langfuse for LLM traces

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Debugging and evaluating RAG answers needs the question, retrieved documents and (later) prompts and
answers. That content must stay out of operational telemetry (ADR-0019), be masked, never bypass the
access policy (ADR-0018), and be deleted on schedule.

## Decision
Self-host Langfuse 4.27 (MIT core): langfuse-web, langfuse-worker, dedicated Postgres, ClickHouse
25.12, a dedicated Valkey with noeviction, and bucket "langfuse" on SeaweedFS (scoped identity,
path-style, 30-day expiry on events/). Sign-up disabled; headless init of org, project, keys and
admin; telemetry off. rag-api uses the Langfuse Python SDK 4.17 on its OWN tracer provider (never
the global one), reuses the request's OTel trace id, masks tokens/keys/emails in-process, withholds
titles of confidential/restricted documents and never copies document text; user = pseudonymous sub.
A nightly job deletes traces older than 30 days (automatic retention is Enterprise-only).
SSO via Keycloak deferred until Keycloak has a hostname reachable from browser and containers.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Langfuse Cloud | No operations | Prompts and documents leave the machine | Self-hosting is the point of this platform |
| Arize Phoenix | Simple, OTel-native, OSS | Smaller annotation/prompt tooling | Langfuse covers prompts, datasets, scores together |
| LangSmith | Rich, polished | Proprietary; tied to LangChain ecosystem | Licence and lock-in |
| Content in Tempo spans | One system | Wide access; breaks ADR-0019 | Content needs its own access rules |

## Consequences
+ Per-request view of questions and retrieval; foundation for evaluation and prompt management.
+ Content is masked, sensitive titles withheld, retention enforced, store isolated.
- Six more containers, ClickHouse the heaviest; secrets visible to docker inspect.
- Retention and SSO are our responsibility until an Enterprise licence or Step 29 respectively.

## Revisit when
Answer generation arrives (Step 33: generation observations via LiteLLM's Langfuse callback with
the same rules), SSO becomes possible, or volume requires ClickHouse clustering.
