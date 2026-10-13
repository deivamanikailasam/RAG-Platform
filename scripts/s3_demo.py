#!/usr/bin/env python3
"""Versioning, least privilege, presigned URLs, object lock, and lineage into Postgres.

Run: just with-secrets uv run --with boto3 --with "psycopg[binary]" scripts/s3_demo.py
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from typing import TYPE_CHECKING

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:  # type hints only (boto3-stubs); nothing extra is needed at run time
    from mypy_boto3_s3 import S3Client

CFG = Config(signature_version="s3v4", s3={"addressing_style": "path"})
ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:8333")


def client(prefix: str) -> S3Client:
    """An S3 client for one identity: ADMIN, INGEST or READER (keys from the SOPS environment)."""
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name="us-east-1",
        config=CFG,
        aws_access_key_id=os.environ[f"S3_{prefix}_ACCESS_KEY"],
        aws_secret_access_key=os.environ[f"S3_{prefix}_SECRET_KEY"],
    )


ingest, reader, admin = client("INGEST"), client("READER"), client("ADMIN")

# 1) Versioning: upload the "same" policy twice with a change. Key = content-independent document id
key = "raw/remote-work-policy.txt"
for text in (
    "Staff may work remotely up to two days per week.",
    "Staff may work remotely up to two days per week with manager approval.",
):
    body = text.encode()
    r = ingest.put_object(
        Bucket="rag-raw-docs",
        Key=key,
        Body=body,
        ContentType="text/plain",
        Metadata={
            "sha256": hashlib.sha256(body).hexdigest(),
            "source-uri": "demo://Remote work policy",
        },
    )
    print("uploaded version", r["VersionId"])
versions = ingest.list_object_versions(Bucket="rag-raw-docs", Prefix=key)["Versions"]
print("versions kept:", len(versions))
latest = next(v for v in versions if v["IsLatest"])

# 2) Least privilege: the reader can read but not write
print("reader GET   :", reader.get_object(Bucket="rag-raw-docs", Key=key)["Body"].read()[:40])
try:
    reader.put_object(Bucket="rag-raw-docs", Key="raw/hack.txt", Body=b"x")
    print("reader PUT   : ALLOWED (unexpected!)")
except ClientError as e:
    print("reader PUT   : rejected ->", e.response["Error"]["Code"])

# 3) Presigned URL: a 5-minute link to EXACTLY this version, no credentials needed by whoever opens it
url = reader.generate_presigned_url(
    "get_object",
    ExpiresIn=300,
    Params={"Bucket": "rag-raw-docs", "Key": key, "VersionId": latest["VersionId"]},
)
with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - presigned localhost URL
    print("presigned    :", resp.status, resp.read()[:40])

# 4) Object lock: a locked audit record cannot be deleted before its retain-until date
lock = admin.put_object(Bucket="rag-audit-archive", Key="audit/demo.json", Body=b'{"event":"demo"}')
try:
    admin.delete_object(
        Bucket="rag-audit-archive", Key="audit/demo.json", VersionId=lock["VersionId"]
    )
    print("locked DEL   : ALLOWED (unexpected!)")
except ClientError as e:
    print("locked DEL   : rejected ->", e.response["Error"]["Code"])

# 5) Lineage: record exactly which file version the Postgres document came from
dsn = f"postgresql://rag_app:{os.environ['RAG_DB_APP_PASSWORD']}@127.0.0.1:5432/rag"
with psycopg.connect(dsn) as conn:
    # Step 36: row-level security. A maintenance script works across tenants ('*', whole session)
    conn.execute("SELECT set_config('rag.tenant', '*', false)")
    stored = ingest.get_object(Bucket="rag-raw-docs", Key=key, VersionId=latest["VersionId"])
    lineage = {
        "s3_bucket": "rag-raw-docs",
        "s3_key": key,
        "s3_version_id": latest["VersionId"],
        "sha256": hashlib.sha256(stored["Body"].read()).hexdigest(),
    }
    n = conn.execute(
        """UPDATE rag.documents SET metadata = metadata || %s::jsonb, updated_at = now()
           WHERE source_uri = 'demo://Remote work policy'""",
        (json.dumps(lineage),),
    ).rowcount
    print("lineage      : recorded on", n, "document row(s):", lineage["s3_version_id"])
