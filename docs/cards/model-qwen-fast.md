# Qwen3.6-35B-A3B, 4-bit MLX (qwen-fast)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `model:qwen-fast` |
| **Status** | approved |
| **Owner** | rag-platform |
| **Last reviewed** | 2026-10-12 (every 180 days) |
| **Task** | generation |
| **Weights** | `lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit` @ `<40-char SHA` |
| **Licence** | [apache-2.0](https://huggingface.co/Qwen/Qwen3.6-35B-A3B), verified 2026-10-11 |
| **Fallback allowed** | yes |

## Summary

The fast mixture-of-experts chat model (about 3B parameters active per token): query rewriting, routing, classification and short replies, with thinking switched off at the server (Step 7).

## Intended use

- Rewriting and expanding search queries (Step 32)
- Routing and classifying requests
- Short answers where speed matters more than depth

## Out of scope

- Long, multi-document synthesis where accuracy matters (use qwen-quality)
- Decisions about people without a human deciding

## Training data

As described by the publisher: large-scale multilingual data; details not disclosed.

## Data handling

Runs on the Mac through the gateway; nothing leaves the machine.

## Risks

- Weaker reasoning than qwen-quality; as a fallback for it, answers may be less accurate
- 4-bit quantisation loses more accuracy than 8-bit

## Known limitations

- Answers degrade faster than qwen-quality on long contexts
- Not yet evaluated on our documents (Step 26)

## Evaluation

No results yet (Step 26).

## Lineage

Built from:

- (none)

Affects if changed:

- prompt:eval-judge (fallback)
- prompt:rag-answer (fallback)
- system:rag-api (input)
  - dataset:audit-log (input)
  - dataset:llm-traces (input)

## Approvals

- 2026-10-11 · you · Step 7
