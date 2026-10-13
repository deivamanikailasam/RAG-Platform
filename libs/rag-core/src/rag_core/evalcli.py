"""`rag` commands of the evaluation loop and of incremental ingestion (extension 04).

rag eval-compare dataset.yaml --a standard --b corrective [--suite answers|search] [--metric faithfulness …]
rag eval-compare --runs runs/a.answers.json runs/b.answers.json      A/B with a paired significance test
rag eval-sweep   dataset.yaml (--grid sweep.yaml | --set chunker.max_tokens=200,400 …) [--suite search]
                 [--rank-by ndcg] [--top 10]                          ablations: every combination, ranked
rag eval-generate (--from dataset.yaml | --source PATH…) --out generated.yaml [--per-document 3]
                 [--mode template|llm]                                synthetic Q/A/evidence, review: pending
rag eval-review  dataset.yaml [--approve ID …] [--reject ID …] [--check]
rag eval-candidates (--events audit.jsonl | --dsn-env V) [--texts texts.jsonl] (--out F | --append-to dataset.yaml)
                                                                      feedback -> candidate dataset items
rag eval-export  run.json --to ragas|deepeval|promptfoo|trulens|phoenix [--out F]
rag sync [--profile p] [--dry-run] [--enqueue] [--no-delete] [--max-items N] [--watch --interval 60]
                                                                      incremental ingestion from `connector`
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from rag_core.registry import ComponentError

COMMANDS = ("eval-compare", "eval-sweep", "eval-generate", "eval-review", "eval-candidates",
            "eval-export", "sync")  # fmt: skip


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")


def add_parsers(sub: Any) -> None:
    p = sub.add_parser(
        "eval-compare", help="A/B: two variants or runs, paired significance test (extension 04)"
    )
    p.add_argument("dataset", nargs="?")
    _common(p)
    p.add_argument("--a", help="a variant/architecture of the dataset, or profile:<name>")
    p.add_argument("--b", help="the same for B (the candidate)")
    p.add_argument("--suite", choices=["answers", "search"], default="answers")
    p.add_argument(
        "--runs", nargs=2, type=Path, metavar=("A", "B"), help="compare two run files instead"
    )
    p.add_argument(
        "--metric", action="append", default=[], help="only these metrics (default: all shared)"
    )
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--resamples", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--fail-if-worse",
        action="store_true",
        help="exit 1 if B is significantly worse on any metric",
    )
    p.add_argument("--include-unreviewed", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser(
        "eval-sweep", help="ablations: a grid of rag.yaml changes, every combination ranked"
    )
    p.add_argument("dataset")
    _common(p)
    p.add_argument("--grid", type=Path, help="a YAML file: grid: {key: [values]}, fixed: {...}")
    p.add_argument(
        "--set", action="append", default=[], metavar="KEY=V1,V2", help="a grid axis inline"
    )
    p.add_argument("--suite", choices=["search", "answers"], default="search")
    p.add_argument("--rank-by", help="default: ndcg (search), context_recall (answers)")
    p.add_argument("--top", type=int)
    p.add_argument("--max-combinations", type=int, default=64)
    p.add_argument("--include-unreviewed", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser(
        "eval-generate", help="synthetic question/answer/evidence triples from the corpus"
    )
    _common(p)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--from", dest="from_dataset", type=Path, help="use this dataset's corpus and person"
    )
    src.add_argument("--source", nargs="+", help="files or folders to generate from")
    p.add_argument(
        "--group", action="append", default=[], help="with --source: the reader's groups"
    )
    p.add_argument("--classification", default="internal")
    p.add_argument("--per-document", type=int, default=3)
    p.add_argument("--mode", choices=["template", "llm"], default="template")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser(
        "eval-review", help="approve or reject generated/proposed questions; --check for CI"
    )
    p.add_argument("dataset", type=Path)
    p.add_argument("--approve", nargs="+", default=[], metavar="ID")
    p.add_argument("--reject", nargs="+", default=[], metavar="ID")
    p.add_argument("--check", action="store_true", help="exit 1 while any question is pending")
    p = sub.add_parser(
        "eval-candidates", help="thumbs-down and flagged answers -> candidate dataset items"
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--events", type=Path, help="audit events exported as JSON lines")
    src.add_argument(
        "--dsn-env", help="the NAME of an environment variable holding the audit_reader DSN"
    )
    p.add_argument("--since-hours", type=float, default=24.0 * 7)
    p.add_argument(
        "--texts", type=Path, help='JSONL {"answer_id", "question", "answer"} (e.g. from Langfuse)'
    )
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument("--out", type=Path)
    dest.add_argument(
        "--append-to", type=Path, help="append to this dataset's questions (comments kept)"
    )
    p = sub.add_parser(
        "eval-export", help="a run file in Ragas/DeepEval/promptfoo/TruLens/Phoenix format"
    )
    p.add_argument("run", type=Path)
    p.add_argument(
        "--to", required=True, choices=["ragas", "deepeval", "promptfoo", "trulens", "phoenix"]
    )
    p.add_argument("--out", type=Path)
    p = sub.add_parser(
        "sync", help="incremental ingestion from the profile's connector (extension 04)"
    )
    _common(p)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--enqueue", action="store_true", help="put jobs on the queue for `rag worker`")
    p.add_argument("--no-delete", action="store_true", help="never delete what disappeared")
    p.add_argument("--max-items", type=int, help="change at most this many items per run")
    p.add_argument("--watch", action="store_true", help="repeat every --interval seconds")
    p.add_argument("--interval", type=float, default=60.0)
    p.add_argument("--json", action="store_true")


def run(a: argparse.Namespace) -> int:
    return {"eval-compare": _compare, "eval-sweep": _sweep, "eval-generate": _generate,
            "eval-review": _review, "eval-candidates": _candidates, "eval-export": _export,
            "sync": _sync}[a.cmd](a)  # fmt: skip


def _profile(a: argparse.Namespace) -> str:
    return a.profile or os.environ.get("RAG_PROFILE", "default")


def _dataset(path: Path, include_unreviewed: bool) -> dict[str, Any]:
    from rag_core import evaluate as ev

    doc, skipped = ev.reviewed_only(ev.load_dataset(path), include_unreviewed)
    if skipped:
        print(f"note: {skipped} question(s) awaiting review left out (--include-unreviewed to use them)",
              file=sys.stderr)  # fmt: skip
    return doc


def _evaluate(name: str, conf: dict[str, Any], doc: dict[str, Any], base: Path, suite: str) -> Any:
    from rag_core import evaluate as ev

    return (
        ev.run_answers(name, conf, doc, base)
        if suite == "answers"
        else ev.run_variant(name, conf, doc, base)
    )


def _side(name: str, a: argparse.Namespace, doc: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A name: `profile:<p>` (a whole profile), else a variant/architecture of the dataset."""
    from rag_core import config as cfg
    from rag_core import evaluate as ev

    if name.startswith("profile:"):
        prof = name.removeprefix("profile:")
        return name, cfg.resolve(cfg.read(a.file), prof)
    key = "architectures" if a.suite == "answers" else "variants"
    return name, ev.variant_configs(Path(a.file), _profile(a), doc, [name], key=key)[name]


def _compare(a: argparse.Namespace) -> int:
    from rag_core.evalkit import runs, stats

    if a.runs:
        run_a, run_b = runs.load_run(a.runs[0]), runs.load_run(a.runs[1])
        names = (f"{run_a['variant']} ({a.runs[0]})", f"{run_b['variant']} ({a.runs[1]})")
    else:
        if not (a.dataset and a.a and a.b):
            raise ComponentError("eval-compare: give a dataset with --a and --b, or --runs A B")
        path = Path(a.dataset)
        doc = _dataset(path, a.include_unreviewed)
        made = []
        for side in (a.a, a.b):
            label, conf = _side(side, a, doc)
            made.append(runs.make_run(_evaluate(label, conf, doc, path.parent, a.suite), suite=a.suite,
                                      profile=_profile(a), dataset=path))  # fmt: skip
        run_a, run_b = made
        names = (a.a, a.b)
    rows = stats.compare_runs(
        run_a, run_b, a.metric or None, alpha=a.alpha, resamples=a.resamples, seed=a.seed
    )
    if a.json:
        print(
            json.dumps({"a": names[0], "b": names[1], "comparisons": stats.as_json(rows)}, indent=2)
        )
    else:
        print(stats.format_comparison(rows, *names))
    worse = [r.metric for r in rows if r.verdict == "A better"]
    if a.fail_if_worse and worse:
        print(f"FAIL: B is significantly worse on {', '.join(worse)}", file=sys.stderr)
        return 1
    return 0


def _sweep(a: argparse.Namespace) -> int:
    from rag_core import evaluate as ev
    from rag_core.evalkit import sweep

    grid: dict[str, list[Any]] = {}
    fixed: dict[str, Any] = {}
    if a.grid:
        grid, fixed = sweep.load_grid(a.grid)
    grid |= sweep.parse_set(a.set)
    if not grid:
        raise ComponentError("eval-sweep: give --grid FILE or at least one --set KEY=V1,V2")
    combos = sweep.combinations(sweep.check_grid(grid))
    if len(combos) > a.max_combinations:
        raise ComponentError(
            f"{len(combos)} combinations > --max-combinations {a.max_combinations}"
        )
    path = Path(a.dataset)
    doc = _dataset(path, a.include_unreviewed)
    fixed_over = sweep.overrides(fixed)
    variants = {label: {**fixed_over, **over} for label, over in combos}
    configs = ev.variant_configs(
        Path(a.file), _profile(a), {**doc, "__sweep__": variants}, key="__sweep__"
    )
    rows = [
        _evaluate(label, conf, doc, path.parent, a.suite).row() for label, conf in configs.items()
    ]
    by = a.rank_by or ("ndcg" if a.suite == "search" else "context_recall")
    if rows and by not in rows[0]:
        raise ComponentError(
            f"--rank-by: unknown metric {by!r} (have: {', '.join(k for k in rows[0] if k != 'variant')})"
        )
    ranked = sweep.rank(rows, by)[: a.top or None]
    if a.json:
        print(json.dumps({"rank_by": by, "rows": ranked}, indent=2))
        return 0
    metrics = (["hit_rate", "recall", "precision", "mrr", "map", "ndcg", "leaks", "p50_ms"] if a.suite == "search"
               else ["context_recall", "answered", "abstain_ok", "faithfulness", "relevance",
                     "context_precision", "citation_precision", "leaks", "p50_ms"])  # fmt: skip
    print(
        f"{len(combos)} combinations, {len(doc['questions'])} questions, profile {_profile(a)!r}\n"
    )
    print(sweep.format_ranked(ranked, by, metrics))
    return 0


def _generate(a: argparse.Namespace) -> int:
    import yaml

    from rag_core import config as cfg
    from rag_core import evaluate as ev
    from rag_core.evalkit import synth
    from rag_core.ingest import load_source
    from rag_core.types import Access, Principal

    container = cfg.load(a.file, a.profile)

    sources = []
    if a.from_dataset:
        doc = ev.load_dataset(a.from_dataset)
        base = a.from_dataset.parent
        corpus, principal, k = doc.get("corpus", []), doc.get("principal", {}), int(doc.get("k", 5))
        for item in corpus:
            acc = item.get("access", {})
            access = Access(
                acc.get("classification", "internal"),
                tuple(acc.get("groups", ())),
                acc.get("tenant", "default"),
            )
            uri = (
                item["uri"] if "://" in item["uri"] else f"file://{(base / item['uri']).resolve()}"
            )
            # only what the dataset's person may read: questions about a forbidden document would
            # turn the access-control cases into "should answer" cases
            if access.allows(Principal(principal.get("subject", "eval"), tuple(principal.get("groups", ())),
                                          tuple(principal.get("classifications", ("public", "internal"))),
                                          principal.get("tenant", "default"))):  # fmt: skip
                sources.append(load_source(uri, access, item.get("metadata", {})))
        out_base = a.out.resolve().parent
        corpus = [{**item, "uri": os.path.relpath((base / item["uri"]).resolve(), out_base)}
                  if "://" not in item["uri"] else item for item in corpus]  # fmt: skip
    else:
        files: list[Path] = []
        for s in a.source:
            p = Path(s)
            files += (
                sorted(x for x in p.rglob("*") if x.is_file() and not x.name.startswith("."))
                if p.is_dir()
                else [p]
            )
        access = Access(a.classification, tuple(a.group))
        sources = [load_source(f.resolve().as_uri(), access) for f in files]
        out_base = a.out.resolve().parent
        corpus = [{"uri": os.path.relpath(f.resolve(), out_base),
                   "access": {"classification": a.classification, "groups": list(a.group)}} for f in files]  # fmt: skip
        principal = {
            "subject": "eval",
            "groups": list(a.group),
            "classifications": ["public", a.classification],
        }
        k = 5
    llm = container.get("llm") if a.mode == "llm" and container.has("llm") else None
    items = synth.generate(container, sources, per_document=a.per_document, mode=a.mode, llm=llm)
    out = synth.dataset(items, corpus=corpus, principal=principal, k=k, mode=a.mode)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("# Generated by `rag eval-generate`: every question needs a person's review before it is\n"
                     "# used (set review: approved or rejected, or `rag eval-review FILE --approve ID …`).\n"
                     + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=120))  # fmt: skip
    print(
        f"{len(items)} question(s) from {len(sources)} document(s) -> {a.out} (all review: pending)"
    )
    return 0


def _review(a: argparse.Namespace) -> int:
    from rag_core import evaluate as ev
    from rag_core.evalkit import synth

    for ids, status in ((a.approve, "approved"), (a.reject, "rejected")):
        if ids:
            n = synth.set_review(a.dataset, ids, status)
            print(f"{status}: {n} of {len(ids)}")
    doc = ev.load_dataset(a.dataset)
    counts = synth.review_status(doc)
    print(", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "no questions")
    for q in doc.get("questions") or []:
        if q.get("review") == "pending":
            print(f"  pending {q['id']:28} {q.get('question', '')[:90]}")
    if a.check and counts.get("pending"):
        print(f"FAIL: {counts['pending']} question(s) still pending review", file=sys.stderr)
        return 1
    return 0


def _candidates(a: argparse.Namespace) -> int:
    import yaml

    from rag_core import evaluate as ev
    from rag_core import online
    from rag_core.evalkit import feedback

    if a.events:
        events: Any = online.load_jsonl(a.events)
    else:  # pragma: no cover - needs the audit database
        dsn = os.environ.get(a.dsn_env, "")
        if not dsn:
            raise ComponentError(f"no DSN in ${a.dsn_env}")
        events = online.load_db(dsn, a.since_hours)
    skip: set[str] = set()
    if a.append_to:
        skip = feedback.existing_answer_ids(ev.load_dataset(a.append_to))
    items = feedback.candidates(events, feedback.load_texts(a.texts), skip)
    if a.append_to:
        n = feedback.append_to(a.append_to, items)
        print(f"{n} candidate(s) appended to {a.append_to} (review: pending)")
        return 0
    a.out.write_text(
        yaml.safe_dump(
            {"version": 1, "questions": items}, sort_keys=False, allow_unicode=True, width=120
        )
    )
    print(f"{len(items)} candidate(s) -> {a.out} (review: pending)")
    return 0


def _export(a: argparse.Namespace) -> int:
    from rag_core.evalkit import export, runs

    text = export.export(runs.load_run(a.run), a.to)
    if a.out:
        a.out.write_text(text)
        print(f"{a.run} -> {a.out} ({a.to})")
    else:
        sys.stdout.write(text)
    return 0


def _sync(a: argparse.Namespace) -> int:
    from dataclasses import asdict

    from rag_core import config as cfg
    from rag_core import sync

    container = cfg.load(a.file, a.profile)
    kw = {
        "dry_run": a.dry_run,
        "enqueue": a.enqueue,
        "delete_missing": not a.no_delete,
        "max_items": a.max_items,
    }

    def show(r: sync.SyncReport) -> None:
        if a.json:
            print(json.dumps(asdict(r)), flush=True)
            return
        print(r.line(), flush=True)
        for uri in r.ingested:
            print(f"  {'+' if not r.dry_run else '?'} {uri}")
        for uri in r.reacl:
            print(f"  ~ {uri}")
        for uri in r.deleted:
            print(f"  - {uri}")
        for uri, why in r.failed:
            print(f"  ! {uri}: {why}")

    if a.watch:  # pragma: no cover - loops forever; sync.watch is tested with rounds=
        sync.watch(container, a.interval, on_report=show, **kw)
        return 0
    report = sync.sync_once(container, **kw)
    show(report)
    return 1 if report.failed else 0


__all__ = ["COMMANDS", "add_parsers", "run"]
