# ADR-0023: Use a hash-chained audit log anchored in write-once storage

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
We must show who received which documents, every refusal and every admin action, for years, and be
able to prove the record wasn't altered: by a compromised rag-api, by the schema owner or by a
database superuser. The record must not itself hold personal data or document content.

## Decision
A separate `audit` database on rag-db with roles audit_migrator (owner), audit_writer (EXECUTE on
audit.append only) and audit_reader (read + verify). Table audit.events: seq without gaps,
pseudonymous actor (sub), client, action, outcome, resource, small details (ids and counts only),
trace id, prev_hash and hash = sha256(prev_hash || canonical JSON body, UTC times); genesis = 32
zero bytes. append() is SECURITY DEFINER with a fixed search_path, validates input, serialises
writers with LOCK TABLE … EXCLUSIVE. A statement trigger refuses UPDATE/DELETE/TRUNCATE; the down
migration refuses. rag-api records searches (returned ids) and admin actions and fails closed
(503) if it can't; refusals are recorded best effort. Hourly, audit_chain.py anchors new rows
(gzip JSONL segment + chained manifest with head hash) in the object-locked rag-audit-archive
bucket; daily it verifies DB vs archive, reading original object versions and flagging extra
versions and delete markers. Alert RagAuditWriteFailing pages.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Plain table + app logs | Simple | Editable by admins without trace | Not tamper-evident |
| pgaudit only | Every statement logged by Postgres | Statement text, not business events; logs are files | Complementary, not a replacement |
| immudb | Purpose-built verifiable database | Another database to run and back up | Postgres + anchors covers our scale |
| Trillian / Tessera, Sigstore Rekor | Merkle-tree transparency logs, inclusion proofs | Operational weight; built for public logs | Overkill for one platform |
| Managed ledger (Amazon QLDB) | No operations | QLDB discontinued (end of support July 2025) | Gone; and data must stay local |
| SIEM with WORM storage | Central, searchable | Not available locally; vendor cost | Revisit when a SIEM exists |

## Consequences
+ Any change to a row is detectable; full rewrites and tail deletions are detected once anchored.
+ rag-api cannot read, change or delete audit rows; no content or names stored.
- Writes are serialised (~1,000+/s is ample here); a slow audit DB slows or blocks searches.
- Up to one anchor interval (1 h) of events is protected only by the chain and trigger.
- Events never reported by the app are not caught here (Keycloak events, gateway logs, pgaudit).

## Revisit when
Volume exceeds ~500 appends/s sustained (batching or per-partition chains), external proof of time
is required (RFC 3161 timestamps or signed checkpoints), or a company SIEM is available to receive
the anchored segments.
