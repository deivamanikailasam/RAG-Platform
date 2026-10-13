"""Quality gates: thresholds a run must meet, and no meaningful regression against the baseline.

evals/gates.yaml
  retrieval:  {recall@5: {min: 0.9}, leaked_docs: {max: 0}, …}
  answer:     {pass_rate: {min: 0.8}, injection_resisted: {min: 1.0}, …}
  regression: {tolerance: 0.02}
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from rag_evals.datasets import EvalError


class Bound(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _one(self) -> Bound:
        if (self.min is None) == (self.max is None):
            raise ValueError("give exactly one of min or max")
        return self


class Gates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    retrieval: dict[str, Bound]
    answer: dict[str, Bound]
    regression: dict[str, float]


def load_gates(path: Path) -> Gates:
    try:
        return Gates.model_validate(yaml.safe_load(path.read_text()))
    except Exception as e:
        raise EvalError(f"{path}: {e}") from e


def check(summary: Mapping[str, Any], suite: str, gates: Gates, *,
          baseline: Mapping[str, Any] | None = None,
          extra_min: Mapping[str, float] | None = None) -> list[str]:  # fmt: skip
    """Every failure, in plain words. An empty list means the run passed."""
    bounds = dict(getattr(gates, suite))
    for metric, floor in (extra_min or {}).items():  # e.g. the prompt's own evaluation.min_score
        current = bounds.get(metric)
        if current is None or current.min is None or current.min < floor:
            bounds[metric] = Bound(min=floor)
    failures = []
    for metric, b in sorted(bounds.items()):
        value = summary.get(metric)
        if value is None:
            failures.append(f"{metric}: not measured in this run")
        elif b.min is not None and value < b.min:
            failures.append(f"{metric} = {value} is below the minimum {b.min}")
        elif b.max is not None and value > b.max:
            failures.append(f"{metric} = {value} is above the maximum {b.max}")
    tolerance = gates.regression.get("tolerance", 0.0)
    for metric, b in sorted(bounds.items()) if baseline else []:
        new, old = summary.get(metric), (baseline or {}).get(metric)
        if new is None or old is None:
            continue
        worse = (old - new) if b.min is not None else (new - old)
        if worse > tolerance:
            failures.append(f"{metric} regressed: {old} -> {new} (tolerance {tolerance})")
    return failures
