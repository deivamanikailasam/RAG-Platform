# Extension 04 · The evaluation loop, and the remaining techniques

*Extension 04 · after the 38 guide steps · RAG core (quality, answers, ingestion)*

## At a glance

| | |
|---|---|
| **Goal** | Every change to a RAG system can be measured the whole way round the loop (labelled questions → metrics → a fair A/B comparison → ablations → new questions from the corpus and from real failures), and the techniques people still ask for by name (spelling, synonyms, translation, recency, citation and answer formats, confidence, follow-ups, embedding caches, rate limits, connectors) are one switch each. |
| **How, in one sentence** | New metrics, a `judge` slot and run files on top of `rag eval-search` / `rag eval-answers`; six new commands (`eval-compare`, `eval-sweep`, `eval-generate`, `eval-review`, `eval-candidates`, `eval-export`); an `answer_formatters` slot; query transformers `normalize` and `translate`; wider `expand-terms`, `recency` and `self-query`; a Valkey second level for the embedding cache, a `batched` embedder; and a `connector` slot with `rag sync`. |
| **You'll end up with** | hit rate, precision and MAP at k · faithfulness, answer relevance, context precision, correctness, citation precision/recall, abstention correctness · judges `lexical`, `llm` · run files (`--out`) · paired bootstrap + permutation A/B test · grid ablations · synthetic Q/A/evidence triples behind a human review gate · thumbs-down → candidate questions · exporters for Ragas, DeepEval, promptfoo, TruLens, Arize Phoenix · formatters `citations`, `json`, `confidence`, `follow-ups` · transformers `normalize`, `translate` · `cached` embedder with `store: valkey`, `batched` embedder · connectors `filesystem`, `s3` (+ `web`, `confluence`, `sharepoint`, `google-drive` as reference interfaces) · `rag sync` · ADR-0042. |
| **New words** | hit rate@k, precision@k, MAP, faithfulness, answer relevance, context precision, context recall, answer correctness, citation precision/recall, LLM-as-judge, run file, paired test, bootstrap interval, permutation test, ablation, synthetic test set, review gate, golden dataset, answer formatter, confidence score, structured answer, footnote citation, query normalisation, cross-lingual retrieval, prompt caching, KV cache, connector, incremental sync. |

## In plain English

> **IN PLAIN ENGLISH**
> Steps 25, 32-35 and 37 gave the platform *some* measurements: did search find the right
> document, did the answer cite it, did the canary do worse than the stable release. What was
> missing is the rest of the circle a team goes round every week: *how good* is the answer (true to
> its sources? on the question? correct?), *is the difference real or luck*, *which of my settings
> actually matters*, *where do new test questions come from*, and *how do real complaints become
> tests*. This extension closes that loop with commands that need no model (so CI can run them)
> and switch to a model judge when you have one.
>
> It also finishes the list of techniques people ask for: fixing typos and synonyms in questions,
> searching an English corpus with a German question, preferring new documents only when someone
> asks for "the latest", answers as footnotes or as JSON, a confidence score, suggested next
> questions, an embedding cache every replica shares, ingestion that respects the provider's rate
> limit, and connectors that keep the index in step with a folder or a bucket.

> **ANALOGY · A KITCHEN THAT TASTES ITS OWN FOOD**
> - **The tasting panel** (metrics and judges): not just "was the dish served" but "does it taste
>   like the recipe" (faithfulness), "is it what the guest ordered" (relevance), "is it the right
>   dish" (correctness). A machine taster scores every plate the same way; a chef (the LLM judge)
>   gives a finer opinion, and if the chef mumbles, the machine's score stands.
> - **The blind test** (A/B): the same guests taste both versions of the same dish, and you only
>   change the menu if the preference is clearly more than chance.
> - **The test kitchen** (sweep): try every combination of two salts, two ovens and two pans,
>   and rank them, to learn which choice actually changes the taste.
> - **Writing new recipes from the cookbook** (synthetic sets): a junior writes test questions from
>   the cookbook; the head chef approves each before it joins the official tasting menu.
> - **The complaints book** (feedback → golden set): every sent-back plate becomes a test the kitchen
>   must pass next week.
> - **The waiter's manners** (formatters): footnotes on the bill, a printed receipt (JSON), "the chef
>   is confident about this one", "you might also like…".
> - **The delivery van** (connectors): it checks the suppliers each morning and brings only what
>   changed, and takes off the shelf what the supplier stopped selling.

## What we're doing

1. Audit what existed (Step 26's `rag-evals`, `evaluate.py`, `online.py`, the gates) and fill the gaps.
2. Retrieval metrics at k: hit rate, recall, precision, MRR, MAP, nDCG.
3. Answer metrics and judges: faithfulness, answer relevance, context precision and recall,
   correctness against a reference, citation precision/recall, abstention correctness; `judge:
   lexical | llm`; run files.
4. A/B comparison with a paired significance test: `rag eval-compare`.
5. Ablations over a grid of `rag.yaml` settings: `rag eval-sweep`.
6. Synthetic test sets from the corpus and the human review gate: `rag eval-generate`, `rag eval-review`.
7. Feedback → candidate questions: `rag eval-candidates`.
8. Exporters to Ragas, DeepEval, promptfoo, TruLens, Arize Phoenix: `rag eval-export`.
9. The remaining techniques (checked one by one; existing ones explained, missing ones added):
   intent routing, spelling, synonyms, temporal questions, citation formats, JSON answers,
   confidence, follow-ups, cross-lingual search, prompt/KV caching, the embedding cache, rate
   limits, connectors.

## Why this matters

- **A number you can't trust is worse than none.** Two configurations scoring 0.91 and 0.93 on 25
  questions are usually *the same*; without a significance test teams ship noise and call it
  progress, then "regress" the next week.
- **Retrieval scores don't tell you if the answer is good.** A system can put the right document
  in the context and still write something the document doesn't say. Faithfulness and correctness
  catch that; recall@k can't.
- **Test sets go stale.** The questions written at launch don't cover the documents added since,
  or the questions people actually ask. Generating from the corpus and harvesting complaints keeps
  the set alive; a review gate keeps it honest.
- **Most knobs don't matter on your data, and a few matter a lot.** A sweep shows which, so you
  spend latency and model calls where they pay.
- **The remaining techniques are small, but they are what users notice:** a typo that finds
  nothing, "WFH" that isn't "remote work", the 2021 policy cited for "current", an answer a UI
  can't highlight, a re-index that dies at 40% on a rate limit.

## Audit: what already existed, and what this extension adds

| Area | Before | Now |
|---|---|---|
| Retrieval metrics | recall@k, MRR, nDCG@k in `rag eval-search`; precision@k in Step 26's `rag-evals` (rag-api retrieval) | + hit rate@k, precision@k, MAP in `rag eval-search` (`rag_core.evalkit.metrics`) |
| Answer metrics | context recall, answered, cite hit, abstain ok, grounded (Step 35); deterministic checks and an optional LLM judge for correct/faithful in `rag-evals` (Step 26) | + faithfulness, answer relevance, context precision, correctness (vs `reference`), citation precision/recall, abstention correctness per case, scored by the `judge` slot |
| LLM-as-judge | `rag-evals` judge (registered prompt `eval-judge`, errors never count as passes) | `judge: llm` for `rag eval-answers`, with a per-metric lexical fallback; the Step 26 judge is unchanged |
| Gates | `just search-eval`, `answer-eval`, `guard-eval` (`--fail-under`), `evals/gates.yaml` with a baseline (Step 26) | unchanged and still passing; `--fail-under` accepts the new metrics |
| Online evaluation | `rag online-eval` (Step 37): rates per release, two-proportion z-test, review queue | unchanged; its review queue now feeds `rag eval-candidates` |
| A/B | release vs release on live traffic (Step 37) | + offline, paired, per question: `rag eval-compare` |
| Ablations | hand-written `variants:` in the dataset | + `rag eval-sweep` over a grid |
| New questions | written by hand | + `rag eval-generate` (template or LLM) + `rag eval-review`; + `rag eval-candidates` from feedback |
| Other tools | none | + `rag eval-export` to five tools' formats |

## How it works

### 1. Retrieval metrics at k

All on the ranked list of **documents** (chunks of the same document count once), with the
dataset's `relevant` documents as the labels:

| Metric | Question it answers | Formula, in words |
|---|---|---|
| hit rate@k | Did we find *anything* useful? | 1 if any relevant document is in the top k |
| recall@k | Did we find *everything* that matters? | relevant found in top k ÷ all relevant |
| precision@k | How much noise reaches the model? | relevant in top k ÷ k |
| MRR | How high is the first right answer? | 1 ÷ rank of the first relevant document, averaged |
| MAP | All of them, early? | mean of precision@i at each relevant rank i, ÷ min(relevant, k), averaged |
| nDCG@k | Are the relevant ones near the top? | gains discounted by log2(rank + 1), ÷ the ideal ordering's |

`precision@k` is low on the handbook (0.217) by design: most questions have one right document
and k is 5. Watch its *change*, not its level.

### 2. Answer metrics and judges

`rag eval-answers` now captures, per question, the exact context the model was shown (through the
pipeline's `before_generation` hook), the answer and the citations, and scores:

| Metric | Meaning | Needs |
|---|---|---|
| faithfulness | share of the answer's sentences supported by the context (content words, **every number exact**) | nothing |
| relevance | share of the question's content words the answer addresses | nothing |
| context precision | are the relevant documents ranked high *in the context*? (mean precision@i at relevant positions) | `relevant` |
| context recall | relevant documents in the context (Step 35); with a `reference`: share of its claims the context supports | `relevant` or `reference` |
| correctness | token F1 against the `reference` answer, 0 if a number differs | `reference` |
| citation precision / recall | cited documents that are relevant / relevant documents cited | `relevant` |
| abstention correct | said "I don't know" exactly when nothing relevant exists | `relevant` (empty = should abstain) |

These are the **lexical** versions of Ragas-style metrics: deterministic, free, offline, and good at
regressions ("faithfulness fell from 1.0 to 0.8 after the prompt change"). They can't recognise a
correct paraphrase. A model judge can:

```yaml
judge: {use: llm, llm_slot: judge_llm}    # a different, stronger model than the answerer
```

The judge must reply with one JSON object of numbers in [0, 1]; anything else is a **judge error**
(counted in the run file), and that metric falls back to the lexical score: never a free pass.
`reference: "…"` on a question turns on correctness; six handbook questions carry one.

**Run files.** `--out runs/` writes one JSON file per variant (`format: rag-core-run/1`): the
summary row and every case with its question, reference, answer, contexts (text and document),
citations and per-case metrics. They are what A/B tests and the exporters read, and a record of
what was measured.

### 3. A/B with a significance test: `rag eval-compare`

Both configurations answer the **same** questions, so compare per question (paired): `diff = B − A`.

```
per metric:  mean diff ─ 95% interval by paired bootstrap (resample questions 2,000 times)
                       └ p-value by paired permutation: flip the sign of each diff at random;
                         how often is |mean| as large? exact up to 16 questions, sampled above
verdict:     "B better" / "A better" only if p < alpha AND the interval excludes 0
             "no significant difference" otherwise; "too few" under 5 paired questions
```

On the handbook, `naive` vs `standard`: context precision +0.20 [+0.05, +0.35], p = 0.012, **B
better**; context recall +0.15, p = 0.125, **no significant difference** with 24 questions,
although every changed question moved the right way. That is the honest reading: grow the set
(or test on real traffic with `rag online-eval`) before claiming it. Latency (`ms`) counts lower as
better. `--fail-if-worse` makes it a CI gate for a candidate (exit 1 if B is significantly worse
on any metric).

### 4. Ablations: `rag eval-sweep`

```yaml
# examples/eval/sweep.yaml
grid:
  chunker.max_tokens: [200, 400]                          # slot.setting: one setting of the profile's component
  fusion: [rrf, {use: weighted, weights: {dense: 0.5, sparse: 0.5}}]   # slot: replace the component
  reranker: [none, {use: term-overlap, top_n: 30}]        # none switches it off
fixed: {retriever: hybrid}
```

Every combination (here 8) is built on the profile, ingests the corpus if it changes ingestion,
answers the same questions, and is ranked (`--rank-by`, best first; any leak puts a row last; ties
go to the faster one). On the handbook the reranker is the setting that matters (MRR 1.000 with
it, 0.972-0.979 without, at every chunk size and fusion), and chunk size makes no difference: read
rows that differ in one key only. `--set key=v1,v2` adds an axis without a file;
`--max-combinations` (64) stops an accidental 1,000-run grid; `--suite answers` sweeps the answer
pipeline instead.

### 5. Synthetic test sets and the review gate: `rag eval-generate`, `rag eval-review`

```
corpus (as the dataset's person may read it) ─▶ the profile's parsers, cleaners, chunker
  ─▶ sentences worth asking about (numbers, rules: must / within / at least …), different chunks first
  ─▶ template: 'In "Annual leave policy", what number fills the gap: "Full-time staff get ___ days…"?'
     or llm:   {"question", "answer", "quote"} kept only if the quote IS in the passage
               and the answer is made of the passage's words (else the template)
  ─▶ question + reference + relevant document + evidence {document, chunk_id, quote, start, end}
     + review: pending
```

- **Template questions** copy the passage's wording: they test retrieval and citation plumbing
  and catch regressions, but they flatter keyword search and don't measure paraphrase robustness.
  `--mode llm` writes natural questions; review them anyway.
- **Only documents the dataset's person may read** are used, so the access-control questions in the
  original set don't turn into "should answer" questions.
- **The gate:** every evaluation command leaves out questions with `review: pending` or `rejected`
  (it says how many on stderr; `--include-unreviewed` to try them). `rag eval-review FILE --approve
  ID … --reject ID …` edits the file in place (comments kept); `rag eval-review FILE --check` exits
  1 while anything is pending: put it in CI for any dataset that gates a release.

### 6. Feedback → candidate questions: `rag eval-candidates`

```
audit log (Step 23) + /v1/feedback ─▶ rag_core.online.collect ─▶ answers rated down or flagged
   ─▶ candidate items: {id: fb-…, question: (from --texts, or "TODO: copy from trace t-…"),
                        relevant: [] (reviewer fills), review: pending,
                        source: {answer_id, trace_id, release, why, context_ids, cited_ids}}
   ─▶ --out candidates.yaml, or --append-to examples/eval/handbook.yaml (comments kept, no duplicates)
```

The audit log holds no question or answer text (Step 23's design), so a candidate carries its
trace id; the reviewer reads the trace where the text lives (Langfuse/Tempo, under its own
retention), writes the question, the documents that answer it (or none: "it should have said I
don't know") and a reference, and approves it. `--texts` takes a JSONL export of `{answer_id,
question, answer}` to pre-fill. Run it daily; the same answer is never proposed twice.

### 7. Exporters: `rag eval-export`

| `--to` | Writes | Load it with |
|---|---|---|
| `ragas` | JSONL: `user_input`, `retrieved_contexts`, `response`, `reference` | `ragas.EvaluationDataset.from_list(...)` |
| `deepeval` | JSON test cases: `input`, `actual_output`, `expected_output`, `retrieval_context` | `EvaluationDataset().add_test_cases_from_json_file(...)` |
| `promptfoo` | a config replaying stored answers through the `echo` provider, with `context-faithfulness`, `answer-relevance`, `factuality`, `context-recall` asserts | `promptfoo eval -c file.yaml` |
| `trulens` | virtual records: `main_input`, `main_output`, the retriever call's contexts | `TruVirtual` / `VirtualRecord` |
| `phoenix` | OpenInference spans (a CHAIN span with a RETRIEVER child per case) | a DataFrame → `px.Client().log_traces(TraceDataset(df))` |

Status **reference**: plain files in each tool's documented input shape, no package installed or
imported (none of them enters `uv.lock`). Check the shape against the version you install.

### 8. Answer formatters: citations, JSON, confidence, follow-ups

A new plural slot runs **after** citations are checked and the output guards pass, in order, and
writes into `Answer.extras` (rag-api: the new `extras` field of `/v1/answer`, also in the
streamed `done` event):

```yaml
answer_formatters:
  - {use: confidence, abstain_below: 0.3}      # extras.confidence: {score, label, signals}
  - {use: follow-ups, n: 3}                    # extras.follow_ups: ["…?"]
  - {use: citations, style: footnotes}         # [^1] + a footnote list; extras.citations: quotes with offsets
  - {use: json}                                # extras.json: {answer, abstained, citations, confidence, follow_ups[, fields]}
```

- **`citations`**: `style: numeric` keeps `[doc 1]`; `footnotes` writes `[^1]` and appends
  `[^1]: Leave policy, "Full-time staff get 25 days…"`. With `quotes` (default), each cited source
  gets the sentence that best supports the answer sentences citing it, with `start`/`end`
  **character offsets in the chunk** so a UI can highlight it; `append_quotes` shows them as `>`
  lines under a numeric answer.
- **`json`**: the answer as an object checked against a JSON Schema (a dependency-free subset:
  type, enum, const, required, properties, additionalProperties, items, min/max length, items and
  values). Built from the checked answer, it is always valid offline. `fields:` (or `fields_file:`)
  adds your own schema (`{days: integer}`) that a model fills from the answer and sources; an
  invalid reply is retried with the errors (`retries`), then left out and reported in
  `extras.json_errors`, never passed on unchecked. `as_text: true` makes the answer text the JSON.
- **`confidence`**: 0..1 from support (sentences whose words and numbers are in the sources),
  citations (sentences that cite) and coverage (question words found in the sources), weighted
  (`weights`). Labels high / medium / low. **Not a probability**: calibrate `abstain_below` on your
  own questions before using it to withhold answers.
- **`follow-ups`**: questions the shown sources can answer, from the cited documents first (and
  other sources only if they share `min_overlap` with the question), so a suggestion never leads to
  "I don't know" or to a document the person can't see. `mode: llm` asks a model and keeps only
  suggestions made of the sources' words.

A formatter that throws is skipped and named in the trace's flags: formatting never takes an
answer down. Blocked answers (a fixed message) are not formatted; abstentions are (a JSON client
still gets JSON). With `stream: live`, the streamed words are the raw text and the `done` event
carries the formatted answer: use `stream: checked` for footnotes or `as_text` JSON.

### 9. Query clean-up, synonyms, translation, time

| Technique | Status | Switch |
|---|---|---|
| Intent routing, "no retrieval" | **already there**: `pipeline: adaptive` replies to small talk with no search and no model, splits compound questions, `router: llm` classifies with a model (Step 35); `retriever: router` routes by topic (extension 01) | unchanged |
| Spelling and normalisation | **new** `normalize` | `query_transformer: normalize` |
| Acronyms and synonyms | `expand-terms` had acronyms → **extended**: `synonyms` (both directions), multi-word keys, a glossary `file`, `mode: variants` | `{use: expand-terms, file: glossary.yaml}` |
| Recency | `recency` post-processor existed → **extended** with `when: asked` | `{use: recency, when: asked}` |
| Dates in questions | `self-query` had "after 2025", "in March 2026", "this/last year" → **extended** with rolling windows | "in the last 6 months", "past 2 weeks" |
| Cross-lingual | **new** `translate` (and notes below) | `{use: translate, mode: glossary}` |

- **`normalize`**: Unicode NFKC, curly quotes and non-breaking spaces, invisible control characters,
  repeated punctuation, spaces; then each word of 4+ letters not in the vocabulary is replaced by
  the most frequent vocabulary word within 1 edit (2 for words of 8+ letters; adjacent swaps count
  once). The vocabulary is the keyword index's words **from the chunks this person may read**
  (otherwise "bonuss" → "bonus" would reveal a word from an executive-only document), plus
  `vocabulary` / `vocabulary_file`. Numbers, codes ("E-4021") and `protected` words are never
  touched, and the question as typed is searched too (`include_original`). Use it in a `chain`
  before `expand-terms`.
- **`translate`**: detects the question's language from function words (en, de, fr, es, nl, it, pt;
  "und" when unsure). `passthrough` (default) changes nothing: the right choice with a
  **multilingual embedder** (BGE-M3, multilingual-e5, Qwen3-Embedding, Cohere multilingual), which
  already places "Urlaub" near "annual leave". `glossary` replaces known words and phrases; `llm`
  asks a model and falls back to passthrough. Keyword search is the part that needs translation:
  BM25 can't match "Urlaub" to "leave". For documents in several languages, keep `language` in
  chunk metadata (the `metadata` enricher detects it) and filter or route by it.
- **Temporal reasoning** is three cooperating parts: `self-query` turns stated periods into filters
  ("updated in the last 6 months" → `updated >= today − 180 days`); `recency` prefers newer
  documents when relevance is close, and with `when: asked` only when the question asks for the
  newest ("latest", "current", "now", "this year", … in `cues`), so "what *was* the 2021 policy?"
  isn't pushed to 2026; and replace-not-append ingestion (Step 31) keeps one version per source.

### 10. Embeddings: a shared cache, batching and rate limits

```yaml
embedder:
  use: cached
  store: valkey                        # a second level behind the in-process LRU
  url_file: /run/bao/valkey_url
  ttl_seconds: 2592000                 # 30 days: vectors of a replaced model expire on their own
  inner:
    use: batched                       # at the provider's pace
    batch_size: 64
    requests_per_second: 5
    max_retries: 3                     # timeouts, 429s, 5xx; doubled backoff
    inner: {use: gateway, model: embedder, dimensions: 1024, …}
```

- **Valkey second level:** keys are `namespace:sha256(model, kind, text)`, so vectors of different
  models never mix; MGET and pipelined SETs (two round trips per batch); a new pod, a restart or a
  re-ingestion after a deploy embeds nothing seen before. If Valkey is down the embedder carries on
  without it (a warning, not an error). Status: tested with a stand-in (fakeredis).
- **`batched`:** fixed batches, a requests-per-second ceiling shared by threads, retries with
  doubled backoff for transient errors; `ValueError`/`TypeError` (bad input) are raised at once.
  The gateway (Step 10) still enforces budgets and rate limits per key; this keeps a big re-index
  under them instead of failing at 40%.

### 11. Prompt caching and KV caching: notes for providers

Not a component, because it happens in the model server, but it changes cost and latency a lot:

- **What it is:** a model server keeps the internal state (the KV cache) of a prompt's beginning;
  the next request with the **same prefix** skips recomputing it. Hosted APIs bill those tokens at
  a discount. Examples (check each provider's current documentation for limits and prices):
  Anthropic (explicit `cache_control` breakpoints, passed through by LiteLLM), OpenAI (automatic
  for long prompts), Google Gemini (implicit and explicit context caching), and on your own
  servers vLLM's automatic prefix caching, SGLang's RadixAttention, llama.cpp's prompt cache and
  mlx-lm's prompt cache (Step 7).
- **What it helps here:** the fixed part of every answer prompt (the registered system prompt and
  instructions, Step 24) comes first, then the documents, then the question; so the system prompt
  is always a shared prefix. Documents differ per question, so they are rarely shared, except in
  conversations (the same context again) and in `long-context` / `speculative`, where the same
  documents are sent several times.
- **Keep the prefix stable:** don't put dates, request ids or the user's name before the documents;
  keep the prompt version fixed for a release (labels, Step 24). Prompt caching is **not** the
  answer cache (Step 33, whole answers) nor the search cache (extension 01): it saves compute, not
  calls, and never changes an answer.

### 12. Connectors and `rag sync`

```yaml
connector:
  use: filesystem                      # or s3: {bucket: rag-raw-docs, prefix: policies/}
  root: /data/handbook
  patterns: ["**/*.md", "**/*.pdf"]
  exclude: ["**/.*", "**/~$*"]         # hidden files, Office lock files
  access: {classification: internal, groups: [all-staff]}
  rules:                               # the longest matching prefix wins
    - {prefix: hr/, classification: confidential, groups: [hr]}
```

```
rag sync:  list the connector (path/key, version = mtime+size or ETag, access from the rules)
   new or version changed       ─▶ fetch + ingest (identical content is still skipped by hash)
   same version, other access   ─▶ update_access in every store (no re-embedding, Step 36)
   same version, same access    ─▶ nothing (not even downloaded)
   in the manifest under this connector's prefix, not listed ─▶ delete everywhere
rag sync --watch --interval 60     poll forever; a failed round is retried next interval
rag sync --enqueue                 jobs for `rag worker` (Step 31's queue) instead of ingesting here
rag sync --dry-run | --no-delete | --max-items 500 | --json
```

- **Never deletes after a failed listing** (an unmounted share must not empty the index), and only
  under its own prefix (a second connector's documents are safe).
- **Event-driven instead of polling:** S3 event notifications or a webhook can call `rag enqueue`
  per object (Step 14's bucket already holds the originals); polling and events end in the same
  pipeline, so they can be mixed.
- **`web`, `confluence`, `sharepoint`, `google-drive`** are **reference interfaces**: their settings
  are declared and validated (a profile naming one passes `rag config validate`, and the catalogue
  lists them), but building one fails with *"the 'confluence' connector is a reference interface
  and is not configured in this platform…"*. To add one, implement `list()` (yield `uri`,
  `version`, `access`, `metadata`) and `fetch()` (return a `Source`) in your project and register it
  under your own name (Step 38's plugins); the hard part is **mapping the source's permissions to
  groups** (page restrictions, sharing settings) before anything is marked `internal`. Until then,
  export to a folder or bucket and use `filesystem` / `s3`.

## How to switch it on in rag.yaml

```yaml
profiles:
  my-project:
    extends: platform/local
    query_transformer: {use: chain, steps: [normalize, {use: expand-terms, file: glossary.yaml}, {use: rewrite, llm_slot: llm}]}
    postprocessors:
      - {use: dedupe, threshold: 0.85}
      - {use: recency, weight: 0.3, when: asked}
      - {use: max-per-document, n: 3}
    answer_formatters: [confidence, {use: citations, style: footnotes}, follow-ups]
    judge: {use: llm, llm_slot: judge_llm}
    connector: {use: s3, bucket: rag-raw-docs, prefix: policies/, access: {groups: [all-staff]}}
```

```bash
# the loop, offline
uv run rag eval-answers examples/eval/handbook.yaml --profile offline --variant naive --variant standard --out runs/
uv run rag eval-compare --runs runs/naive.answers.json runs/standard.answers.json
uv run rag eval-sweep examples/eval/handbook.yaml --profile offline --grid examples/eval/sweep.yaml --rank-by mrr
uv run rag eval-generate --from examples/eval/handbook.yaml --profile offline --out examples/eval/generated.yaml
uv run rag eval-review examples/eval/generated.yaml --approve gen-annual-leave-1 && uv run rag eval-review examples/eval/generated.yaml --check
uv run rag online-eval --events audit.jsonl --queue review.jsonl          # Step 37
uv run rag eval-candidates --events audit.jsonl --append-to examples/eval/handbook.yaml
uv run rag eval-export runs/standard.answers.json --to ragas --out standard.ragas.jsonl
# formatters and sync, on one command
RAG__ANSWER_FORMATTERS='[confidence, {use: citations, style: footnotes}, json]' \
  uv run rag ask "How many days a week can I work from home?" --profile offline --group all-staff --classification internal --corpus examples/eval/handbook.yaml --json
uv run rag sync --profile my-project --dry-run
```

## When to use which

Measured offline on the handbook (25 questions; hashing embedder, extractive answers, lexical
judge): `standard` scores faithfulness 1.000, relevance 0.706, context precision 0.921,
correctness 0.582 (6 questions with a reference; extractive answers quote more than the reference
says), citation precision/recall 0.955. These describe the plumbing, not a model: run them with
`--profile local` for yours.

| Situation | Choose |
|---|---|
| A quick regression gate in CI | `just search-eval` / `answer-eval` with `--fail-under` (lexical judge, no model) |
| "Is the answer true to its sources?" at scale | `judge: llm` on `judge_llm`; spot-check it against people's ratings first |
| "Is B really better than A?" | `rag eval-compare` (paired); on live traffic, `rag online-eval` (Step 37) |
| "Which setting matters?" | `rag eval-sweep` with 2-3 values per key, then compare the winners with `eval-compare` |
| Few labelled questions | `rag eval-generate --mode llm`, review, approve |
| Real failures should become tests | `rag online-eval --queue` + `rag eval-candidates` weekly |
| The team already uses Ragas / DeepEval / promptfoo / TruLens / Phoenix | `rag eval-export` and score there too |
| Typos and odd spacing in questions | `normalize` (first in a `chain`) |
| Company jargon, synonyms | `expand-terms` with a glossary file |
| Questions in other languages, one-language corpus | a multilingual embedder; + `translate` (`llm` or `glossary`) for keyword search |
| "Latest / current" questions, many versions | `recency` with `when: asked`; `self-query` for stated periods |
| A UI that highlights sources | `citations` (quotes with offsets) |
| Printed or emailed answers | `citations: {style: footnotes}`, `stream: checked` |
| Another program reads the answer | `json` (+ `fields` for extracted values) |
| "How sure is it?" | `confidence` (label in the UI); `abstain_below` only after calibrating |
| Help people continue | `follow-ups` |
| Several replicas, frequent re-ingestion | `cached` with `store: valkey` |
| Big re-index, strict provider limits | `batched` inside `cached` |
| A share or bucket that changes daily | `connector` + `rag sync --watch` (or `--enqueue` with workers) |
| Confluence, SharePoint, Drive, a website | export to a folder/bucket now; implement the reference connector with permission mapping |

## Trade-offs

- **Lexical metrics** are blind to paraphrase (a correct reworded answer scores lower) and can be
  fooled by copying (extractive answers are always "faithful"). **LLM judges** see meaning but cost a
  call per question, drift with the judge model, prefer long answers and their own style. Keep both;
  gate on the one you have validated.
- **Significance** needs questions: with 25, only large effects show. A "no significant
  difference" is not "no difference".
- **Sweeps** multiply runtime by the number of combinations and re-ingest for ingestion settings;
  keep grids small and offline first.
- **Template questions** are easy for keyword search; LLM questions can be wrong or leading; both
  need review, which is the point of the gate.
- **Feedback candidates** are biased toward what people bother to rate; mix them with generated and
  hand-written questions.
- **`normalize`** can "correct" a rare real word to a common one; that is why the original is
  searched too. Building the vocabulary walks the in-memory index per person (cached until it
  changes); with Postgres/OpenSearch indexes give it a `vocabulary_file`.
- **`translate: llm`** adds a call per non-English question; `glossary` is free but literal.
- **`confidence`** is a heuristic; `json` with `fields` adds a model call (and retries).
- **Valkey vectors** use memory (about 10-15 KB per 1024-dim vector as JSON); the TTL bounds it.
- **Polling** costs a listing per interval (cheap for thousands, slow for millions of objects: use
  events there).

## Common mistakes

> **WATCH OUT**
> - **Gating on an unreviewed generated set.** Generated questions are left out until approved;
>   don't `--include-unreviewed` in CI. Add `rag eval-review FILE --check` to the pipeline.
> - **Reading 0.93 vs 0.91 as a win.** Run `eval-compare`; check the interval, not just the mean.
> - **Changing two things in one variant.** A sweep row that differs in two keys can't say which
>   one helped.
> - **Judging with the answering model.** Use `judge_llm` (a different model), and count judge
>   errors: a judge that fails half the time is measuring its own format.
> - **A `reference` that isn't in the documents.** Correctness then rewards invention. The
>   reference is what the *documents* say.
> - **Spelling against the whole index.** Always per person (the default with `memory-bm25`); a
>   shared `vocabulary_file` must not contain restricted terms.
> - **`recency` without dates.** Undated chunks get `missing` freshness (0.5); add `updated` metadata
>   (the `metadata` enricher can extract dates).
> - **Expecting footnotes while streaming live.** Live deltas are the raw text; the `done` event has
>   the formatted one. Use `stream: checked`.
> - **`abstain_below` from a guess.** Calibrate on labelled questions: plot confidence against
>   correctness first.
> - **A connector without a manifest.** `rag sync` refuses: the manifest is how it knows versions and
>   what to delete.
> - **Access rules in the connector looser than the source.** The rules are the only permissions the
>   index gets; derive them from the source system's, and re-sync after changing them (only
>   permissions are updated).
> - **Two connectors with overlapping prefixes.** Each deletes what it doesn't list under its
>   prefix: give each its own root or bucket prefix.

## What was added to the repo

| Where | What |
|---|---|
| `libs/rag-core/src/rag_core/evalkit/` | `metrics` (retrieval and answer metrics), `runs` (run files), `stats` (bootstrap, permutation, verdicts), `sweep` (grids), `synth` (generation, review edits), `feedback` (candidates, append), `export` (five formats) |
| `components/judges.py` | `judge` slot: `lexical`, `llm` (per-metric fallback) |
| `evaluate.py`, `cli.py`, `evalcli.py` | new metrics in `eval-search` / `eval-answers`, `--out`, `--include-unreviewed`; `eval-compare`, `eval-sweep`, `eval-generate`, `eval-review`, `eval-candidates`, `eval-export`, `sync` |
| `components/formatting.py`, `answer.py`, `types.py` | `answer_formatters` slot: `citations`, `json` (schema validator), `confidence`, `follow-ups`; `Answer.extras` |
| `services/rag-api/src/rag_api/main.py` | `extras` in `/v1/answer` responses and the streamed `done` event |
| `components/querytext.py`, `retrieval.py`, `selfquery.py`, `basics.py` | `normalize`, `translate`; `expand-terms` synonyms/phrases/file/variants; `recency` `when: asked`; rolling date windows; per-person vocabulary of `memory-bm25` |
| `components/enrichment.py` | `cached` embedder `store: valkey`; `batched` embedder |
| `components/connectors.py`, `sync.py` | `connector` slot: `filesystem`, `s3`, reference `web` / `confluence` / `sharepoint` / `google-drive`; incremental sync and watch |
| `contracts.py`, `registry.py` | `AnswerFormatter`, `Judge`, `Connector` contracts; slots `answer_formatters`, `judge`, `connector` |
| `rag.yaml`, `profiles/platform.yaml`, `examples/eval/` | the options in comments; six reference answers in `handbook.yaml`; `sweep.yaml` |
| Tests | `test_evaluation_loop_ext04.py`, `test_techniques_ext04.py`, `test_ingestion_ext04.py` (fakeredis, moto) |
| Docs | this page, ADR-0042, handbook sections 7, 11, 13, 19 and 20, glossary, catalogue |
