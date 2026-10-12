"""rag-evals (Step 26): the evaluation harness.

datasets  versioned golden datasets, pinned by SHA-256
metrics   retrieval and answer metrics, small pure functions
targets   what is evaluated: retrieval as a persona through the real policy, or a prompt version
judge     an optional LLM judge from the registered eval-judge prompt
runner    runs a dataset against a target and keeps every case plus provenance
gates     thresholds, the prompt's own min_score and the baseline
record    writes results into model cards (Step 25)
"""
