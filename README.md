# rag-platform

Local-first, enterprise-grade RAG platform (Project 0 of the RAG curriculum).

## What's inside

A RAG engine (`rag-core`) where every stage is a switchable component (159 in 31 kinds, see the
[catalogue](docs/catalogue.md)), plus the platform around it. Is a technique here? See the
**[coverage matrix](docs/concepts/coverage-matrix.md)**. Which one to use? See the
**[decision guide](docs/concepts/decision-guide.md)** (with ten validated
[starter configs](examples/profiles/recipes.yaml)).

- **Ingestion:** parsers (Markdown, HTML, PDF, Word, CSV, text; Tika, Docling), cleaning, PII redaction, connectors with incremental `rag sync`.
- **Chunking:** structure-aware, recursive, fixed, semantic, sentence-window, parent-child, hierarchical, proposition, code; late chunking; RAPTOR and document summaries; metadata extraction; contextual retrieval.
- **Embeddings and stores:** any model through the gateway, instruction prefixes, Matryoshka, quantization, embedding cache; pgvector, Qdrant, OpenSearch; cosine, dot, Euclidean, Manhattan; HNSW, IVF, flat.
- **Search:** hybrid (dense + BM25/SPLADE), metadata filters and self-query, query rewriting, multi-query, HyDE, step-back, decomposition, expansion, translation, routing, ensembles, precise section retrieval; fusion by RRF, relative score, weighted, DBSF, CombSUM/MNZ, Borda; cross-encoder, LLM and ColBERT-style reranking; MMR, recency, auto-merge.
- **Answers:** context compression, lost-in-the-middle packing, checked citations, abstention, confidence, JSON, streaming, memory, exact and semantic caches.
- **Architectures:** naive, standard, vector, keyword/vectorless, PageIndex, RAG-Fusion, HyDE, conversational, corrective, self-reflective, adaptive, FLARE, speculative, agentic, graph (local and global), SQL, table, long-context; MCP tools for agents.
- **Safety and operations:** layered guardrails measured in CI, permissions inside every query, audit log, evaluation loop (metrics, judges, A/B, sweeps, synthetic sets, online evaluation), observability, Kubernetes with canaries and DR.

## Documentation

Start with the **[documentation map](docs/README.md)**: who should read what. The two hands-on guides:

- **[Local setup](docs/guides/local-setup.md)**: from an empty Apple Silicon Mac to the whole platform running, step by step, with checks after each stage.
- **[Production promotion](docs/guides/production-promotion.md)**: from the laptop to staging and production: signed images, GitOps, gates, canaries, HA/DR and the pre-production checklist.

And to understand it: [architecture overview](docs/architecture/overview.md) ·
[RAG handbook](docs/concepts/rag-handbook.md) · [decision guide](docs/concepts/decision-guide.md) ·
[coverage matrix](docs/concepts/coverage-matrix.md) · [quality and operations](docs/guides/quality-and-operations.md) ·
[new RAG project](docs/guides/new-rag-project.md) · [contributing](CONTRIBUTING.md) · [security](SECURITY.md).

## Quick start
    just bootstrap     # install system tools from bootstrap/Brewfile
    just sync          # install Python packages for every workspace member
    just install-hooks # install the git hooks (pre-commit, commit-msg, pre-push) once per clone
    just check         # every gate CI runs: tools, lockfile, all hooks and tests

Secrets (Step 6): create your age key, put its public key in `.sops.yaml`, then
`just secrets-init` once; run things with `just with-secrets <cmd>`. See [secrets/README.md](secrets/README.md).

## Layout
- `libs/` shared Python packages · `services/` deployable apps · `infra/` compose, k8s, config
- `evals/` evaluation data and runs · `tests/` cross-service tests · `docs/adr/` decision records
- `templates/rag-project/` the template for a new RAG project (`just new-project ../my-project`, Step 38)

## Building a new RAG project on the platform (Step 38)
- Start from the template: `just new-project ../hr-assistant`, then `just check` in it.
- In code: `from rag_core.sdk import RagApp` (rag-core 1.0.0, [changelog](libs/rag-core/CHANGELOG.md)).
- The rules every project meets: [docs/standards/rag-standards.md](docs/standards/rag-standards.md), checked by `just doctor`.
- Every switchable component: [docs/catalogue.md](docs/catalogue.md) (generated: `just catalogue`).

## Decisions
See [docs/adr](docs/adr/README.md).

## Build guide
- Step-by-step write-ups of each chapter: [docs/steps/README.md](docs/steps/README.md)
- Every file and command in one place (Appendix A): [docs/reference.md](docs/reference.md)
- Plain-English glossary (Appendix B): [docs/glossary.md](docs/glossary.md)
- What was checked against the guide: [docs/coverage-audit.md](docs/coverage-audit.md)
- The source build guide (PDF): [docs/source/](docs/source/)
