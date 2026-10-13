#!/usr/bin/env python3
"""Anchor the audit chain outside the database, and verify it end to end (Step 23).

Why: the hash chain proves no row was changed *unless someone rewrote the whole chain after it*.
A database superuser can do exactly that. So, regularly, we copy the new events and the latest
hash (the "head") into the write-once audit bucket (object lock, Step 14). From then on, a
rewrite no longer matches what the archive holds, and nobody can change the archive.

  anchor   copy events since the last anchor to s3://rag-audit-archive/audit/…, plus a manifest
  verify   re-check the database chain, the archive, and that they still agree

Run:  just audit-anchor   (hourly, from cron)
      just audit-verify   (daily, and whenever an auditor asks)

Both connect to Postgres as audit_reader (read-only) and never need write access to the database.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = "rag-audit-archive"
ZERO = "00" * 32  # the genesis "previous hash": 32 zero bytes


class AnchorError(Exception):
    """Something is wrong enough that we must not anchor. Investigate before anything else."""


# ------------------------------------------------------------------ the chain, checked in Python


def link_hash(prev_hex: str, body: str) -> str:
    """The same rule as the database: sha256(previous hash bytes || body text as UTF-8)."""
    return hashlib.sha256(bytes.fromhex(prev_hex) + body.encode("utf-8")).hexdigest()


def check_rows(rows: list[dict[str, Any]], prev_head: str, first_seq: int) -> str | None:
    """Independent re-check of exported rows. Returns the first problem, or None."""
    expected, prev = first_seq, prev_head
    for r in rows:
        if r["seq"] != expected:
            return f"row {expected} is missing (found {r['seq']})"
        if json.loads(r["body"])["seq"] != r["seq"]:
            return f"row {r['seq']}: body belongs to a different row"
        if r["prev_hash"] != prev:
            return f"row {r['seq']}: link broken (prev_hash does not match)"
        if link_hash(r["prev_hash"], r["body"]) != r["hash"]:
            return f"row {r['seq']}: contents changed (hash does not match)"
        prev, expected = r["hash"], expected + 1
    return None


def export_rows(conn: psycopg.Connection[Any], first: int, last: int) -> list[dict[str, Any]]:
    cur = conn.execute(
        """SELECT seq, encode(prev_hash, 'hex'), encode(hash, 'hex'), audit.event_body(e)
             FROM audit.events e WHERE seq BETWEEN %s AND %s ORDER BY seq""",
        (first, last),
    )
    return [{"seq": s, "prev_hash": p, "hash": h, "body": b} for s, p, h, b in cur]


# ------------------------------------------------------------------ the archive


@dataclass(frozen=True)
class Manifest:
    key: str
    from_seq: int
    to_seq: int
    head_hash: str
    prev_head_hash: str
    segment: str
    segment_sha256: str
    versions: int  # more than 1 = someone tried to replace it
    delete_markers: int  # more than 0 = someone tried to delete it


def segment_key(first: int, last: int) -> str:
    return f"audit/segments/{first:012d}-{last:012d}.jsonl.gz"


def manifest_key(last: int) -> str:
    return f"audit/manifests/{last:012d}.json"  # zero-padded: alphabetical order = chain order


def history(s3: Any, prefix: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every version and every delete marker under a prefix (newest first, as S3 lists them)."""
    versions: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=BUCKET, Prefix=prefix):
        versions += page.get("Versions", [])
        markers += page.get("DeleteMarkers", [])
    return versions, markers


def original_body(s3: Any, key: str) -> tuple[bytes, int, int]:
    """The FIRST version ever written of a key, plus how many versions and delete markers exist.

    Object lock stops anyone deleting or overwriting a locked version. But in a versioned bucket
    a newer version can be stacked on top, and a "delete marker" can hide the key from normal
    listings. So we always read the oldest version (the genuine one) and report anything else.
    """
    versions, markers = history(s3, key)
    versions = [v for v in versions if v["Key"] == key]
    if not versions:
        raise KeyError(key)
    oldest = versions[-1]
    obj = s3.get_object(Bucket=BUCKET, Key=key, VersionId=oldest["VersionId"])
    return obj["Body"].read(), len(versions), sum(m["Key"] == key for m in markers)


def read_manifests(s3: Any) -> list[Manifest]:
    # List VERSIONS, not current objects: a delete marker must not make a manifest invisible.
    versions, _ = history(s3, "audit/manifests/")
    out = []
    for key in sorted({v["Key"] for v in versions}):
        raw, n_versions, n_markers = original_body(s3, key)
        m = json.loads(raw)
        out.append(
            Manifest(key, m["from_seq"], m["to_seq"], m["head_hash"], m["prev_head_hash"],
                     m["segment"], m["segment_sha256"], n_versions, n_markers)
        )  # fmt: skip
    return out


def put_once(s3: Any, key: str, body: bytes, content_type: str) -> None:
    """Write a key that must not exist yet, then confirm the store actually locked it."""
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        raise AnchorError(f"{key} already exists: another anchor run, or tampering")
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
            raise
    s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type,
                  ChecksumAlgorithm="SHA256")  # fmt: skip
    head = s3.head_object(Bucket=BUCKET, Key=key)
    if not head.get("ObjectLockMode") or not head.get("ObjectLockRetainUntilDate"):
        raise AnchorError(f"{key} was stored WITHOUT object lock: fix the bucket (Step 14)")


# ------------------------------------------------------------------ the two commands


def anchor(conn: psycopg.Connection[Any], s3: Any) -> dict[str, Any] | None:
    """Archive everything since the last anchor. Returns the new manifest, or None if no news."""
    manifests = read_manifests(s3)
    last = manifests[-1] if manifests else None
    first = last.to_seq + 1 if last else 1
    prev_head = last.head_hash if last else ZERO

    # One consistent snapshot of the database for everything below
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        # 1. The database must still agree with the last anchor. If not, history was rewritten.
        if last:
            row = conn.execute(
                "SELECT encode(hash, 'hex') FROM audit.events WHERE seq = %s", (last.to_seq,)
            ).fetchone()
            if row is None or row[0] != last.head_hash:
                raise AnchorError(
                    f"row {last.to_seq} no longer matches the anchored head hash: "
                    "the database chain was rewritten. Run `just audit-verify` and investigate."
                )
        head = conn.execute("SELECT coalesce(max(seq), 0) FROM audit.events").fetchone()
        newest = int(head[0]) if head else 0
        if newest < first:
            return None  # nothing new to anchor
        # 2. The database's own check of the new range (includes the link to the anchored head)
        ok, _, bad, problem = conn.execute(
            "SELECT * FROM audit.verify(%s, %s)", (first, newest)
        ).fetchone() or (False, 0, None, "verify returned nothing")
        if not ok:
            raise AnchorError(f"database chain broken at row {bad}: {problem}")
        rows = export_rows(conn, first, newest)

    # 3. An independent re-check in Python (doesn't trust the database's own function)
    if problem := check_rows(rows, prev_head, first):
        raise AnchorError(f"exported rows failed the re-check: {problem}")

    # 4. Segment (the events themselves) first, manifest (the summary) second
    segment = gzip.compress(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode(), mtime=0
    )
    seg_key = segment_key(first, newest)
    put_once(s3, seg_key, segment, "application/gzip")
    manifest = {
        "version": 1,
        "from_seq": first,
        "to_seq": newest,
        "rows": len(rows),
        "head_hash": rows[-1]["hash"],
        "prev_head_hash": prev_head,  # chains the manifests together too
        "segment": seg_key,
        "segment_sha256": hashlib.sha256(segment).hexdigest(),
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    put_once(s3, manifest_key(newest), json.dumps(manifest, indent=2).encode(), "application/json")
    return manifest


def verify(conn: psycopg.Connection[Any], s3: Any) -> dict[str, Any]:
    """Check the database chain, the archive, and that they agree. Never stops at the first issue."""
    problems: list[str] = []
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        # 1. The database chain on its own
        ok, checked, bad, problem = conn.execute("SELECT * FROM audit.verify()").fetchone() or (
            False, 0, None, "verify returned nothing",
        )  # fmt: skip
        if not ok:
            problems.append(f"database: row {bad}: {problem}")
        db_hashes = dict(conn.execute("SELECT seq, encode(hash, 'hex') FROM audit.events"))

    # 2. The archive on its own, and 3. the database against the archive
    prev_to, prev_head, anchored_to = 0, ZERO, 0
    for m in read_manifests(s3):
        if m.versions > 1:
            problems.append(f"archive: {m.key} has {m.versions} versions (replacement attempted)")
        if m.delete_markers:
            problems.append(f"archive: {m.key} was hidden by a delete marker (deletion attempted)")
        if m.from_seq != prev_to + 1 or m.prev_head_hash != prev_head:
            problems.append(f"archive: {m.key} does not continue the previous manifest")
        raw, versions, markers = original_body(s3, m.segment)
        if versions > 1:
            problems.append(f"archive: {m.segment} has {versions} versions (replacement attempted)")
        if markers:
            problems.append(
                f"archive: {m.segment} was hidden by a delete marker (deletion attempted)"
            )
        if hashlib.sha256(raw).hexdigest() != m.segment_sha256:
            problems.append(f"archive: {m.segment} does not match its manifest checksum")
        rows = [json.loads(line) for line in gzip.decompress(raw).splitlines()]
        if problem := check_rows(rows, m.prev_head_hash, m.from_seq):
            problems.append(f"archive: {m.segment}: {problem}")
        elif not rows or rows[-1]["hash"] != m.head_hash or rows[-1]["seq"] != m.to_seq:
            problems.append(f"archive: {m.segment} does not end at the manifest's head")
        for r in rows:  # every archived event must still be in the database, unchanged
            current = db_hashes.get(r["seq"])
            if current is None:
                problems.append(f"database: row {r['seq']} was deleted after it was anchored")
            elif current != r["hash"]:
                problems.append(f"database: row {r['seq']} was changed after it was anchored")
        prev_to, prev_head, anchored_to = m.to_seq, m.head_hash, m.to_seq

    newest = max(db_hashes, default=0)
    return {
        "ok": not problems,
        "database_rows": len(db_hashes),
        "database_chain_checked": checked,
        "anchored_up_to": anchored_to,
        "not_yet_anchored": max(newest - anchored_to, 0),
        "problems": problems[:50],  # the first 50 is plenty to start an investigation
    }


# ------------------------------------------------------------------ command line


def _clients(identity: str) -> tuple[psycopg.Connection[Any], Any]:
    # postgres://audit_reader:…@127.0.0.1:5432/audit ; autocommit: we open our own transactions
    conn = psycopg.connect(os.environ["AUDIT_DB_DSN"], autocommit=True)
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:8333"),
        region_name="us-east-1",
        aws_access_key_id=os.environ[f"S3_{identity}_ACCESS_KEY"],
        aws_secret_access_key=os.environ[f"S3_{identity}_SECRET_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return conn, s3


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "anchor":
        conn, s3 = _clients("AUDIT_ANCHOR")
        try:
            manifest = anchor(conn, s3)
        except AnchorError as e:
            print(f"ANCHOR REFUSED: {e}", file=sys.stderr)
            return 2
        print(json.dumps(manifest or {"anchored": 0, "reason": "no new events"}))
        return 0
    if command == "verify":
        conn, s3 = _clients("AUDIT_READER")
        report = verify(conn, s3)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    print("usage: audit_chain.py anchor|verify", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
