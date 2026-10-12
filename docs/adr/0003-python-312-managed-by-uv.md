# ADR-0003: Use Python 3.12 managed by uv, with a committed lockfile

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** deivamanikailasam

## Context
RAG services depend on hundreds of transitive packages (mlx, torch, sentence-transformers,
spaCy, pyarrow, grpcio). Unpinned dependencies cause silent breakage; compiled packages need
pre-built wheels for the chosen Python version.

## Decision
We will use uv for interpreters, environments and locking; pin Python to 3.12 (>=3.12,<3.13);
organise Python code as a uv workspace with one committed uv.lock; and use only uv-managed
interpreters (python-preference = only-managed, python-downloads = manual).

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Poetry | Mature, popular | Slower; weaker workspace support | uv is faster and standards-based |
| pip + pip-tools | Minimal | Per-platform locks, many tools | More moving parts |
| conda / pixi | Handles native libraries | Heavier; not needed for PyPI wheels | Our stack is wheel-based |
| Python 3.13+ | Newer features | Wheel coverage less certain across the ML stack | Revisit later |

## Consequences
+ Byte-identical installs everywhere; CI enforces `uv sync --locked`.
+ One lockfile keeps every service on the same versions.
- Lockfile pins can preserve vulnerable versions: requires scheduled upgrades and scanning (Step 27).
- Dependence on a young, single-vendor tool, mitigated by standards-based pyproject.toml.

## Revisit when
All critical dependencies publish wheels for a newer Python, or uv's direction changes.
