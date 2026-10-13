"""`rag` command line (Step 30).

rag components [--kind reranker] [--json]                 what can be switched, and to what
rag config check    [--file rag.yaml] [--profile dev]     build every component of a profile
rag config validate [--file rag.yaml] [--profile prod]    names and parameters only: no services
rag config show     [--file rag.yaml] [--profile dev]     the resolved profile (after extends + env)

Step 31 adds the ingestion commands (ingest, delete, enqueue, worker) to this same entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

from rag_core import config as cfg
from rag_core.registry import ComponentError, describe


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


if __name__ == "__main__":
    sys.exit(main())
