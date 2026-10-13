"""Online evaluation (Step 37): how answers are doing in real use, per release.

Offline evaluation (Steps 25, 32-35) asks labelled questions. Production has no labels, but it has
signals: the audit log (Step 23) records every answer's outcome, citations and guard verdicts, and
people's thumbs up/down arrive through /v1/feedback. This module turns those events into a few
rates per release, compares a candidate (the canary) with the baseline (the stable release), and
lists the answers a person should review: the raw material for the next labelled questions.

No question or answer text is read: the audit log never holds it (only ids, counts and verdicts).
A reviewer opens the trace (Langfuse/Tempo, by answer id) where the text lives under its own
retention rule (Step 22).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Rates where HIGHER is WORSE: a candidate fails when it is clearly worse than the baseline.
WORSE_IF_HIGHER = ("error_rate", "blocked_rate", "abstain_rate", "ungrounded_rate", "down_rate")
# Rates where LOWER is worse.
WORSE_IF_LOWER = ("cited_rate",)


@dataclass
class Stats:
    """Counts for one group of answers (usually one release)."""

    answers: int = 0
    answered: int = 0
    abstained: int = 0
    blocked: int = 0
    errors: int = 0
    cited: int = 0  # answered with at least one citation
    ungrounded: int = 0  # the groundedness guard flagged or blocked a sentence
    cache_hits: int = 0
    rated: int = 0
    down: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def rate(self, name: str) -> tuple[int, int]:
        """(numerator, denominator) for a named rate: the denominator matters for the test."""
        return {
            "error_rate": (self.errors, self.answers),
            "blocked_rate": (self.blocked, self.answers),
            "abstain_rate": (self.abstained, self.answers),
            "ungrounded_rate": (self.ungrounded, self.answered),
            "down_rate": (self.down, self.rated),
            "cited_rate": (self.cited, self.answered),
            "feedback_rate": (self.rated, self.answers),
            "cache_hit_rate": (self.cache_hits, self.answers),
        }[name]

    def rates(self) -> dict[str, float | None]:
        names = (*WORSE_IF_HIGHER, *WORSE_IF_LOWER, "feedback_rate", "cache_hit_rate")
        return {n: (k / d if d else None) for n in names for k, d in [self.rate(n)]}


def load_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Audit events exported as JSON lines (one object per line, the audit.events columns)."""
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_db(
    dsn: str, since_hours: float
) -> Iterator[dict[str, Any]]:  # pragma: no cover - needs a DB
    """Audit events straight from the audit database, as the read-only audit_reader role."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        yield from conn.execute(
            "SELECT occurred_at, actor, action, outcome, resource, details, trace_id FROM audit.events"
            " WHERE action IN ('answer', 'answer.completed', 'feedback')"
            " AND occurred_at > now() - make_interval(secs => %s) ORDER BY seq",
            (since_hours * 3600,),
        )


def _details(e: Mapping[str, Any]) -> dict[str, Any]:
    d = e.get("details") or {}
    return json.loads(d) if isinstance(d, str) else dict(d)


def collect(
    events: Iterable[Mapping[str, Any]], group_by: str = "release"
) -> tuple[dict[str, Stats], list[dict[str, Any]]]:
    """Join answers with their completion and feedback events. Returns (stats per group, review queue)."""
    answers: dict[str, dict[str, Any]] = {}
    feedback: dict[str, dict[str, Any]] = {}
    for e in events:
        d = _details(e)
        if e["action"] == "answer":
            answers[d["answer_id"]] = {**d, "trace_id": e.get("trace_id"), "outcome": e["outcome"]}
        elif e["action"] == "answer.completed" and d.get("answer_id") in answers:
            # streaming: the first record says "streaming"; the completion has the final result
            answers[d["answer_id"]].update({k: v for k, v in d.items() if v is not None})
        elif e["action"] == "feedback":
            feedback[str(e["resource"]).removeprefix("answer:")] = d  # the latest rating wins
    groups: dict[str, Stats] = {}
    queue: list[dict[str, Any]] = []
    for answer_id, a in answers.items():
        key = _group_key(a, group_by)
        s = groups.setdefault(key, Stats())
        s.answers += 1
        result = a.get("result")
        if a["outcome"] == "error" or result in (None, "streaming"):
            s.errors += 1  # refused for an error, or a stream that never completed
            continue
        s.blocked += result == "blocked"
        s.abstained += result == "abstained"
        if result == "answered":
            s.answered += 1
            s.cited += bool(a.get("cited_ids"))
        flagged = any(v.get("guard") == "groundedness" and v.get("action") != "allow"
                      for v in a.get("guards") or [])  # fmt: skip
        s.ungrounded += flagged and result == "answered"
        s.cache_hits += a.get("cache") == "hit"
        why = []
        if answer_id in feedback:
            f = feedback[answer_id]
            s.rated += 1
            if f.get("rating") == "down":
                s.down += 1
                reason = f.get("reason") or "none"
                s.reasons[reason] = s.reasons.get(reason, 0) + 1
                why.append(f"thumbs down ({reason})")
        if flagged:
            why.append("groundedness flagged")
        if why:
            queue.append({"answer_id": answer_id, "trace_id": a.get("trace_id"), "group": key,
                          "why": why, "context_ids": a.get("context_ids"), "cited_ids": a.get("cited_ids")})  # fmt: skip
    return groups, queue


def _group_key(a: Mapping[str, Any], group_by: str) -> str:
    if group_by == "release":
        return str(a.get("release") or "unknown")
    if group_by == "prompt":
        return ",".join(a.get("prompts") or ["unknown"])
    if group_by == "model":
        return str(a.get("model") or "unknown")
    if group_by == "all":
        return "all"
    raise ValueError(f"unknown group_by {group_by!r} (release | prompt | model | all)")


def _z_worse(k1: int, n1: int, k2: int, n2: int) -> float:
    """One-sided two-proportion z statistic: how clearly is p1 (candidate) above p2 (baseline)?"""
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return 0.0 if se == 0 else (k1 / n1 - k2 / n2) / se


@dataclass
class Check:
    metric: str
    candidate: float | None
    baseline: float | None
    status: str  # pass | fail | insufficient
    detail: str


@dataclass
class Verdict:
    candidate: str
    baseline: str
    status: str  # pass | fail | insufficient
    checks: list[Check]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def compare(
    candidate: Stats,
    baseline: Stats,
    *,
    names: tuple[str, str] = ("candidate", "baseline"),
    margin: float = 0.02,
    z: float = 1.645,
    min_n: int = 50,
    limits: Mapping[str, float] | None = None,
) -> Verdict:
    """Fail a metric only when the candidate is worse by more than `margin` AND the difference is
    unlikely to be chance (one-sided z-test, 95% by default). Too few events -> "insufficient":
    the gate waits for more traffic instead of guessing. `limits` are absolute ceilings
    (e.g. error_rate=0.02) that apply whatever the baseline does."""
    checks = []
    limits = dict(limits or {})
    for metric in (*WORSE_IF_HIGHER, *WORSE_IF_LOWER):
        k1, n1 = candidate.rate(metric)
        k2, n2 = baseline.rate(metric)
        c, b = (k1 / n1 if n1 else None), (k2 / n2 if n2 else None)
        if n1 < min_n or n2 < min_n:
            checks.append(
                Check(metric, c, b, "insufficient", f"{n1} vs {n2} events (need {min_n})")
            )
            continue
        c, b = c or 0.0, b or 0.0  # both counts are >= min_n here, so both rates exist
        if metric in limits and metric in WORSE_IF_HIGHER and c > limits[metric]:
            checks.append(Check(metric, c, b, "fail", f"{c:.3f} above the limit {limits[metric]}"))
            continue
        worse = (c - b) if metric in WORSE_IF_HIGHER else (b - c)
        stat = (
            _z_worse(k1, n1, k2, n2)
            if metric in WORSE_IF_HIGHER
            else _z_worse(n1 - k1, n1, n2 - k2, n2)
        )
        if worse > margin and stat > z:
            checks.append(Check(metric, c, b, "fail", f"worse by {worse:.3f} (z={stat:.2f})"))
        else:
            checks.append(Check(metric, c, b, "pass", f"difference {worse:+.3f} (z={stat:.2f})"))
    statuses = {ch.status for ch in checks}
    status = (
        "fail" if "fail" in statuses else "insufficient" if "insufficient" in statuses else "pass"
    )
    return Verdict(names[0], names[1], status, checks)


def format_report(groups: Mapping[str, Stats]) -> str:
    cols = ("answers", "error_rate", "blocked_rate", "abstain_rate", "cited_rate", "ungrounded_rate",
            "feedback_rate", "down_rate")  # fmt: skip
    lines = [f"{'group':16}" + "".join(f"{c:>16}" for c in cols)]
    for key, s in sorted(groups.items()):
        r = s.rates()
        cells = [f"{s.answers:>16}"] + [
            f"{r[c]:>16.3f}" if r[c] is not None else f"{'-':>16}" for c in cols[1:]
        ]
        lines.append(f"{key[:16]:16}" + "".join(cells))
    return "\n".join(lines)
