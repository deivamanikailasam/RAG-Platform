"""The evaluation loop (extension 04), on top of `rag eval-search` / `rag eval-answers` (Steps 32, 35).

    metrics   retrieval (hit rate, recall, precision, MRR, MAP, nDCG @k) and answer metrics
              (faithfulness, answer relevance, context precision/recall, correctness, citation
              precision/recall, abstention): small pure functions, offline
    runs      the run file every evaluation can write (`--out`): questions, answers, contexts,
              references and per-case scores; what A/B tests and exporters read
    stats     paired bootstrap confidence intervals and a paired permutation test (A/B)
    sweep     a grid of rag.yaml overrides, every combination evaluated and ranked (ablations)
    synth     synthetic question/answer/evidence triples from the corpus (template or LLM)
    feedback  thumbs-down and flagged answers from the audit log -> candidate dataset items
    export    our run format -> Ragas, DeepEval, promptfoo, TruLens, Arize Phoenix (no deps)

Judges (LLM-as-judge with a deterministic fallback) are components: `judge: {use: llm}`.
"""
