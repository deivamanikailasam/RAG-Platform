# ADR-0032: Search through one switchable pipeline: hybrid retrieval, fusion, reranking

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Projects need exact-word and meaning-based search, protection from leaks, robust behaviour when
model services fail, and a way to prove a search change helps. Step 11's single vector query had
none of the techniques that close the common retrieval failures.

## Decision
rag-core's SearchPipeline: transform (none by default; nine options) → retrieve (hybrid by
default: dense + keyword in parallel, inside each store's access filter) → fuse (RRF k=60) →
re-check access → rerank the top 30 (gateway cross-encoder; fails open) → post-process (dedupe,
min-score on rerank relevance, max 3 per document) → top k. Every hit keeps its per-stage scores;
every stage is traced. `rag eval-search` scores variants (recall@k, MRR, nDCG@k, leaks, latency);
CI gates the shipped settings offline. rag-api's /v1/search uses it behind the same OPA and audit
checks, selectable per deployment (legacy remains for rollback).

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Vector search only | Simple | Misses codes, names, rare terms | Hybrid default; dense selectable |
| Server-side hybrid (Qdrant Query API, OpenSearch hybrid query) | One round trip | Engine-specific; different per store | Client-side fusion works on every store; engine features remain an option |
| LLM reranking by default | Strong reasoning | Slow, costly | Cross-encoder default; LLM selectable |
| Reranker failure = request failure | Strict | Search down whenever TEI is | Fail open, counted and logged |
| Framework retrievers (LangChain, LlamaIndex) | Many integrations | Their abstractions, upgrades and tracing | Our contracts; frameworks can wrap as plugins |

## Consequences
+ Any project gets hybrid search, reranking and evaluation by configuration.
- More moving parts per request (reranker latency, LLM calls if transformers are on).
- Fusion and thresholds need tuning per corpus; the evaluation file must be maintained.

## Revisit when
A store's native hybrid search measurably beats client-side fusion, latency budgets can't fit a
reranker, or learned sparse (SPLADE) or late-interaction (ColBERT) models become available locally.
