# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Step 1: `bootstrap/Brewfile` with the Core CLI tools (git, gh, jq, yq, just, direnv, wget, tree), reference shell snippets for Homebrew's PATH and the direnv hook under `bootstrap/home/`, and the step write-up.
- Step 2: `uv` added to the Brewfile, reference global uv config (`bootstrap/home/.config/uv/uv.toml`: only-managed interpreters, manual downloads, commented company mirror), the `bootstrap/labs/uv-lab.sh` lab replay script, and the step write-up.
- Step 3: OrbStack and dive added to the Brewfile, reference Docker engine config with log rotation (`bootstrap/home/.orbstack/config/docker.json`), `bootstrap/orbstack-setup.sh` (VM cap 24 GB / 8 CPUs), the `bootstrap/labs/container-lab.sh` lab replay script, `bootstrap/NOTES-step3.md` decisions (models native, services in containers), and the step write-up.
- Step 4: monorepo skeleton (`libs/`, `services/`, `infra/`, `evals/`, `tests/`, `scripts/`, `docs/`), hygiene files (`.gitignore`, `.gitattributes`, `.editorconfig`), project README, PR template and CODEOWNERS, the uv workspace (`pyproject.toml`, `.python-version`, `uv.lock`) with the first shared library `libs/rag-common`, the `justfile` command menu, the ADR template with ADR-0001 to ADR-0004 and index, `bootstrap/git-setup.sh` plus reference `~/.gitconfig` / `~/.ssh` copies, and the step write-up.
- Step 5: code quality gates: ruff, mypy, pytest and pre-commit as locked dev dependencies configured in the root `pyproject.toml`, the first `rag-common` unit test, `.pre-commit-config.yaml` (file hygiene, detect-private-key, gitleaks, no-commit-to-branch, ruff, strict mypy, uv.lock check, Conventional Commits message check, pytest at pre-push; generic hooks frozen to SHAs), new `just` recipes with `just check` running every gate, `.vscode/extensions.json`, ADR-0005, and the step write-up.
- Step 6: local secrets handling: `age` and `sops` in the Brewfile, `.sops.yaml` encryption rules, `scripts/new-dev-secrets.sh` (random dev secrets encrypted into `secrets/dev.enc.env`), the `secrets-encrypted` pre-commit hook (`scripts/check-sops-encrypted.sh`) and `.gitleaks.toml`, the file-based container secret demo `infra/compose/secrets-demo.yaml`, `.envrc` (direnv: venv, SOPS key, Keychain HF token), `.env.example`, `secrets-*` / `with-secrets` just recipes, `rag_common.settings` with pydantic-settings and `SecretStr`, the secret-leak runbook, ADR-0006, and the step write-up.
