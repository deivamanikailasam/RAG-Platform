# ADR-0018: Use OPA as the policy decision point

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Authorisation rules (roles per action, group- and classification-based document access, caps for
contractors) were starting to appear as if-statements in services. They must be consistent across
services, reviewable, tested and logged.

## Decision
OPA 1.21.x (digest-pinned) is the Policy Decision Point. Policies (Rego v1) and mappings (data.json)
live in policies/ in Git, changed by PR; `just policy-check` runs opa fmt/check --strict, Regal
lint and opa test with >= 90% coverage. Entrypoints: rag/authz/decision (allow, reasons, search
filter) and rag/authz/readable_ids (post-check). Deny by default; missing input fields are treated
as empty (never undefined). Clearance = highest group grant, capped by capped_groups (caps win).
OPA's API is protected by system.authz (token required, read-only, decisions only). Decisions are
logged as JSON. Services name actions, not roles; they fail closed (503) when OPA is unavailable,
pre-filter queries with the policy's filter and post-check results with readable_ids.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Rules in service code | No new component | Scattered, untested, inconsistent | The problem we're solving |
| OpenFGA / SpiceDB (ReBAC) | Sharing, inheritance at scale | Relationship store to sync | Our rules are attribute-based today; add for sharing later |
| Cedar (AWS Verified Permissions) | Analysable language, fast | Smaller ecosystem off AWS | OPA is CNCF graduated and runs anywhere |
| Cerbos | Simple YAML policies | Less general | OPA also covers Kubernetes and CI checks later |
| Keycloak Authorization Services | Built into the IdP | Couples rules to the IdP; harder to test | Keep identity and policy separate |

## Consequences
+ One reviewed, tested, logged source of truth for access decisions.
+ Access changes are data changes; services don't change.
- One more service; it must be available (fail closed means OPA down = API down).
- The SQL filter shape mirrors the policy (mitigated by the post-check and live tests).

## Revisit when
Document sharing or folder inheritance appears (add OpenFGA), rules need SQL compilation (OPA
data filtering), or policies must be distributed as signed bundles (production).
