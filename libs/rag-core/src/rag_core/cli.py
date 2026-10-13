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

A URI is file:///abs/path, s3://bucket/key, or a local path (turned into a file:// URI).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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
        container = cfg.load(a.file, a.profile)
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


if __name__ == "__main__":
    sys.exit(main())
