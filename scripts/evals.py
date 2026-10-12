#!/usr/bin/env python3
"""The evaluation harness's command line (Step 26).

just evals run retrieval                                  as each persona, through the real policy
just evals run answer --prompt rag-answer --label staging [--judge]
just evals gate <run>                                     thresholds + no regression vs baseline
just evals compare <run-a> <run-b>                        what changed, metric by metric and case by case
just evals baseline <run>                                 make this run the new reference (commit it)
just evals record <run> --card model:embedder             write the results into the model card
just evals release <dataset>                              freeze a new dataset version (hash)

Runs are written to evals/runs/ (not committed): results.jsonl (every case) + summary.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"


def _registry() -> Any:
    from rag_common.prompts import Registry

    return Registry.load(ROOT / "prompts")


def _gateway() -> Any:
    from openai import OpenAI

    return OpenAI(base_url=os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000") + "/v1",
                  api_key=os.environ["EVAL_GATEWAY_KEY"], timeout=600, max_retries=1)  # fmt: skip


def cmd_run(a: argparse.Namespace) -> int:
    from rag_evals.datasets import load_dataset
    from rag_evals.runner import run_answers, run_retrieval, write_run

    if a.suite == "retrieval":
        from pydantic import SecretStr

        from rag_api.policy import OpaClient
        from rag_api.search import PgSearch
        from rag_api.settings import Settings
        from rag_evals.targets import PolicySearchTarget

        dataset = load_dataset(EVALS / "datasets", a.dataset or "retrieval-golden", a.version)
        s = Settings(  # only what search needs; the evaluator reads with the read-only role
            oidc_issuer="unused", oidc_jwks_url="unused", audit_db_password=SecretStr("unused"),
            gateway_url=os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000") + "/v1",
            gateway_key=SecretStr(os.environ["EVAL_GATEWAY_KEY"]), db_host="127.0.0.1",
            db_user="rag_readonly", db_password=SecretStr(os.environ["RAG_DB_READONLY_PASSWORD"]),
            opa_token=SecretStr(os.environ["OPA_API_TOKEN"]), prompts_dir=ROOT / "prompts",
            prompt_label=a.label or "production",
        )  # fmt: skip
        registry = _registry()
        qi, _ = registry.get("query-instruction", label=s.prompt_label)
        target = PolicySearchTarget(
            PgSearch(s, registry), OpaClient(os.environ.get("OPA_URL", "http://127.0.0.1:8181"),
                                             s.opa_token.get_secret_value()),
            {"query_instruction": qi.ref, "embedder": "embedder", "policy": "rag.authz"},
        )  # fmt: skip
        result = run_retrieval(dataset, target, k=a.k)
    else:
        from rag_evals.judge import Judge
        from rag_evals.targets import GatewayAnswerTarget

        dataset = load_dataset(EVALS / "datasets", a.dataset or "rag-answer-golden", a.version)
        client, registry = _gateway(), _registry()
        answer_target = GatewayAnswerTarget(client, registry, a.prompt, label=a.label,
                                            version=a.prompt_version)  # fmt: skip
        judge = Judge(client, registry) if a.judge else None
        result = run_answers(dataset, answer_target, judge)
    out = write_run(EVALS / "runs", result)
    print(f"run written to {out.relative_to(ROOT)}")
    _print_summary(result.summary)
    return 0


def _print_summary(summary: dict[str, Any]) -> None:
    for k, v in summary.items():
        print(f"  {k:22} {v}")


def _baseline_path(run: dict[str, Any]) -> Path:
    target = run["provenance"]["target"]
    name = (
        run["suite"] if run["suite"] == "retrieval" else f"answer-{target['prompt'].split('@')[0]}"
    )
    return EVALS / "baselines" / f"{name}.json"


def cmd_gate(a: argparse.Namespace) -> int:
    from rag_evals.gates import check, load_gates
    from rag_evals.runner import read_summary

    run = read_summary(a.run)
    extra: dict[str, float] = {}
    prompt_ref = run["provenance"]["target"].get("prompt")
    if prompt_ref:  # the prompt's own bar (Step 24: evaluation.min_score) applies too
        name, version = prompt_ref.split("@")
        p, _ = _registry().get(name, version=int(version))
        if p.evaluation is not None:
            extra["pass_rate"] = p.evaluation.min_score
    base_path = a.baseline or _baseline_path(run)
    baseline = json.loads(base_path.read_text())["summary"] if base_path.exists() else None
    failures = check(run["summary"], run["suite"], load_gates(EVALS / "gates.yaml"),
                     baseline=baseline, extra_min=extra)  # fmt: skip
    print(f"{run['suite']} run of {run['provenance']['dataset']}"
          f" against {prompt_ref or run['provenance']['target']['target']}"
          f" (baseline: {base_path.name if baseline else 'none yet'})")  # fmt: skip
    for f in failures:
        print(f"  FAIL  {f}")
    print("GATE PASSED" if not failures else f"GATE FAILED ({len(failures)})")
    return 0 if not failures else 1


def cmd_compare(a: argparse.Namespace) -> int:
    from rag_evals.runner import read_summary

    ra, rb = read_summary(a.a), read_summary(a.b)

    def label(r: dict[str, Any]) -> str:
        return str(r["provenance"]["target"].get("prompt", r["provenance"]["target"]["target"]))

    print(f"{'metric':22} {label(ra):>16} {label(rb):>16}")
    for k in ra["summary"]:
        print(f"{k:22} {ra['summary'][k]!s:>16} {rb['summary'].get(k)!s:>16}")
    key = "passed" if ra["suite"] == "answer" else "leaked"
    rows_a = {r["id"]: r for r in map(json.loads, (a.a / "results.jsonl").read_text().splitlines())}
    rows_b = {r["id"]: r for r in map(json.loads, (a.b / "results.jsonl").read_text().splitlines())}
    changed = [i for i in rows_a if i in rows_b and rows_a[i].get(key) != rows_b[i].get(key)]
    print(f"cases whose '{key}' changed: {', '.join(changed) or 'none'}")
    return 0


def cmd_baseline(a: argparse.Namespace) -> int:
    from rag_evals.runner import read_summary

    run = read_summary(a.run)
    path = _baseline_path(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(a.run / "summary.json", path)
    print(f"baseline {path.relative_to(ROOT)} <- {a.run.name} (commit it, with the reason)")
    return 0


def cmd_record(a: argparse.Namespace) -> int:
    from rag_evals.record import record_results
    from rag_evals.runner import read_summary

    run = read_summary(a.run)
    s = run["summary"]
    wanted = (["recall@5", "mrr", "ndcg@5"] if run["suite"] == "retrieval"
              else ["pass_rate", "citation_recall", "judge_correct"])  # fmt: skip
    results = {k: s[k] for k in wanted if s.get(k) is not None}
    kind, name = a.card.split(":")
    card = ROOT / "cards" / f"{kind}s" / f"{name}.yaml"
    record_results(card, results, run["provenance"]["dataset"], dt.date.today())
    print(
        f"recorded {sorted(results)} from {run['provenance']['dataset']} in {card.relative_to(ROOT)}"
    )
    print("then: just cards docs && just cards lint")
    return 0


def cmd_release(a: argparse.Namespace) -> int:
    from rag_evals.datasets import release

    added = release(EVALS / "datasets", a.name)
    print(f"{a.name}: released {['v' + str(n) for n in added] or 'nothing new'}")
    return 0


def main(argv: list[str]) -> int:
    from rag_common.prompts import PromptError
    from rag_evals.datasets import EvalError

    ap = argparse.ArgumentParser(prog="evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("suite", choices=["retrieval", "answer"])
    p.add_argument("--dataset")
    p.add_argument("--version", type=int, help="dataset version (default: latest)")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--prompt", default="rag-answer")
    p.add_argument("--label")
    p.add_argument("--prompt-version", type=int)
    p.add_argument("--judge", action="store_true")
    p = sub.add_parser("gate")
    p.add_argument("run", type=Path)
    p.add_argument("--baseline", type=Path)
    p = sub.add_parser("compare")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    sub.add_parser("baseline").add_argument("run", type=Path)
    p = sub.add_parser("record")
    p.add_argument("run", type=Path)
    p.add_argument("--card", required=True)
    sub.add_parser("release").add_argument("name")
    a = ap.parse_args(argv)
    commands = {"run": cmd_run, "gate": cmd_gate, "compare": cmd_compare,
                "baseline": cmd_baseline, "record": cmd_record, "release": cmd_release}  # fmt: skip
    try:
        return commands[a.cmd](a)
    except (EvalError, PromptError, KeyError, FileNotFoundError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
