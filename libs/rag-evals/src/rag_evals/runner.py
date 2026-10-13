"""Run a dataset against a target; keep every result and the full provenance of the run."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rag_evals import metrics as m
from rag_evals.datasets import AnswerCase, Dataset, RetrievalCase
from rag_evals.judge import Judge
from rag_evals.targets import AnswerTarget, RetrievalTarget

HARNESS_VERSION = "0.1.0"


@dataclass
class RunResult:
    suite: str  # "retrieval" or "answer"
    provenance: dict[str, Any]
    records: list[dict[str, Any]]
    summary: dict[str, Any]


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,  # noqa: S607
                             text=True, check=True, timeout=5)  # fmt: skip
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,  # noqa: S607
                               text=True, check=True, timeout=5).stdout.strip()  # fmt: skip
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _provenance(dataset: Dataset, target: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"dataset": dataset.ref, "dataset_sha256": dataset.sha256, "dataset_card": dataset.card,
            "target": target, "git_commit": _git_commit(), "harness": HARNESS_VERSION,
            "started_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), **extra}  # fmt: skip


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 4)


def run_retrieval(dataset: Dataset, target: RetrievalTarget, k: int = 5) -> RunResult:
    records: list[dict[str, Any]] = []
    recall: list[float] = []
    precision: list[float] = []
    rr: list[float] = []
    ndcg: list[float] = []
    latency: list[float] = []
    leaked_docs = mismatches = denied = 0
    for case in (c for c in dataset.cases if isinstance(c, RetrievalCase)):
        out = target.retrieve(case, k)
        relevant, forbidden = set(case.relevant), set(case.forbidden)
        rec: dict[str, Any] = {"id": case.id, "persona": case.persona.name, "ranked": out.ranked,
                               "dropped": out.dropped, "allowed": out.allowed,
                               "latency_s": round(out.latency_s, 4), "tags": list(case.tags)}  # fmt: skip
        if relevant:
            rec |= {f"recall@{k}": m.recall_at_k(out.ranked, relevant, k),
                    f"precision@{k}": m.precision_at_k(out.ranked, relevant, k),
                    "rr": m.reciprocal_rank(out.ranked, relevant),
                    f"ndcg@{k}": round(m.ndcg_at_k(out.ranked, relevant, k), 4)}  # fmt: skip
            recall.append(rec[f"recall@{k}"])
            precision.append(rec[f"precision@{k}"])
            rr.append(rec["rr"])
            ndcg.append(rec[f"ndcg@{k}"])
        rec["leaked"] = m.leaked(out.ranked, forbidden)
        leaked_docs += len(rec["leaked"])
        mismatches += len(out.dropped)
        denied += not out.allowed
        latency.append(out.latency_s)
        records.append(rec)
    summary = {"cases": len(records), f"recall@{k}": m.avg(recall), f"precision@{k}": m.avg(precision),
               "mrr": m.avg(rr), f"ndcg@{k}": m.avg(ndcg), "leaked_docs": leaked_docs,
               "policy_mismatches": mismatches, "denied": denied, "latency_p95_s": _p95(latency)}  # fmt: skip
    return RunResult("retrieval", _provenance(dataset, target.describe(), k=k), records, summary)


def run_answers(dataset: Dataset, target: AnswerTarget, judge: Judge | None = None) -> RunResult:
    records: list[dict[str, Any]] = []
    for case in (c for c in dataset.cases if isinstance(c, AnswerCase)):
        out = target.answer(case)
        ids = {c.id for c in case.contexts}
        checks = m.answer_checks(out.text, context_ids=ids, must_cite=set(case.must_cite),
                                 should_refuse=case.should_refuse,
                                 must_not_contain=case.must_not_contain)  # fmt: skip
        rec: dict[str, Any] = {"id": case.id, "answer": out.text, "checks": checks,
                               "passed": all(checks.values()), "cited": sorted(m.citations(out.text)),
                               "citation_precision": m.citation_precision(out.text, ids),
                               "refused": m.is_refusal(out.text), "should_refuse": case.should_refuse,
                               "latency_s": round(out.latency_s, 4), "usage": out.usage,
                               "tags": list(case.tags)}  # fmt: skip
        if case.must_cite:
            rec["citation_recall"] = len(set(case.must_cite) & m.citations(out.text)) / len(
                case.must_cite
            )
        if judge is not None:
            rec["judge"] = asdict(judge.grade(case, out.text))
        records.append(rec)

    def rate(rows: list[dict[str, Any]], key: str) -> float | None:
        return m.avg([1.0 if r[key] else 0.0 for r in rows])

    refusals = [r for r in records if r["should_refuse"]]
    answers = [r for r in records if not r["should_refuse"]]
    injections = [r for r in records if "injection" in r["tags"]]
    judged = [r["judge"] for r in records if "judge" in r]
    ok = [j for j in judged if j["error"] is None]
    summary = {
        "cases": len(records),
        "pass_rate": rate(records, "passed"),
        "refusal_accuracy": m.avg([1.0 if r["refused"] else 0.0 for r in refusals]),
        "false_refusal_rate": m.avg([1.0 if r["refused"] else 0.0 for r in answers]),
        "citation_recall": m.avg([r["citation_recall"] for r in answers if "citation_recall" in r]),
        "citation_precision": m.avg([r["citation_precision"] for r in records]),
        "injection_resisted": rate(injections, "passed"),
        "judge_correct": m.avg([1.0 if j["correct"] else 0.0 for j in ok]) if judge else None,
        "judge_faithful": m.avg([1.0 if j["faithful"] else 0.0 for j in ok]) if judge else None,
        "judge_errors": len(judged) - len(ok) if judge else None,
        "latency_p95_s": _p95([r["latency_s"] for r in records]),
    }
    extra = judge.describe() if judge else {}
    return RunResult("answer", _provenance(dataset, target.describe(), **extra), records, summary)


def write_run(root: Path, result: RunResult) -> Path:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    label = result.provenance["target"].get("prompt", result.provenance["target"]["target"])
    base = root / f"{stamp}-{result.suite}-{label.replace('@', '-v')}"
    out, n = base, 1
    while out.exists():  # two runs in the same second: never overwrite one
        n += 1
        out = base.with_name(f"{base.name}-{n}")
    out.mkdir(parents=True)
    (out / "results.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in result.records)
    )
    (out / "summary.json").write_text(json.dumps(
        {"suite": result.suite, "provenance": result.provenance, "summary": result.summary},
        indent=2) + "\n")  # fmt: skip
    return out


def read_summary(run_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((run_dir / "summary.json").read_text())
    return data
