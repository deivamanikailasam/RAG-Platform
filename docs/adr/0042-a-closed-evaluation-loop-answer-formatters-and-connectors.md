# ADR-0042: A closed evaluation loop, answer formatters and connectors

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
The platform measured search (recall, MRR, nDCG), answers (context recall, cited, abstained,
grounded) and releases (online rates, Step 37), and Step 26's `rag-evals` judged rag-api answers
with an LLM. It could not say how faithful or correct an answer was for a rag-core profile, whether
a difference between two configurations was more than chance, which setting in a profile mattered,
or where new test questions should come from; complaints in the audit log never became tests.
Teams also asked for techniques that were missing or partial: spelling and synonyms in questions,
cross-lingual search, recency only for "latest" questions, rolling date windows, footnote and
quote citations, JSON answers, a confidence score, follow-up questions, an embedding cache shared
by replicas, rate-limited ingestion, and connectors that keep the index in step with its sources.

## Decision
We will:
1. Add the metrics to rag-core (`rag_core.evalkit.metrics`): hit rate, precision and MAP at k for
   search; faithfulness, answer relevance, context precision and recall, correctness against a
   `reference`, citation precision/recall and abstention correctness for answers, computed
   lexically (deterministic, offline) and by an optional `judge: llm` component whose unusable
   replies fall back to the lexical score per metric and are counted as judge errors.
2. Write run files (`rag-core-run/1`) with every case's question, answer, contexts and metrics, and
   build the loop on them: `eval-compare` (paired bootstrap interval + paired permutation test;
   "better" only when both agree), `eval-sweep` (grid of `rag.yaml` overrides, ranked, leaks last),
   `eval-generate` (template or LLM triples with evidence offsets), `eval-candidates` (rated-down
   and flagged answers from the audit log), `eval-export` (Ragas, DeepEval, promptfoo, TruLens,
   Phoenix shapes, no dependencies).
3. Gate generated and proposed questions behind a human review: `review: pending` questions are
   left out of every evaluation until approved; `rag eval-review --check` fails while any are
   pending.
4. Shape answers in a new plural `answer_formatters` slot that runs after citations are checked and
   output guards pass, writes into `Answer.extras` (and rag-api's `extras`), never adds a claim,
   and is skipped (with a trace flag) if it fails.
5. Add query transformers `normalize` (spelling against the vocabulary of chunks the person may
   read) and `translate` (passthrough, glossary or LLM); extend `expand-terms`, `recency` and
   `self-query` rather than adding parallel components.
6. Give the `cached` embedder a Valkey second level and add a `batched` embedder (batches, a
   requests-per-second ceiling, retries with backoff).
7. Add a `connector` slot with working `filesystem` and `s3` connectors and incremental
   `rag sync` (versions, permission-only updates, deletions only after a complete listing and only
   under the connector's prefix); declare `web`, `confluence`, `sharepoint` and `google-drive` as
   reference interfaces that fail with a clear "not configured" error.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Depend on Ragas / DeepEval for metrics | Mature, model-based | Heavy dependencies, model calls in CI, changing APIs | Our lexical metrics + an LLM judge; exporters for those tools |
| Reuse Step 26's `rag-evals` for rag-core profiles | One harness | Built around rag-api's retrieval and the prompt registry, not around swappable profiles | Kept for rag-api; the loop lives in rag-core |
| Unpaired t-test or comparing means | Simple | Ignores that both runs answer the same questions; assumes normality | Paired bootstrap + permutation |
| Let generated questions in with a warning | Faster to start | Unreviewed questions would become release gates | Hard review gate |
| Formatters inside the generator prompt | One model call | Unchecked output, model-dependent, no offline mode | A slot after the checks, offline by default |
| A vocabulary from the whole index for spelling | Simpler | Corrections reveal words from documents a person can't read | Per-person vocabulary |
| Full Confluence / SharePoint / Drive connectors | Ready to use | Permission mapping is per organisation; untested code against services we don't run | Reference interfaces with a clear error; folder/bucket today |
| Event-driven sync only | No polling cost | Needs per-source notification set-up | Polling `rag sync --watch`; events through `rag enqueue` |

## Consequences
+ A change can be measured end to end offline, compared with a significance test, attributed to a
  setting, and turned into tests from the corpus and from real failures.
+ Answers can be shown with highlights, footnotes, a confidence label and suggestions, or consumed as
  checked JSON, without changing the generator.
+ Ingestion stays in step with folders and buckets, at the provider's pace, with a shared cache.
- Lexical answer metrics miss paraphrases; the LLM judge costs a call per question and must itself
  be validated.
- More commands and settings to learn; the confidence score is a heuristic that needs calibrating.
- Reference connectors need project work (especially permission mapping) before use.

## Revisit when
A judge model is validated against human ratings well enough to gate on; the datasets grow past a
few hundred questions (consider stratified bootstrap and per-tag reports); a project needs a SaaS
connector with permission sync (implement it as a plugin, then promote it here); or users need
structured answers produced by the generator itself (tool calling / constrained decoding).
