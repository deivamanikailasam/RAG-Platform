# ADR-0008: Serve embeddings and reranking with TEI natively, behind an API key

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Retrieval needs a dense embedder (indexing + queries) and a cross-encoder reranker. They are called
at very different volumes, must use the Metal GPU, and the embedder's behaviour must stay fixed for
the life of an index.

## Decision
We will run Hugging Face Text Embeddings Inference (Homebrew build, Metal) natively:
Qwen3-Embedding-0.6B on 127.0.0.1:8083 and bge-reranker-v2-m3 on 127.0.0.1:8084, loaded from
pinned local snapshot folders, protected by TEI_API_KEY (from SOPS, passed via environment), kept
alive by launchd. The embedding contract (model, revision, dimensions, normalisation, pooling,
query instruction, chunk limit) is recorded in models.yaml and must be stored with every index.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| llama.cpp llama-server (--embedding / --reranking) | Metal, GGUF, also runs Qwen3-Reranker | GGUF conversions, separate quant choices | Strong option; used to compare Qwen3-Reranker in Step 32 |
| Ollama embeddings | Very easy | No rerank endpoint; less control over pooling/batching | Missing reranking |
| Custom FastAPI + sentence-transformers (MPS) | Full control | We'd build batching, auth, metrics ourselves | TEI already provides them |
| Infinity server | Embeddings + rerank, many models | Smaller community | TEI is better supported |
| Bigger embedders (Qwen3-Embedding-4B/8B) now | Higher quality | Slower indexing, more memory | Start small; measure in Step 32 |

## Consequences
+ Two authenticated, batched, metrics-ready services with a standard API.
+ Embedding contract makes index compatibility explicit.
- Changing the embedder means re-embedding every document (planned migration).
- TEI's model support is a fixed list; some rerankers (e.g. Qwen3-Reranker) need another server.

## Revisit when
Step 32 evaluations show a better embedder or reranker is worth the re-index or latency cost.
