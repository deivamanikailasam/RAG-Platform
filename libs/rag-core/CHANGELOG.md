# rag-core changelog

Semantic versioning (docs/standards/rag-standards.md, "Versioning"): MAJOR for breaking changes
to contracts, the SDK, the CLI, component names and settings, rag.yaml or the packaged profiles.

## 1.0.0 (Step 38)
First stable release: the public API is fixed for 1.x.
- Contracts and types; 94 registered components in 24 kinds (docs/catalogue.md)
- Pipelines: ingestion (31), search (32), answers (33), guardrails (34), architectures (35)
- Lifecycle: access changes, retention with legal holds, erasure, re-index (36, 37)
- Evaluation: eval-search, eval-guards, eval-answers (32-35), online-eval (37)
- Readiness (37) and doctor (38); the SDK `rag_core.sdk.RagApp` (38)
- rag.yaml `include:` and the packaged platform profiles `rag-core:platform.yaml` (38)
- Plugins by entry point `rag_core.components` or `RAG_PLUGINS` (38)
