"""A/B comparison with a significance test (extension 04).

Two configurations answered the SAME questions, so compare them question by question (paired):
for each metric, the per-question differences B - A give

    mean difference     how much better (or worse) B is on average
    95% interval        a paired bootstrap: resample the questions with replacement, many times
    p-value             a paired permutation (sign-flip) test: if A and B were interchangeable,
                        how often would a difference this large appear by chance? Exact for up
                        to 16 questions, sampled above that.

"B is better" needs both: p below alpha AND an interval that excludes zero. With 25 questions a
difference of a few points is usually "not significant": that is the honest answer, and the
reason to grow the dataset (or to run `rag online-eval` on real traffic, Step 37).
"""

from __future__ import annotations

import itertools
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from rag_core.evalkit.runs import case_scores, metrics_in

LOWER_IS_BETTER = frozenset({"ms", "p50_ms", "leaks"})


def bootstrap_ci(diffs: Sequence[float], resamples: int = 2000, alpha: float = 0.05,
                 seed: int = 0) -> tuple[float, float]:  # fmt: skip
    """Percentile bootstrap interval of the mean difference."""
    if not diffs:
        return 0.0, 0.0
    rng = random.Random(seed)  # noqa: S311 - statistics, not secrets
    n = len(diffs)
    means = sorted(statistics.fmean(rng.choices(diffs, k=n)) for _ in range(resamples))
    lo = means[int((alpha / 2) * (resamples - 1))]
    hi = means[int((1 - alpha / 2) * (resamples - 1))]
    return lo, hi


def permutation_p(diffs: Sequence[float], resamples: int = 10_000, seed: int = 0) -> float:
    """Two-sided paired sign-flip test of "the mean difference is zero"."""
    nz = [d for d in diffs if d != 0]
    if not nz:
        return 1.0
    observed = abs(sum(nz))
    if len(nz) <= 16:  # every sign pattern: exact
        total = extreme = 0
        for signs in itertools.product((1, -1), repeat=len(nz)):
            total += 1
            extreme += abs(sum(s * d for s, d in zip(signs, nz, strict=True))) >= observed - 1e-12
        return extreme / total
    rng = random.Random(seed)  # noqa: S311 - statistics, not secrets
    extreme = sum(abs(sum(d if rng.random() < 0.5 else -d for d in nz)) >= observed - 1e-12
                  for _ in range(resamples))  # fmt: skip
    return (extreme + 1) / (resamples + 1)


@dataclass
class Comparison:
    metric: str
    n: int  # questions measured in both runs
    mean_a: float
    mean_b: float
    diff: float  # B - A
    ci_low: float
    ci_high: float
    p_value: float
    verdict: str  # "B better" | "A better" | "no significant difference" | "too few"


def compare(a: dict[str, float], b: dict[str, float], metric: str, *, alpha: float = 0.05,
            resamples: int = 2000, seed: int = 0, min_n: int = 5) -> Comparison:  # fmt: skip
    ids = sorted(set(a) & set(b))
    diffs = [b[i] - a[i] for i in ids]
    if len(ids) < min_n:
        ma = statistics.fmean([a[i] for i in ids]) if ids else 0.0
        mb = statistics.fmean([b[i] for i in ids]) if ids else 0.0
        return Comparison(metric, len(ids), ma, mb, mb - ma, 0.0, 0.0, 1.0, "too few")
    lo, hi = bootstrap_ci(diffs, resamples, alpha, seed)
    p = permutation_p(diffs, resamples * 5, seed)
    mean_a = statistics.fmean(a[i] for i in ids)
    mean_b = statistics.fmean(b[i] for i in ids)
    d = mean_b - mean_a
    better_b = d < 0 if metric in LOWER_IS_BETTER else d > 0
    significant = p < alpha and (lo > 0 or hi < 0)
    verdict = (
        ("B better" if better_b else "A better") if significant else "no significant difference"
    )
    r = 4
    return Comparison(metric, len(ids), round(mean_a, r), round(mean_b, r), round(d, r),
                      round(lo, r), round(hi, r), round(p, 4), verdict)  # fmt: skip


def compare_runs(run_a: dict[str, Any], run_b: dict[str, Any], metrics: Sequence[str] | None = None,
                 **kw: Any) -> list[Comparison]:  # fmt: skip
    names = (
        list(metrics) if metrics else [m for m in metrics_in(run_a) if m in set(metrics_in(run_b))]
    )
    return [compare(case_scores(run_a, m), case_scores(run_b, m), m, **kw) for m in names]


def format_comparison(rows: Sequence[Comparison], a: str, b: str) -> str:
    head = (f"{'metric':20} {'n':>4} {'A':>8} {'B':>8} {'B - A':>8} {'95% interval':>19} "
            f"{'p':>7}  verdict")  # fmt: skip
    lines = [f"A = {a}", f"B = {b}", "", head, "-" * (len(head) + 12)]
    for c in rows:
        lines.append(f"{c.metric:20} {c.n:4d} {c.mean_a:8.3f} {c.mean_b:8.3f} {c.diff:+8.3f} "
                     f"[{c.ci_low:+7.3f}, {c.ci_high:+7.3f}] {c.p_value:7.4f}  {c.verdict}")  # fmt: skip
    return "\n".join(lines)


def as_json(rows: Sequence[Comparison]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]


__all__ = ["Comparison", "as_json", "bootstrap_ci", "compare", "compare_runs", "format_comparison",
           "permutation_p"]  # fmt: skip
