"""Run files (extension 04): one JSON file per evaluated variant, everything needed afterwards.

    rag eval-answers examples/eval/handbook.yaml --profile offline --variant standard --out runs/
    -> runs/standard.answers.json

    {"format": "rag-core-run/1", "suite": "answers", "variant": "standard", "profile": "offline",
     "dataset": "examples/eval/handbook.yaml", "dataset_sha256": "…", "judge": "lexical",
     "created_at": "…", "summary": {…the table row…},
     "cases": [{"id", "question", "reference", "relevant", "answer", "cited", "contexts": [{"document", "text"}],
                "metrics": {"faithfulness": 1.0, …}, "ms"}, …]}

A/B tests (`rag eval-compare --runs a.json b.json`) pair cases by id; exporters
(`rag eval-export`) turn the cases into other tools' formats. Run files hold question, answer and
document text: they are evaluation artefacts of a labelled dataset, not production data, but
keep them where the dataset itself may be kept.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from rag_core.registry import ComponentError

FORMAT = "rag-core-run/1"


def make_run(scores: Any, *, suite: str, profile: str, dataset: Path) -> dict[str, Any]:
    """A run from a Scores (search) or AnswerScores (answers) result."""
    if suite == "answers":
        cases = list(scores.records)
        judge = scores.judge
    else:
        cases = [{"id": cid, "ranked": e.get("docs", []), "leaks": e.get("leaks", []),
                  "metrics": {k: e[k] for k in ("hit_rate", "recall", "precision", "rr", "ap", "ndcg") if k in e}}
                 for cid, e in scores.per_case.items()]  # fmt: skip
        judge = None
    try:
        sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
    except OSError:
        sha = None
    return {"format": FORMAT, "suite": suite, "variant": scores.variant, "profile": profile,
            "dataset": str(dataset), "dataset_sha256": sha, "judge": judge,
            "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "summary": scores.row(), "cases": cases}  # fmt: skip


def write_runs(out: Path, runs: list[dict[str, Any]]) -> list[Path]:
    """`out` is a folder (one file per variant) or, for a single run, a .json file."""
    if out.suffix == ".json" and len(runs) == 1:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(runs[0], indent=2, ensure_ascii=False))
        return [out]
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for r in runs:
        safe = "".join(ch if ch.isalnum() or ch in "-_.+" else "_" for ch in r["variant"])
        path = out / f"{safe}.{r['suite']}.json"
        path.write_text(json.dumps(r, indent=2, ensure_ascii=False))
        paths.append(path)
    return paths


def load_run(path: Path) -> dict[str, Any]:
    try:
        run = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ComponentError(f"{path}: not a readable run file: {e}") from None
    if not isinstance(run, dict) or run.get("format") != FORMAT:
        raise ComponentError(f"{path}: expected a run file with format {FORMAT!r}")
    return run


def case_scores(run: dict[str, Any], metric: str) -> dict[str, float]:
    """Case id -> one metric (cases where it was measured)."""
    out = {}
    for c in run["cases"]:
        v = c.get("metrics", {}).get(metric)
        if isinstance(v, int | float) and not isinstance(v, bool):
            out[str(c["id"])] = float(v)
    return out


def metrics_in(run: dict[str, Any]) -> list[str]:
    seen: dict[str, None] = {}
    for c in run["cases"]:
        for k, v in c.get("metrics", {}).items():
            if isinstance(v, int | float) and not isinstance(v, bool):
                seen.setdefault(k)
    return list(seen)


__all__ = ["FORMAT", "case_scores", "load_run", "make_run", "metrics_in", "write_runs"]
