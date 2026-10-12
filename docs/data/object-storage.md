# Object storage: buckets, rules and access

Endpoint: http://127.0.0.1:8333 (containers: http://object-store:8333) · path-style · region us-east-1

| Bucket | Purpose | Versioning | Lock | Lifecycle | Write | Read |
|---|---|---|---|---|---|---|
| rag-raw-docs | Original files (raw zone) | On | No | Non-current versions expire after 90 d | rag-ingest | rag-ingest, rag-reader |
| rag-audit-archive | Immutable evidence (Step 23) | On (required by lock) | Governance, 1 d (dev) → Compliance, years (prod) | None | admin (later: audit service) | admin |
| rag-tmp | Scratch files for pipelines | Off | No | Expire after 1 d | rag-ingest | rag-ingest |

Rules
- Every document row in Postgres records s3_bucket, s3_key, s3_version_id, sha256 (lineage).
- No credentials in ~/.aws; access only via SOPS-decrypted environment (just s3 / just with-secrets).
- Deletion requests (right to be forgotten) must remove ALL versions, chunks and index entries (Step 36).

Identities (built at container start from SOPS secrets into a RAM-only file; see `infra/compose/compose.yaml`)

| Identity | Secret names | Actions |
|---|---|---|
| admin | `S3_ADMIN_ACCESS_KEY` / `S3_ADMIN_SECRET_KEY` | Admin, Read, Write, List, Tagging (all buckets; setup and admin tasks only) |
| rag-ingest | `S3_INGEST_ACCESS_KEY` / `S3_INGEST_SECRET_KEY` | Read, Write, List, Tagging on rag-raw-docs; Read, Write, List on rag-tmp |
| rag-reader | `S3_READER_ACCESS_KEY` / `S3_READER_SECRET_KEY` | Read, List on rag-raw-docs |

Set-up and checks: `just with-secrets uv run --with boto3 scripts/s3_setup.py` (idempotent),
`just with-secrets uv run --with boto3 --with "psycopg[binary]" scripts/s3_demo.py`, `just s3 s3 ls`.
