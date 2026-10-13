# ADR-0037: Production environments with gated promotion, canary releases, HA Postgres and online evaluation

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** <you>

## Context

The platform ran on one laptop. Production needs a path for changes that catches what offline
evaluation misses, limits the blast radius of a bad release, survives machine and zone loss,
recovers from destructive mistakes, and separates the identities of workloads.

## Decision

- Staging and prod overlays on the same base and a shared production component.
- Argo Rollouts canaries (10/25/50/100%) with Prometheus checks against the stable release and an
  online-evaluation Job; abort on failure.
- Promotion rules in deploy/envs/promotion.yaml, enforced by scripts/gates.py in `just promote`:
  evidence per digest, 24 h soak in staging, online evaluation, no critical alerts, freezes;
  break glass recorded in the commit.
- CloudNativePG: 3 instances over 3 zones, quorum synchronous commit (durability required),
  WAL archiving and nightly base backups to a locked bucket in another region, 30-day PITR,
  monthly restore drill into a new cluster.
- `rag config readiness` and `rag online-eval` in rag-core; quality alerts with unit tests.
- The ingestion worker and lifecycle jobs as `rag-ingest`, with their own OpenBao role.
- Legal holds in the retention file.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Blue/green deployments | Instant switch, simple | Double capacity; all users switch at once | Canary limits the blast radius |
| Flagger | Works with many meshes | Needs a mesh or ingress integration | Rollouts works without a mesh |
| Managed Postgres (RDS, Cloud SQL, …) | Less to operate | Provider-specific; pgvector versions lag | Supported via managed-deps; CNPG is the portable default |
| Manual promotion checklists | No tooling | Skipped under pressure; no record | Gates in code, break glass recorded |

## Consequences

+ Bad releases reach a small share of users and roll back by themselves; promotions are
  evidence-based and recorded; zone loss is absorbed; mistakes are recoverable to the second.
- More moving parts: two operators, cert-manager for the backup plugin, two more clusters.
- Low-traffic environments can't produce significant online results; synthetic traffic or longer
  pauses are needed.

## Revisit when

A service mesh is adopted (exact traffic splits, header routing), traffic is large enough for
per-tenant canaries, or the organisation standardises on a managed database.
