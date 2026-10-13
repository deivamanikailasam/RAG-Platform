# rag-core changelog

Semantic versioning (docs/standards/rag-standards.md, "Versioning"): MAJOR for breaking changes
to contracts, the SDK, the CLI, component names and settings, rag.yaml or the packaged profiles.

## Unreleased (minor: additions only)
- Extension 01: `metric`, index and quantization settings on every vector store with an
  embedding-contract check; `rag_core.filters` (typed metadata filters, pushed down into every
  store); `self-query`; fusion `relative-score`, `combsum`, `combmnz`, `borda`; the `search_cache`
  slot; the `ensemble` and `router` retrievers; `rag search/ask --filter`, `rag index ddl`;
  conformance checks `check_metadata_filters`, `check_metrics`. Existing settings keep their meaning
  (Qdrant's `hnsw_ef` is accepted as `ef_search`); the answer-cache key changes only when a filter is given.

- Extension 02: chunkers `hierarchical`, `proposition`, `code`; enrichers `summary-tree`, `summary`,
  `metadata`, `llm-metadata`; post-processors `auto-merge`, `section-expand`, `summary-expand`; the
  `section` retriever; the `compressors` slot (`extractive`, `embedding-filter`, `llm-extract`,
  `summarize`, `llmlingua`); embedders `instructed`, `matryoshka`, `late-chunking`; the
  `sparse_embedder` slot (`bm25`, `splade-tei`) and keyword indexes `sparse`, `qdrant-sparse`;
  rerankers `maxsim`, `colbert`; contracts `Compressor`, `DocumentEmbedder`, `SparseEmbedder`;
  conformance `check_chunker`, `check_compressor`, `check_sparse_embedder`; `rag_core.text`.
  Additive: structure chunks gain `heading`, `section_path`, `section_numbers` metadata (ids
  unchanged); oversized code blocks are now cut between lines instead of at sentence ends.

## 1.0.0 (Step 38)
First stable release: the public API is fixed for 1.x.
- Contracts and types; 94 registered components in 24 kinds (docs/catalogue.md)
- Pipelines: ingestion (31), search (32), answers (33), guardrails (34), architectures (35)
- Lifecycle: access changes, retention with legal holds, erasure, re-index (36, 37)
- Evaluation: eval-search, eval-guards, eval-answers (32-35), online-eval (37)
- Readiness (37) and doctor (38); the SDK `rag_core.sdk.RagApp` (38)
- rag.yaml `include:` and the packaged platform profiles `rag-core:platform.yaml` (38)
- Plugins by entry point `rag_core.components` or `RAG_PLUGINS` (38)
