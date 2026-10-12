# Audit log (who received what)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `dataset:audit-log` |
| **Status** | approved |
| **Owner** | security |
| **Last reviewed** | 2026-10-12 (every 180 days) |
| **Role** | operational |
| **Highest classification** | internal |
| **Personal data** | yes |
| **Retention** | Years, per the compliance owner (object-lock retention, Step 14/23). |

## Summary

The hash-chained, append-only record of searches, refusals and admin actions (Step 23), and its anchored copies in write-once storage.

## Where it lives

- Postgres database audit, table audit.events (Step 23)
- s3://rag-audit-archive/audit/ (segments and manifests, object lock)

## Provenance

Written by rag-api through audit.append(); anchored hourly by audit_chain.py.

## Personal data

Pseudonymous user ids (sub) with actions, times and document ids. No names, questions or document text. Pseudonymous data is still personal data.

## Legal basis

Legal obligation and legitimate interest in securing access to company information.

## Deletion

Rows are never deleted; erasure is by deleting the person's identity in Keycloak, which leaves the ids unlinkable (crypto-shredding by lookup, Step 23).

## Access

audit_reader role and the audit-reader identity; security and auditors only.

## Known limitations

- Records only what rag-api reports; up to one hour of events is not yet anchored

## Lineage

Built from:

- dataset:company-chunks
- dataset:company-documents
- model:embedder
- prompt:query-instruction
- system:rag-api

Affects if changed:

- (nothing)

## Approvals

- 2026-10-12 · you
