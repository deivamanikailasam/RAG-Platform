# ADR-0014: Use SeaweedFS as the S3-compatible object store instead of MinIO

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Original files need durable, versioned, access-controlled storage with an S3 API. The curriculum
named MinIO, but its community edition is unmaintained: no free images/binaries since Oct 2025,
repository archived early 2026, and reported vulnerabilities left unpatched in community images.

## Decision
Run SeaweedFS 4.x (Apache 2.0, digest-pinned) via `weed mini` as service object-store, S3 API on
127.0.0.1:8333 only. Identities (admin, rag-ingest, rag-reader) are generated at start-up from SOPS
secrets into a tmpfs file. Buckets: rag-raw-docs (versioned, 90-day non-current expiry),
rag-audit-archive (object lock), rag-tmp (1-day expiry). Postgres records object lineage.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| MinIO community (last image) | Familiar | Unmaintained, unpatched | Fails security governance |
| Chainguard MinIO image | Free, rebuilt from source | Upstream code unmaintained | Dependency on archived project |
| RustFS | MinIO-like, Apache 2.0 | Still beta; some features under testing | Revisit when stable |
| Garage | Lightweight, geo-distributed | Smaller S3 feature set; AGPL | SeaweedFS features fit better |
| Ceph RGW | Very mature, enterprise | Heavy (3+ nodes) | Overkill for one Mac |

## Consequences
+ Maintained, permissively licensed S3 store with versioning, lock, lifecycle, presigned URLs.
+ Code uses plain S3 APIs, so it's portable to AWS S3 or any other store.
- Different admin model from MinIO (identities file / IAM commands).
- Single-node `weed mini` is for dev/small use; production needs a multi-component or managed setup.

## Revisit when
RustFS reaches stable, or the platform moves to a cloud provider's S3 (Step 37).
