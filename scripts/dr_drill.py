#!/usr/bin/env python3
"""Disaster-recovery drill (Step 37): restore production's backups into a NEW cluster and prove it.

    dr_drill.py render "2026-10-13 08:59:00+00"     print the restore manifest (review it)
    dr_drill.py run    "2026-10-13 08:59:00+00"     apply, wait, compare row counts, delete

The restore is the real procedure (docs/runbooks/disaster-recovery.md), just never switched to.
It records how long it took: that number is your measured recovery time (RTO).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy/data/drills/restore-cluster.yaml"
TABLES = ["rag.documents", "rag.chunks", "rag.ingest_manifest"]
NS = "rag-data"


def render(target: str | None) -> dict[str, Any]:
    doc = yaml.safe_load(TEMPLATE.read_text())
    target_spec = doc["spec"]["bootstrap"]["recovery"]
    if target is None:
        target_spec.pop("recoveryTarget", None)  # the latest point the archived WAL reaches
    else:
        when = dt.datetime.fromisoformat(target)
        if when.tzinfo is None:
            raise ValueError("give the time WITH its offset, e.g. 2026-10-13 08:59:00+00")
        target_spec["recoveryTarget"] = {
            "targetTime": when.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S+00")
        }
    return dict(doc)


def _kubectl(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True,  # noqa: S603, S607 - fixed program, list arguments
                          check=True).stdout  # fmt: skip


def _counts(cluster: str) -> dict[str, int]:
    pod = _kubectl("get", "pod", "-n", NS, "-l", f"cnpg.io/cluster={cluster},cnpg.io/instanceRole=primary",
                   "-o", "jsonpath={.items[0].metadata.name}")  # fmt: skip
    counts = "".join(f"SELECT '{t}', count(*) FROM {t};" for t in TABLES)  # noqa: S608 - fixed table names
    sql = "SELECT set_config('rag.tenant', '*', false);" + counts
    out = _kubectl(
        "exec",
        "-n",
        NS,
        pod,
        "-c",
        "postgres",
        "--",
        "psql",
        "-d",
        "rag",
        "-At",
        "-F",
        "\t",
        "-c",
        sql,
    )
    return {
        line.split("\t")[0]: int(line.split("\t")[1]) for line in out.splitlines() if "\t" in line
    }


def run(
    target: str | None, timeout_minutes: int = 180
) -> dict[str, Any]:  # pragma: no cover - needs a cluster
    manifest = render(target)
    name = manifest["metadata"]["name"]
    started = time.monotonic()
    _kubectl("apply", "-f", "-", stdin=json.dumps(manifest))
    try:
        _kubectl(
            "wait",
            f"cluster/{name}",
            "-n",
            NS,
            "--for=condition=Ready",
            f"--timeout={timeout_minutes}m",
        )
        seconds = round(time.monotonic() - started)
        restored, live = _counts(name), _counts("rag-db")
        return {"target": target or "latest", "restore_seconds": seconds, "restored": restored, "production_now": live,
                "note": "counts differ by what changed since the target time; zero rows restored is a failure",
                "ok": all(restored.get(t, 0) > 0 for t in TABLES)}  # fmt: skip
    finally:
        _kubectl("delete", f"cluster/{name}", "-n", NS, "--wait=false")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dr_drill.py")
    ap.add_argument("cmd", choices=["render", "run"])
    ap.add_argument("target", nargs="?", help='"YYYY-MM-DD HH:MM:SS+00"; omit for the latest point')
    a = ap.parse_args(argv)
    if a.cmd == "render":
        print(yaml.safe_dump(render(a.target), sort_keys=False))
        return 0
    result = run(a.target)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
