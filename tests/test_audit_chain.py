"""Anchoring and end-to-end verification: real Postgres + an S3 with object lock (moto)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from .conftest import REWRITE_FROM_2, append, tamper

if TYPE_CHECKING:
    from .conftest import AuditDb


def _load() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/audit_chain.py"
    spec = importlib.util.spec_from_file_location("audit_chain", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_chain"] = module  # dataclasses look their module up while being created
    spec.loader.exec_module(module)
    return module


ac = _load()


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The Step 14 archive bucket: versioned, object lock, default retention."""
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=ac.BUCKET, ObjectLockEnabledForBucket=True)
        client.put_object_lock_configuration(Bucket=ac.BUCKET, ObjectLockConfiguration={
            "ObjectLockEnabled": "Enabled",
            "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}}})  # fmt: skip
        yield client


@pytest.fixture
def reader(chain: AuditDb) -> Iterator[Any]:
    with chain.connect("reader") as conn:
        yield conn


def test_anchor_archives_new_events_incrementally(chain: AuditDb, reader: Any, s3: Any) -> None:
    append(chain, 3)
    first = ac.anchor(reader, s3)
    assert (first["from_seq"], first["to_seq"], first["prev_head_hash"]) == (1, 3, ac.ZERO)
    assert ac.anchor(reader, s3) is None  # nothing new
    append(chain, 2)
    second = ac.anchor(reader, s3)
    assert (second["from_seq"], second["to_seq"]) == (4, 5)
    assert second["prev_head_hash"] == first["head_hash"]  # the manifests are chained too
    keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket=ac.BUCKET)["Contents"])
    assert keys == ["audit/manifests/000000000003.json", "audit/manifests/000000000005.json",
                    "audit/segments/000000000001-000000000003.jsonl.gz",
                    "audit/segments/000000000004-000000000005.jsonl.gz"]  # fmt: skip
    head = s3.head_object(Bucket=ac.BUCKET, Key=keys[0])
    assert head["ObjectLockMode"] == "GOVERNANCE"  # locked by the bucket's default rule


def test_archived_objects_cannot_be_deleted(chain: AuditDb, reader: Any, s3: Any) -> None:
    append(chain, 1)
    ac.anchor(reader, s3)
    key = ac.manifest_key(1)
    version = s3.head_object(Bucket=ac.BUCKET, Key=key)["VersionId"]
    with pytest.raises(ClientError) as e:
        s3.delete_object(Bucket=ac.BUCKET, Key=key, VersionId=version)
    assert e.value.response["Error"]["Code"] == "AccessDenied"


def test_verify_passes_on_a_clean_log(chain: AuditDb, reader: Any, s3: Any) -> None:
    append(chain, 4)
    ac.anchor(reader, s3)
    append(chain, 2)  # not anchored yet: fine, just reported
    report = ac.verify(reader, s3)
    assert report == {"ok": True, "database_rows": 6, "database_chain_checked": 6,
                      "anchored_up_to": 4, "not_yet_anchored": 2, "problems": []}  # fmt: skip


def test_full_rewrite_is_caught_by_the_anchor(chain: AuditDb, reader: Any, s3: Any) -> None:
    """The attack the chain alone can't see (test_audit_db.py) is visible against the archive."""
    append(chain, 5)
    ac.anchor(reader, s3)
    tamper(chain, REWRITE_FROM_2)
    report = ac.verify(reader, s3)
    assert not report["ok"]
    assert "database: row 2 was changed after it was anchored" in report["problems"]
    append(chain, 1)
    with pytest.raises(ac.AnchorError, match="rewritten"):  # and the anchor job refuses to continue
        ac.anchor(reader, s3)


def test_deleting_the_newest_rows_is_caught(chain: AuditDb, reader: Any, s3: Any) -> None:
    append(chain, 5)
    ac.anchor(reader, s3)
    tamper(chain, "DELETE FROM audit.events WHERE seq >= 4")
    report = ac.verify(reader, s3)
    assert report["problems"] == ["database: row 4 was deleted after it was anchored",
                                  "database: row 5 was deleted after it was anchored"]  # fmt: skip


def test_stacking_a_fake_manifest_on_top_is_caught(chain: AuditDb, reader: Any, s3: Any) -> None:
    """Object lock protects the original version; a newer version can still be ADDED on top.
    Verify always reads the original and reports the attempt."""
    append(chain, 3)
    ac.anchor(reader, s3)
    key = ac.manifest_key(3)
    fake = json.loads(s3.get_object(Bucket=ac.BUCKET, Key=key)["Body"].read())
    fake["head_hash"] = "ab" * 32
    s3.put_object(Bucket=ac.BUCKET, Key=key, Body=json.dumps(fake).encode())
    report = ac.verify(reader, s3)
    assert report["problems"] == [f"archive: {key} has 2 versions (replacement attempted)"]


def test_hiding_a_manifest_with_a_delete_marker_is_caught(
    chain: AuditDb, reader: Any, s3: Any
) -> None:
    """Deleting without a version id doesn't remove anything in a versioned bucket: it adds a
    "delete marker" that hides the key from normal listings. Verify lists versions, so it still
    checks the hidden manifest, and the database rows it covers, and reports the attempt."""
    append(chain, 3)
    ac.anchor(reader, s3)
    append(chain, 2)
    ac.anchor(reader, s3)
    tamper(chain, "DELETE FROM audit.events WHERE seq >= 4")  # cut the newest events…
    s3.delete_object(Bucket=ac.BUCKET, Key=ac.manifest_key(5))  # …and hide their manifest
    assert "Contents" not in s3.list_objects_v2(Bucket=ac.BUCKET, Prefix=ac.manifest_key(5))
    report = ac.verify(reader, s3)
    assert report["anchored_up_to"] == 5
    assert report["problems"] == [
        "archive: audit/manifests/000000000005.json was hidden by a delete marker (deletion attempted)",
        "database: row 4 was deleted after it was anchored",
        "database: row 5 was deleted after it was anchored",
    ]


def test_anchor_refuses_a_bucket_without_object_lock(
    chain: AuditDb, reader: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    append(chain, 1)
    with mock_aws():
        plain = boto3.client("s3", region_name="us-east-1")
        plain.create_bucket(Bucket=ac.BUCKET)  # misconfigured: no lock
        plain.put_bucket_versioning(Bucket=ac.BUCKET, VersioningConfiguration={"Status": "Enabled"})
        with pytest.raises(ac.AnchorError, match="WITHOUT object lock"):
            ac.anchor(reader, plain)


def test_archive_alone_is_checkable(chain: AuditDb, reader: Any, s3: Any) -> None:
    """The segments are a complete copy: anyone can re-check them with nothing but Python."""
    append(chain, 3)
    m = ac.anchor(reader, s3)
    raw, _, _ = ac.original_body(s3, m["segment"])
    rows = [json.loads(line) for line in gzip.decompress(raw).splitlines()]
    assert ac.check_rows(rows, ac.ZERO, 1) is None
    assert json.loads(rows[0]["body"])["details"] == {"returned_ids": [0]}
    rows[1]["body"] = rows[1]["body"].replace('"allowed"', '"denied"')  # edit a downloaded copy
    assert ac.check_rows(rows, ac.ZERO, 1) == "row 2: contents changed (hash does not match)"
