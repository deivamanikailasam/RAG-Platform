"""Ablations (extension 04): evaluate every combination of a grid of rag.yaml changes, ranked.

    # sweep.yaml
    grid:
      chunker.max_tokens: [200, 400]
      fusion: [rrf, weighted]
      reranker: [none, {use: term-overlap, top_n: 30}]
    fixed: {retriever: hybrid}        # applied to every combination (optional)

    rag eval-sweep examples/eval/handbook.yaml --grid examples/eval/sweep.yaml --rank-by ndcg

A key is a slot (`fusion`: the value replaces the component, `none` switches it off) or
`slot.setting` (`chunker.max_tokens`: one setting of the profile's component). 2 x 2 x 2 = 8
combinations, each built fresh and evaluated on the same questions (ingesting the corpus again
when the combination changes ingestion). The table shows which component matters: compare rows
that differ in one key only.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from rag_core.registry import ComponentError

LOWER_IS_BETTER = frozenset({"p50_ms", "leaks"})


def load_grid(path: Path) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ComponentError(f"{path}: {e}") from None
    grid = doc.get("grid") if isinstance(doc, dict) else None
    if not isinstance(grid, dict) or not grid:
        raise ComponentError(f"{path}: expected `grid: {{key: [values…]}}`")
    return check_grid(grid), dict(doc.get("fixed") or {})


def check_grid(grid: Mapping[str, Any]) -> dict[str, list[Any]]:
    out = {}
    for k, v in grid.items():
        if not isinstance(v, list) or not v:
            raise ComponentError(f"grid: {k!r} needs a non-empty list of values")
        out[str(k)] = v
    return out


def parse_set(items: list[str]) -> dict[str, list[Any]]:
    """`--set chunker.max_tokens=200,400 --set reranker=none,term-overlap` -> a grid."""
    grid: dict[str, list[Any]] = {}
    for raw in items:
        key, sep, values = raw.partition("=")
        if not sep or not key.strip():
            raise ComponentError(f"--set {raw!r}: expected key=value1,value2")
        grid[key.strip()] = [yaml.safe_load(v) for v in values.split(",")]
    return grid


def overrides(assignment: Mapping[str, Any]) -> dict[str, Any]:
    """{"chunker.max_tokens": 200, "fusion": "rrf"} -> {"chunker": {"max_tokens": 200}, "fusion": "rrf"}."""
    out: dict[str, Any] = {}
    for key in sorted(assignment, key=lambda k: k.count(".")):  # whole slots before their settings
        value = copy.deepcopy(assignment[key])
        parts = key.split(".")
        target = out
        for p in parts[:-1]:
            current = target.get(p)
            if isinstance(current, str):
                current = {"use": current}
            target[p] = current if isinstance(current, dict) else {}
            target = target[p]
        target[parts[-1]] = value
    return out


def _short(v: Any) -> str:
    if isinstance(v, dict):
        rest = ",".join(f"{k}={w}" for k, w in v.items() if k != "use")
        return f"{v.get('use', '')}{'(' + rest + ')' if rest else ''}"
    return str(v)


def combinations(grid: Mapping[str, list[Any]]) -> list[tuple[str, dict[str, Any]]]:
    keys = list(grid)
    out = []
    for values in itertools.product(*(grid[k] for k in keys)):
        assign = dict(zip(keys, values, strict=True))
        label = " ".join(f"{k}={_short(v)}" for k, v in assign.items())
        out.append((label, overrides(assign)))
    return out


def rank(rows: list[dict[str, Any]], by: str) -> list[dict[str, Any]]:
    """Best first; a row that leaked a forbidden document is always last."""

    def key(r: dict[str, Any]) -> tuple[int, float, float]:
        v = r.get(by)
        score = float(v) if isinstance(v, int | float) else float("-inf")
        score = -score if by in LOWER_IS_BETTER else score
        return (1 if r.get("leaks") else 0, -score, float(r.get("p50_ms") or 0.0))

    return sorted(rows, key=key)


def format_ranked(rows: list[dict[str, Any]], by: str, metrics: list[str]) -> str:
    width = max([len("combination"), *(len(str(r["variant"])) for r in rows)])
    head = f"{'#':>3} {'combination':{width}} " + " ".join(f"{m:>10}" for m in metrics)
    lines = [f"ranked by {by}", head, "-" * len(head)]
    for i, r in enumerate(rows, 1):
        cells = []
        for m in metrics:
            v = r.get(m)
            cells.append(f"{v:10.3f}" if isinstance(v, float) else f"{v!s:>10}")
        lines.append(f"{i:3d} {r['variant']:{width}} " + " ".join(cells))
    return "\n".join(lines)


__all__ = [
    "check_grid",
    "combinations",
    "format_ranked",
    "load_grid",
    "overrides",
    "parse_set",
    "rank",
]
