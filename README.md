# rag-platform

Local-first, enterprise-grade RAG platform (Project 0 of the RAG curriculum).

## Documentation

Start with the **[documentation map](docs/README.md)**: who should read what. The two hands-on guides:

- **[Local setup](docs/guides/local-setup.md)**: from an empty Apple Silicon Mac to the whole platform running, step by step, with checks after each stage.
- **[Production promotion](docs/guides/production-promotion.md)**: from the laptop to staging and production: signed images, GitOps, gates, canaries, HA/DR and the pre-production checklist.

And to understand it: [architecture overview](docs/architecture/overview.md) ·
[RAG handbook](docs/concepts/rag-handbook.md) · [quality and operations](docs/guides/quality-and-operations.md) ·
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
