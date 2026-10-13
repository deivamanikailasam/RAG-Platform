# ADR-0010: Govern model access with virtual keys, budgets, shadow prices and fallbacks

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
After Step 9 every client used the master key: no per-app scoping, limits, spend visibility or
expiry. Local models have zero real cost, so budgets would never trigger. One model outage failed
all chat requests.

## Decision
- A dedicated, unpublished Postgres (litellm-db) stores gateway state; DATABASE_URL and
  LITELLM_SALT_KEY come from SOPS secrets via the in-container wrapper.
- Teams own budgets; each app/environment gets a virtual key with an allow-list, RPM, max parallel
  requests and 90-day expiry, per docs/security/gateway-access-policy.md. Master key is admin-only.
- Local models carry shadow prices derived from benchmarks (docs/finops/shadow-pricing.md).
- Chat models fall back to each other (1 retry, cooldown 30 s after 3 fails/min). Embedder and
  reranker never fall back at the gateway.
- Models are defined only in config.yaml (store_model_in_db: false).

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Keep the master key everywhere | Simple | No least privilege, no attribution | Unacceptable once >1 app |
| Share the RAG Postgres (Step 11) | One fewer container | Mixed blast radius, backup/retention coupling | Separation preferred |
| Zero prices, no budgets | No made-up numbers | No usage visibility; budgets disabled | Shadow prices make use comparable |
| Fallback for embedder too | Fewer errors | Silently wrong retrieval | Correctness over availability |

## Consequences
+ Leaked or misbehaving keys are contained (models, rate, budget, expiry, block).
+ Spend per app/team/model is visible; chat survives a single model outage.
- Shadow prices need re-deriving after model/benchmark changes.
- Another stateful service to back up (Capstone DR) and upgrade carefully.

## Revisit when
Real multi-team usage begins (chargeback), or a second machine serves models (load balancing).
