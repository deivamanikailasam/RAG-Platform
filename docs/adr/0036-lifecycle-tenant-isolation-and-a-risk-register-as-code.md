# ADR-0036: Lifecycle operations, tenant RLS, restore drills and a risk register as code

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** <you>

## Context
Permissions change, documents expire, people ask to be forgotten, models get replaced and
databases fail. Reviewers expect a threat model with tested controls mapped to frameworks.

## Decision
- Stores implement update_access; the pipeline applies it to every store, the graph, the manifest
  and the cache; a conformance check enforces it. `rag reacl` exposes it.
- Retention (rules by URI, from the last ingestion), erasure of sources (all object versions) and of
  people (conversations, cache, mentions listed), and re-indexing from originals: dry run by default.
- The manifest records access and metadata. Postgres row-level security by a per-transaction tenant
  setting ('*' for ingestion and maintenance).
- Backups with checksum and row-count receipts; scheduled restore drills.
- docs/compliance/risk-register.yaml: threats → controls → evidence → framework references,
  validated and rendered in CI.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Re-ingest on every access change | No new code | Slow; old access applies meanwhile | In-place updates |
| Separate database per tenant | Strong isolation | Many databases to run and migrate | RLS now; per-tenant databases for regulated tenants |
| GRC tool for the register | Workflow, reporting | Evidence drifts from code | Register in git, checked against real tests; export to a GRC tool if needed |
| Backups without drills | Simple | Unknown recoverability | Drill with comparison |

## Consequences
+ Revocation in seconds, erasure across every copy, re-indexing without downtime, provable
  recovery, a reviewable safety case.
- Lifecycle jobs need their own identity and schedule (Step 37); retention rules need an owner.
- Legal holds aren't modelled yet: add a hold list that retention and erasure must respect.

## Revisit when
Tenants need contractual isolation (separate databases or clusters), a GRC platform becomes the
system of record, or source systems can publish change events (adopt CDC).
