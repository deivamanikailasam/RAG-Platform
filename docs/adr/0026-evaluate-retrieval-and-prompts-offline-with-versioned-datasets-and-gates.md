# ADR-0026: Evaluate retrieval and prompts offline with versioned datasets and gates

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** deivamanikailasam

## Context
Prompts, models, retrieval settings and policies change. We need evidence, before shipping, that a
change doesn't make answers worse or leak documents, tied to exact versions so results stay
comparable, and usable as a gate in CI (Step 27) and for prompt promotion (Step 24).

## Decision
A workspace package rag-evals. Golden datasets as JSONL with a manifest pinning each version's
SHA-256 (released versions immutable): retrieval cases run AS synthetic personas through the same
SearchBackend and PolicyEngine as /v1/search (consistency test); answer cases use fixed contexts
and a registered prompt version via the gateway with EVAL_GATEWAY_KEY. Deterministic checks
(citations, refusals, forbidden text, leaks) form the gate; an optional LLM judge (prompt
eval-judge, temperature 0, strict JSON, errors counted) adds correctness and faithfulness.
Every run stores all cases and provenance (dataset ref and hash, target, prompt, model, judge, git
commit). Gates come from evals/gates.yaml, the prompt's evaluation.min_score (stricter only) and a
committed baseline with a tolerance. Results are written into model cards with ruamel.yaml. Search
hits expose document ids; the harness reads the database as rag_readonly.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Ragas / DeepEval / TruLens | Many ready-made metrics | Mostly LLM-judged; another abstraction over our code | Can be added as metrics later |
| promptfoo | Great for prompt A/B and red-teaming | Separate config world from our registry | Revisit for red-team suites |
| Langfuse datasets and evaluations | Integrated with traces | Online-first; gates live elsewhere | Use for online evals (Step 37) |
| Only LLM-judge scores | Covers nuance | Biased, non-deterministic, costly | Judge is advisory; rules gate |

## Consequences
+ Changes ship with numbers; regressions and leaks are blocked; results are reproducible.
+ Prompt promotion and model cards rest on recorded runs.
- Small datasets give coarse numbers; they must grow from real failures.
- Runs need the model servers; judge runs cost GPU time and inherit judge bias.

## Revisit when
Datasets exceed a few hundred cases (sampling, parallelism), a different judge model is available,
end-to-end answers exist (Step 33), or online evaluation starts (Step 37).
