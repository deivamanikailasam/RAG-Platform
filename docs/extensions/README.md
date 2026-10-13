# Extensions: techniques added after the build guide

The 38 [step write-ups](../steps/README.md) build the platform the guide describes. These pages add
the RAG techniques the guide left out, each as a switchable rag-core component with an offline
implementation, tests and an honest status in the [catalogue](../catalogue.md). Every page follows
the same pattern: in plain English, an analogy, what and why, how it works, how to switch it on in
`rag.yaml`, when to use which, trade-offs, common mistakes, and what was added to the repository.
The [RAG handbook](../concepts/rag-handbook.md) links each technique to its page.

| # | Feature group | Adds | Decision |
|---:|---|---|---|
| 01 | [Retrieval maths, metadata filters, fusion, caching and routing](01-retrieval-math-filters-fusion.md) | Similarity metrics (cosine, dot, L2, L1) with index settings, quantization and a contract check on every vector store · typed metadata filters pushed into every store, `--filter`, `"filter"` in the API · `self-query` · fusion `relative-score`, `combsum`, `combmnz`, `borda` · `search_cache` · `ensemble` and `router` retrievers | [ADR-0039](../adr/0039-switchable-metrics-pushed-down-filters-and-multi-retriever-search.md) |
| 02 | [Chunking, indexing, metadata, sections, compression and embedding options](02-chunking-indexing-compression.md) | `hierarchical` chunker + `auto-merge` · RAPTOR `summary-tree`, document `summary` + `summary-expand` · `proposition` and `code` chunkers · `metadata` and `llm-metadata` enrichers · section metadata, `section` retriever, `section-expand` · `compressors` slot: `extractive`, `embedding-filter`, `llm-extract`, `summarize`, `llmlingua` · embedders `instructed`, `matryoshka`, `late-chunking` · `sparse_embedder` (`bm25`, `splade-tei`) with `sparse` / `qdrant-sparse` · `maxsim` / `colbert` rerankers · choosing an embedding model | [ADR-0040](../adr/0040-chunk-trees-metadata-sections-compression-and-embedding-options.md) |
