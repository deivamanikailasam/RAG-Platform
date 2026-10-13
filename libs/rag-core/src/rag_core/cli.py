"""`rag` command line (Step 30).

rag components [--kind reranker] [--json]                 what can be switched, and to what
rag config check    [--file rag.yaml] [--profile dev]     build every component of a profile
rag config validate [--file rag.yaml] [--profile prod]    names and parameters only: no services
rag config show     [--file rag.yaml] [--profile dev]     the resolved profile (after extends + env)

Ingestion (Step 31):
rag ingest  [--profile p] [--group hr] [--classification internal] [--tenant t] [--force] URI…
rag delete  [--profile p] URI…                            remove sources from every store
rag enqueue [--profile p] [--group hr] [--delete] URI…    add jobs to the profile's queue
rag worker  [--profile p] [--forever]                     take jobs from the queue

Search (Step 32):
rag search "question" --group hr [--classification internal] [-k 5] [--json] [--ingest FILE…]
                                                          search as someone, with every score
rag eval-search dataset.yaml [--variant …] [--no-ingest] [--fail-under recall=0.9] [--json]
                                                          compare search variants on labelled questions

Answers (Step 33):
rag ask "question" ["follow-up" …] --group hr [--corpus dataset.yaml] [--stream] [--no-memory] [--json]
                                                          cited answers, as someone, as a conversation

Guardrails (Step 34):
rag eval-guards guards.yaml [--profile p] [--min-catch-rate 0.95] [--max-false-positive-rate 0.05] [--json]
                                                          attacks caught, ordinary questions spared, known gaps

Architectures (Step 35):
rag eval-answers dataset.yaml [--variant naive --variant standard …] [--no-ingest]
                 [--fail-under context_recall=0.95] [--json]
                                                          compare RAG architectures end to end
Switch the architecture with `pipeline: {use: corrective}` in rag.yaml or RAG__PIPELINE__USE=adaptive.

Data lifecycle (Step 36), every command a DRY RUN unless --apply (reacl acts at once):
rag retention --rules retention.yaml [--apply] [--json]   delete what has outlived its rule
rag erase-source URI… [--apply]                           every store, the manifest, every S3 version
rag erase-subject [--subject SUB] [--tenant t] [--identifier jane@…] [--apply]
                                                          conversations, cached answers, mentions listed
rag reacl URI --group hr --classification confidential [--tenant t]
                                                          new permissions in every store, now
rag reindex --profile local --to local-v2 [--apply]       rebuild from the originals into a new collection

A URI is file:///abs/path, s3://bucket/key, or a local path (turned into a file:// URI).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from rag_core import config as cfg
from rag_core.registry import ComponentError, Container, describe


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("components", help="list every component that can fill a slot")
    p.add_argument("--kind")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("config", help="check, validate or show a profile of rag.yaml")
    p.add_argument("action", choices=["check", "show", "validate"])
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
    for name in ("ingest", "delete", "enqueue", "worker"):
        p = sub.add_parser(name, help=f"{name} (Step 31 ingestion)")
        p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
        p.add_argument("--profile")
        if name != "worker":
            p.add_argument("uris", nargs="+")
        if name in ("ingest", "enqueue"):
            p.add_argument("--group", action="append", default=[])
            p.add_argument("--classification", default="internal")
            p.add_argument("--tenant", default="default")
        if name == "ingest":
            p.add_argument("--force", action="store_true")
        if name == "enqueue":
            p.add_argument("--delete", action="store_true")
        if name == "worker":
            p.add_argument("--forever", action="store_true")
    p = sub.add_parser("search", help="search as a given person and show why each chunk ranked")
    p.add_argument("question")
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
    p.add_argument("--group", action="append", default=[])
    p.add_argument("--classification", action="append", default=[])
    p.add_argument("--tenant", default="default")
    p.add_argument("-k", type=int, default=5)
    p.add_argument(
        "--ingest", nargs="*", default=[], help="ingest these files first (in-memory profiles)"
    )
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("ask", help="answer questions with citations, as a given person (Step 33)")
    p.add_argument("questions", nargs="+", help="later questions can be follow-ups of earlier ones")
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
    p.add_argument("--group", action="append", default=[])
    p.add_argument("--classification", action="append", default=[])
    p.add_argument("--tenant", default="default")
    p.add_argument(
        "--corpus", help="ingest this evaluation dataset's documents first (in-memory profiles)"
    )
    p.add_argument("--stream", action="store_true", help="print the answer as it is generated")
    p.add_argument("--no-memory", action="store_true", help="every question on its own")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("eval-search", help="compare search variants on a labelled dataset")
    p.add_argument("dataset")
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
    p.add_argument("--variant", action="append", default=[])
    p.add_argument("--no-ingest", action="store_true", help="the stores already hold the corpus")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--fail-under",
        action="append",
        default=[],
        metavar="METRIC=VALUE",
        help="exit 1 if a variant scores below, e.g. recall=0.8 (CI gate)",
    )
    p = sub.add_parser(
        "eval-answers", help="compare RAG architectures on a labelled dataset (Step 35)"
    )
    p.add_argument("dataset")
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
    p.add_argument("--variant", action="append", default=[], help="an entry of `architectures:`")
    p.add_argument("--no-ingest", action="store_true", help="the stores already hold the corpus")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--fail-under",
        action="append",
        default=[],
        metavar="METRIC=VALUE",
        help="exit 1 if an architecture scores below, e.g. context_recall=0.95 (CI gate)",
    )
    p = sub.add_parser(
        "eval-guards", help="measure the guards on attacks and ordinary cases (Step 34)"
    )
    p.add_argument("dataset")
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
    p.add_argument("--min-catch-rate", type=float, help="exit 1 below this share of attacks caught")
    p.add_argument(
        "--max-false-positive-rate",
        type=float,
        help="exit 1 above this share of benign cases stopped",
    )
    p.add_argument("--json", action="store_true")
    _lifecycle_parsers(sub)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "components":
            rows = [r for r in describe() if not a.kind or r["kind"] == a.kind]
            if a.json:
                print(json.dumps(rows, indent=2, default=str))
                return 0
            for r in rows:
                params = ", ".join(
                    f"{k}={v[1]!r}" if v[1] != "required" else f"{k}=<required>"
                    for k, v in r["params"].items()
                )
                extra = f"   [extra: {', '.join(r['requires'])}]" if r["requires"] else ""
                print(f"{r['kind']:18} {r['name']:22} {r['status']:9} {r['summary']}{extra}")
                if params:
                    print(f"{'':51} {params}")
            return 0
        if a.cmd == "eval-search":
            return _eval_search(a)
        if a.cmd == "eval-answers":
            return _eval_answers(a)
        container = cfg.load(a.file, a.profile)
        if a.cmd in LIFECYCLE:
            return _lifecycle(a, container)
        if a.cmd == "eval-guards":
            return _eval_guards(a, container)
        if a.cmd == "search":
            return _search(a, container)
        if a.cmd == "ask":
            return _ask(a, container)
        if a.cmd in ("ingest", "delete", "enqueue", "worker"):
            return _ingestion(a, container)
        if a.action == "validate":
            problems = container.validate()
            for prob in problems:
                print(f"ERROR: {prob}", file=sys.stderr)
            print(
                f"profile {container.profile!r}: {len(container.config)} slot(s), {len(problems)} problem(s)"
            )
            return 1 if problems else 0
        if a.action == "show":
            print(
                yaml.safe_dump(
                    {"profile": container.profile, **dict(container.config)}, sort_keys=False
                )
            )
            return 0
        built = container.build_all()
        for slot, obj in built.items():
            names = [type(o).__name__ for o in obj] if isinstance(obj, list) else type(obj).__name__
            print(f"ok   {slot:18} {names}")
        print(f"profile {container.profile!r}: {len(built)} slot(s) built")
        return 0
    except ComponentError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


LIFECYCLE = ("retention", "erase-source", "erase-subject", "reacl", "reindex")


def _lifecycle_parsers(sub: Any) -> None:
    """Step 36: the data lifecycle commands."""
    for name, help_ in (("retention", "delete sources that outlived their retention rule"),
                        ("erase-source", "forget sources everywhere, including every S3 object version"),
                        ("erase-subject", "a person's erasure request: conversations, cache, mentions"),
                        ("reacl", "change a source's access in every store at once"),
                        ("reindex", "rebuild the profile's collection into another profile's")):  # fmt: skip
        p = sub.add_parser(name, help=help_)
        p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
        p.add_argument("--profile")
        p.add_argument("--json", action="store_true")
        if name != "reacl":
            p.add_argument("--apply", action="store_true", help="act (the default is a dry run)")
        if name == "retention":
            p.add_argument(
                "--rules", required=True, help="a retention YAML (examples/retention.yaml)"
            )
        if name == "erase-source":
            p.add_argument("uris", nargs="+")
        if name == "erase-subject":
            p.add_argument("--subject", help="the person's token subject: their conversations go")
            p.add_argument("--tenant", default="default")
            p.add_argument("--identifier", "--email", action="append", default=[], dest="identifiers",
                           help="text that identifies them in documents (email, employee number)")  # fmt: skip
        if name == "reacl":
            p.add_argument("uri")
            p.add_argument("--group", action="append", default=[])
            p.add_argument("--classification", default="internal")
            p.add_argument("--tenant", default="default")
        if name == "reindex":
            p.add_argument(
                "--to", required=True, help="the profile with the new collection/embedder"
            )


def _lifecycle(a: argparse.Namespace, c: Container) -> int:
    from rag_core import lifecycle as lc
    from rag_core.ingest import IngestionPipeline
    from rag_core.types import Access, Classification, Principal

    if a.cmd == "retention":
        report = lc.apply_retention(
            IngestionPipeline(c), lc.load_retention(Path(a.rules)), apply=a.apply
        )
    elif a.cmd == "erase-source":
        pipe = IngestionPipeline(c)
        report = lc.LifecycleReport("erase-source", a.apply)
        for uri in (_uri(u) for u in a.uris):
            report.items += lc.erase_source(pipe, uri, apply=a.apply).items
    elif a.cmd == "erase-subject":
        if not a.subject and not a.identifiers:
            raise ComponentError("erase-subject needs --subject and/or --identifier")
        who = Principal(a.subject, (), ("public",), a.tenant) if a.subject else None
        report = lc.erase_subject(c, who, a.identifiers, apply=a.apply)
    elif a.cmd == "reacl":
        level: Classification = a.classification
        if level not in ("public", "internal", "confidential", "restricted"):
            raise ComponentError(f"unknown classification {level!r}")
        report = lc.change_access(
            IngestionPipeline(c), _uri(a.uri), Access(level, tuple(a.group), a.tenant)
        )
    else:
        report = lc.reindex(c, cfg.load(a.file, a.to), apply=a.apply)
    if a.json:
        print(json.dumps({"action": report.action, "applied": report.applied, "items": report.items},
                         indent=2, default=str))  # fmt: skip
    else:
        for item in report.items:
            print("   " + "   ".join(f"{k}={v}" for k, v in item.items()))
        print(report.summary())
    return 1 if any(i.get("status") == "failed" for i in report.items) else 0


def _uri(u: str) -> str:
    """`examples/corpus/a.md` -> `file:///…/examples/corpus/a.md`; URIs with a scheme pass as they are."""
    return u if "://" in u else Path(u).resolve().as_uri()


def _ingestion(a: argparse.Namespace, container: Container) -> int:
    from rag_core.components.queues import Job
    from rag_core.ingest import IngestionPipeline, Worker, load_source
    from rag_core.types import Access

    c = container
    uris = [_uri(u) for u in getattr(a, "uris", [])]
    if a.cmd == "enqueue":
        q = c.get("queue")
        access = {"classification": a.classification, "groups": a.group, "tenant": a.tenant}
        for uri in uris:
            print(q.put(Job("delete" if a.delete else "upsert", uri, access=access)), uri)
        return 0
    pipeline = IngestionPipeline(c, on_event=lambda e: None)
    if a.cmd == "worker":
        results = Worker(pipeline, c.get("queue")).run(forever=a.forever)
    elif a.cmd == "delete":
        results = [pipeline.delete(u) for u in uris]
    else:
        who = Access(a.classification, tuple(a.group), a.tenant)
        results = [pipeline.ingest(load_source(u, who), force=a.force) for u in uris]
    for r in results:
        extra = f"   pii: {', '.join(r.pii)}" if r.pii else ""
        print(
            f"{r.status:9} {r.chunks:4} chunks {r.seconds:6.2f}s   {r.uri}{'   ' + r.detail if r.detail else ''}{extra}"
        )
    return 1 if any(r.status == "failed" for r in results) else 0


def _search(a: argparse.Namespace, c: Container) -> int:
    from rag_core.ingest import IngestionPipeline, load_source
    from rag_core.search import SearchPipeline
    from rag_core.types import Access, Classification, Principal, Query

    classes: tuple[Classification, ...] = tuple(a.classification) or ("public", "internal")
    if a.ingest:
        pipe = IngestionPipeline(c)
        for path in a.ingest:
            pipe.ingest(load_source(f"file://{Path(path).resolve()}",
                                    Access("internal", tuple(a.group), a.tenant)))  # fmt: skip
    who = Principal("cli", tuple(a.group), classes, a.tenant)
    result = SearchPipeline(c).search(Query(a.question, who, k=a.k))
    if a.json:
        hits: list[dict[str, Any]] = [
            {"id": h.chunk.id, "document": h.chunk.document_uri, "score": h.score, "scores": dict(h.scores),
             "section": h.chunk.metadata.get("section", ""), "text": h.chunk.text} for h in result.hits]  # fmt: skip
        print(json.dumps({"trace": result.trace, "hits": hits}, indent=2, default=str))
        return 0
    print(f"searched: {result.texts}")
    print(f"pipeline: {result.trace['components']}")
    print(f"counts:   {result.trace['counts']}   ms: {result.trace['ms']}")
    for i, h in enumerate(result.hits, 1):
        parts = " ".join(f"{k}={v:.3f}" for k, v in h.scores.items())
        where = h.chunk.document_uri.rsplit("/", 1)[-1]
        section = h.chunk.metadata.get("section", "")
        print(f"{i}. {h.score:.4f}   {where}{' > ' + section if section else ''}   [{parts}]")
        print(f"     {h.chunk.text[:110].replace(chr(10), ' ')}")
    return 0


def _ask(a: argparse.Namespace, c: Container) -> int:
    from rag_core import evaluate as ev
    from rag_core.answer import AnswerPipeline, answer_dict
    from rag_core.types import Answer, Classification, Principal

    if a.corpus:  # the dataset's documents, with their real access rules
        dataset = Path(a.corpus)
        ev.ingest_corpus(c, ev.load_dataset(dataset), dataset.parent)
    classes: tuple[Classification, ...] = tuple(a.classification) or ("public", "internal")
    who = Principal("cli", tuple(a.group), classes, a.tenant)
    pipeline = AnswerPipeline(c)
    session = None if a.no_memory else "cli"  # one conversation: later questions can be follow-ups
    for question in a.questions:
        if a.stream and not a.json:
            print(f"Q: {question}\nA: ", end="", flush=True)
            done: Answer | None = None
            streamed = ""
            for event in pipeline.stream(question, who, session_id=session):
                if event.kind == "delta":
                    streamed += event.data
                    print(event.data, end="", flush=True)
                elif event.kind == "done":
                    done = event.data
            print()
            if done is None:  # pragma: no cover - the pipeline always ends with "done"
                return 1
            if done.blocked:  # an output guard stopped it after (live) streaming: Step 34
                print(f"   [blocked] {done.blocked}")
            elif done.text != streamed.strip():  # the citation check changed the draft
                print(f"   checked: {done.text}")
            _print_details(done, ms="-")
            continue
        answer = pipeline.answer(question, who, session_id=session)
        if a.json:
            print(json.dumps({"question": question, **answer_dict(answer),
                              "cache": answer.trace.get("cache"), "model": answer.trace.get("model"),
                              "prompt": answer.trace.get("prompt")}, indent=2))  # fmt: skip
            continue
        print(
            # the CLI shows the reason; rag-api shows people only the fixed message (Step 34)
            f"Q: {question}\nA: {answer.text if not answer.blocked else '[blocked] ' + answer.blocked}"
        )
        _print_details(answer, ms=str(answer.trace.get("ms", "-")))
        print()
    return 0


def _print_details(answer: Any, ms: str) -> None:
    for cit in answer.citations:
        name = cit.document_uri.rsplit("/", 1)[-1]
        print(f"     [doc {cit.marker}] {name:30} ({cit.title})")
    t = answer.trace
    chunks = len((t.get("context") or {}).get("chunks", []))
    print(f"     abstained={answer.abstained} cache={t.get('cache', '-')} model={t.get('model', '-')} "
          f"prompt={t.get('prompt', '-')} context={chunks} chunks ms={ms}")  # fmt: skip


def _eval_search(a: argparse.Namespace) -> int:
    from rag_core import evaluate as ev

    dataset = Path(a.dataset)
    doc = ev.load_dataset(dataset)
    profile = a.profile or os.environ.get("RAG_PROFILE", "default")
    rows = [ev.run_variant(name, conf, doc, dataset.parent, ingest=not a.no_ingest)
            for name, conf in ev.variant_configs(Path(a.file), profile, doc, a.variant).items()]  # fmt: skip
    k = int(doc.get("k", 5))
    if a.json:
        print(json.dumps([r.row() | {"per_case": r.per_case} for r in rows], indent=2))
    else:
        print(f"{len(doc['questions'])} questions, profile {profile!r}, k={k}\n")
        print(ev.format_table(rows, k))
    failed = []
    for rule in a.fail_under:
        metric, _, value = rule.partition("=")
        for r in rows:
            if metric not in r.row():
                raise ComponentError(f"--fail-under: unknown metric {metric!r} (recall, mrr, ndcg)")
            if r.row()[metric] < float(value):
                failed.append(f"{r.variant}: {metric} {r.row()[metric]} < {value}")
    if any(r.leaks for r in rows):
        failed += [
            f"{r.variant}: {r.leaks} forbidden document(s) returned" for r in rows if r.leaks
        ]
    for f in failed:
        print(f"FAIL: {f}", file=sys.stderr)
    return 1 if failed else 0


def _eval_answers(a: argparse.Namespace) -> int:
    from rag_core import evaluate as ev

    dataset = Path(a.dataset)
    doc = ev.load_dataset(dataset)
    profile = a.profile or os.environ.get("RAG_PROFILE", "default")
    configs = ev.variant_configs(Path(a.file), profile, doc, a.variant, key="architectures")
    rows = [ev.run_answers(name, conf, doc, dataset.parent, ingest=not a.no_ingest)
            for name, conf in configs.items()]  # fmt: skip
    if a.json:
        print(json.dumps([r.row() | {"per_case": r.per_case} for r in rows], indent=2))
    else:
        print(f"{len(doc['questions'])} questions, profile {profile!r}\n")
        print(ev.format_answer_table(rows))
    failed = []
    for rule in a.fail_under:
        metric, _, value = rule.partition("=")
        for r in rows:
            if metric not in r.row() or metric in ("variant", "leaks", "p50_ms"):
                raise ComponentError(
                    f"--fail-under: unknown metric {metric!r} "
                    "(context_recall, answered, cite_hit, abstain_ok, grounded)"
                )
            if r.row()[metric] < float(value):
                failed.append(f"{r.variant}: {metric} {r.row()[metric]} < {value}")
    failed += [f"{r.variant}: {r.leaks} forbidden document(s) cited" for r in rows if r.leaks]
    for f in failed:
        print(f"FAIL: {f}", file=sys.stderr)
    return 1 if failed else 0


def _eval_guards(a: argparse.Namespace, c: Container) -> int:
    from rag_core import evaluate as ev

    s = ev.eval_guards(c, ev.load_dataset(Path(a.dataset)))
    print(json.dumps(s.row(), indent=2) if a.json else ev.format_guard_scores(s))
    failed = []
    if a.min_catch_rate is not None and s.catch_rate < a.min_catch_rate:
        failed.append(f"catch rate {s.catch_rate} < {a.min_catch_rate}")
    if a.max_false_positive_rate is not None and s.false_positive_rate > a.max_false_positive_rate:
        failed.append(f"false positive rate {s.false_positive_rate} > {a.max_false_positive_rate}")
    for f in failed:
        print(f"FAIL: {f}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
