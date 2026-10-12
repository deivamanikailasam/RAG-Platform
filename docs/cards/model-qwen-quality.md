# Qwen3.8-27B, 8-bit MLX (qwen-quality)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `model:qwen-quality` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-12 (every 180 days) |
| **Task** | generation |
| **Weights** | `mlx-community/Qwen3.8-27B-8bit` @ `<40-char SHA` |
| **Licence** | [apache-2.0](https://huggingface.co/Qwen/Qwen3.8-27B), verified 2026-10-11 |
| **Fallback allowed** | yes |

## Summary

The careful, slower chat model: answers grounded in retrieved documents, synthesis across several sources, and drafting evaluation judgements. Served locally by mlx-lm (Step 7).

## Intended use

- Answering employee questions from retrieved company documents (Step 33), with citations
- Summarising and comparing several documents the user is allowed to read
- Drafting judgements for offline evaluation, reviewed by people (Step 26)

## Out of scope

- Decisions about people (hiring, performance, pay, discipline) without a human deciding
- Legal, medical or financial advice presented as authoritative
- Answering without retrieved sources, from "its own knowledge", on company matters

## Training data

Large-scale multilingual web, code and curated data, as described by the publisher. The exact datasets are not disclosed in detail; treat its world knowledge as unverified and possibly dated.

## Data handling

Runs on the Mac through the gateway (Step 9). Prompts, documents and answers never leave the machine; the gateway logs metadata only (Step 10).

## Risks

- Hallucination (fluent, confident statements the documents don't support)
- Prompt injection through retrieved documents (mitigated by Step 24's prompt rules and Step 18's policy)
- 8-bit quantisation can lose a little accuracy versus the full-precision model

## Known limitations

- Slow (tens of tokens per second); long answers take minutes
- Knowledge cut-off and training data unknown in detail
- Quality in languages other than English not yet measured on our documents

## Evaluation

No results yet (Step 26).

## Lineage

Built from:

- (none)

Affects if changed:

- prompt:eval-judge (runs on)
- prompt:rag-answer (runs on)

## Approvals

- 2026-10-11 · you · Step 7: selected after the benchmark in docs/benchmarks
