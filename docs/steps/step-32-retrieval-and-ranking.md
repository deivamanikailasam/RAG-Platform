# Step 32 · Retrieval and ranking: finding the right chunks

*Step 32 of 38 · Phase H · RAG core*

## At a glance

| | |
|---|---|
| **Goal** | For any question, from any permitted person, return the few chunks that best answer it, quickly, with a record of why each one was chosen, and with every technique switchable in `rag.yaml`. |
| **How, in one sentence** | A search pipeline in rag-core runs five switchable stages (transform the question, retrieve with vectors and/or keywords, fuse the lists, rerank the best candidates, post-process), re-checks access on everything, traces every stage, and an evaluation command scores any combination on labelled questions. |
| **Time** | About 3 hours. |
| **You'll end up with** | 9 query transformers: identity, expand-terms (acronyms), with-history (no-LLM follow-ups), rewrite, multi-query, HyDE, decompose, step-back, and a chain of any of them · 3 retrievers (dense, keyword, hybrid) that run in parallel, and 3 fusion methods (RRF, weighted, DBSF) · 5 rerankers: the gateway's cross-encoder (TEI locally, Cohere/Voyage/Jina in cloud), TEI directly, an LLM listwise reranker, an in-process cross-encoder, and an offline baseline; all fail open · 7 post-processors: min-score, dedupe, max-per-document, MMR diversity, parent and window expansion, recency · `rag search` (with every score shown) and `rag eval-search` (recall, MRR, nDCG, leaks, latency per variant), a 17-document sample handbook with 25 labelled questions, and a CI gate · rag-api's `/v1/search` on rag-core (`RAG_API_SEARCH_BACKEND=core`), still checked by OPA and audited · gateway and PII keys from OpenBao files; the registered query instruction (Step 24) used by the embedder · 38 new tests, including the whole pipeline against real Postgres; ADR-0032. |
| **New words** | dense retrieval, sparse (keyword) retrieval, hybrid search, fusion, RRF, min-max normalisation, DBSF, query transformation, query rewriting, multi-query, HyDE, query decomposition, step-back prompting, reranking, cross-encoder, bi-encoder, listwise reranking, fail open, MMR, recency boost, recall@k, MRR, nDCG. |

## The big idea

> **ANALOGY · A GOOD REFERENCE LIBRARIAN**
> Ask a good librarian "how long can I be off when the baby comes?" and watch what they do:
> - They rephrase it in the library's words: "parental leave".
> - They look in two places: the subject catalogue (by meaning) and the index at the back of each book
>   (exact words).
> - They merge what both turned up, favouring what appears in both.
> - They skim the most promising few, reading your question and each page together, and put the best on
>   top.
> - They tidy the pile: no two copies of the same page, not five pages from one book, the current edition
>   rather than the old one.
> - They never hand you a book from the locked room you aren't allowed in, even if it was the best match.
>
> The search pipeline is that librarian, with each habit a part you can switch on, off or for another.

### The search pipeline (Figure 101)

```
 question                transform                           RETRIEVE · each text, in parallel, filtered by access
 + who is asking    →    rewrite · multi-query · HyDE    →     dense (vectors): same meaning          →   fusion
 + conversation,         decompose · step-back · terms         keyword (BM25 / FTS): same words, codes     rrf · weighted · dbsf
   filters
                                                                                                          ↓
 top k               ←   post-process                    ←   rerank (top_n)                  ←   access re-check
 with every score        min-score · dedupe · MMR · cap      cross-encoder via gateway, TEI,     a chunk the caller may
 kept                    parent/window · recency             LLM listwise; fails open            not see is dropped and counted
```

Every box is a slot in `rag.yaml`. Every stage is a trace span; the result carries the components, texts,
counts and milliseconds. The question (with who is asking) is transformed into one or more search texts;
each is searched by meaning and by words in parallel, inside each store's access filter; the lists are
fused; access is checked again; the best `top_n` are reranked; post-processors tidy the list; the top k
come back with every score kept.

## What we're doing

1. Transform the question when it helps: expand acronyms, resolve follow-ups, paraphrase, imagine an
   answer, split or generalise it.
2. Retrieve by meaning (vectors), by words (BM25 / full-text) or both, for every search text, in parallel.
3. Fuse the ranked lists into one.
4. Re-check access on every candidate (defence in depth).
5. Rerank the best candidates with a model that reads question and passage together.
6. Post-process: drop weak and duplicate chunks, cap per document, diversify, expand to parents or
   windows, prefer fresh content.
7. Measure every combination on labelled questions, and gate CI on it.
8. Serve it from rag-api behind the same token, policy and audit checks.

## Why we're doing this

> **WHY THIS MATTERS**
> The model can only answer from what retrieval gives it. If the right chunk isn't in the top few, the answer
> will be wrong, vague or a confident invention, however good the model is. Retrieval fails in predictable
> ways, and each has a known fix:
> - **Different words:** the question says "holidays", the policy says "annual leave". Fix: vectors,
>   synonyms, multi-query.
> - **Exact codes and names:** "E-4021" means nothing to an embedding model. Fix: keyword search, hence
>   hybrid.
> - **Follow-ups:** "how do I fix it?" has no searchable words. Fix: rewrite with the conversation.
> - **Close but not quite:** ten chunks about leave, only one about parental leave for secondary carers.
>   Fix: a reranker.
> - **Repetition:** five near-identical chunks fill the context. Fix: dedupe, MMR, per-document caps.
> - **Old versions:** the 2021 policy outranks the 2026 one. Fix: recency, and Step 31's
>   replace-not-append.

| Need | How this step meets it |
|---|---|
| Find by meaning and by exact words | Dense, keyword or hybrid retrievers over any store from Step 31 |
| Mix lists fairly | RRF (rank-based, no tuning), weighted (score-based), DBSF (spread-based), with per-source weights |
| Better questions | Nine transformers, from free (acronyms, history) to LLM-powered (rewrite, multi-query, HyDE, decompose, step-back) |
| Precise top results | Cross-encoder reranking through the gateway, TEI, in-process, or an LLM; offline baseline for CI |
| No waste in the context | Min-score, dedupe, MMR, per-document caps, parent/window expansion, recency |
| Never leak | Access filtered inside every store and re-checked in the pipeline; OPA post-check in rag-api |
| Never go down because a helper did | LLM transformers fall back to the question; rerankers fail open (logged, counted) |
| Know why | Every hit keeps its dense, sparse, fusion and rerank scores; every stage is a span with counts and timings |
| Decide with numbers | `rag eval-search`: recall@k, MRR, nDCG@k, leaks, latency per variant; a CI gate |

> **IN A COMPANY**
> Search quality is a product decision with risk attached: a regulator, an auditor or a customer may ask why
> the assistant showed a document. Mature teams therefore keep per-hit explanations (scores per stage), a
> labelled evaluation set owned by the business (not only engineers), gates that block a change that lowers
> recall or leaks a restricted document, and a fallback that keeps search working when a model service is
> down. Everything here maps onto that: explanations in `scores`, `examples/eval/handbook.yaml` as the
> pattern for a real set, `just search-eval` in CI, fail-open rerankers.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Dense retrieval** | Search by meaning: the question and chunks are turned into vectors (Step 8) and the closest vectors win. Finds "holiday" when the text says "annual leave". |
| **Sparse / keyword retrieval** | Search by words: BM25 or Postgres full-text. Finds "E-4021" exactly; misses synonyms. |
| **Hybrid search** | Both, merged. The usual production default. |
| **Fusion, RRF** | Merging ranked lists. Reciprocal Rank Fusion scores each chunk by 1/(60 + its rank) in each list, summed: only positions matter. |
| **Min-max, DBSF** | Two ways to put scores of different kinds on one scale before adding them: stretch each list to 0–1, or scale it by its own spread. |
| **Query transformation** | Changing what is searched for: expanding, rewriting, paraphrasing, imagining an answer, splitting or generalising the question. |
| **HyDE** | "Hypothetical Document Embeddings": let an LLM write a plausible answer, then search with that, because answers look like answers. |
| **Bi-encoder vs cross-encoder** | A bi-encoder embeds question and passage separately (fast, for search); a cross-encoder reads them together and scores the pair (slow, much more precise, for reranking). |
| **Reranking, listwise** | Re-ordering the top candidates with a stronger model. Listwise: an LLM sees all candidates at once and returns their order. |
| **Fail open** | When a helper (reranker, rewriter) fails, continue without it and record that, rather than failing the whole request. |
| **MMR** | Maximal Marginal Relevance: choose results that are relevant and different from those already chosen. |
| **recall@k, MRR, nDCG@k** | Was the right document in the top k? How high was the first right one (1, ½, ⅓…)? How good is the whole order (higher is better, 1 = perfect)? |

> **IN PLAIN ENGLISH**
> Query transformation decides *what to look for*; retrieval *looks*; fusion *merges what two kinds of
> looking found*; reranking *reads the best few carefully*; post-processing *tidies the pile*. Each is
> optional, each is one line in `rag.yaml`, and the evaluation command tells you whether switching one on
> actually helped your documents.

### Fusion, by example (Figure 102)

```
 dense (cosine)          keyword (BM25)          RRF: score = Σ 1 / (60 + rank)
 1. chunk A   0.82       1. chunk C   12.3       1. chunk A   1/61 + 1/62   0.0325
 2. chunk B   0.80       2. chunk A    4.1       2. chunk C   1/63 + 1/61   0.0323
 3. chunk C   0.41       3. chunk D    3.9       3. chunk B   1/62          0.0161
                                                 4. chunk D   1/63          0.0159
```

Scores of different kinds (0.82 vs 12.3) can't be added. RRF uses only positions: found high by both =
top. Chunk A (1st and 2nd) and chunk C (3rd and 1st) end up on top because both searches found them.
Weighted fusion scales each list to 0–1 first; DBSF scales by each list's spread. Measure which suits your
data.

## How to do it

All commands run from the repository root (`~/dev/rag-platform` on your Mac). Nothing in sections 1–5
needs any service running: the `offline` profile keeps everything in memory.

### 1 · The components

One file, `libs/rag-core/src/rag_core/components/retrieval.py`, holds every query transformer,
retriever, fusion method, reranker and post-processor. Each is registered with its settings, so
`rag components` lists them and `rag.yaml` picks them.

```bash
uv run rag components --kind query_transformer
uv run rag components --kind reranker          # five rerankers
uv run rag components --kind postprocessor
```

> **READING THE COMPONENTS**
> - `Passage` is a string with a label: "this is a hypothetical answer". Dense search embeds it as a
>   document (no query instruction, Step 8); keyword search skips it, because invented words are noise for
>   exact matching.
> - LLM transformers share one class and one safety rule: if the LLM call fails, search continues with the
>   question as asked. The built-in instructions can be replaced (`system:`), for example by a registered
>   prompt.
> - `rewrite` replaces the question (a follow-up becomes standalone); the others add texts to the original.
>   At most eight texts are searched.
> - Retrievers run every search at once in a small thread pool; `copy_context` carries the current trace span
>   into each thread, so the spans still nest correctly in Tempo (Step 21).
> - Fusion keeps every explanation: a chunk found by both searches carries `dense`, `sparse` and `fusion`
>   scores.
> - Rerankers read at most `top_n` candidates, cut each to `max_chars`, and add a `rerank` score. If the
>   service fails they keep the retrieval order, mark `rerank_skipped`, count the failure and log it
>   (`fail_open: false` makes it an error instead).
> - The LLM reranker parses "3 > 1 > 2"; anything it leaves out gets 0 (judged unhelpful); a reply with no
>   numbers counts as a failure.
> - Post-processors are small and composable: each takes the list and returns a list.

What each family contains:

| Kind | Name | What it does |
|---|---|---|
| query_transformer | `identity` | Search with the question exactly as asked. |
| | `expand-terms` | Add the meaning of known acronyms/jargon (`terms: {wfh: work from home}`): "Can I WFH on Fridays? (work from home)". No LLM. |
| | `with-history` | Prepend the last user turns (`turns: 2`) to the question: free, crude follow-up handling. |
| | `rewrite` | LLM: turn a follow-up into ONE standalone query; it replaces the question (the original is kept too when there is history). |
| | `multi-query` | LLM: `n` paraphrases, one per line (numbering and bullets stripped, duplicates dropped), searched and fused. |
| | `hyde` | LLM: a short hypothetical answer passage, embedded like a document. |
| | `decompose` | LLM: split a compound question into at most `n` simpler ones. |
| | `step-back` | LLM: add one more general "principle" question. |
| | `chain` | Several of the above in order (`steps: [{use: rewrite}, {use: multi-query, n: 2}]`); a HyDE passage passes through untouched. |
| retriever | `dense` / `keyword` / `hybrid` | Vector search, keyword search, or both fused by the `fusion` slot (RRF when unset). `candidates: 30` per text and store; `parallel: true`. |
| fusion | `rrf` | 1/(k + rank), `k: 60`; `weights: {sparse: 2}` per source. |
| | `weighted` | Min-max to 0–1 per list, weighted sum (`weights: {dense: 0.5, sparse: 0.5}`). |
| | `dbsf` | Scaled by mean ± 3 standard deviations per list (as in Qdrant). |
| reranker | `gateway` | The gateway's Cohere-style `/rerank` (alias `reranker`, Step 9): TEI locally, Cohere/Voyage/Jina in cloud. |
| | `tei` | TEI's own `/rerank` (Step 8), bypassing the gateway (no budgets, no logs). |
| | `llm` | Listwise reranking by the judge model; `top_n: 10`, `max_chars: 600`. |
| | `cross-encoder` | sentence-transformers in-process (`BAAI/bge-reranker-v2-m3`); status `reference`. |
| | `term-overlap` | Offline baseline: idf-weighted coverage of the question's words plus a phrase bonus. For tests and CI. |
| postprocessor | `min-score` | Drop candidates below `threshold` on a chosen `stage` score; `min_keep` keeps at least that many. |
| | `dedupe` | Drop near-copies (Jaccard similarity of word triples ≥ `threshold`, 0.85). |
| | `max-per-document` | At most `n` chunks per document. |
| | `mmr` | Maximal Marginal Relevance (`lambda: 0.7`; 1 = relevance only, 0 = diversity only); uses the embedder. |
| | `parent-expand` | Replace matched child chunks (Step 31's parent-child chunker) by their parent section; siblings merge into one candidate. |
| | `window-expand` | Replace a matched sentence (sentence-window chunker) by its window. |
| | `recency` | Blend relevance with freshness: `field: updated`, `half_life_days: 365`, `weight: 0.2`, `missing: 0.5`. |

### 2 · The pipeline

`libs/rag-core/src/rag_core/search.py` runs the stages in order:

```python
pipeline = SearchPipeline(config.load("rag.yaml", "local"))
result = pipeline.search(Query("How many days of leave?", principal, k=5))
result.hits      # ScoredChunk, best first; .scores shows dense/sparse/fusion/rerank per hit
result.trace     # which components ran, the search texts, counts and milliseconds per stage
```

> **READING THE PIPELINE**
> - No retriever configured? It picks hybrid if the profile has both stores, otherwise whichever exists.
> - Defence in depth: stores filter by access inside their own queries (Step 31's conformance tests prove
>   it). The pipeline checks again and drops and counts anything that slipped through (`pipeline.leaks`, a
>   span attribute and an error log), so a buggy plugin store can't leak.
> - The reranker reads the (rewritten) question, never a HyDE passage.
> - The result explains itself: components used, texts searched, counts after each stage, milliseconds per
>   stage. Spans: `rag.search`, `rag.search.transform`, `rag.search.retrieve`, `rag.search.rerank`,
>   `rag.search.post.<Name>`.

### 3 · Measure it

`libs/rag-core/src/rag_core/evaluate.py` compares search configurations on the same questions. A
dataset names its corpus, the person asking, the questions with the documents that answer them (and
documents that must NEVER appear), and *variants*: small changes to the profile, merged on top of it with
the same rules as `extends`. Each variant is built fresh, ingests the corpus (unless `--no-ingest`),
answers every question and gets document-level scores: recall@k, MRR, nDCG@k, leaks and latency.

The sample handbook in `examples/corpus/handbook/` is 17 short policies written for this guide, including
an outdated 2021 leave policy (to test recency) and a restricted executive-pay document (to test access).
`examples/eval/handbook.yaml` names the corpus (with an `updated` date per document), the person asking
(`all-staff`, public and internal), eleven variants and 25 questions of different kinds: paraphrases,
synonyms, acronyms, error codes, two-document questions, follow-ups, and one that must return nothing.

> **READING THE EVALUATION**
> - Document-level scores: a question is answered if a right document is in the top k, whichever chunk of
>   it was found. Step 26's harness scores answers; this scores retrieval alone, which is what you change
>   here.
> - Each variant is built fresh and ingests the corpus itself (offline profiles keep stores in memory). For
>   persistent stores, `--no-ingest` searches what's already there.
> - A leak fails the run, whatever the other scores.

### 4 · The command line

`rag search` searches as a given person and shows every score; `--ingest` loads files first into an
in-memory profile:

```bash
uv run rag search "My VPN shows E-4021" --profile offline --group all-staff \
  --ingest examples/corpus/handbook/*.md
```

Output in this repository:

```text
searched: ['My VPN shows E-4021']
pipeline: {'query_transformer': None, 'retriever': 'HybridRetriever', 'fusion': 'ReciprocalRankFusion', 'reranker': 'TermOverlapReranker', 'postprocessors': ['Dedupe', 'MaxPerDocument']}
counts:   {'retrieved': 30, 'reranked': 30, 'Dedupe': 30, 'MaxPerDocument': 30, 'returned': 5}   ms: {'transform': 0.0, 'retrieve': 2.6, 'rerank': 1.2, 'postprocess': 44.2}
1. 0.6493   vpn-troubleshooting.md > VPN troubleshooting   [dense=0.207 sparse=10.562 fusion=0.033 rerank=0.649]
     E-4021 means your device certificate has expired. Open Self Service, run "Reinstall VPN profile", then restart
2. 0.3322   vpn-troubleshooting.md > VPN troubleshooting > Error E-3003   [dense=0.150 sparse=8.099 fusion=0.032 rerank=0.332]
     E-3003 means split tunnelling was blocked by policy. Disconnect from public Wi-Fi networks that use a captive
3. 0.0000   laptop-policy.md > Laptops and devices > Personal use   [dense=0.107 fusion=0.016 rerank=0.000]
...
```

> **READING THE OUTPUT**
> The VPN page wins on every signal: keyword search scored it about 10.6 (the code "E-4021" is rare), dense
> search ranked it too, fusion put it first, and the reranker gave it 0.649. The other VPN chunk follows.
> Results 3–5 are filler with a rerank score of 0: in the `local` profile, the `min-score` post-processor
> drops those, so the model isn't handed irrelevant text.

`rag eval-search` compares every variant:

```bash
uv run rag eval-search examples/eval/handbook.yaml --profile offline
```

Output in this repository (offline profile: word-hash vectors, in-memory BM25):

```text
25 questions, profile 'offline', k=5

variant                             recall@5    MRR   nDCG@5  leaks  p50 ms
---------------------------------------------------------------------------
keyword                                0.958  0.958    0.958      0     1.7
dense                                  0.833  0.802    0.788      0     3.5
hybrid-rrf                             0.958  0.917    0.921      0     5.0
hybrid-weighted                        0.958  0.896    0.912      0     5.0
hybrid-dbsf                            0.958  0.896    0.912      0     7.6
hybrid+expand-terms                    0.958  0.917    0.921      0     5.2
hybrid+history                         1.000  0.979    0.978      0     5.6
hybrid+rerank                          0.958  0.958    0.958      0     6.0
hybrid+rerank+recency                  1.000  0.979    0.985      0     4.3
hybrid+mmr+per-doc                     1.000  0.925    0.935      0   185.5
all-together                           1.000  1.000    1.000      0     7.5
```

(The guide prints different figures for its own copy of the handbook, for example keyword 0.958 / MRR
0.799, dense 0.688, hybrid-rrf 0.771, all-together 0.958 / 0.854. Only the VPN page is printed in the
guide; the other 16 documents here were written for this repository, so the absolute numbers differ while
the lessons below hold.)

> **READ THESE NUMBERS CAREFULLY**
> These numbers measure mechanics, not models. The offline profile's hashing "embedder" only captures shared
> words, so dense search looks poor and hybrid looks no better than keyword alone. With Qwen3-Embedding (the
> `local` profile), dense search finds paraphrases that keyword search misses, and hybrid usually beats both.
> The lessons that do carry over: fusion choice matters, a reranker recovers a lot, recency fixes the
> old-policy problem, conversation history rescues follow-ups ("How do I fix it?"), MMR trades rank quality
> (MRR) for coverage, and MMR re-embeds candidates (about 185 ms here; reuse stored vectors or cache in
> production). Run the same file with `--profile local --no-ingest` on your Mac, after ingesting the
> handbook, to see your real numbers.

The same evaluation on real Postgres (pgvector for vectors, Postgres full-text search for keywords, a
throwaway database, 64-dimension hashing vectors), measured in this repository:

```text
variant                             recall@5    MRR   nDCG@5  leaks  p50 ms
---------------------------------------------------------------------------
keyword (postgres)                     0.958  0.931    0.938      0     2.6
dense (postgres)                       0.771  0.518    0.576      0     6.3
hybrid-rrf (postgres)                  0.958  0.889    0.903      0     9.5
hybrid-weighted (postgres)             0.958  0.910    0.917      0     9.3
all-together (postgres)                1.000  1.000    1.000      0    11.9
```

Postgres full-text search's English configuration stems words, so different forms of a word match
("claims", "claim"), and ignores stop words like "the". The in-memory index does neither; on the guide's
handbook that made Postgres rank noticeably better (MRR 0.904 vs 0.799).

A failing gate (what CI does): `--fail-under METRIC=VALUE` exits 1 when any variant scores below it, and
any leak always fails.

```bash
uv run rag eval-search examples/eval/handbook.yaml --profile offline --variant dense --fail-under recall=0.9
```

```text
variant                             recall@5    MRR   nDCG@5  leaks  p50 ms
---------------------------------------------------------------------------
dense                                  0.833  0.802    0.788      0     3.5
FAIL: dense: recall 0.833 < 0.9
exit=1
```

(The guide uses `recall=0.8`, which its dense score of 0.688 fails; on this repository's handbook dense
reaches 0.833, so the example uses 0.9.)

### 5 · Profiles

`rag.yaml` gains the search slots:

```yaml
  offline:
    # … ingestion (Step 31) …
    # search (Step 32)
    query_transformer: none    # identity | expand-terms | with-history | rewrite | multi-query | hyde | decompose | step-back | chain
    retriever: {use: hybrid, candidates: 30}     # dense | keyword | hybrid
    fusion: {use: rrf, k: 60}                    # rrf | weighted | dbsf
    reranker: {use: term-overlap, top_n: 30}     # offline stand-in for a cross-encoder
    postprocessors:
      - {use: dedupe, threshold: 0.85}
      - {use: max-per-document, n: 3}

  local:
    extends: offline
    llm: {use: gateway, model: qwen-fast, base_url: "http://litellm:4000/v1", api_key_file: /run/bao/rag_api_gateway_key}
    judge_llm: {use: gateway, model: qwen-quality, base_url: "http://litellm:4000/v1", api_key_file: /run/bao/rag_api_gateway_key}
    pii: {use: regex, strategy: pseudonymise, key_file: /run/bao/pii_hmac_key}
    embedder:
      use: cached
      inner: {use: gateway, model: embedder, dimensions: 1024, base_url: "http://litellm:4000/v1", api_key_file: /run/bao/rag_api_gateway_key,
              query_prompt: query-instruction, prompts_dir: /app/prompts}   # Step 24's registered instruction
    # … stores as in Step 31 …
    reranker: {use: gateway, model: reranker, base_url: "http://litellm:4000", top_n: 30, api_key_file: /run/bao/rag_api_gateway_key}
    postprocessors:
      - {use: dedupe, threshold: 0.85}
      - {use: min-score, stage: rerank, threshold: 0.05, min_keep: 1}
      - {use: max-per-document, n: 3}
```

> **READING THE PROFILES**
> - `offline`: hybrid retrieval, RRF, the offline reranker, dedupe and a per-document cap. Runs anywhere.
> - `local`: adds the real reranker (the gateway's `reranker` alias, Step 9: Qwen3-Reranker or
>   bge-reranker on TEI, Step 8) and a min-score on its 0–1 relevance, keeping at least one result. The
>   gateway key and the PII key are files written by OpenBao Agent; the embedder uses the registered query
>   instruction.
> - `local-engines` inherits all of it, with Qdrant and OpenSearch as the stores.
> - Switch anything without editing: `RAG__RERANKER__USE=none`, `RAG__RETRIEVER__USE=keyword`,
>   `RAG__QUERY_TRANSFORMER__USE=multi-query`, `RAG__FUSION__USE=weighted`.

```bash
for p in offline local local-engines; do uv run rag config validate --profile $p; done
```

### 6 · Secrets from files, the registered query instruction, document ids

Three small changes make the components production-ready.

**Secrets from files.** `basics.py` gains `FileSecret`, a `SecretStr` read from a file on *every* use, so a
key rotated by OpenBao Agent (Step 28) is picked up without a restart; never stored in config, never in an
environment variable. It reads the file once at start-up too, so a missing file stops start-up with the
slot's name ("reranker 'gateway' could not start …") instead of failing on the first request.
`gateway_key(env, file)` returns the file secret when a file is configured (containers), else the
environment variable (dev). The gateway LLM, embedder and rerankers gain `api_key_file`; the regex PII
redactor gains `key_file`. A new agent template writes the PII key (in both
`infra/config/openbao/agent-rag-api.hcl` and `deploy/base/rag-api/openbao-agent.hcl`):

```hcl
template {
  contents             = "{{ with secret \"secret/data/rag-api\" }}{{ .Data.data.pii_hmac_key }}{{ end }}"
  destination          = "/openbao/out/pii_hmac_key"
  perms                = "0400"
  error_on_missing_key = true
}
```

A random PII key, kept in SOPS, then in OpenBao:

```bash
openssl rand -hex 32                   # copy the output
sops secrets/dev.enc.env               # add a line: RAG_PII_HMAC_KEY=<the value>
# A KV write REPLACES the whole secret: put every rag-api value again, plus the new one
just vault-put rag-api gateway_key=RAG_API_GATEWAY_KEY opa_token=RAG_API_OPA_TOKEN \
  valkey_url=RAG_API_VALKEY_URL s3_access_key=S3_INGEST_ACCESS_KEY s3_secret_key=S3_INGEST_SECRET_KEY \
  pii_hmac_key=RAG_PII_HMAC_KEY
just vault-agent-start
```

(`scripts/new-dev-secrets.sh` already generates `RAG_PII_HMAC_KEY` since Step 31; if your
`secrets/dev.enc.env` has it, skip the first two lines.)

> **WATCH OUT · THE AGENT NOW NEEDS PII_HMAC_KEY**
> The new template uses `error_on_missing_key`, so the agent refuses to render anything until
> `pii_hmac_key` exists in `secret/rag-api`. That's deliberate (a missing key should stop ingestion, not
> silently disable pseudonymisation), but it means you must run the `vault-put` above before restarting the
> agent.

> **WATCH OUT · KEEP THE PII KEY FOR AS LONG AS THE INDEX**
> Pseudonyms are only stable while the key is. A new key gives every person a new token, so joins across old
> and new chunks break. Rotate it only together with a full re-index (Step 36's blue/green re-index), and
> keep it in OpenBao, never in `rag.yaml`.

**The registered query instruction.** The gateway embedder can now take its query instruction from the
prompt registry (Step 24) instead of a constant, so search uses the reviewed, versioned text that the audit
log records. `GatewayEmbedderParams` gains `query_prompt` (e.g. `query-instruction`), `prompts_dir`
(`/app/prompts` in the image) and `prompt_label` (`production`; staging sets
`RAG__EMBEDDER__INNER__PROMPT_LABEL=staging`). The embedder loads the registry (verifying the lock),
records which version shapes the vectors in `prompt_refs` (`["query-instruction@1"]`), and an unknown
prompt stops start-up ("embedder 'gateway' could not start").

> **A BUG THIS FIXED**
> The old fallback used `str.format`, so a question containing `{` or `}` would have crashed the embedder.
> Plain replacement treats it as text.

**Document ids.** Postgres rows now carry Step 11's numeric document id (`d.id`, as
`metadata["document_id"]`), which rag-api's policy post-check and audit events use.

### 7 · rag-api on rag-core

`/v1/search` keeps its contract (same request, same response, same token check, OPA decision, OPA
post-check and audit event). Only the backend changes, chosen by a setting:

- `services/rag-api/src/rag_api/search.py` gains `CoreSearch`, the same contract as `PgSearch`, answered
  by rag-core's pipeline. OPA still decides WHAT may be seen (the filter goes in as the principal's groups
  and classifications); rag-core decides HOW to find it (`rag.yaml`). No classifications: nothing (fail
  closed, exactly like `PgSearch`).
- `settings.py` gains `search_backend: Literal["legacy", "core"] = "legacy"`, `rag_config`
  (`/app/rag.yaml`), `rag_profile` (`local`) and `tenant` (`default`; one tenant per deployment until Step
  36).
- `main.py`'s `get_search()` returns `CoreSearch(s)` when `search_backend == "core"`, else `PgSearch`.
- Compose (`infra/compose/compose.yaml`, rag-api) and Kubernetes (`deploy/base/rag-api/deployment.yaml`)
  set `RAG_API_SEARCH_BACKEND=core` and `RAG_API_RAG_PROFILE=local`.

> **WHY BOTH BACKENDS STAY**
> - OPA still decides what may be seen; rag-core decides how to find it. The filter goes in as the
>   principal's groups and classifications, and the OPA post-check runs on the results exactly as before.
> - Chunks become documents: the pipeline is asked for three times as many chunks as documents, then the
>   best chunk of each document gives its score, so one long policy can't fill the list.
> - Rolling back is one setting (`legacy`), merged through a pull request like any promotion (Step 29).
>   Keep `legacy` until Step 26's harness on your real data says `core` is at least as good; then remove it.
> - Ingest first: the core backend reads rag-core's collection (`default`), which Step 31's worker fills.
>   Run `rag enqueue --profile local …` for your documents before switching.

### 8 · Gates in CI

The `justfile`'s `ci-config` recipe gains two lines, and two recipes:

```make
ci-config:
    # … (as before)
    just rag-config-check
    just search-eval

# rag.yaml: every profile names real components with valid settings (Step 30), no services needed
rag-config-check:
    for p in offline local local-engines; do uv run rag config validate --profile $p; done

# Search quality gate (Step 32): the shipped search settings must keep finding the handbook answers,
# and must never return a forbidden document. Offline: no models or stores needed.
search-eval *args:
    uv run rag eval-search examples/eval/handbook.yaml --profile offline --variant all-together --fail-under recall=0.9 --fail-under mrr=0.8 {{args}}
```

> **TIP · GROW THE QUESTIONS**
> 25 questions catch broken code, not small quality changes (one question is 4 points of recall). Add a
> question for every search bug you fix, and build a project's own file from real questions (Step 37 collects
> them from feedback and traces). Keep forbidden documents in it: the leak check is the one gate that must
> never be relaxed.

### 9 · Test it

```bash
uv run pytest -q libs/rag-core/tests/test_retrieval.py services/rag-api/tests/test_core_search.py
just audit-test        # everything, including the live Postgres test
just search-eval
```

- `libs/rag-core/tests/test_retrieval.py`: the guide's 34 tests of fusion, retrievers and access,
  transformers, rerankers, post-processors, the pipeline, the evaluation and the CLI, the registered query
  prompt and file secrets.
- `services/rag-api/tests/test_core_search.py`: 3 tests of `/v1/search` on rag-core with the shipped
  handbook ingested (offline profile), through the real token check, OPA test double and audit log.
- `libs/rag-core/tests/test_stores.py::test_hybrid_search_on_postgres_end_to_end`: the handbook ingested
  into pgvector + Postgres FTS, searched through the whole pipeline, scored by the same evaluation; needs
  `RAG_TEST_PGVECTOR_DSN` (a throwaway Postgres with pgvector), which `just audit-test` provides.

> **WHAT THE TESTS PROVE**
> - Fusion: RRF uses ranks only and keeps every source's score; weights change winners; weighted and DBSF
>   reward "good in both".
> - Access: dense, keyword and hybrid never return a chunk Alice, Bob or another tenant may not see; a buggy
>   store that ignores permissions is caught by the pipeline.
> - Transformers: multi-query parses numbered lines and drops duplicates; rewrite uses the conversation;
>   HyDE passages are embedded as documents and not keyword-searched; LLM failures fall back to the question;
>   chains compose.
> - Rerankers: the gateway request is exactly Cohere-style with the key, only `top_n` candidates are sent, cut
>   to `max_chars`; TEI's format; fail open and fail closed; LLM listwise parsing; two rerankers pass the new
>   reranker conformance check.
> - Post-processors: each one's rule, including MMR promoting a different chunk, parent expansion merging
>   siblings, and recency preferring the newer policy only when relevance is close.
> - Pipeline and evaluation: traces, defaults, the reranker reading the question, metric arithmetic, the CLI
>   gate failing, rag-api's `/v1/search` on rag-core with OPA and audit, and the whole pipeline on real
>   Postgres.
> - Secrets: keys come from files and rotate without a restart; a missing file stops start-up with the
>   slot's name.

### 10 · Record the decision

`docs/adr/0032-search-through-a-switchable-hybrid-pipeline.md` records the decision: rag-core's
SearchPipeline (transform, none by default → hybrid retrieval inside each store's access filter → RRF k=60
→ access re-check → rerank the top 30 with the gateway cross-encoder, failing open → dedupe, min-score on
rerank relevance, max 3 per document → top k), with per-stage scores, traces, `rag eval-search` gated in CI,
and rag-api's `/v1/search` on it behind the same OPA and audit checks, with `legacy` kept for rollback.

## Benefits

- Finds both meanings and exact codes, and each technique is one line of config.
- Explains itself: per-hit scores per stage, per-stage counts and timings, all traced.
- Safe by construction: access filtered in the store, re-checked in the pipeline, post-checked by OPA in
  rag-api.
- Resilient: helpers that fail don't take search down; the failure is visible.
- Measured, not guessed: one command compares any set of variants, and CI holds the line.
- Reusable: rag-api, a future chat service and offline jobs all use the same pipeline.

## Drawbacks and risks

- **Latency adds up:** a reranker adds tens to hundreds of milliseconds; LLM transformers add a model call
  (or several) before search even starts. Budget it against Step 20's SLO (p95 under 2 s).
- **Cost:** multi-query and HyDE multiply embedding calls; LLM reranking is expensive. Step 10's budgets
  apply because everything goes through the gateway.
- **Thresholds are corpus-specific:** a min-score that works on policies may drop good answers on tickets.
  Tune with evaluation.
- **Small evaluation sets mislead:** with 25 questions, differences under ~5 points are noise.
- **Over-transforming:** a rewriter that "improves" a precise question can lose the one word that mattered.
  Keep `include_original` unless measured otherwise.
- **MMR re-embeds candidates on every request;** cache or reuse stored vectors at scale.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Client-side hybrid + RRF (default) | Search each store, fuse in rag-core | Any store; one behaviour everywhere |
| Qdrant Query API (prefetch + fusion) | Hybrid and fusion inside Qdrant, one call | Qdrant is your only store and latency is tight |
| OpenSearch / Elasticsearch hybrid query | Normalisation and combination inside the engine | OpenSearch is your search platform |
| Weaviate / Vespa / Milvus hybrid | Engines with built-in hybrid ranking | You run one of them already |
| SPLADE / learned sparse | Keyword-style vectors that also know synonyms | Keyword precision with some meaning, one index |
| ColBERT / late interaction | One vector per token, matched token by token | Highest quality, more storage |
| Cohere / Voyage / Jina rerank | Hosted cross-encoders | Cloud deployments, via the gateway reranker |
| bge-reranker / Qwen3-Reranker / mxbai | Open cross-encoders on TEI or llama.cpp | Local or self-hosted (Step 8) |
| RankGPT-style LLM reranking | An LLM orders candidates | Hard, reasoning-heavy questions; small `top_n` |
| Self-query / metadata extraction | An LLM turns "policies updated this year" into a filter | Rich metadata; covered by routing in Step 35 |
| LangChain / LlamaIndex / Haystack retrievers | Framework building blocks | Prototyping; wrap them as rag-core plugins if needed |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| General enterprise documents | Hybrid + RRF + cross-encoder rerank + dedupe + per-document cap (the `local` default) |
| Error codes, part numbers, legal citations | Keyword weight up (`weights: {sparse: 2}`), or the keyword retriever |
| Users ask in different words from the documents | Dense weight up, `multi-query` or HyDE; measure the cost |
| Chat assistants | `rewrite` (LLM) or `with-history` (free) for follow-ups |
| Compound questions ("X and Y?") | `decompose` or `multi-query`, plus a larger k |
| Many versions of the same document | Replace-not-append (Step 31), `recency`, `dedupe` |
| Long documents dominate results | `max-per-document` |
| Answers need surrounding context | Parent-child chunking + `parent-expand`, or sentence windows + `window-expand` |
| Tight latency budget | No transformer, smaller `top_n`, or no reranker; measure what you lose |
| "Say I don't know" when nothing fits | `min-score` on rerank relevance (Step 33 turns an empty result into an honest abstention) |

## Common mistakes

- Vector-only search for content full of codes and names.
- Adding raw scores from different searches (cosine + BM25) instead of fusing.
- Reranking only the top 5 (the reranker can't promote what it never sees) or the top 500 (too slow).
- Letting a reranker outage fail every search.
- Filtering permissions after retrieval only: the top 30 may all be forbidden and the user gets nothing
  (filter inside the store, then check again).
- Embedding the question without the query instruction, or the documents with it (Step 8).
- Tuning on the test questions until they pass, then shipping: keep a held-out set.
- Logging the question text in traces (Step 19 masks content; keep it that way).

## Done when

- [ ] `uv run rag components --kind reranker` lists five rerankers.
- [ ] `uv run rag search "My VPN shows E-4021" --profile offline --group all-staff --ingest examples/corpus/handbook/*.md`
      puts the VPN page first, with all four scores.
- [ ] `uv run rag eval-search examples/eval/handbook.yaml --profile offline` prints the comparison with 0
      leaks; `just search-eval` passes.
- [ ] The PII key is in OpenBao and `/run/bao/pii_hmac_key` exists in the agent's output.
- [ ] With the handbook ingested into the platform: `rag eval-search … --profile local --no-ingest` gives
      your real-model numbers.
- [ ] `RAG_API_SEARCH_BACKEND=core` is set; `/v1/search` answers, OPA post-check and audit events unchanged.
- [ ] `just audit-test` passes (the guide counts 385 tests at this point).
- [ ] ADR-0032 is committed.

## Recap

> **RECAP**
> Finding the right chunks is now a configurable, measurable pipeline:
> - transform questions when it pays (nine options, from free to LLM-powered)
> - retrieve by meaning and words in parallel, fuse fairly (RRF, weighted, DBSF)
> - rerank with a cross-encoder that fails open, tidy with seven post-processors
> - never leak: store filter, pipeline re-check, OPA post-check
> - prove it: recall, MRR, nDCG, leaks and latency per variant, gated in CI
>
> Next, Step 33: turning the chunks into an answer: context packing, citations, abstaining, streaming,
> conversation memory and caching, behind `/v1/answer`.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-core/src/rag_core/components/retrieval.py` | The 9 query transformers, 3 retrievers, 3 fusion methods, 5 rerankers and 7 post-processors, all registered |
| `libs/rag-core/src/rag_core/search.py` | `SearchPipeline` and `SearchResult`: transform → retrieve → access re-check → rerank → post-process, traced |
| `libs/rag-core/src/rag_core/evaluate.py` | Datasets, variants merged onto a profile, recall@k / MRR / nDCG@k / leaks / p50 per variant, the results table |
| `libs/rag-core/src/rag_core/cli.py` (changed) | `rag search` and `rag eval-search` (with `--fail-under`) |
| `libs/rag-core/src/rag_core/components/basics.py` (changed) | `FileSecret`, `gateway_key()`; the gateway LLM's `api_key_file` |
| `libs/rag-core/src/rag_core/components/enrichment.py` (changed) | Gateway embedder: `api_key_file`, the registered query prompt (`query_prompt`, `prompts_dir`, `prompt_label`, `prompt_refs`), plain substitution instead of `str.format` |
| `libs/rag-core/src/rag_core/components/cleaning.py` (changed) | Regex PII redactor's `key_file` |
| `libs/rag-core/src/rag_core/components/pgstore.py` (changed) | Rows carry Step 11's numeric `document_id` |
| `libs/rag-core/src/rag_core/testing/conformance.py` (changed) | `check_reranker`: the conformance check every reranker must pass |
| `libs/rag-core/src/rag_core/__init__.py` (changed) | Module map mentions ingest, search and evaluate |
| `libs/rag-core/tests/test_retrieval.py` | The guide's 34 search tests |
| `libs/rag-core/tests/test_stores.py` (changed) | The whole pipeline and evaluation on live Postgres |
| `libs/rag-core/tests/test_cli_ingest.py` (changed) | Ingests only the files directly in `examples/corpus/` (not the new handbook folder) |
| `examples/corpus/handbook/*.md` | The 17-document sample handbook (including the 2021 leave policy and the restricted executive pay document) |
| `examples/eval/handbook.yaml` | Corpus, principal, 11 variants and 25 labelled questions |
| `rag.yaml` (changed) | Search slots in `offline`; real reranker and min-score in `local`; keys from `/run/bao` files; the registered query instruction |
| `services/rag-api/src/rag_api/search.py` (changed) | `CoreSearch` and `_document_id` |
| `services/rag-api/src/rag_api/settings.py` (changed) | `search_backend`, `rag_config`, `rag_profile`, `tenant` |
| `services/rag-api/src/rag_api/main.py` (changed) | `get_search()` picks the backend |
| `services/rag-api/tests/test_core_search.py` | `/v1/search` on rag-core through token, OPA and audit |
| `infra/compose/compose.yaml` (changed) | rag-api uses the core backend with profile `local`; the ingestion worker no longer takes keys from environment variables |
| `deploy/base/rag-api/deployment.yaml` (changed) | `RAG_API_SEARCH_BACKEND=core`, `RAG_API_RAG_PROFILE=local` |
| `infra/config/openbao/agent-rag-api.hcl`, `deploy/base/rag-api/openbao-agent.hcl` (changed) | Render `pii_hmac_key` |
| `tests/test_vault.py` (changed) | The live agent test seeds `pii_hmac_key` and checks the rendered file |
| `justfile` (changed) | `rag-config-check` and `search-eval`, both in `ci-config` |
| `pyproject.toml` (changed) | mypy skips the optional `sentence_transformers` import |
| `.env.example`, `docs/runbooks/openbao.md` (changed) | `pii_hmac_key` in OpenBao; never rotate it on its own |
| `docs/adr/0032-search-through-a-switchable-hybrid-pipeline.md` | ADR-0032 |
| `docs/glossary.md`, `docs/adr/README.md`, `docs/steps/README.md`, `CHANGELOG.md` (changed) | New terms, indexes, changelog |

## Notes for this repository

- **Code reconstructed from the PDF.** The listings were extracted from the PDF and their indentation and
  line wraps rebuilt. Two tidy-ups that don't change behaviour: the hybrid retriever builds its jobs from
  two helper methods on the shared base class (`_dense_jobs`, `_sparse_jobs`) instead of calling
  `DenseRetriever._jobs(self, …)` with a `type: ignore`; and the factory of the LLM transformers is defined
  once outside the registration loop. The pipeline reads the reranker's `top_n` with `getattr`, so a plugin
  reranker without that attribute still works.
- **The CLI was extended, not replaced.** The guide prints a whole new `cli.py`; Step 31's version here
  already had small improvements (local paths turned into `file://` URIs, typed helpers), so `search` and
  `eval-search` were added to it. `--fail-under` with an unknown metric name is reported as an error
  instead of a Python traceback.
- **The handbook was written for this repository.** The guide shows only `vpn-troubleshooting.md` (copied
  exactly) and describes the other 16 documents by name and by the questions they must answer, so they were
  written from those questions and the snippets visible in the guide's output (titles such as "Annual leave
  policy", "Parental leave policy", "Laptops and devices", "Executive compensation 2026"). The evaluation
  numbers therefore differ from the guide's printed tables; the VPN search output matches it to the digit.
- **The cross-encoder extra is not locked.** `reranker: cross-encoder` imports `sentence-transformers`
  (status `reference`). As with Step 31's Docling and Presidio, the extra is not declared in rag-core's
  `pyproject.toml`: it would add PyTorch and dozens of packages to `uv.lock` for everyone (and pin
  `huggingface-hub` back a major version). A project that wants it runs `uv add sentence-transformers`;
  mypy is told to skip the import.
- **The ingestion worker's keys.** Step 31 gave the Compose worker `LLM_GATEWAY_KEY` and
  `RAG_PII_HMAC_KEY` environment variables because the `local` profile read keys from the environment.
  Now that the profile reads `/run/bao/rag_api_gateway_key` and `/run/bao/pii_hmac_key` (files the agent
  writes into the volume the worker already mounts), those two variables were removed. Until Step 37 gives
  the worker its own identity, it uses rag-api's gateway key.
- **One Step 31 test adjusted.** `test_ingest_the_corpus_offline` listed everything in `examples/corpus/`;
  it now takes only files, because the handbook lives in a sub-folder.
- **What was validated here.** ruff, strict mypy and the full pytest suite (600 passed); the live Postgres
  tests (including the new end-to-end search) against a throwaway `pgvector/pgvector:0.8.1-pg17` container;
  `just rag-config-check` and `just search-eval`. The OpenBao agent tests need the `bao` binary and were
  skipped here; the Compose/Kubernetes agent configs are still checked to render the same files by
  `tests/test_k8s.py`. Real models (the `local` profile's gateway reranker and embedder) can't run in this
  container.
