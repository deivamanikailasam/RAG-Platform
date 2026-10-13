#!/usr/bin/env python3
"""Database backups and restore drills (Step 36).

    backup.py backup       --dsn-env RAG_BACKUP_DSN --out backups/rag-<date>.dump [--s3 s3://bucket/prefix/]
    backup.py restore-test --dump backups/rag-<date>.dump --admin-dsn-env RAG_RESTORE_ADMIN_DSN

A backup is a pg_dump custom-format file plus a small JSON "receipt": its SHA-256 and the row
counts of the tables that matter. A restore drill restores it into a throwaway database and checks
the counts and checksum match: a backup that has never been restored is a hope, not a backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TABLES = ["rag.collections", "rag.documents", "rag.chunks", "rag.ingest_manifest"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _counts(dsn: str) -> dict[str, int]:
    import psycopg

    out = {}
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "SELECT set_config('rag.tenant', '*', true)"
        )  # row-level security (Step 36): all tenants
        for t in TABLES:
            exists = conn.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0]  # type: ignore[index]
            if exists:
                out[t] = int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0])  # type: ignore[index]  # noqa: S608 - fixed names
    return out


def backup(dsn: str, out: Path, s3: str | None = None, s3_client: Any = None) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    counts = _counts(dsn)  # before the dump: rows added during it may or may not be included
    subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={out}", dsn],  # noqa: S603, S607 - fixed program, list arguments (no shell)
                   check=True)  # fmt: skip
    receipt = {"file": out.name, "sha256": _sha256(out), "bytes": out.stat().st_size, "counts": counts,
               "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}  # fmt: skip
    Path(f"{out}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if s3:
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        bucket, _, prefix = s3[len("s3://") :].partition("/")
        for p in (out, Path(f"{out}.json")):
            # Object Lock (Step 14) on the bucket keeps these immutable for the retention period
            s3_client.upload_file(str(p), bucket, prefix + p.name)
        receipt["uploaded"] = f"s3://{bucket}/{prefix}{out.name}"
    return receipt


def restore_test(dump: Path, admin_dsn: str) -> dict[str, Any]:
    import psycopg
    from psycopg.conninfo import make_conninfo

    receipt = json.loads(Path(f"{dump}.json").read_text())
    problems = []
    if _sha256(dump) != receipt["sha256"]:
        problems.append("checksum differs from the receipt: the file changed or is corrupt")
    name = f"restore_check_{int(time.time())}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    target = make_conninfo(admin_dsn, dbname=name)
    started = time.monotonic()
    try:
        subprocess.run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", f"--dbname={target}", str(dump)],  # noqa: S603, S607 - fixed program, list arguments (no shell)
                       check=True)  # fmt: skip
        restored = _counts(target)
        for table, n in receipt["counts"].items():
            if restored.get(table) != n:
                problems.append(f"{table}: {restored.get(table)} rows restored, {n} in the backup")
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    return {"dump": dump.name, "restore_seconds": round(time.monotonic() - started, 2), "counts": receipt["counts"],
            "problems": problems, "ok": not problems}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backup.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument(
        "--dsn-env", required=True, help="NAME of the variable holding the DSN (never the DSN)"
    )
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--s3")
    r = sub.add_parser("restore-test")
    r.add_argument("--dump", required=True, type=Path)
    r.add_argument("--admin-dsn-env", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "backup":
        print(json.dumps(backup(os.environ[a.dsn_env], a.out, a.s3), indent=2))
        return 0
    result = restore_test(a.dump, os.environ[a.admin_dsn_env])
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
