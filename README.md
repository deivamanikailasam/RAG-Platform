# rag-platform

Local-first, enterprise-grade RAG platform (Project 0 of the RAG curriculum).

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
- The source build guide (PDF): [docs/source/](docs/source/)
