# ADR-0005: Automated code quality gates with ruff, mypy, pytest and pre-commit

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** deivamanikailasam

## Context
Style drift, common Python bugs, type errors, leaked secrets and unclear history are cheapest
to catch before a commit exists. Tool versions must be identical in the editor, hooks and CI.

## Decision
We will use ruff (lint + format), mypy (strict, for libraries) and pytest, installed as dev
dependencies locked in uv.lock and run as local pre-commit hooks via `uv run`. Generic hooks
(file hygiene, detect-private-key, no-commit-to-branch, gitleaks, conventional-pre-commit) are
pinned to commit SHAs with `pre-commit autoupdate --freeze`. Tests run at pre-push.
CI (Step 27) runs `just check` so the same gates are enforced server-side.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Black + isort + Flake8 + plugins | Long track record | Several tools and configs; slower | ruff covers them in one fast tool |
| pyright / basedpyright | Fast, great editor experience | Different inference from mypy; Node-based | mypy is the most established; revisit |
| ty / pyrefly (new Rust type checkers) | Very fast | Young; rule coverage still maturing | Revisit when stable |
| prek / lefthook instead of pre-commit | Faster, no Python needed | Smaller ecosystem | pre-commit is the standard; prek reads the same config |
| Hooks from upstream repos for ruff/mypy | Isolated environments | Second pin, which can drift from uv.lock | Single source of truth preferred |

## Consequences
+ Bugs, secrets and style issues are blocked before they enter history.
+ One locked version of each tool everywhere.
- Commits take a few seconds longer; first hook run is slow.
- Local hooks can be skipped with --no-verify, so CI enforcement is mandatory (Step 27).

## Revisit when
A new type checker matures, or hook run time exceeds ~10 s on typical commits.
