"""`rag` command line (Step 30).

rag components [--kind reranker] [--json]                 what can be switched, and to what
rag config check    [--file rag.yaml] [--profile dev]     build every component of a profile
rag config validate [--file rag.yaml] [--profile prod]    names and parameters only: no services
rag config show     [--file rag.yaml] [--profile dev]     the resolved profile (after extends + env)
rag config readiness [--file rag.yaml] [--profile production]
                                                          fit for production? (Step 37; exit 1 on errors)

Ingestion (Step 31):
rag ingest  [--profile p] [--group hr] [--classification internal] [--tenant t] [--force] URI…
rag delete  [--profile p] URI…                            remove sources from every store
rag enqueue [--profile p] [--group hr] [--delete] URI…    add jobs to the profile's queue
rag worker  [--profile p] [--forever]                     take jobs from the queue

Search (Step 32):
rag search "question" --group hr [--classification internal] [-k 5] [--json] [--ingest FILE…]
           [--filter 'department=hr' --filter 'updated>=2025-01-01' | --filter '{"or": [...]}']
                                                          search as someone, with every score
rag index ddl [--profile p]                               the CREATE INDEX for the vector store's metric
rag eval-search dataset.yaml [--variant …] [--no-ingest] [--fail-under recall=0.9] [--json]
                                                          compare search variants on labelled questions

Answers (Step 33):
rag ask "question" ["follow-up" …] --group hr [--corpus dataset.yaml] [--stream] [--no-memory] [--json] [--filter …]
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

Production (Step 37):
rag online-eval (--events audit.jsonl | --dsn-file F | --dsn-env V) [--since-hours 24]
                [--candidate R --baseline R] [--group-by release] [--limit error_rate=0.02]
                [--on-insufficient wait|pass|fail] [--queue review.jsonl] [--json verdict.json]
                                                          answer quality per release from the audit log
                                                          exit 0 pass, 1 fail, 3 not enough data yet

Agents (extension 03):
rag mcp --subject ann --group all-staff [--classification internal] [--corpus dataset.yaml]
        | --token-file F --oidc-issuer URL --oidc-audience A --oidc-jwks-url URL
                                                          search and answer as MCP tools over stdio

Reuse (Step 38):
rag doctor [PATH] [--json]                                does a project meet the platform's standards?
                                                          (docs/standards/rag-standards.md; exit 1 on a MUST)

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

FILTER_HELP = ("a metadata filter: key=value, key!=value, key=a,b (any of), key>=2025-01-01 (also >, <, <=), "
               "key? (has a value), or a JSON/YAML expression; repeat to AND them")  # fmt: skip
_CONDITION = __import__("re").compile(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*(!=|>=|<=|=|>|<|\?)\s*(.*)$")


def _typed(raw: str) -> Any:
    """A --filter value as YAML reads it (4.2, 2025, true, 2025-01-01), dates as ISO strings."""
    v = yaml.safe_load(raw) if raw else ""
    return v.isoformat() if hasattr(v, "isoformat") else v


def _same_value(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def parse_filters(items: list[str]) -> dict[str, Any]:
    """`--filter` values as one filter expression (rag_core.filters): ANDed, validated."""
    from rag_core import filters

    parts: list[dict[str, Any]] = []
    for raw in items:
        raw = raw.strip()
        if raw.startswith("{"):
            data = yaml.safe_load(raw)
            if not isinstance(data, dict):
                raise filters.FilterError(f"--filter {raw!r}: expected a mapping")
            parts.append(data)
            continue
        m = _CONDITION.match(raw)
        if not m:
            raise filters.FilterError(
                f"--filter {raw!r}: expected key=value, key>=value, … or a JSON expression"
            )
        key, op, text = m.groups()
        if op == "?":
            parts.append({key: {"exists": True}})
            continue
        raws = [v.strip() for v in text.split(",")]
        values = [_typed(v) for v in raws]
        if op in ("=", "!="):
            # extension 03: `section_numbers=4.2` must match the STRING "4.2" (YAML reads a
            # number), and `year=2025` the number 2025: equality matches the text as typed AND
            # its number/boolean reading, so it works whatever type the metadata field holds
            values = []
            for raw in raws:
                for v in (raw, _typed(raw)):
                    if v is not None and not any(_same_value(v, w) for w in values):
                        values.append(v)
        if op in ("=", "!=") and len(values) > 1:
            parts.append({key: {"in" if op == "=" else "nin": values}})
        else:
            parts.append(
                {
                    key: {
                        {"=": "eq", "!=": "ne", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[
                            op
                        ]: values[0]
                    }
                }
            )
    return filters.combine(*parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("components", help="list every component that can fill a slot")
    p.add_argument("--kind")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("config", help="check, validate or show a profile of rag.yaml")
    p.add_argument("action", choices=["check", "show", "validate", "readiness"])
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
    p.add_argument("--filter", action="append", default=[], help=FILTER_HELP)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("index", help="vector index statements for a profile (extension 01)")
    p.add_argument("action", choices=["ddl"])
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
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
    p.add_argument("--filter", action="append", default=[], help=FILTER_HELP)
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
    _online_parser(sub)
    p = sub.add_parser("mcp", help="serve search and answer as MCP tools over stdio (extension 03)")
    p.add_argument("--file", default=os.environ.get("RAG_CONFIG", "rag.yaml"))
    p.add_argument("--profile")
    p.add_argument("--subject", help="who is asking (required unless --token-file)")
    p.add_argument("--group", action="append", default=[])
    p.add_argument("--classification", action="append", default=[])
    p.add_argument("--tenant", default="default")
    p.add_argument("--token-file", help="an OIDC access token, verified on every call")
    p.add_argument("--oidc-issuer")
    p.add_argument("--oidc-audience")
    p.add_argument("--oidc-jwks-url")
    p.add_argument(
        "--corpus", help="ingest this evaluation dataset's documents first (in-memory profiles)"
    )
    p = sub.add_parser("doctor", help="check a project against the platform standards (Step 38)")
    p.add_argument("path", nargs="?", default=".", help="the project folder (default: here)")
    p.add_argument("--json", action="store_true")
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
        if a.cmd == "online-eval":
            return _online_eval(a)
        if a.cmd == "doctor":
            return _doctor(a)
        container = cfg.load(a.file, a.profile)
        if a.cmd in LIFECYCLE:
            return _lifecycle(a, container)
        if a.cmd == "eval-guards":
            return _eval_guards(a, container)
        if a.cmd == "search":
            return _search(a, container)
        if a.cmd == "mcp":
            return _mcp(a, container)
        if a.cmd == "index":
            return _index(container)
        if a.cmd == "ask":
            return _ask(a, container)
        if a.cmd in ("ingest", "delete", "enqueue", "worker"):
            return _ingestion(a, container)
        if a.action == "readiness":
            return _readiness(container)
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
    except ValueError as e:  # a bad --filter (FilterError), with what is wrong and where
        if type(e).__name__ != "FilterError":
            raise
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


def _mcp(a: argparse.Namespace, c: Container) -> int:
    """Extension 03: the platform as MCP tools, for agents. Refuses to start without an identity."""
    from rag_core import mcp

    try:
        identity = mcp.identity_from(a)
    except mcp.IdentityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if a.corpus:
        from rag_core import evaluate as ev

        ev.ingest_corpus(c, ev.load_dataset(Path(a.corpus)), Path(a.corpus).parent)
    print(f"rag mcp: profile {c.profile!r}, serving search and answer on stdio", file=sys.stderr)
    mcp.McpServer(mcp.RagTools(c, identity)).serve(sys.stdin, sys.stdout)
    return 0


def _readiness(container: Container) -> int:
    """Step 37: fit for production, not just buildable. Errors fail; warnings are for a person."""
    from rag_core import readiness

    findings = readiness.check(container.config)
    for f in findings:
        print(f)
    errors = sum(f.level == "error" for f in findings)
    print(f"profile {container.profile!r}: {errors} error(s), {len(findings) - errors} warning(s)")
    return 1 if errors else 0


def _doctor(a: argparse.Namespace) -> int:
    """Step 38: the automatable standards. Reads files only; MUST failures exit 1."""
    from rag_core import doctor

    root = Path(a.path)
    if not root.is_dir():
        raise ComponentError(f"{root} is not a folder")
    results = doctor.run(root)
    if a.json:
        print(json.dumps(doctor.as_dicts(results), indent=2))
    else:
        for r in results:
            print(r)
        print(f"\n{doctor.summary(results)}")
    return 1 if any(not r.ok and r.level == "MUST" for r in results) else 0


def _online_parser(sub: Any) -> None:
    """Step 37: answer quality per release, from the audit log and feedback."""
    p = sub.add_parser(
        "online-eval", help="answer quality per release from the audit log (Step 37)"
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--events", type=Path, help="audit events exported as JSON lines")
    src.add_argument(
        "--dsn-file", type=Path, help="a file holding the audit_reader DSN (OpenBao Agent)"
    )
    src.add_argument("--dsn-env", help="the NAME of an environment variable holding the DSN")
    p.add_argument("--since-hours", type=float, default=24.0)
    p.add_argument("--group-by", default="release", choices=["release", "prompt", "model", "all"])
    p.add_argument("--candidate", help="the group under test (the canary's release)")
    p.add_argument("--baseline", help="the group to compare with (the stable release)")
    p.add_argument("--margin", type=float, default=0.02, help="ignore differences up to this")
    p.add_argument("--z", type=float, default=1.645, help="one-sided z threshold (1.645 = 95%%)")
    p.add_argument("--min-n", type=int, default=50, help="fewer events than this: insufficient")
    p.add_argument("--limit", action="append", default=[], metavar="METRIC=VALUE",
                   help="an absolute ceiling, e.g. error_rate=0.02")  # fmt: skip
    p.add_argument("--on-insufficient", default="wait", choices=["wait", "pass", "fail"],
                   help="too few answers: exit 3 (wait), 0 (pass) or 1 (fail)")  # fmt: skip
    p.add_argument("--queue", type=Path, help="write the answers to review here (JSON lines)")
    p.add_argument("--json", type=Path, help="write the verdict here")


def _online_eval(a: argparse.Namespace) -> int:
    from rag_core import online

    if a.events:
        events: Any = online.load_jsonl(a.events)
    else:  # pragma: no cover - needs the audit database
        dsn = a.dsn_file.read_text().strip() if a.dsn_file else os.environ.get(a.dsn_env, "")
        if not dsn:
            raise ComponentError(f"no DSN in {a.dsn_file or '$' + a.dsn_env}")
        events = online.load_db(dsn, a.since_hours)
    groups, queue = online.collect(events, a.group_by)
    print(online.format_report(groups) + "\n")
    if a.queue:
        a.queue.write_text("".join(json.dumps(q) + "\n" for q in queue))
        print(f"{len(queue)} answer(s) to review -> {a.queue}\n")
    if not (a.candidate and a.baseline):
        return 0
    limits = {}
    for rule in a.limit:
        metric, _, value = rule.partition("=")
        if metric not in online.WORSE_IF_HIGHER or not value:
            raise ComponentError(
                f"--limit {rule!r}: use METRIC=VALUE with one of {online.WORSE_IF_HIGHER}"
            )
        limits[metric] = float(value)
    empty = online.Stats()
    verdict = online.compare(groups.get(a.candidate, empty), groups.get(a.baseline, empty),
                             names=(a.candidate, a.baseline), margin=a.margin, z=a.z, min_n=a.min_n,
                             limits=limits)  # fmt: skip
    print(f"{a.candidate} vs {a.baseline}: {verdict.status.upper()}")
    for ch in verdict.checks:
        print(f"   {ch.status:12} {ch.metric:18} {ch.detail}")
    if a.json:
        a.json.write_text(verdict.to_json() + "\n")
    if verdict.status == "insufficient":
        return {"wait": 3, "pass": 0, "fail": 1}[a.on_insufficient]
    return 1 if verdict.status == "fail" else 0


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
            # Step 37: legal holds live in the retention file; erasing a held source needs a reason
            p.add_argument("--rules", help="the retention YAML whose legal_holds apply")
            p.add_argument("--override-hold", default="", metavar="REASON",
                           help="erase despite a legal hold (legal's decision, recorded)")  # fmt: skip
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
        policy = lc.load_retention(Path(a.rules)) if a.rules else None
        for uri in (_uri(u) for u in a.uris):
            report.items += lc.erase_source(pipe, uri, apply=a.apply, policy=policy,
                                            override_hold=a.override_hold).items  # fmt: skip
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
        print(json.dumps({"action": report.action, "applied": report.applied, "items": report.items,
                          "held": report.held}, indent=2, default=str))  # fmt: skip
    else:
        for item in report.items:
            print("   " + "   ".join(f"{k}={v}" for k, v in item.items()))
        for item in report.held:  # reported, never hidden: a hold is a decision someone owns
            print("   HELD " + "   ".join(f"{k}={v}" for k, v in item.items()))
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
    result = SearchPipeline(c).search(Query(a.question, who, parse_filters(a.filter), k=a.k))
    if a.json:
        hits: list[dict[str, Any]] = [
            {"id": h.chunk.id, "document": h.chunk.document_uri, "score": h.score, "scores": dict(h.scores),
             "section": h.chunk.metadata.get("section", ""), "text": h.chunk.text} for h in result.hits]  # fmt: skip
        print(json.dumps({"trace": result.trace, "hits": hits}, indent=2, default=str))
        return 0
    print(f"searched: {result.texts}")
    if result.trace.get("filters") or a.filter:
        print(f"filters:  {result.trace.get('filters') or parse_filters(a.filter)}")
    if result.trace.get("retriever"):
        print(f"routing:  {result.trace['retriever']}")
    print(f"pipeline: {result.trace['components']}")
    print(f"counts:   {result.trace['counts']}   ms: {result.trace['ms']}")
    for i, h in enumerate(result.hits, 1):
        parts = " ".join(f"{k}={v:.3f}" for k, v in h.scores.items())
        where = h.chunk.document_uri.rsplit("/", 1)[-1]
        section = h.chunk.metadata.get("section", "")
        print(f"{i}. {h.score:.4f}   {where}{' > ' + section if section else ''}   [{parts}]")
        print(f"     {h.chunk.text[:110].replace(chr(10), ' ')}")
    return 0


def _index(c: Container) -> int:
    """Extension 01: the CREATE INDEX a profile's vector store needs (for a project migration)."""
    store = c.get("vector_store")
    ddl = store.index_ddl() if hasattr(store, "index_ddl") else None
    if hasattr(store, "collection_config"):  # Qdrant: the collection body
        print(json.dumps(store.collection_config(), indent=2))
    elif hasattr(store, "mapping"):  # OpenSearch: the index body
        print(json.dumps(store.mapping(), indent=2))
    elif ddl:
        print(ddl + ";")
    else:
        print(
            f"-- {type(store).__name__}: no index to create (exact search, or created by the store)"
        )
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
    wanted = parse_filters(a.filter)
    session = None if a.no_memory else "cli"  # one conversation: later questions can be follow-ups
    for question in a.questions:
        if a.stream and not a.json:
            print(f"Q: {question}\nA: ", end="", flush=True)
            done: Answer | None = None
            streamed = ""
            for event in pipeline.stream(question, who, session_id=session, filters=wanted):
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
        answer = pipeline.answer(question, who, session_id=session, filters=wanted)
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
