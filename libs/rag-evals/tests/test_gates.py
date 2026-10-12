"""Gates: thresholds, the prompt's own bar, and regressions against a baseline."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_evals.datasets import EvalError
from rag_evals.gates import check, load_gates

from .conftest import REPO

GATES = load_gates(REPO / "evals/gates.yaml")
GOOD = {
    "pass_rate": 0.875,
    "citation_precision": 1.0,
    "refusal_accuracy": 1.0,
    "injection_resisted": 1.0,
}


def test_a_good_run_passes() -> None:
    assert check(GOOD, "answer", GATES) == []


def test_each_bound_is_checked() -> None:
    bad = GOOD | {"injection_resisted": 0.6667, "citation_precision": 0.95}
    assert check(bad, "answer", GATES) == [
        "citation_precision = 0.95 is below the minimum 1.0",
        "injection_resisted = 0.6667 is below the minimum 1.0",
    ]
    assert check({"recall@5": 1.0, "mrr": 1.0, "leaked_docs": 1, "policy_mismatches": 0},
                 "retrieval", GATES) == ["leaked_docs = 1 is above the maximum 0.0"]  # fmt: skip


def test_missing_metric_fails() -> None:
    assert "refusal_accuracy: not measured in this run" in check(
        {k: v for k, v in GOOD.items() if k != "refusal_accuracy"}, "answer", GATES)  # fmt: skip


def test_the_prompts_own_minimum_applies() -> None:
    """A prompt declaring evaluation.min_score 0.9 is held to it: stricter than the global 0.8."""
    assert check(GOOD, "answer", GATES, extra_min={"pass_rate": 0.9}) == [
        "pass_rate = 0.875 is below the minimum 0.9"
    ]
    assert check(GOOD, "answer", GATES, extra_min={"pass_rate": 0.5}) == []  # never loosens


def test_regression_against_baseline() -> None:
    baseline = GOOD | {"pass_rate": 0.95}
    assert check(GOOD, "answer", GATES, baseline=baseline) == [
        "pass_rate regressed: 0.95 -> 0.875 (tolerance 0.02)"
    ]
    assert check(GOOD, "answer", GATES, baseline=GOOD | {"pass_rate": 0.89}) == []  # within noise


def test_bad_gate_file(tmp_path: Path) -> None:
    (tmp_path / "g.yaml").write_text(
        "retrieval: {mrr: {min: 0.5, max: 0.9}}\nanswer: {}\nregression: {}\n"
    )
    with pytest.raises(EvalError, match="exactly one of min or max"):
        load_gates(tmp_path / "g.yaml")
