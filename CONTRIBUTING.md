# Contributing

> **IN PLAIN ENGLISH**
> Every change goes through a short branch and a pull request, is described with a structured commit
> message, passes the same automated checks on your machine and in CI, and is reviewed by the owner of
> the files it touches. Anything that changes how the platform *behaves* (a prompt, a model, a policy, a
> threshold, an architectural choice) also leaves a record: a new prompt version, a card, an ADR. This
> page lists the conventions and the exact commands.

New here? Set up your machine with [docs/guides/local-setup.md](docs/guides/local-setup.md) (at least
Stage A and B), and read the [documentation map](docs/README.md).

## Branches and pull requests

- `main` is protected: no direct commits (the `no-commit-to-branch` hook refuses them locally, the
  ruleset on GitHub refuses them remotely), no force pushes, linear history.
- Work on a short-lived branch named after the change: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`
  (the steps used names like `feat/gateway`, `feat/opa-policy`). Promotions use `promote/<env>-<digest>`,
  created by `just promote`.
- Open a pull request with `gh pr create --fill` and complete the
  [pull request template](.github/pull_request_template.md): what and why (link the step, issue or ADR),
  how it was tested, and the checklist.
- Merging needs green required checks and a **Code Owner** review ([CODEOWNERS](.github/CODEOWNERS);
  `/prompts/` and `/cards/` have named owners). Merge with squash: `gh pr merge --squash --delete-branch`.
- Commits are signed (SSH signing, set up by [`bootstrap/git-setup.sh`](bootstrap/git-setup.sh)); the
  `main` ruleset requires it.

## Commit messages: Conventional Commits

The `commit-msg` hook enforces [Conventional Commits](https://www.conventionalcommits.org/) with these
types: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `perf`, `revert`, and
`deploy` (used only by `just promote` for promotion commits).

```text
feat(gateway): virtual keys, team budgets, shadow pricing, rate limits and fallbacks

A plain-English body of a few lines: what changed and why, what a reviewer
should look at, and anything deliberately left out.
```

Use a scope that names the area (`gateway`, `db`, `rag-core`, `policy`, `docs`, `step-31`, …). Promotion
commits are written by `just promote` as `deploy(<env>): rag-api <digest>` with the gate result in the body.

## Before you push: the same gates as CI

```bash
just install-hooks     # once per clone: pre-commit, commit-msg and pre-push hooks
just fmt && just lint  # ruff format and ruff check --fix
just typecheck         # strict mypy
just test              # pytest (the pre-push hook runs it too)
just ci                # everything a PR must pass: static, tests, config-as-code, policy, supply chain
just audit-test        # all tests incl. the audit-DB and OpenBao tests on a throwaway Postgres
```

The pre-commit hooks ([`.pre-commit-config.yaml`](.pre-commit-config.yaml)) check file hygiene, private
keys and secrets (gitleaks), that files in `secrets/` are SOPS-encrypted, ruff, strict mypy, that
`uv.lock` matches `pyproject.toml`, the prompt registry, and that cards and their generated pages agree.
Don't bypass them with `--no-verify`; if one is wrong, fix the hook in its own PR.

Python changes: Python 3.12, a uv workspace member for any new package (`uv init --lib libs/<name>`),
typed (mypy strict passes), ruff-clean, with tests. Dependencies: `uv add <pkg>` (it must pass the
[licence policy](ci/licence-policy.yaml) and `pip-audit`). Never commit secrets, data or model files.

## Recording decisions: ADRs

A change to an architectural choice (a new service, a different store, a new default) needs an
Architecture Decision Record ([ADR-0001](docs/adr/0001-record-architecture-decisions.md)):

```bash
just adr "Use Qdrant for vectors"      # creates docs/adr/NNNN-use-qdrant-for-vectors.md from the template
```

Fill in Context, Decision, Alternatives considered (with why not), Consequences and "Revisit when", add
a row to [docs/adr/README.md](docs/adr/README.md), and land it in the same PR as the change. Accepted ADRs
are never edited to change their meaning: a new ADR supersedes an old one.

## How to add…

### A switchable component (to rag-core)

1. Implement it in `libs/rag-core/src/rag_core/components/<area>.py` with a Pydantic settings model
   (`extra="forbid"`) and register it:
   `@register("<kind>", "<name>", params=<Params>, summary="…", status="live|mocked|reference", requires=(…))`.
2. Tests in `libs/rag-core/tests/`; stores and embedders must pass the conformance kit
   (`rag_core/testing/conformance.py`), **including the access-leak checks**.
3. `just catalogue` to regenerate [docs/catalogue.md](docs/catalogue.md) (CI runs `just catalogue --check`).
4. If it changes a default in `rag.yaml`: measure with `rag eval-search` / `eval-answers` / `eval-guards`,
   run `just sync-profiles` and `just rag-config-check`, and write an ADR.
5. Note it in [libs/rag-core/CHANGELOG.md](libs/rag-core/CHANGELOG.md): new components are a minor
   version; changing a public name or contract is a major version with a migration note.

Project-specific components belong in the project (see [new-rag-project.md](docs/guides/new-rag-project.md));
contribute them here when other teams would use them.

### A prompt (or a new prompt version)

```bash
just prompts new rag-answer                    # next version, copied from the latest
# edit prompts/rag-answer/v<N>.yaml (owner, model alias, variables with max length, changelog)
just prompts lint
just prompts lock                              # release: records the SHA-256; released files are frozen
just prompts promote rag-answer <N> staging    # try it in staging, evaluate it
just evals run answer --prompt rag-answer --label staging --judge && just evals gate evals/runs/<run>
```

Moving `production` to the new version is a separate, reviewed PR (`just prompts promote rag-answer <N>
production`). Roll back the same way. See [Step 24](docs/steps/step-24-prompt-registry.md).

### A model, dataset or system card

Cards are YAML in `cards/{models,datasets,systems}/`; the pages in `docs/cards/` are generated.

```bash
# edit or add cards/models/<id>.yaml (owner, licence with verified date, intended / out-of-scope use, risks…)
just cards lint                 # every rule and cross-check
just cards docs                 # regenerate docs/cards/*.md (commit them with the card)
just cards impact model:<id>    # what depends on it: who must re-check before the change
```

A model change also updates [`infra/model-serving/models.yaml`](infra/model-serving/models.yaml) (pinned
revision, licence, approval) and, for the embedder, means a re-index ([Step 36](docs/steps/step-36-lifecycle-threat-model-compliance.md)).

### An evaluation dataset or questions

- Golden datasets: `evals/datasets/<name>/v<N>.jsonl` plus `dataset.yaml`; freeze a version with
  `just evals release <name>` (pins its SHA-256; released versions are immutable); give it a dataset card.
- Offline gates: add questions to [`examples/eval/handbook.yaml`](examples/eval/handbook.yaml) (with
  `relevant:` documents, `relevant: []` for unanswerable, `forbidden:` for access checks) or cases to
  [`examples/eval/guards.yaml`](examples/eval/guards.yaml) (attacks **and** ordinary questions).
- Accept a new baseline only with a reason: `just evals baseline evals/runs/<run>`, committed.

### A policy, alert or dashboard

- Policies: edit `policies/`, add tests, `just policy-check` (≥ 90% coverage).
- Alerts: edit `infra/config/prometheus/rules/`, add a promtool test and a runbook in `docs/runbooks/`,
  `just alerts-test`.
- Dashboards: edit `scripts/build_dashboards.py`, then `just dashboards` (never hand-edit the JSON).
- Risk register: edit [`docs/compliance/risk-register.yaml`](docs/compliance/risk-register.yaml), then
  `just compliance-docs` and `just compliance-check`.

## Documentation

Docs live in [`docs/`](docs/README.md). Write for a newcomer: start with an "In plain English" summary,
then go deep; link to the step write-up, ADR and runbook rather than repeating them; every command must
exist in the `justfile` or `scripts/`. Generated pages (cards, catalogue, threat model, controls) are
changed through their sources. Add a line to [CHANGELOG.md](CHANGELOG.md) under *Unreleased*.

## Security

Never open a public issue for a vulnerability or a leaked secret: see [SECURITY.md](SECURITY.md).
