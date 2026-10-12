# ADR-0009: Route all model access through a LiteLLM gateway

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Four model servers (two LLMs, embedder, reranker) have different ports, model IDs and auth;
mlx-lm has no authentication and can be made to load arbitrary models. Every later project,
the evaluation harness and governance controls need one controlled, logged access point.

## Decision
All model access goes through LiteLLM on 127.0.0.1:4000, running in Docker Compose with a
digest-pinned image, read-only config, file-based secrets (wrapper exports them in-process),
no-new-privileges, resource limits and a liveness healthcheck. Clients use role names
(qwen-quality, qwen-fast, embedder, reranker) defined in infra/config/litellm/config.yaml.
Model servers are never called directly by applications.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Direct calls to each server | Simplest | No auth, no central logs/limits, model IDs everywhere | Fails governance needs |
| Portkey / Kong AI Gateway / Envoy AI Gateway | Strong policy features | Heavier or partly commercial | LiteLLM covers needs, OSS, Python ecosystem |
| Custom FastAPI proxy | Full control | Rebuild auth, budgets, routing, provider adapters | Reinventing a mature tool |
| Cloud gateways (Bedrock, Azure API Management, Vertex) | Managed | Not local; cloud lock-in | Mapped in Step 37 |

## Consequences
+ Apps are decoupled from model backends; swapping a model is a config change.
+ One place for auth, allow-listing, retries, logging; budgets/fallbacks next (Step 10).
- One more hop (small latency) and a critical single point of failure (healthcheck + restart now; HA later).
- Master key must not be used by apps once virtual keys exist (Step 10).

## Revisit when
Policy needs exceed LiteLLM (e.g. complex data-loss prevention), or multi-region HA is required.
