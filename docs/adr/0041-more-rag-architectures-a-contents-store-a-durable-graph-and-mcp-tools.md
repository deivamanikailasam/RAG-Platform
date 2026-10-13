# ADR-0041: More RAG architectures, a contents store, a durable graph and MCP tools for agents

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Step 35 (ADR-0035) put eight architectures behind the `pipeline` slot. Teams ask for more by name
(vector-only, vectorless / PageIndex, RAG-Fusion, HyDE, FLARE, speculative RAG, GraphRAG global
search, long context, table QA, conversational) and want them compared on their own questions.
Several were configurations of `standard` with no name, no trace and no offline mode; others were
missing. GraphRAG had local search only, and its graph lived in one process's memory. Agents
(MCP clients) want to call the platform's search, which raises the question of whose permissions
an agent acts with. And `rag search --filter section_numbers=4.2` matched nothing, because the
value was read as a number while section numbers are stored as text.

## Decision
We will:
1. Add each named technique as a component in the existing `pipeline` slot (`vector`, `keyword`,
   `pageindex`, `rag-fusion`, `hyde`, `conversational`, `long-context`, `table`, `flare`,
   `speculative`, `graph-global`), registering a second name where two are common (`vectorless`,
   `multi-query`). Each gathers context through the SearchPipeline (a new `search_with` lets it
   choose its own search texts or retriever while the access filter, reranker and post-processors
   still run) and goes through the shared answer steps. An architecture may write the answer itself
   (`draft`, used by `speculative`); citations and output guards are checked afterwards as always.
2. Give every model-based step a deterministic offline mode (heuristic variants, heuristic rewrites,
   heading-overlap navigation, support-scored drafts, extractive community summaries, the offline
   entity extractor) that is also the fallback when a model's reply is unusable, so CI evaluates
   all of them with `rag eval-answers`.
3. Implement vectorless navigation with a new `toc_store` slot filled at ingestion from the parsed
   document's headings (not from search chunks), built into a tree per question from what the
   person may see; allow profiles with no embedder and no vector store.
4. Compute GraphRAG communities per person (label propagation or connected components over the
   entity graph of visible chunks), cached by person and graph version, rather than precomputing
   global communities and reports; validate LLM-extracted entities and relations against a schema.
5. Add a `postgres` graph store with its own tables (a copy of each chunk's text and access,
   mentions, relations), access filtered in SQL and row-level security per tenant, created by a
   new migration.
6. Expose search and answer to agents with `rag mcp`: a minimal MCP server over stdio (JSON-RPC
   2.0: initialize, ping, tools/list, tools/call) with no new dependency, whose identity is fixed at
   launch (flags, or an OIDC token verified on every call) and never taken from tool arguments.
7. Make `--filter key=value` equality match both the text as typed and its number/boolean reading.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Document the presets as configurations only | No new code | No name to switch, no trace, no offline mode, not in the comparison | Named components |
| Build the contents tree from search chunks | No new slot | Merged small sections disappear from the contents; depends on the chunker | Headings of the parsed document, in a `toc_store` |
| Precomputed global communities and reports (Microsoft GraphRAG) | Fast queries, richer reports | Built from all documents: a report can reveal what a person may not see; heavy re-indexing | Per-person communities, cached; Microsoft GraphRAG / Neo4j documented as references |
| Graph in `rag.chunks` via joins | No duplicated text | Ties the graph to the pgvector store; Qdrant/OpenSearch profiles couldn't use it | Own tables with the same access columns |
| Neo4j as the durable graph | Real graph queries, Leiden | Another service to run, secure and back up | Postgres now; Neo4j as a plugin when a project needs it |
| The official `mcp` SDK | Full protocol, HTTP transport | More dependencies (web server stack) for two tools | Minimal stdio server; the SDK is the reference for more |
| Identity as a tool argument | Flexible | The model (or an injected prompt) chooses whose permissions to use | Fixed at launch |
| Coerce `--filter` values by declared field types | Exact | There is no declared type for most metadata | Match the text and its number reading |

## Consequences
+ Every common RAG architecture is one word in `rag.yaml`, with a trace of what it did, and appears
  in `rag eval-answers` next to the others (nine new rows), offline in CI.
+ Vectorless deployments (keyword and contents only) are possible; GraphRAG answers "big picture"
  questions without leaking hidden documents, and its graph survives restarts.
+ Agents can use the knowledge base with exactly their user's permissions.
- More components to understand and evaluate; several add model calls per question (documented per
  architecture).
- Per-person community detection is fine for thousands of entities, not millions.
- `rag mcp` is a single-user, local server; multi-user access must go through rag-api.

## Revisit when
A corpus needs hierarchical (Leiden) communities or precomputed reports with a permission design; an
MCP client needs resources, prompts or the HTTP transport (adopt the SDK, behind rag-api's auth);
or a model-based weak-sentence judge beats the lexical check for `flare` on our answer evaluation.
