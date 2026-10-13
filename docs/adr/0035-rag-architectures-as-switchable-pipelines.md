# ADR-0035: RAG architectures as switchable pipelines sharing every control

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** <you>

## Context
Projects need different RAG designs (baseline, advanced, corrective, self-reflective, adaptive,
agentic, graph, structured). Hard-coding one per project duplicates the plumbing and, worse, the
controls; frameworks offer many designs but each with its own tracing, safety and audit story.

## Decision
The `pipeline` slot holds an architecture with two hooks: retrieve() and review(). The answer
pipeline keeps memory, guards, cache, post-check, context packing, generation, citation checks,
memory/cache writes and audit hooks for all of them. Built in: naive, standard (default),
corrective, self-reflective, adaptive, agentic, graph (memory graph store + entity enricher) and
sql (read-only SQL under an SQLite authorizer, permitted tables only). `rag eval-answers` compares
them; CI gates the default on context recall and abstention.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| One fixed architecture | Simple | Wrong for many projects | Switchable |
| LangGraph / LlamaIndex workflows per project | Powerful agent graphs | Controls re-implemented per project | Can be wrapped as an architecture plugin |
| Microsoft GraphRAG as the graph design | Global summaries | Heavy indexing (LLM per chunk), batch rebuilds | Local graph search built in; GraphRAG as an option |
| Text-to-SQL with a database user only | Familiar | One mistake in grants exposes data | Authorizer + permitted tables + read-only + limits |

## Consequences
+ A project switches design by configuration and keeps every control and record.
- Model-dependent designs (agentic, sql, LLM grading/routing) need a model to evaluate.
- The in-memory graph store suits one process; production needs a persistent one.

## Revisit when
Agent workflows need tools beyond search and SQL, a persistent graph store is needed (Neo4j,
Apache AGE in Postgres), or global (community-summary) graph search is required.
