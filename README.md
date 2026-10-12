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

## Decisions
See [docs/adr](docs/adr/README.md).

## Build guide
- Step-by-step write-ups of each chapter: [docs/steps/README.md](docs/steps/README.md)
- The source build guide (PDF): [docs/source/](docs/source/)
