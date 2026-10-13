# ADR-0007: Serve local models natively with mlx-lm, bound to localhost

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** deivamanikailasam

## Context
The platform needs a high-quality generator and a fast helper model with an OpenAI-compatible API.
Models must use the Metal GPU (ADR-0004), be reproducible, and not be exposed to the network.

## Decision
We will serve Qwen3.8-27B-8bit on 127.0.0.1:8081 and Qwen3.6-35B-A3B-4bit on 127.0.0.1:8082 with
mlx_lm.server, from an isolated uv project (infra/model-serving) with a locked mlx-lm version.
Model repos and revision SHAs are recorded in infra/model-serving/models.yaml; serving runs with
HF_HUB_OFFLINE=1. CORS is restricted; launchd keeps both servers alive. From Step 9 the LiteLLM
gateway is the only client. Benchmarks are recorded in docs/benchmarks/models.md.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Ollama (llama.cpp, GGUF) | Very easy, model library, auto load/unload | Separate model format; MLX usually faster on Apple Silicon | Kept as an option for extra models |
| LM Studio server | GUI, MLX + GGUF | Desktop app, harder to automate | Less suited to scripted, versioned setup |
| llama.cpp server | Mature, many features | GGUF format, separate conversions | MLX models already in use |
| vllm-mlx / other MLX servers | Continuous batching, more API features | Younger projects | Revisit if concurrency becomes a bottleneck |
| One model only | Simpler, less memory | Slow helper tasks or weak final answers | Two roles justify two models |

## Consequences
+ Real, measured TTFT/throughput/memory numbers for capacity planning.
+ Model changes are deliberate and reviewed (inventory + offline serving).
- No authentication in mlx_lm.server; safety depends on localhost binding and the gateway.
- ~50 GB of unified memory permanently in use while both servers run.

## Revisit when
Concurrency needs exceed mlx_lm.server's batching, a judge model is added (memory), or mlx-lm adds
auth.
