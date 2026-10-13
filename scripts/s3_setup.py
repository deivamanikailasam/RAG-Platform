#!/usr/bin/env python3
"""Create buckets with versioning, object lock and lifecycle rules (admin identity).

Run: just with-secrets uv run --with boto3 scripts/s3_setup.py
"""

import os
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:8333"),
    region_name="us-east-1",
    aws_access_key_id=os.environ["S3_ADMIN_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_ADMIN_SECRET_KEY"],
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)


def create(bucket: str, **kwargs: Any) -> None:
    """Create a bucket; running the script again is safe (an existing bucket is fine)."""
    try:
        s3.create_bucket(Bucket=bucket, **kwargs)
        print("created", bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise


# 1) Originals: keep every version; expire non-current versions after 90 days
create("rag-raw-docs")
s3.put_bucket_versioning(Bucket="rag-raw-docs", VersioningConfiguration={"Status": "Enabled"})
s3.put_bucket_lifecycle_configuration(
    Bucket="rag-raw-docs",
    LifecycleConfiguration={
        "Rules": [
            {
                "ID": "expire-old-versions",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
            }
        ]
    },
)

# 2) Audit archive: object lock (WORM). GOVERNANCE + 1 day for dev; real audit use = COMPLIANCE + years
create("rag-audit-archive", ObjectLockEnabledForBucket=True)
s3.put_object_lock_configuration(
    Bucket="rag-audit-archive",
    ObjectLockConfiguration={
        "ObjectLockEnabled": "Enabled",
        "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}},
    },
)

# 3) Scratch: everything expires after 1 day
create("rag-tmp")
s3.put_bucket_lifecycle_configuration(
    Bucket="rag-tmp",
    LifecycleConfiguration={
        "Rules": [
            {
                "ID": "expire-tmp",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Expiration": {"Days": 1},
            }
        ]
    },
)

for b in ("rag-raw-docs", "rag-audit-archive", "rag-tmp"):
    v = s3.get_bucket_versioning(Bucket=b).get("Status", "Off")
    print(f"{b:18} versioning={v}")
