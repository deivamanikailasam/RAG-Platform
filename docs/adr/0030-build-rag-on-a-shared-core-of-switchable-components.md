# ADR-0030: Build RAG on a shared core of switchable components

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Steps 1-29 built the platform around RAG; ingestion, retrieval, generation and guardrails were left
to each project. Every project would re-implement them differently, with uneven access control,
observability and quality, and comparing techniques would require rewrites.

## Decision
libs/rag-core: shared types; one Protocol per component kind; a registry of named implementations
with Pydantic-validated parameters (extra fields forbidden), a status (live/mocked/reference) and
optional extras; a Container that builds a rag.yaml profile lazily with dependency injection;
profiles with extends, "none" to switch off, RAG__SLOT__PARAM overrides; validate() without
building; plugins via the rag_core.components entry point; a conformance kit (ranking,
idempotency, deletes, filters, access control) that every store must pass.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| LangChain / LlamaIndex / Haystack as the core | Hundreds of integrations | Large, fast-moving APIs; their own abstractions for access control and tracing | Wrap them as components where useful |
| Each project builds its own | Full freedom | Duplicated work, uneven safety | The problem |
| Abstract base classes | Familiar | Forces inheritance; harder to wrap third-party code | Protocols are structural |
| Hydra / dynaconf for config | Powerful | More concepts than needed | ~100 lines cover our needs |

## Consequences
+ Any part is swappable per environment; options are compared with Step 26 on equal terms.
+ Safety properties are tested once, for every implementation.
- A thin layer to maintain; new upstream features need a component.

## Revisit when
A framework offers the same guarantees (access-aware stores, typed config, conformance tests) with
less code, or the number of components makes a plugin catalogue worth publishing.
