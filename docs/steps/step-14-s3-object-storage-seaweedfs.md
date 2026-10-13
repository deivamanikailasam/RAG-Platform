# Step 14 · S3 object storage for original files (SeaweedFS)

*Step 14 of 38 · Phase C · Data stores*

## At a glance

| | |
|---|---|
| **Goal** | Give the platform an S3-compatible object store for the original files (PDFs, Word documents, HTML, spreadsheets) that every ingestion pipeline starts from. Use SeaweedFS, because MinIO's free edition is no longer maintained. Configure buckets with versioning, object lock and lifecycle rules, least-privilege identities, and lineage from every chunk back to the exact file version. |
| **Time** | About 75 minutes. |
| **You'll end up with** | An `object-store` service (SeaweedFS 4.x, pinned, credentials from secrets, localhost-only S3 endpoint); three buckets with distinct rules, and three identities (admin, ingest, reader); a demo proving versioning, permissions, presigned links and object lock; lineage recorded in Postgres, a bucket policy document, and ADR-0014. |
| **New words** | Object storage, S3 API, bucket, key, object, metadata, versioning, version ID, delete marker, object lock, retention (governance vs compliance), legal hold, lifecycle rule, presigned URL, content addressing, lineage, endpoint, path-style addressing. |

## The big idea

> **ANALOGY · A CLOAKROOM WITH TICKETS**
> You hand over your coat and get a ticket (the key). You don't care which rack it's on. You just present the
> ticket and get exactly that coat back. The cloakroom has rooms (buckets) with different rules:
>
> - one keeps every version of a coat you've ever checked in
> - one is a sealed vault where nothing can be removed before a date
> - one throws everything out every night
>
> Staff badges (identities) decide who may hand in or collect from which room. That's object storage, and S3 is
> the universal language every cloakroom in the world speaks.

```text
  Files on a disk                                   Object storage (S3 API)
  /Users/you/docs/HR/policies/remote.pdf            bucket   rag-raw-docs
  folders inside folders                            key      raw/9f2c…e1.pdf
  edit in place, no history                         object   the bytes + metadata
  tied to one machine's disk                        version  every overwrite kept
  access = OS file permissions                      access   keys + per-bucket permissions

  One HTTP API (S3) understood by almost every tool, cloud and library: write once, run anywhere.
```

*Figure 44 of the guide: files on a disk vs object storage. Objects live in buckets under keys, carry metadata and
versions, and are reached through one universal HTTP API: S3.*

### Why not MinIO, as the curriculum originally said?

> **WATCH OUT · WHY NOT MINIO?**
> The curriculum named MinIO, which was the default self-hosted S3 store for years. Its free community edition is
> no longer maintained:
>
> - the admin console was removed (2025)
> - free Docker images and binaries stopped being published (October 2025)
> - the GitHub repository was declared unmaintained and archived (early 2026)
> - a reported vulnerability went unpatched in the community images
>
> Running unpatched storage software is exactly what this platform's governance forbids. So we use SeaweedFS
> (Apache 2.0, actively released, long track record, strong S3 support including versioning, object lock, bucket
> policies and presigned URLs). The skills (buckets, keys, versioning, policies) are identical across every
> S3-compatible store, including AWS S3 itself. ADR-0014 records this decision.

## What we're doing

1. Rename the Step 6 MinIO secrets and add per-identity keys.
2. Run `object-store` (SeaweedFS `weed mini`) in Compose: pinned, identities generated in memory from secrets, S3
   port on localhost only.
3. Install the AWS CLI and boto3 tooling, using the store as a custom endpoint.
4. Create three buckets with versioning, object lock and lifecycle rules.
5. Prove: versions are kept, the reader can't write, presigned links expire, and locked objects can't be deleted.
6. Record lineage (bucket, key, version) on the document row in Postgres.
7. Document bucket rules and access, then write ADR-0014.

## Why we're doing this

> **WHY THIS MATTERS**
> Chunks and vectors are derived from original files. If you can't produce the exact original a chunk came from,
> you can't re-process it with a better parser, prove what an answer was based on, honour a deletion request
> completely, or rebuild an index after changing the embedding contract. Object storage is where the raw truth
> lives, cheaply, durably and with history.

| Need | How S3 object storage meets it |
|---|---|
| Keep originals for re-parsing and re-embedding | Cheap, durable storage for any file type and size |
| Know exactly which file version an answer used | Versioning + version IDs recorded in Postgres (lineage) |
| Evidence that can't be tampered with (audit exports, Step 23) | Object lock retention: no delete or overwrite until a date |
| Automatic clean-up and retention | Lifecycle rules that expire temp files and old versions |
| Least privilege | Separate identities scoped to buckets and actions |
| Let a user open a cited source without exposing credentials | Time-limited presigned URLs |
| Portability | The S3 API: the same code works on AWS S3, GCS (interop), Azure (via gateways), Ceph, SeaweedFS… |

> **IN A COMPANY**
> Data platforms keep a *raw zone* (sometimes called "bronze"): immutable original data from which everything else
> can be rebuilt. Regulators and auditors ask for retention (keep records N years), immutability (WORM: write once,
> read many) and deletion (right to be forgotten). S3 versioning, object lock and lifecycle rules are the standard
> tools for all three, and the same configuration skills apply directly on AWS.

Where this sits in the platform so far: Postgres (Step 11) is the source of truth for documents, chunks and
vectors; Qdrant (Step 12) and OpenSearch (Step 13) are *derived* indexes rebuilt from Postgres. Object storage sits
one level further back: Postgres rows are themselves derived from the original files. That makes the object store
the one data store here that **cannot** be rebuilt from anything else, which is why it gets versioning, lineage and
(later) backups.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Object storage / S3 API** | Storing files as *objects* in *buckets*, reached over HTTP using Amazon's S3 protocol, now an industry standard. |
| **Bucket / key / object** | A top-level container / the object's name (it can look like a path) / the bytes plus metadata. |
| **Metadata** | Extra key-value information stored with an object (content type, source URI…). |
| **Versioning / version ID** | Keeping every overwrite as a separate version, each with its own ID. |
| **Delete marker** | With versioning, "delete" adds a marker hiding the object; older versions still exist. |
| **Object lock / retention** | Rules preventing deletion or overwrite until a date. *Governance* mode: privileged users can override. *Compliance* mode: nobody can, not even admins. |
| **Legal hold** | An indefinite lock, applied during investigations, until explicitly removed. |
| **Lifecycle rule** | Automatic actions by age, e.g. "delete temp files after 1 day", "expire old versions after 90 days". |
| **Presigned URL** | A link with a built-in signature and expiry that grants temporary access to one object. |
| **Content addressing** | Naming an object by a hash of its content (`sha256`), so identical files share a name and changes are detectable. |
| **Lineage** | The recorded chain from an output (an answer) back to its inputs (chunks → document → file version). |
| **Endpoint / path-style** | The server URL to send S3 requests to / putting the bucket in the URL path (`/bucket/key`), common for self-hosted stores. |

### Keys are not folders

> **IN PLAIN ENGLISH · KEYS THAT LOOK LIKE PATHS**
> `raw/remote-work-policy.txt` looks like a file in a folder called `raw`, but S3 has no folders. The whole string is
> just the object's name; tools show a "folder" view by splitting names on `/` (the *prefix*). That's why lifecycle
> rules and listings filter by `Prefix`, and why renaming a "folder" means copying every object under it.

In this step the demo uses a *content-independent* key (`raw/remote-work-policy.txt`, the document's identity), so
each edit becomes a new **version** of the same key. The alternative, *content addressing* (key = `sha256` of the
bytes, e.g. `raw/9f2c…e1.pdf`), gives every distinct file its own permanent name and makes duplicates obvious; the
demo still stores the `sha256` in the object's metadata and in the lineage record, so changes are detectable either
way.

### Versions, delete markers and real deletion

With versioning on, nothing is ever silently overwritten: each `PUT` to the same key creates a new version with
its own *version ID*, and the newest is the "latest". A plain `DELETE` doesn't remove anything; it adds a *delete
marker* that hides the object from normal reads. To truly erase an object (a right-to-be-forgotten request) you
must delete **every version and every delete marker** by version ID, and then the chunks and index entries derived
from it (Step 36). The `rag-raw-docs` lifecycle rule (non-current versions expire after 90 days) stops history
growing forever.

### Object lock: governance vs compliance

Object lock makes an object *WORM* (write once, read many) until a *retain-until* date. It can only be switched on
when the bucket is created (and it requires versioning). A bucket can have a *default retention*, applied to every
new object.

- **Governance mode**: nobody can delete or overwrite the locked version, *except* a privileged user who explicitly
  asks to bypass governance retention. Good for learning and for "protect against accidents".
- **Compliance mode**: nobody can, not even the administrator, until the date passes. Good for regulated evidence;
  dangerous by mistake.
- **Legal hold**: an on/off lock with no date, used during investigations, until someone removes it.

> **WATCH OUT · GOVERNANCE VS COMPLIANCE MODE**
> We used governance mode with a 1-day retention so you can clean up while learning. For real audit evidence
> (Step 23), regulated organisations use compliance mode with multi-year retention: then even an administrator with
> full rights cannot delete the object early. Choose it deliberately, because mistakes are permanent until the date
> passes.

### Three buckets, three identities

```text
  rag-raw-docs                     rag-audit-archive               rag-tmp
  original files                   evidence (Step 23)              scratch space
    versioning ON                    object lock (retention)         no versioning
    old versions expire after 90 d   can't be deleted or changed     objects expire after 1 day
    ingest: read/write · reader: read  until retain-until date       ingest only

  s3 admin                         rag-ingest                      rag-reader
  everything · admin tasks only    write raw docs + tmp            read raw docs only
```

*Figure 45 of the guide: three buckets with different rules, and three identities with different powers. Each
application only gets the access its job needs.*

### Presigned URLs

A presigned URL is an ordinary HTTP link with the signature, the identity's access key ID and an expiry baked into
the query string. Whoever holds it can `GET` exactly that object (and, if the link names one, exactly that
version) until it expires, without having any credentials themselves. The RAG API will use this to let a user open
the exact source version a citation points to, without ever handing out keys. The link can only grant what the
signing identity could do: one signed by `rag-reader` can never write.

### Lineage

```text
  original file                 document row                 chunks + vectors              answer citation
  rag-raw-docs/raw/remote.pdf → Postgres rag.documents     →  rag.chunks (pgvector)      →  "source: remote.pdf v3"
  + versionId                   metadata: s3 key + version    → Qdrant, OpenSearch           presigned link to that version
```

*Figure 46 of the guide: lineage from the original file version to the document row, its chunks and vectors, and
finally the citation shown to a user, which can link to that exact version. Every answer can be traced back to the
exact bytes of the exact file version it came from.*

## How to do it

All commands run on the Mac in the project folder (`~/dev/rag-platform`, the root of this repository).

```bash
cd ~/dev/rag-platform
git switch -c feat/object-storage
```

### 1 · Secrets: rename and add identities

```bash
gen_ak() { LC_ALL=C tr -dc 'A-Z0-9' </dev/urandom | head -c 20; echo; }        # access-key style
gen_sk() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-40; echo; }      # secret-key style
gen_ak; gen_sk; gen_ak; gen_sk; gen_ak; gen_sk
just secrets-edit
#   remove MINIO_ROOT_USER and MINIO_ROOT_PASSWORD (from Step 6), then add:
#   S3_ADMIN_ACCESS_KEY=<…>     S3_ADMIN_SECRET_KEY=<…>
#   S3_INGEST_ACCESS_KEY=<…>    S3_INGEST_SECRET_KEY=<…>
#   S3_READER_ACCESS_KEY=<…>    S3_READER_SECRET_KEY=<…>
```

`.env.example` now lists the six `S3_*` names instead of the two `MINIO_*` lines, and
`scripts/new-dev-secrets.sh` has the same `gen_ak` / `gen_sk` helpers, so a fresh machine's `just secrets-init`
generates these names directly.

### 2 · Run SeaweedFS with identities built in memory

SeaweedFS reads its users ("identities") from a JSON file. Rather than storing that file anywhere, the container
builds it at start-up from the secret files, into an in-memory folder, then starts the server. Pick the current
release (4.45 at the time of writing; check SeaweedFS's GitHub releases), pin the digest, and confirm `weed` is on
the image's path:

```bash
docker buildx imagetools inspect chrislusf/seaweedfs:4.45 | head -5
docker run --rm --entrypoint sh chrislusf/seaweedfs:4.45 -c 'which weed && weed version'
```

The service in [`infra/compose/compose.yaml`](../../infra/compose/compose.yaml):

```yaml
services:
  object-store:
    image: chrislusf/seaweedfs:4.45@sha256:fc9f76fa993ad69966ffeb2f65d0318fcae39c6f8e20cf68ef7b3a5cb97769e5
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        umask 077
        cat > /run/seaweed/s3.json <<EOF
        {"identities": [
          {"name": "admin",
           "credentials": [{"accessKey": "$$(cat /run/secrets/s3_admin_access_key)", "secretKey": "$$(cat /run/secrets/s3_admin_secret_key)"}],
           "actions": ["Admin", "Read", "Write", "List", "Tagging"]},
          {"name": "rag-ingest",
           "credentials": [{"accessKey": "$$(cat /run/secrets/s3_ingest_access_key)", "secretKey": "$$(cat /run/secrets/s3_ingest_secret_key)"}],
           "actions": ["Read:rag-raw-docs", "Write:rag-raw-docs", "List:rag-raw-docs", "Tagging:rag-raw-docs",
                       "Read:rag-tmp", "Write:rag-tmp", "List:rag-tmp"]},
          {"name": "rag-reader",
           "credentials": [{"accessKey": "$$(cat /run/secrets/s3_reader_access_key)", "secretKey": "$$(cat /run/secrets/s3_reader_secret_key)"}],
           "actions": ["Read:rag-raw-docs", "List:rag-raw-docs"]}
        ]}
        EOF
        exec weed mini -dir=/data -s3.config=/run/seaweed/s3.json -master.telemetry=false
    secrets: [s3_admin_access_key, s3_admin_secret_key, s3_ingest_access_key, s3_ingest_secret_key,
              s3_reader_access_key, s3_reader_secret_key]
    tmpfs:
      - /run/seaweed:size=1m,mode=0700          # identities file lives in RAM only
    volumes:
      - object-store-data:/data
    ports:
      - "127.0.0.1:8333:8333"                   # S3 API only. Master/filer/admin UIs stay internal
    healthcheck:
      test: ["CMD-SHELL", "nc -z 127.0.0.1 8333 || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 10
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 1g, cpus: "2" }

volumes:
  object-store-data:

secrets:
  s3_admin_access_key:  { environment: S3_ADMIN_ACCESS_KEY }
  s3_admin_secret_key:  { environment: S3_ADMIN_SECRET_KEY }
  s3_ingest_access_key: { environment: S3_INGEST_ACCESS_KEY }
  s3_ingest_secret_key: { environment: S3_INGEST_SECRET_KEY }
  s3_reader_access_key: { environment: S3_READER_ACCESS_KEY }
  s3_reader_secret_key: { environment: S3_READER_SECRET_KEY }
```

How it works, line by line:

- `$$(cat /run/secrets/…)`: the doubled `$$` stops Compose from interpolating; inside the container the shell runs
  `cat` on each secret file, so the keys go straight from the secret files into the JSON.
- `umask 077` + the `tmpfs` at `/run/seaweed` with `mode=0700`: the identities file is readable only by its owner
  and lives in RAM. It never touches the volume, the image or `docker inspect`.
- `exec weed mini …`: `weed mini` runs the master, volume server, filer and S3 gateway in one process, ideal for
  one machine; `exec` makes it the container's main process so it receives stop signals.
- Only `8333` (S3) is published, on `127.0.0.1`. The master (9333), filer (8888), WebDAV, admin UI and the other
  ports `weed mini` opens stay inside the Compose network.

> **IN PLAIN ENGLISH · BUCKET-SCOPED ACTIONS**
> `"Write:rag-raw-docs"` means "may write, but only into the `rag-raw-docs` bucket". The ingest identity can write
> originals and scratch files. The reader can only read originals. Neither can touch the audit archive. Once any
> identity exists, SeaweedFS refuses anonymous requests; without identities it would allow everyone, which is
> development-only behaviour you never want.

> **TIP · IF START-UP FAILS**
> - Check `just logs object-store`.
> - If `weed mini` or `-s3.config` isn't recognised by your version, run
>   `docker run --rm chrislusf/seaweedfs:4.45 mini -h`. Older releases use `weed server -s3 -s3.config=…` instead.
> - If the healthcheck's `nc` is missing in the image, remove the healthcheck and use `just s3 s3 ls` as your check.

### 3 · Tools: AWS CLI with a custom endpoint

[`bootstrap/Brewfile`](../../bootstrap/Brewfile) gains:

```ruby
# ---- Object storage tools (Step 14) ----
brew "awscli"               # AWS CLI v2: speaks S3 to any compatible store via --endpoint-url
```

and the [`justfile`](../../justfile) gains the endpoint variable and the `s3` recipe:

```just
s3_endpoint   := "http://127.0.0.1:8333"

# AWS CLI against the local object store as ADMIN:   just s3 s3 ls   /   just s3 s3api list-buckets
[positional-arguments]
s3 *args:
    #!/usr/bin/env bash
    set -euo pipefail
    sops exec-env secrets/dev.enc.env "AWS_ACCESS_KEY_ID=\"\$S3_ADMIN_ACCESS_KEY\" AWS_SECRET_ACCESS_KEY=\"\$S3_ADMIN_SECRET_KEY\" AWS_REGION=us-east-1 aws --endpoint-url {{s3_endpoint}} $(printf '%q ' "$@")"
```

(See *Notes for this repository* for why the recipe re-quotes its arguments.) Then:

```bash
just bootstrap
just up && just ps
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8333/     # 403: anonymous access refused
just s3 s3 ls                                                       # (empty) = authenticated as admin
```

> **WATCH OUT · NO CREDENTIALS IN ~/.AWS**
> The AWS CLI normally stores keys in plain text in `~/.aws/credentials`. Don't: the `just s3` recipe passes them
> only into that one command, decrypted from SOPS (Step 6 rules).

### 4 · Create the buckets and their rules

[`scripts/s3_setup.py`](../../scripts/s3_setup.py) connects as **admin** with SigV4 signing and path-style
addressing, and is safe to re-run (an existing bucket is fine):

1. `rag-raw-docs`: versioning **Enabled**; lifecycle rule `expire-old-versions` (non-current versions expire after
   90 days).
2. `rag-audit-archive`: created with `ObjectLockEnabledForBucket=True` (which also turns versioning on), default
   retention **GOVERNANCE, 1 day** for development. Real audit use is COMPLIANCE + years.
3. `rag-tmp`: no versioning; lifecycle rule `expire-tmp` (every object expires after 1 day).

It ends by printing each bucket's versioning status.

```bash
just with-secrets uv run --with boto3 scripts/s3_setup.py
#   created rag-raw-docs
#   created rag-audit-archive
#   created rag-tmp
#   rag-raw-docs       versioning=Enabled
#   rag-audit-archive  versioning=Enabled
#   rag-tmp            versioning=Off
```

### 5 · Prove the rules, and record lineage

[`scripts/s3_demo.py`](../../scripts/s3_demo.py) makes one client per identity and runs five checks:

1. **Versioning.** As `rag-ingest`, upload the remote-work policy twice under the same key
   (`raw/remote-work-policy.txt`), the second time with "with manager approval" added. Each upload carries
   metadata (`sha256` of the bytes, `source-uri` = `demo://Remote work policy`). Listing the versions shows two.
2. **Least privilege.** `rag-reader` can `GET` the object, but its `PUT` is rejected with `AccessDenied`.
3. **Presigned URL.** `rag-reader` signs a 5-minute link to exactly the latest *version*; a plain HTTP client with
   no credentials opens it (`200`).
4. **Object lock.** As admin, write `audit/demo.json` into `rag-audit-archive` and try to delete that version: it
   is rejected, because the default governance retention locked it for a day.
5. **Lineage.** As the Step 11 `rag_app` role, write `{"s3_bucket", "s3_key", "s3_version_id", "sha256"}` into the
   `metadata` of the Postgres document whose `source_uri` is `demo://Remote work policy` (loaded by `pg_demo.py`
   in Step 11), so the document row records which file version it was built from.

```bash
just with-secrets uv run --with boto3 --with "psycopg[binary]" scripts/s3_demo.py
just s3 s3api list-object-versions --bucket rag-raw-docs --query 'Versions[].{key:Key,version:VersionId,latest:IsLatest}'
```

> **WHAT YOU JUST PROVED**
> - Overwriting kept the old version.
> - The reader identity can't write.
> - A presigned link opened one exact version without any credentials, and expires in 5 minutes.
> - The locked audit record couldn't be deleted.
> - The Postgres document now records which file version it was built from.
>
> That's raw-data governance in miniature.

### 6 · Document the buckets, then decide

[`docs/data/object-storage.md`](../data/object-storage.md) is the one-page reference for the store: the endpoint
(`http://127.0.0.1:8333` on the Mac, `http://object-store:8333` from containers, path-style, region `us-east-1`),
a table of the three buckets (purpose, versioning, lock, lifecycle, who may write, who may read) and the rules:

- Every document row in Postgres records `s3_bucket`, `s3_key`, `s3_version_id`, `sha256` (lineage).
- No credentials in `~/.aws`; access only via the SOPS-decrypted environment (`just s3` / `just with-secrets`).
- Deletion requests (right to be forgotten) must remove ALL versions, chunks and index entries (Step 36).

Then record the decision:

```bash
just adr "Use SeaweedFS as the S3-compatible object store instead of MinIO"
```

[ADR-0014](../adr/0014-use-seaweedfs-as-the-s3-compatible-object-store-instead-of-minio.md) records the context
(MinIO community edition unmaintained), the decision (SeaweedFS 4.x via `weed mini`, digest-pinned, S3 on
127.0.0.1:8333 only, identities from SOPS secrets in tmpfs, the three buckets, lineage in Postgres), the
alternatives (MinIO's last image, the Chainguard MinIO image, RustFS, Garage, Ceph RGW), the consequences, and when
to revisit (RustFS stable, or a move to a cloud provider's S3 in Step 37).

```bash
git add -A
git commit -m "feat(storage): SeaweedFS S3 object store with versioning, object lock, lifecycle and lineage"
git push -u origin feat/object-storage
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **A raw zone:** originals are kept durably, so any index can be rebuilt with better parsers or embedders.
- **History and lineage:** versions plus recorded version IDs let you prove exactly which file an answer used.
- **Immutability when required:** object lock gives WORM storage for audit evidence.
- **Automatic hygiene:** lifecycle rules clean up temporary data and old versions without manual work.
- **Least privilege:** bucket-scoped identities; no credentials stored in plain text anywhere.
- **Portability:** standard S3 code that runs unchanged against AWS S3 or any compatible store.

## Drawbacks and risks

- **Versioning costs space.** Every overwrite is kept until lifecycle rules expire it; size and expiry need
  monitoring.
- **Deletion is harder.** "Delete" with versioning only adds a marker. Real erasure must remove every version, and
  object-locked data can't be erased early, so think before locking personal data.
- **S3 compatibility varies.** Each self-hosted store implements a subset of S3; test the features you rely on
  (this step's demo does).
- **Single node.** No replication here; durability depends on your Mac's disk and backups (Capstone).
- **The tool landscape moves.** MinIO's change shows open-source infrastructure can change licensing or maintenance
  overnight. Pinning, ADRs and portable APIs limit the damage.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| **SeaweedFS** (our choice) | Apache-2.0 distributed file/object store with an S3 gateway | Self-hosted S3 with good feature coverage, from one node to clusters |
| **RustFS** | MinIO-style S3 server in Rust, Apache 2.0 | You want a MinIO-like drop-in, once it's stable |
| **Garage** | Lightweight geo-distributed S3 store | Small clusters across unreliable or distant machines |
| **Ceph RGW** | S3 gateway of the Ceph storage platform | Large enterprise on-prem storage with an ops team |
| **AWS S3 / GCS / Azure Blob** | Managed cloud object storage | Cloud deployments: the reference implementation of these features |
| **Wasabi / Backblaze B2 / Cloudflare R2** | Low-cost S3-compatible cloud storage | Cheap off-site copies and backups (check feature gaps, e.g. object lock) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Local lab / single machine | SeaweedFS `weed mini` (this step) |
| On-prem production, small team | SeaweedFS multi-component, or RustFS once stable |
| On-prem enterprise with storage team | Ceph RGW |
| Cloud production | The provider's native object storage with versioning, lock and lifecycle |
| Regulated evidence retention | Object lock in compliance mode + legal holds + documented retention schedule |

## Common mistakes

- Running an S3 store with no identities, so anonymous access is allowed.
- Storing AWS-style keys in `~/.aws/credentials` or in code.
- Using unversioned buckets for originals, so an overwrite loses the old file forever.
- Not recording the version ID in the document row, so lineage is broken.
- Locking data in compliance mode by accident. You can't undo it until retention expires.
- Forgetting old versions in deletion requests, leaving "deleted" personal data recoverable.
- Pinning to an unmaintained image because "it still works".

## Done when

- [ ] `MINIO_*` secrets are replaced by six `S3_*` keys (encrypted), and `.env.example` and the generator script are
      updated
- [ ] `object-store` runs pinned at SeaweedFS 4.x; anonymous requests get 403; only `127.0.0.1:8333` is published
- [ ] `just s3 s3 ls` lists `rag-raw-docs`, `rag-audit-archive` and `rag-tmp`
- [ ] `rag-raw-docs` shows versioning Enabled; the lifecycle and lock rules are applied
- [ ] `s3_demo.py` shows 2 versions, reader PUT rejected, presigned GET 200, locked DELETE rejected, and lineage
      recorded
- [ ] `docs/data/object-storage.md` and ADR-0014 are merged through a PR

## Recap

> **RECAP**
> The platform has a raw zone: S3-compatible object storage on SeaweedFS (chosen over the now-unmaintained MinIO
> community edition), with versioned originals, a write-once audit archive, a self-cleaning scratch bucket,
> least-privilege identities, presigned links and recorded lineage from document rows to exact file versions.
> Next, Redis (Step 15): caching, queues and shared rate-limit state.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `infra/compose/compose.yaml` (changed) | New `object-store` service (SeaweedFS 4.45 pinned by tag@digest, identities JSON built from six secret files into a RAM-only tmpfs, `weed mini`, only 127.0.0.1:8333 published, `nc` healthcheck, `no-new-privileges`, 1 GB / 2 CPU limit), the `object-store-data` volume and six `s3_*` secrets. |
| `scripts/new-dev-secrets.sh` (changed) | Replaces `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` with six `S3_*` keys made by the `gen_ak` / `gen_sk` helpers. |
| `.env.example` (changed) | Lists the six `S3_*` names (no values) instead of the two `MINIO_*` lines. |
| `bootstrap/Brewfile` (changed) | Adds `awscli`, which speaks S3 to any compatible store via `--endpoint-url`. |
| `justfile` (changed) | `s3_endpoint` variable and `just s3 …`: the AWS CLI as admin with keys decrypted from SOPS for that one command. |
| `scripts/s3_setup.py` | Creates the three buckets with versioning, object lock (governance, 1 day) and lifecycle rules as admin; idempotent. |
| `scripts/s3_demo.py` | Proves versioning, reader-can't-write, a version-pinned presigned link, the object lock, and records lineage on the Postgres document row. |
| `tests/test_object_storage.py` | Static checks of the service, identities, secrets, recipe, scripts and docs; live checks (opt-in) of 403 for anonymous requests, bucket rules, bucket-scoped permissions, versions and delete markers, presigned-link expiry, governance retention, and the full demo with lineage. |
| `pyproject.toml`, `uv.lock` (changed) | `boto3` and `boto3-stubs[s3]` added to the dev group so mypy and the tests can check the scripts. |
| `.gitignore` (changed) | Re-includes `docs/data/`, which the existing `data/` rule (meant for datasets) would otherwise have ignored. |
| `docs/data/object-storage.md` | The bucket, rule and access reference for the store. |
| `docs/adr/0014-use-seaweedfs-as-the-s3-compatible-object-store-instead-of-minio.md` | ADR-0014, plus its row in `docs/adr/README.md`. |
| `docs/steps/step-14-s3-object-storage-seaweedfs.md` | This write-up, plus its row in `docs/steps/README.md`, the changelog entry and new glossary terms. |

## Notes for this repository

- **The image digest is real.** The guide leaves `<digest>`. The multi-arch digest of `chrislusf/seaweedfs:4.45`
  is `sha256:fc9f76fa993ad69966ffeb2f65d0318fcae39c6f8e20cf68ef7b3a5cb97769e5` (pulled here through the
  `mirror.gcr.io` Docker Hub mirror because Docker Hub rate-limited the container; a mirror serves the same
  content-addressed digest). Inside the image `which weed` prints `/usr/bin/weed`, `weed version` prints `4.45`,
  `nc` exists at `/usr/bin/nc` (so the guide's healthcheck works), and `weed mini -h` lists `-s3.config`. Confirm the
  digest on your Mac with `docker buildx imagetools inspect chrislusf/seaweedfs:4.45 | head -5`.
- **Telemetry off.** `weed mini` sends anonymous cluster statistics to `telemetry.seaweedfs.com` by default
  (`-master.telemetry` defaults to true in 4.45). Following the platform habit from Steps 1 and 12 (no usage
  reports), the start command adds `-master.telemetry=false`; otherwise it is the guide's command.
- **`just s3` re-quotes its arguments.** The guide's one-line recipe puts the arguments inside a single-quoted
  `sops exec-env` command, which `sops` runs through `/bin/sh`. The user's own quotes are gone by then, so the
  guide's example `--query 'Versions[].{key:Key,version:VersionId,latest:IsLatest}'` would be split by brace
  expansion on macOS (where `sh` is bash). The recipe is the same command, written as a bash script recipe with
  `[positional-arguments]`, that quotes each argument with `printf '%q '` before handing it to `sops exec-env`. Both
  `just s3 s3 ls` and the `--query` example were run successfully this way.
- **Small script changes for strict mypy, ruff and testing.** The scripts are the guide's code formatted by ruff,
  with these differences, none of which change behaviour with the defaults: both read the endpoint from
  `S3_ENDPOINT_URL` if set (default `http://127.0.0.1:8333`; from a container you would set
  `http://object-store:8333`); `s3_setup.py`'s `create()` takes `**kwargs: Any` and `s3_demo.py`'s `client()` is
  annotated `-> S3Client` (from `boto3-stubs`, imported only for type checking) instead of the guide's
  `# noqa: ANN201`; in the lineage step the versioned `get_object` call is pulled into a variable for readability.
- **`.gitignore` exception.** The Step 4 `.gitignore` ignores every `data/` folder (datasets are too big for git),
  which also matched `docs/data/`. A `!docs/data/` exception keeps the documentation tracked.
- **No real keys are committed.** Only the six names appear, in `.env.example`; the generator creates real values
  per machine, encrypted by SOPS. The existing `secrets/dev.enc.env` on your Mac is updated with `just secrets-edit`
  as in section 1.
- **Faithful formatting fixes.** Line wraps from the PDF inside the Compose file, the recipe, the Markdown table
  and the Python were rejoined and indentation reconstructed.
- **What was validated here (Linux container, Docker, no Mac, no SOPS key).** The real
  `chrislusf/seaweedfs:4.45` image (same digest) was started with this Compose file and random test keys (a
  throwaway, uncommitted override only swapped in the mirror's image name). The container became **healthy**, the
  identities file existed only in the tmpfs with mode `0600` inside a `0700` folder, only `127.0.0.1:8333` was
  published, and an anonymous request got **403**. `s3_setup.py` created the buckets and printed
  `versioning=Enabled / Enabled / Off`; re-running it was harmless; the lifecycle and lock configurations read
  back exactly as set. With `rag-db` running and the Step 11 migration applied (plus a "Remote work policy" document
  row), `s3_demo.py` printed **2 versions**, reader PUT **rejected -> AccessDenied**, presigned **200**, locked DEL
  **rejected -> AccessDenied**, and lineage **recorded on 1 document row**, whose `metadata` then held the bucket,
  key, version ID and sha256. Extra checks: `rag-ingest` was denied on the audit archive and on creating buckets,
  `rag-reader` was denied listing `rag-tmp`, an expired presigned link returned **403**, a plain delete created a
  delete marker while both versions survived, and admin could delete a locked object only with
  `BypassGovernanceRetention` (governance semantics). The AWS CLI (v1 from PyPI here; v2 from Homebrew on the Mac)
  ran `just s3 s3 ls` and the `--query` example through a stand-in for `sops`. All of this is automated in
  `tests/test_object_storage.py` (18 tests passed live; without the services the live ones skip). The containers and
  volumes were removed afterwards.
