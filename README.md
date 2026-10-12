# rag-platform

Local-first, enterprise-grade RAG platform (Project 0 of the RAG curriculum).

## Quick start
    just bootstrap     # install system tools from bootstrap/Brewfile
    just sync          # install Python packages for every workspace member
    just check         # verify tools and lockfile are in sync

## Layout
- `libs/` shared Python packages · `services/` deployable apps · `infra/` compose, k8s, config
- `evals/` evaluation data and runs · `tests/` cross-service tests · `docs/adr/` decision records

## Decisions
See [docs/adr](docs/adr/README.md).

## Build guide
- Step-by-step write-ups of each chapter: [docs/steps/README.md](docs/steps/README.md)
- The source build guide (PDF): [docs/source/](docs/source/)
