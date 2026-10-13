# Document access policy (dev environment)

Who may see which documents through the RAG platform, how that is enforced, and how it changes.
It is the `terms` link of the dataset cards (`cards/datasets/company-documents.yaml`, Step 25) and
the human-readable side of the policy code in `policies/rag/authz/` (Step 18). Model and key
access through the gateway is a separate policy: [gateway-access-policy.md](gateway-access-policy.md)
(Step 10).

## Classifications

Every document has exactly one classification, set by its owner at the source and copied to every
chunk at ingestion (Steps 11 and 31). Same names in the documents table, the policy and every store.

| Level | Meaning | Examples | Who may see it |
|---|---|---|---|
| `public` | Could be published outside the company | Press releases, published policies | Anyone signed in (within the tenant) |
| `internal` | For staff; harmless if leaked, but not public | Handbook, how-tos, team pages | Members of the document's groups with clearance `internal` or higher |
| `confidential` | Harm to people or the company if leaked | Salary bands, HR cases, contracts | Members of the document's groups with clearance `confidential` or higher |
| `restricted` | Serious harm if leaked; named audience | Executive compensation, M&A, investigations | Members of the document's groups with clearance `restricted` |

A non-public document with **no groups is visible to nobody** (fail closed), not to everybody.

## Groups and clearance

Groups come from the identity provider (Keycloak, Step 16) in the token. The clearance each group
grants lives in `policies/rag/authz/data.json`, so access changes are data, not code:

| Group | Clearance | Owner |
|---|---|---|
| `all-staff` | internal | People team |
| `engineering` | internal | Engineering lead |
| `platform-admins` | internal | Platform owner |
| `auditors` | internal | Internal audit |
| `hr` | confidential | People team |
| `executives` | restricted | Chief of staff |
| `contractors` | **capped** at internal, whatever else the person belongs to | Procurement |

A person's clearance is the highest level any of their groups grants, lowered by any cap. To see a
document they need the clearance for its classification **and** (unless it is public) at least one
of its groups.

## Tenants

Every document and every person belongs to one tenant (`default` for a single organisation). A
person never sees another tenant's documents, whatever their groups. Tenants are separated at four
levels: the policy's filter, every store's query (Step 31), Postgres row-level security keyed by a
per-transaction `rag.tenant` setting (Step 36), and the answer cache's access fingerprint (Step 33).
Ingestion and maintenance jobs use the cross-tenant setting `*` under their own identity, and the
audit log records them.

## Where it is enforced

1. **rag-api** checks the token (Step 17) and asks OPA what the person may do and see (Step 18).
2. The **filter** (tenant, classifications, groups) goes into every store query: pgvector, Postgres
   full-text, Qdrant, OpenSearch (Steps 11-13, 31). One conformance kit proves each store applies it.
3. **Row-level security** in Postgres returns nothing to a query that forgets the tenant (Step 36).
4. The search pipeline and OPA **re-check every result** before it reaches the model (Steps 32-33).
5. Cached answers are only reused for people who can see exactly the same documents (Step 33).
6. Every search and answer is written to the **audit log** with document ids, never text (Step 23).

## Changing access

- **Document access** changes at the source. The change is applied everywhere at once (every store,
  the graph, the manifest, the cache) with `rag reacl <uri> --group … --classification …`, ideally
  triggered by the source system's permission-change events. Target: revocation within minutes;
  never "at the next nightly sync".
- **Group clearance or caps** change by a pull request to `policies/rag/authz/data.json`, reviewed
  by the group's owner and the platform owner; `just policy-check` must pass.
- **New groups** need an owner in the table above before they are used in documents.

## Retention and deletion

Indexed copies never outlive the original: deleting a source removes it from every store and every
object version (`rag erase-source`); `examples/retention.yaml` sets how long indexed sources may stay
(`rag retention`); a person's erasure request removes their conversations, invalidates cached answers
and lists the documents that mention them for their owners (`rag erase-subject`). The audit log is
kept, with pseudonymous ids only, as a documented exception. See Step 36.

## Rules

- Classify at the source; when in doubt, classify higher and narrow the groups.
- Never ingest special-category personal data (health, union membership, …) without a separate
  privacy assessment.
- Service identities (the ingestion worker) may ingest but not search or answer (`documents:ingest`).
- Quarterly review: group membership, the clearance table, documents with no owner, and a sample of
  `restricted` documents.
- Any exception is recorded here, with an owner and an expiry date.

| Exception | Owner | Expires |
|---|---|---|
| (none) | | |
