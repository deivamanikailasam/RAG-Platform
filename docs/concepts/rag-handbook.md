# The RAG handbook: concepts, techniques and how to switch them

> **IN PLAIN ENGLISH**
> RAG (retrieval-augmented generation) means: before a language model answers, *look things up* in
> your own documents and give it the relevant passages, so it answers from them instead of from
> memory, and says which passage each claim came from. Doing that well is a chain of choices: how to
> read files, how to cut them into passages, how to find the right passages, how to put them in front
> of the model, and how to check the result. In this platform every one of those choices is a named,
> swappable part. This handbook explains each technique in everyday terms, when to pick it, what it
> costs, what else exists, and the exact line in [`rag.yaml`](../../rag.yaml) that switches it.

Every component listed here is in the generated [catalogue](../catalogue.md) (159 components in 31
kinds, with every setting and default). The steps that built them: [30](../steps/step-30-rag-core-contracts-and-components.md)
(core), [31](../steps/step-31-ingestion-pipeline.md) (ingestion), [32](../steps/step-32-retrieval-and-ranking.md)
(retrieval), [33](../steps/step-33-augmentation-and-generation.md) (answers),
[34](../steps/step-34-guardrails.md) (guardrails), [35](../steps/step-35-rag-architectures.md) (architectures).

**Two companion pages.** The [decision guide](decision-guide.md) takes the whole pipeline one link at
a time and says, for every option (in this repository or not), when to use it, when not to, the
trade-off and where it is, with a flowchart for choosing an architecture and validated
[starter configs](decision-guide.md#starter-configs). The [coverage matrix](coverage-matrix.md)
answers "do we have X?" item by item.

Contents: [1 · RAG in one picture](#1-rag-in-one-picture) · [2 · How switching works](#2-how-switching-works) ·
[3 · Parsing](#3-parsing-reading-files) · [4 · Cleaning and PII](#4-cleaning-and-personal-data) ·
[5 · Chunking](#5-chunking-strategies) · [6 · Enrichment](#6-contextual-enrichment) ·
[7 · Embeddings](#7-embeddings-and-caching) · [8 · Retrieval](#8-retrieval-dense-keyword-hybrid) ·
[9 · Fusion](#9-fusion-combining-result-lists) · [10 · Reranking](#10-reranking-and-post-processing) ·
[11 · Query transformations](#11-query-transformations) · [12 · Context packing](#12-context-packing-and-generation) ·
[13 · Citations and abstention](#13-citations-and-abstention) · [14 · Streaming](#14-streaming) ·
[15 · Memory](#15-conversation-memory) · [16 · Caching](#16-answer-caching-exact-and-semantic) ·
[17 · Guardrails](#17-guardrails) · [18 · Architectures](#18-rag-architectures) ·
[19 · Measuring a change](#19-how-to-know-a-change-helped) · [20 · Cheat sheet](#20-cheat-sheet-situation--choice)

---

## 1. RAG in one picture

```text
 INGESTION (once per document change)                       QUESTION TIME (every request)
 file → parse → clean → redact PII → chunk → enrich →        question → (rewrite) → retrieve: dense + keyword
        embed → index (vectors + keywords + access labels)              → fuse → rerank → filter/shape
                                                                        → pack numbered context → generate
                                                                        → check citations → guards → answer
```

Why bother instead of just asking the model?

| Problem with a model alone | What RAG adds |
|---|---|
| It doesn't know your company's documents | Passages from them, at question time |
| It can't say where a claim came from | Numbered sources and checked citations |
| Its knowledge is frozen at training time | Re-ingest a changed document and the next answer uses it |
| It can't respect who may see what | Only passages the person may read are ever retrieved |
| It invents when unsure | Abstain when nothing relevant is found |

The alternatives: **fine-tuning** teaches style and format, not reliable facts with sources; **long
context** (paste whole documents) works for a handful of small documents but is slow, costly and
ignores permissions at scale. RAG is the default for "answer from our documents".

## 2. How switching works

A **profile** in `rag.yaml` says which component fills each **slot** ([ADR-0030](../adr/0030-build-rag-on-a-shared-core-of-switchable-components.md)):

```yaml
profiles:
  offline:                                   # runs with nothing else running (tests, CI, demos)
    chunker: {use: structure, max_tokens: 400, overlap_tokens: 40, min_tokens: 60}
    retriever: {use: hybrid, candidates: 30}
  local:
    extends: offline                         # inherit, then change only what differs
    reranker: {use: gateway, model: reranker, base_url: "http://litellm:4000", top_n: 30, api_key_file: /run/bao/rag_api_gateway_key}
```

The rules:

- `slot: {use: <name>, <setting>: <value>}`; `use: none` switches an optional slot off.
- `extends:` inherits a profile. Same component → only the named settings change; another component →
  the slot is replaced.
- **For one run, without editing anything**: environment variables `RAG__<SLOT>__<SETTING>`, e.g.
  `RAG__RERANKER__USE=none`, `RAG__CHUNKER__MAX_TOKENS=300`, `RAG__ENRICHERS='[context-header, graph-entities]'`.
- Secrets never go in the file: components take the *name* of a file (`api_key_file`, `credentials_file`,
  `url_file`, `key_file`) or of an environment variable (`api_key_env`).

The profiles shipped: `offline` (in-memory everything, no services), `local` (pgvector, Postgres full
text, gateway models, Valkey), `local-engines` (Qdrant + OpenSearch instead), `local-v2` (the next
collection for a blue/green re-index), `production` (local's parts, stricter: `uncited: abstain`,
`stream: checked`, full guard list).

```bash
uv run rag components [--kind reranker]            # what can go in each slot
uv run rag config validate --profile local         # names and settings valid (no services needed)
uv run rag config show --profile local             # the fully resolved profile
uv run rag config readiness --profile production   # fit for production?
```

After editing `rag.yaml`, run `just sync-profiles` (rag-core ships a copy for projects) and
`just rag-config-check`.

---

## 3. Parsing (reading files)

**What it is.** Turning a file into text *with its structure*: headings, lists, tables, page numbers.
Structure matters later: chunkers keep sections together and citations can say "page 4".

| Component | Reads | Notes |
|---|---|---|
| `markdown` | `.md` | Headings, lists, tables, code blocks as structure |
| `html` | `.html` | Drops nav, footer, scripts |
| `pdf` | `.pdf` text layer (pypdf) | Keeps page numbers; **flags scanned pages** with no text (`min_chars_per_page`) |
| `docx` | Word | Heading styles, lists, tables |
| `csv` | `.csv` | One element per row (or per N rows), columns named |
| `text` | plain text | Paragraphs on blank lines |
| `docling` | PDF/DOCX/HTML/images | Layout-aware, OCR and table structure (reference; extra `docling`) |
| `tika` | Legacy Office, email, RTF… | Apache Tika server, text only |

**Switch:** `parsers: [markdown, html, pdf, docx, csv, text]` (the parser is chosen by detected file type).
**Choose** Docling for scanned archives and complex layouts; the built-ins otherwise.
**Alternatives:** Unstructured.io, cloud document-AI services (ADR-0031 keeps them as options).
**Watch out:** silently indexing scanned pages as empty; splitting tables into word soup.

## 4. Cleaning and personal data

**Normalisers** fix the text: `unicode` (NFKC, control characters, hyphenated line breaks, whitespace)
and `boilerplate` (drops repeated headers, footers, banners and duplicate paragraphs).
**Switch:** `normalizers: [unicode, boilerplate]`.

**PII redaction** happens **before** anything is stored, so personal data never reaches an index,
cache, trace or log ([ADR-0031](../adr/0031-ingest-through-a-replace-not-append-pipeline.md)).

| Strategy | What the stored text says | Choose when |
|---|---|---|
| `mask` | `[EMAIL]` | Nobody needs to know *which* person (offline default) |
| `pseudonymise` | A keyed token: the same email always gives the same token | You need "same person" joins without the identity (`local`); keep the key as long as the index |
| `remove` | Nothing | Minimal data |

| Component | Detects | Trade-off |
|---|---|---|
| `regex` | Emails, cards, AU TFN/ABN, IBAN, phones, IPs, **with checksums** (fewer false hits) | Fast, offline; misses names |
| `presidio` | Adds names and places (NER) and more identifiers | Slower, needs extra models |

**Switch:** `pii: {use: regex, strategy: pseudonymise, key_file: /run/bao/pii_hmac_key}`.
Readiness **fails** a production profile without a PII component.

## 5. Chunking strategies

**What it is.** Cutting documents into passages ("chunks") small enough to match a question precisely
and to fit many into the model's context, but big enough to make sense alone.

| Chunker | How it cuts | Best for | Cost / risk |
|---|---|---|---|
| `structure` (default) | By section: never crosses a heading, keeps tables and code whole, records the heading path | Policies, handbooks, wikis | Needs structure in the source |
| `recursive` | Paragraphs, then sentences, then words, only as fine as needed | Unstructured long text | Can split mid-topic |
| `fixed` | Every N tokens with overlap, ignoring structure | A baseline to beat | Splits sentences and tables |
| `sentence-window` | One sentence per chunk; neighbours kept for the answer (with `window-expand`) | FAQs, short precise facts | Many tiny chunks |
| `semantic` | Cuts where the topic changes (embedding similarity drops) | Transcripts, chats | Slower ingestion (embeds every sentence) |
| `parent-child` | Search small children, give the model the larger parent (with `parent-expand`) | Contracts, manuals: answers need surrounding detail | More storage; two sizes to tune |
| `hierarchical` | A tree of any depth (document > section > … > paragraph); leaves know their ancestors (with `auto-merge` or `section-expand`) | Long manuals with deep headings | Larger metadata per leaf |
| `proposition` | One self-contained fact per chunk (LLM, grounded-checked; rules offline); passage kept for `window-expand` | Precise factual questions over dense prose | 3-5× more chunks; an LLM call per passage |
| `code` | Source code at top-level definitions, with symbols and line numbers | Repositories, scripts, SQL | Pattern-based, not a parser |

**Switch:** `chunker: {use: parent-child, parent_tokens: 1200, child_tokens: 200, child_overlap: 20}` and
add `{use: parent-expand}` to `postprocessors`; for sentence windows add `{use: window-expand}`.
**Key settings:** `max_tokens` (default 400), `overlap_tokens` (40), `min_tokens` (60). The embedder's
contract caps chunks at its own limit (`max_chunk_tokens` in [`models.yaml`](../../infra/model-serving/models.yaml)).
Structure chunks also record `heading`, `section_path` and `section_numbers`, so a filter, the
`section` retriever or `section-expand` can return an exact section ([extension 02](../extensions/02-chunking-indexing-compression.md#4-exact-sections)).
Late chunking is an embedder option (section 7). **Alternatives:** agentic/LLM chunking; measure
against `structure`.
**Watch out:** one chunk size for every document type, never measured.

## 6. Contextual enrichment

**What it is.** Adding context to what gets *embedded* (not to what is shown) so a chunk is findable
out of context. "Section 4.2: 20 days" means nothing alone; "Annual leave policy > Entitlement: 20 days"
does.

| Enricher | Adds | Cost |
|---|---|---|
| `context-header` (default) | "Title > Section" | Free, strong |
| `llm-context` | An LLM-written sentence situating the chunk in its document ("contextual retrieval") | One LLM call per chunk |
| `questions` | The questions the chunk answers | One LLM call per chunk |
| `graph-entities` | Records named things (codes, acronyms, phrases) per chunk in the graph store | For `graph` RAG |
| `summary-tree` | RAPTOR: summaries of clusters of chunks, then of the summaries, indexed next to the chunks | An embedding per level; an LLM call per cluster (extractive offline) |
| `summary` | One summary chunk per document (a "document summary index"); `summary-expand` adds its best chunks | One LLM call per document (extractive offline) |
| `metadata` | Filterable facts: dates, language, document type, keywords (TF-IDF/YAKE), entities (regex) | Free |
| `llm-metadata` | The fields you declare, filled by an LLM and checked against the schema | One LLM call per document |

**Switch:** `enrichers: [context-header, llm-context]`. **Choose** LLM context for transcripts and
long unstructured text; measure recall gain against ingestion cost. Citations always show the
original chunk text, never the enriched text. LLM-written summaries and metadata are stored only
when they pass a deterministic check ([extension 02](../extensions/02-chunking-indexing-compression.md#3-metadata-extraction-at-ingestion)).

## 7. Embeddings and caching

**What it is.** An embedding model turns text into a list of numbers (a vector) so that texts with
similar *meaning* are close together. Questions get an **instruction prefix** ("Given an employee
question, retrieve passages…") registered as the prompt `query-instruction`; documents don't.

| Component | What |
|---|---|
| `gateway` | Any embedding model behind LiteLLM (here Qwen3-Embedding-0.6B, 1024 dims), batched, dimension-checked |
| `cached` | Wraps any embedder: the same text is never embedded twice (LRU; `store: valkey` shares it across replicas and restarts, E04) |
| `batched` (E04) | Wraps any embedder: fixed batches, a requests-per-second ceiling, retries with backoff for big re-indexes |
| `hashing` | Offline, deterministic word-hash vectors for tests and CI (readiness refuses it in production) |
| `instructed` | Query/passage prefixes for asymmetric models: presets `e5`, `bge`, `nomic`, `qwen3`, … |
| `matryoshka` | Keeps the first N dimensions of a Matryoshka-trained model (or `request_dimensions: true` on `gateway`) |
| `late-chunking` | Embeds the whole document, then pools each chunk's token vectors (context for "it", "this") |

**Switch:** `embedder: {use: cached, inner: {use: gateway, model: embedder, dimensions: 1024, …}}`.
Keeping the index in step with a folder or bucket: `connector: {use: filesystem | s3, …}` and
`rag sync [--watch]` ingest only what changed ([extension 04](../extensions/04-evaluation-loops-and-remaining-techniques.md#12-connectors-and-rag-sync)).

> **WATCH OUT · THE EMBEDDING CONTRACT**
> Model, revision, dimensions, normalisation, pooling and query instruction must match between
> indexing and searching. Changing any of them means a full re-index: `rag reindex --profile local
> --to local-v2 --apply` into a new collection, compare with `rag eval-search`, then switch by PR
> ([Step 36](../steps/step-36-lifecycle-threat-model-compliance.md)). That's also why the gateway has no
> fallback for the embedder.

Other vector databases (Weaviate, Milvus, Pinecone, Elasticsearch, Vespa, managed cloud search…) and when
each wins: [decision guide](decision-guide.md#vector-databases).
**Alternatives:** bigger embedders (Qwen3-Embedding-4B/8B), hosted embeddings (OpenAI, Cohere,
Voyage, Jina, Mistral, Gemini, Bedrock) through a gateway alias. How to choose (language, domain,
context length, dimensions, MTEB, cost, local vs API) and switch: [extension 02](../extensions/02-chunking-indexing-compression.md#7-choosing-an-embedding-model-and-switching-it-through-the-gateway).

## 8. Retrieval: dense, keyword, hybrid

| Retriever | Finds by | Strong at | Weak at |
|---|---|---|---|
| `dense` | Meaning (vector similarity) | Paraphrases, synonyms ("WFH" ≈ "remote work") | Codes, names, rare exact terms |
| `keyword` | Words (BM25) | Error codes, part numbers, names | Different wording |
| `hybrid` (default) | Both, in parallel, then fused | Enterprise documents with both | Two searches per query |

Every store filters **inside the query** by tenant, classification and groups, and every store passes
the same conformance tests, including access-leak tests.

| Slot | Options |
|---|---|
| `vector_store` | `pgvector` (default: HNSW on halfvec), `qdrant`, `opensearch-knn`, `memory` (tests) |
| `keyword_index` | `postgres-fts` (default, no extra service), `opensearch` (analysers, synonyms), `memory-bm25` (tests), `sparse` / `qdrant-sparse` (sparse vectors from the `sparse_embedder` slot: `bm25` or SPLADE via `splade-tei`) |

**Switch:** `retriever: {use: hybrid, candidates: 30}`; engines via the `local-engines` profile.
**Choose** Postgres first; add Qdrant/OpenSearch when scale or keyword features demand it.

**Similarity metric and index settings** ([extension 01](../extensions/01-retrieval-math-filters-fusion.md)). Every vector store takes
`metric: cosine | dot | l2 | l1` (use what the embedding model was trained for; cosine for this
platform's model), `index_type: hnsw | flat | ivfflat`, `hnsw_m`, `ef_construction`, `ef_search`, and
quantization where supported (pgvector `binary`, Qdrant `scalar`/`binary`, with rescoring). Scores
always mean "higher = more similar". The store refuses to search an index built for another metric or
size (the embedding contract); `rag index ddl` prints the index a non-cosine collection needs.

**Metadata filters** narrow a search to documents whose metadata match: `{"department": "hr",
"updated": {"gte": "2025-01-01"}}` with eq, ne, in, nin, gt/gte/lt/lte, range, exists, and/or/not.
Each store applies them inside its own query, always ANDed with the permission filter (a filter can
only narrow). Use `rag search --filter department=hr`, `"filter"` in `/v1/search` and `/v1/answer`,
or `filters=` in the SDK.

| Retriever | Use |
|---|---|
| `ensemble` | Several retrievers (another collection, model or profile) in parallel, fused with per-member weights |
| `router` | One index per department/language/product: keyword rules or an LLM pick the route |
| `section` | "Section 4.2" or a heading title in the question: that exact section first, then the usual results |

**Alternatives:** engine-native hybrid queries (ADR-0032's "revisit when"); learned sparse (SPLADE)
and late interaction (ColBERT) are now components ([extension 02](../extensions/02-chunking-indexing-compression.md#6-embedding-options)).

## 9. Fusion: combining result lists

Dense and keyword scores are on different scales; you can't add them. Fusion combines the *lists*.

| Fusion | How | When |
|---|---|---|
| `rrf` (default, `k: 60`) | Reciprocal rank fusion: uses ranks only | No tuning needed; robust |
| `weighted` | Min-max normalised scores, weighted sum | You've measured that one side deserves more (`weights: {dense: 0.5, sparse: 0.5}`) |
| `dbsf` | Distribution-based (mean ± 3 std devs), as in Qdrant | Score distributions differ a lot |

| `relative-score` | Same maths as `weighted`, set with one `alpha` (Weaviate's relative score fusion) | Tuning dense vs keyword with one number |
| `combsum` | Normalised scores summed (`normalize`: minmax, zscore or none) | Agreement and score size both matter |
| `combmnz` | CombSUM × number of lists that found the chunk | Several similar retrievers voting (an ensemble) |
| `borda` | Points by position (N, N−1, …) | Ranks only, more weight to mid-list than RRF |

**Switch:** `fusion: {use: weighted, weights: {dense: 1, sparse: 2}}` for code-heavy content.
Comparison and examples: [extension 01](../extensions/01-retrieval-math-filters-fusion.md#3-fusion-the-result-cache-and-the-ensemble).

## 10. Reranking and post-processing

**Reranking** re-reads the top candidates *together with the question* (a cross-encoder) and reorders
them: slower than search, much more precise. Rerank enough candidates that it can promote the right
one (30 by default), not 5 or 500.

| Reranker | What | Notes |
|---|---|---|
| `gateway` (local default) | Cross-encoder via the gateway's `/rerank` (bge-reranker-v2-m3 on TEI) | Budgets and logs apply |
| `tei` | Straight to TEI | No gateway governance |
| `cross-encoder` | In-process (sentence-transformers) | No server; uses app memory |
| `llm` | Listwise LLM reranking | Few candidates, high cost |
| `term-overlap` | Offline stand-in | Tests and CI only (readiness warns) |
| `maxsim` / `colbert` | Multi-vector late interaction (MaxSim): offline hashed token vectors / a real ColBERT model (PyLate, reference) | Token-level matching |

All rerankers **fail open** by default (`fail_open: true`): if the reranker is down, the fused order is
used and the failure is counted. **Switch:** `reranker: {use: gateway, top_n: 30, …}` or `reranker: none`.

**Post-processors** shape the final list, in order:

| Post-processor | Does | Use for |
|---|---|---|
| `dedupe` | Drops near-duplicate chunks (`threshold` 0.85) | Many versions or copies |
| `min-score` | Drops candidates below a score (e.g. `stage: rerank`) | Enable honest "I don't know" |
| `recency` | Blends relevance with freshness (`half_life_days`); `when: asked` only for "latest / current…" questions (E04) | Policies that change; needs an `updated` date |
| `max-per-document` | Caps chunks per document | Long documents dominating |
| `mmr` | Relevant **and** different | Broad questions |
| `parent-expand` / `window-expand` | Swap a matched child/sentence for its parent/window | With those chunkers |
| `auto-merge` | Enough children of one parent found: return the parent, recursively | With `hierarchical` |
| `section-expand` | Replace a hit by its whole section (token budget); merge hits of one section | Answers need the full rule |
| `summary-expand` | A retrieved summary brings its document's best detailed chunks | With `summary` / `summary-tree` |

## 11. Query transformations

Changing the *question* before searching.

| Transformer | Does | Cost | Choose when |
|---|---|---|---|
| `identity` | Nothing | Free | Default in production search |
| `with-history` | Prepends recent user turns | Free | Cheap follow-up support (offline default) |
| `rewrite` | LLM turns "and for part-timers?" into a standalone question | 1 call, only with history | Chat assistants (`local` default) |
| `expand-terms` | Adds meanings of known acronyms/jargon and synonyms (both ways, phrases, a glossary `file`) | Free | Known vocabulary ("MFA", "SEV1", "holiday" = "annual leave") |
| `normalize` (E04) | Cleans Unicode/spacing; fixes misspellings against the words of documents the person may read | Free | Typos ("anual leeve") |
| `translate` (E04) | Adds the question in the corpus language (passthrough, glossary or LLM) | Free / 1 call | Questions in other languages (with a multilingual embedder) |
| `multi-query` | LLM paraphrases, each searched, then fused | n calls | Users word things differently |
| `hyde` | LLM writes a hypothetical answer; that is searched | n calls | Questions short, documents long |
| `decompose` | Splits compound questions | n calls | "X and Y?" questions |
| `step-back` | Adds a more general question | n calls | Questions needing principles |
| `chain` | Several in order (e.g. rewrite, then multi-query) | Sum | Combining |
| `self-query` | Pulls a metadata filter out of the question ("HR policies updated after 2025") against a declared schema; rules offline or an LLM checked against the schema; retries without it if nothing matches | Free (rules) / 1 call (llm) | Users write conditions into questions |

**Switch:** `query_transformer: {use: rewrite, llm_slot: llm}`; for one run
`RAG__QUERY_TRANSFORMER__USE=multi-query`. The `llm` slot is the fast model (`qwen-fast`).

**As named pipelines** ([extension 03](../extensions/03-more-rag-architectures.md#3-query-side-presets-rag-fusion-hyde-conversational)):
`pipeline: rag-fusion` (also `multi-query`: each rephrasing searched on its own, fused with RRF,
reranked against the original question), `pipeline: hyde` and `pipeline: conversational` (rewrite +
memory) do the same with their own settings, a trace, and a no-model mode for offline runs.

## 12. Context packing and generation

**Context packing** decides what the model sees: `context_builder: {use: numbered, max_tokens: 3000,
order: relevance}` writes numbered `<doc id="n">` blocks within a token budget, capping each chunk
(`max_chunk_tokens`); a document can't forge another document's markers.

| `order` | Puts | When |
|---|---|---|
| `relevance` (default) | Best first | Most cases |
| `lost-in-middle` | Best at the start and end, weakest in the middle | Long contexts: models attend less to the middle |
| `document` | In document order | Narrative continuity |

`compress: true` keeps only the sentences that matter so more sources fit. For more control, the
`compressors` slot runs before the context builder (after the context guards), in order, and records
tokens before/after in the answer trace ([extension 02](../extensions/02-chunking-indexing-compression.md#5-context-compression)):

| Compressor | Keeps | Cost |
|---|---|---|
| `extractive` | Sentences relevant to the question (term overlap or embedding similarity) | Free |
| `embedding-filter` | Chunks/sentences above a similarity threshold | Embeddings |
| `llm-extract` | What an LLM copies as relevant (verified against the chunk) | An LLM call per chunk |
| `summarize` | A question-focused summary of long chunks (kept only if grounded) | An LLM call per long chunk |
| `llmlingua` | Informative tokens only (LLMLingua-2; reference) | A local model |

**Generation:**

| Generator | What | When |
|---|---|---|
| `llm` | The registered, versioned prompt `rag-answer` (by label: `staging`/`production`) on the answer model (`answer_llm`: `qwen-quality`) | The product |
| `extractive` | No model: quotes the best-matching sentences with citations | Offline, demos, model outage (readiness warns in production) |

**Switch:** `generator: {use: llm, llm_slot: answer_llm, prompt: rag-answer, prompt_label: production}`;
`RAG__GENERATOR__PROMPT_LABEL=staging` tries the staging prompt for one run. Prompt changes go through the
[registry](../steps/step-24-prompt-registry.md): `just prompts new rag-answer` → edit → `lock` → `promote`.

## 13. Citations and abstention

**Citations.** The prompt asks for `[n]` markers; the platform **checks them**: markers pointing at
nothing are removed and counted. `pipeline.uncited` says what happens to an answer citing nothing:

| `uncited` | Behaviour | Where |
|---|---|---|
| `flag` | Shown, flagged in the trace and audit | offline/local default |
| `abstain` | Replaced by "I don't know based on the documents" | `production` |
| `keep` | Shown as if sourced | Refused by readiness |

**Citation and answer formats** ([extension 04](../extensions/04-evaluation-loops-and-remaining-techniques.md#8-answer-formatters-citations-json-confidence-follow-ups)):
the `answer_formatters` slot runs after the checks and guards: `citations` (inline `[doc n]` or
footnotes `[^n]`, with the supporting quote and its character offsets), `json` (a schema-checked
answer object, optional model-extracted fields), `confidence` (0..1 from support, citations and
coverage; can abstain below a floor) and `follow-ups` (questions the shown sources can answer).
They appear in `Answer.extras` and rag-api's `extras`.

**Abstention.** If nothing relevant survives search and the access post-check
(`abstain_without_hits: true`), the platform says so **without calling a model**: cheaper, and no
invention. `min-score` on rerank relevance makes "nothing relevant" a real outcome.
Decision: [ADR-0033](../adr/0033-answer-with-checked-citations-and-abstention.md).

## 14. Streaming

Server-sent events: `meta` (answer id), `delta`s (text), `done` (the checked answer), or `error`.

| `pipeline.stream` | Behaviour | When |
|---|---|---|
| `live` | Words sent as generated; output guards run on the final answer | Internal assistants, best perceived speed |
| `checked` | Nothing sent until the output guards have run | `production`, customer-facing, regulated |

`rag ask … --stream` and `POST /v1/answer {"stream": true}` use it.

## 15. Conversation memory

Follow-ups ("and for part-timers?") need the conversation. Memory is keyed by **tenant + person +
session** and expires.

| Memory | Where | When |
|---|---|---|
| `memory` | Process memory | Dev, tests |
| `valkey` | Valkey, shared by replicas, TTL (`ttl_seconds: 86400`) | Every multi-replica deployment |

**Switch:** `memory: {use: valkey, url_file: /run/bao/valkey_url, ttl_seconds: 86400}`; `memory: none`
for single-shot search tools. Erasure by person: `rag erase-subject`. **Conversational RAG** in this
platform is any architecture with `memory` plus a history-aware query transformer.

## 16. Answer caching: exact and semantic

| Cache | Reuses an answer when | Risk |
|---|---|---|
| `memory` | Exact same question, in this process | Not shared, not invalidated across pods (readiness warns) |
| `valkey` (local default) | Exact same question, shared by replicas | Low |
| `semantic` | A question with nearly the same meaning (`threshold: 0.95`), same access set, never for follow-ups | **False hits**: "primary carers" vs "secondary carers" can look 96% alike |

Every key includes the person's **access fingerprint**, the normalised question, the conversation, the
settings, prompt, model, and an **index epoch** bumped by every ingestion or access change, so two people
with different access never share an answer and a changed document empties the cache at once.
**Switch:** `cache: {use: valkey, …}`, `cache: none`. Keep `semantic` off for regulated advice; measure
false hits first.

**Retrieval-result cache** (`search_cache` slot, [extension 01](../extensions/01-retrieval-math-filters-fusion.md)): the same search, by someone with
the same access, with the same filter and k, against the same index epoch, returns the stored hits
(no embedding call, no store round trips, no reranker). `memory` per process, `valkey` shared by
replicas; invalidated by every ingestion change like the answer cache.

## 17. Guardrails

Checks at three stages, each returning **allow, flag, redact or block**. A blocked person sees a fixed
message (`pipeline.blocked_text`); the reason goes to the audit log, never to the person.

| Stage | Guard | Catches |
|---|---|---|
| input | `size` | Huge or degenerate inputs |
| input | `injection` | Prompt injection, jailbreak patterns (incl. base64) |
| input/output | `pii` | Personal data in questions and answers |
| input | `topics` | Denied topics: legal, medical, investment advice |
| context | `context-injection` | Retrieved documents that give orders (indirect injection) |
| output | `groundedness` | Sentences the sources don't support (words and exact numbers) |
| output | `secrets` | Keys, tokens, private keys, passwords |
| output | `toxicity` | Toxic language (word-list baseline) |
| any | `llm-judge` | A model classifies against safety categories (Llama Guard style); uses `judge_llm` |
| any | `webhook` | Any vendor or in-house guard service over HTTP |

The offline set is measured in CI (`just guard-eval`: ≥ 95% attacks caught, ≤ 5% ordinary questions
stopped) on [`examples/eval/guards.yaml`](../../examples/eval/guards.yaml), which also lists **known
gaps** (rephrased attacks patterns can't catch). Production requires `injection`, `context-injection`,
`secrets` and `groundedness`. Model-based and webhook guards fail open by default (`fail_closed: false`).
**Switch:** append `{use: llm-judge, stage: input}` to `guards`, then `rag eval-guards
examples/eval/guards.yaml --profile local`. **Alternatives:** NeMo Guardrails, Guardrails AI, cloud
guardrails, all pluggable via `webhook` ([ADR-0034](../adr/0034-layered-guardrails-measured-in-ci.md)).

## 18. RAG architectures

The `pipeline` slot picks the overall strategy. All of them share memory, guards, cache, the access
post-check, context packing, citation checks and audit ([ADR-0035](../adr/0035-rag-architectures-as-switchable-pipelines.md));
the ones marked E03 came with [extension 03](../extensions/03-more-rag-architectures.md)
([ADR-0041](../adr/0041-more-rag-architectures-a-contents-store-a-durable-graph-and-mcp-tools.md)).

| Architecture | In plain words | Choose when | Cost |
|---|---|---|---|
| `naive` | Dense top-k only, no transforms or reranking | A baseline to prove the extras pay | Lowest |
| `standard` (default) | "Advanced RAG": configured search → context → generate → cite | Most projects | Moderate |
| `vector` (E03) | Dense search only, but with the configured transformer, reranker and post-processors | Measuring dense search; no keyword index | Like standard, minus keyword search |
| `keyword` (E03) | Keyword (BM25) search only, reranked: vectorless, no embeddings | No embedding model allowed; exact codes and names | Lowest |
| `pageindex` / `vectorless` (E03) | A model walks each document's table of contents and reads the chosen sections (heading overlap offline); no embeddings; needs `toc_store: memory` | Long, well-structured documents; explainable retrieval | 2 small calls |
| `rag-fusion` / `multi-query` (E03) | N model-written rephrasings searched in parallel, fused by RRF, reranked | Users word things differently from the documents | 1 call + N searches |
| `hyde` (E03) | Searches with a model-written hypothetical answer passage as well as the question | Short questions, long documents | 1 call |
| `conversational` (E03) | Rewrites a follow-up into a standalone question (needs `memory`), then standard | Chat assistants | 1 call per follow-up |
| `corrective` | Grades retrieved chunks; broadens the search or abstains when they're poor (CRAG) | Wrong context is worse than no answer (policy, compliance) | + grading |
| `self-reflective` | Checks the answer's support; retrieves wider and regenerates if poor (Self-RAG style) | Every answer must be verified (+ `stream: checked`) | Up to `max_rounds` generations |
| `adaptive` | Routes per question: no retrieval for small talk, splits compound questions, else standard | Mixed chat traffic | Small router cost |
| `agentic` | A model plans searches step by step (multi-hop), up to `max_steps` | Investigations across documents | Several LLM calls |
| `graph` | Entities and their neighbours add chunks, fused with search (local GraphRAG) | Facts connected by named entities | Entity extraction at ingestion |
| `sql` | A model writes read-only SQL over **permitted** tables; the result is cited (+ documents) | Numbers, totals, limits in tables | SQL safety controls |
| `table` (E03) | The CSV rows that match the question, cited; no model | Lookups in spreadsheets (aggregates: `sql`) | Free |
| `long-context` (E03) | Whole documents when the best ones fit the context budget, else chunks | A few short documents answer most questions | More tokens |
| `flare` (E03) | Searches for the answer's uncited, unsupported or hedged sentences, then regenerates | Answers that hedge or leave claims uncited | + 1 generation when weak |
| `speculative` (E03) | The fast model drafts from evidence subsets in parallel; the quality model picks one | Many passages; a fast and a quality model | N short drafts + 1 check |
| `graph-global` (E03) | Communities of entities (label propagation) with summaries answer "main themes" questions; others go local | Big-picture questions across documents | Entities at ingestion; summaries |

```yaml
pipeline: {use: corrective, search_k: 8, uncited: abstain}
# graph also needs:
graph_store: memory
enrichers: [context-header, graph-entities]
# sql needs tables with their groups:
pipeline: {use: sql, tables: {expense_limits: {path: examples/tables/expense_limits.csv, groups: [all-staff]}}}
```

For one run: `RAG__PIPELINE__USE=adaptive`, or
`RAG__PIPELINE__USE=graph RAG__GRAPH_STORE__USE=memory RAG__ENRICHERS='[context-header, graph-entities]'`.

GraphRAG extras (extension 03): `enrichers: [context-header, llm-entities]` has a model extract entities
**and relations** (schema-checked, offline fallback); `graph_store: postgres` keeps the graph durable
and shared (migration `20261016000000_graph_store.sql`). Agents can call search and answer as MCP
tools with `rag mcp` (identity fixed at launch; see the [trust model](../extensions/03-more-rag-architectures.md#7-agents-rag-mcp)).

Quick pick, first yes wins (as a flowchart: [decision guide](decision-guide.md#rag-architectures)): small talk → `adaptive`; numbers in tables → `sql`; facts from several places
→ `agentic` (or `graph`); wrong context worse than none → `corrective`; every answer checked →
`self-reflective`; otherwise → `standard`. Tiny corpus → `long-context`. "Main themes" → `graph-global`.
No embeddings → `keyword` or `pageindex`.
**Alternatives:** LangGraph/LlamaIndex workflows (wrap as an architecture plugin), Microsoft GraphRAG,
LightRAG, Neo4j (as a `graph_store` plugin).

## 19. How to know a change helped

Never switch on a hunch: compare on labelled questions.

```bash
uv run rag eval-search examples/eval/handbook.yaml --profile offline --variant all-together
#   recall@k, MRR, nDCG@k, LEAKS (any leak fails), latency, for 11 variants
uv run rag eval-answers examples/eval/handbook.yaml --profile offline --variant standard
#   context recall, answered, cited, abstentions, groundedness, leaks, latency, per architecture
uv run rag eval-guards examples/eval/guards.yaml --profile offline
#   catch rate, false-positive rate, wrong cases, known gaps
```

Add a variant to the evaluation file (e.g. `{retriever: hybrid, reranker: none}`), run it, and keep the
change only if the numbers move the right way. The full loop ([extension 04](../extensions/04-evaluation-loops-and-remaining-techniques.md)):

```bash
uv run rag eval-answers … --out runs/          # + faithfulness, relevance, context precision, correctness, citation P/R
uv run rag eval-compare --runs runs/a.answers.json runs/b.answers.json   # is the difference more than chance?
uv run rag eval-sweep … --grid examples/eval/sweep.yaml                  # which setting matters (ablation)
uv run rag eval-generate --from examples/eval/handbook.yaml --out gen.yaml && uv run rag eval-review gen.yaml --check
uv run rag eval-candidates --events audit.jsonl --out candidates.yaml   # thumbs-down -> questions to review
uv run rag eval-export runs/a.answers.json --to ragas                   # or deepeval, promptfoo, trulens, phoenix
```

`judge: {use: llm, llm_slot: judge_llm}` scores with a model, falling back to the lexical score. On the platform: `--profile local --no-ingest` after
ingesting the handbook. In production: online evaluation per release
([quality-and-operations.md](../guides/quality-and-operations.md#1-evaluation-and-testing)).

## 20. Cheat sheet: situation → choice

The short version. The long version, with "avoid it when" and ecosystem tools for every row, is the
[decision guide](decision-guide.md); whole profiles for common situations are its
[starter configs](decision-guide.md#starter-configs).

| Situation | Choice |
|---|---|
| Policies, handbooks, wikis | `structure` chunker + `context-header` (default) |
| Transcripts, chats | `semantic` or `recursive` + `llm-context` |
| FAQs, short facts | `sentence-window` + `window-expand` |
| Contracts, manuals | `parent-child` + `parent-expand` |
| Scanned archives | `docling` parser with OCR |
| Personal data in documents | `pii: {strategy: pseudonymise}` or `remove`; `presidio` for names |
| Error codes, part numbers | Keyword weight up (`weights: {sparse: 2}`) or `keyword` retriever |
| Users word things differently | `multi-query` or `hyde`; measure the cost |
| Chat follow-ups | `rewrite` or `with-history`; Valkey `memory` |
| Compound questions | `decompose` or `multi-query`, larger k |
| Many versions of a document | Replace-not-append, `recency`, `dedupe` |
| Tight latency | No transformer, smaller `top_n`, or no reranker; measure the loss |
| "Say I don't know" | `min-score` on rerank + `uncited: abstain` |
| Regulated advice | `uncited: abstain`, groundedness `block`, `stream: checked`, no semantic cache, `corrective` |
| Repeated questions (help desk) | `valkey` exact cache; `semantic` only after measuring |
| Model outage / offline demo | `extractive` generator |
| Large volumes | More workers on the Valkey stream; Qdrant/OpenSearch |
| Embedding model trained for inner product / L2 | `metric: dot` / `l2` on the vector store, a new collection, `rag index ddl` |
| "Only HR documents from this year" | `filter` in the request; `self-query` when users type it into the question |
| One index per department | `router` retriever |
| Search a second collection or model too | `ensemble` retriever with `combmnz` or `rrf` |
| Repeated identical searches | `search_cache: valkey` |
| Long manuals; answers need the whole subsection | `hierarchical` + `auto-merge`, or `section-expand` |
| "What is this document about?" | `summary-tree` or `summary` + `summary-expand` |
| Users cite "section 4.2" or a heading | `retriever: section` (and `min_tokens: 0`) |
| Filters wanted, documents have no metadata | `metadata` enricher; `llm-metadata` for business fields |
| Long contexts, short answers, token bills | `compressors: [extractive]`, then `llm-extract` if it pays |
| e5 / bge / nomic embedding models | `embedder: {use: instructed, preset: …}` |
| Index too big, Matryoshka-trained model | `matryoshka` or `request_dimensions` |
| Chunks full of pronouns | `late-chunking` with a long-context model |
| Exact terms in Qdrant, or synonyms in keyword search | `qdrant-sparse` with `bm25`, or `splade-tei` |
| Source code | `chunker: code` |
| No embedding model allowed | `pipeline: keyword`, or `pageindex` + `toc_store` |
| Long structured manuals, explainable retrieval | `pipeline: pageindex` |
| Vague questions, very different wording | `pipeline: rag-fusion` or `hyde` |
| A few short documents | `pipeline: long-context` |
| Answers hedge or leave claims uncited | `pipeline: flare` |
| "What are the main themes?" | `pipeline: graph-global` + `llm-entities` |
| Graph must survive restarts | `graph_store: postgres` |
| Lookups in CSV tables | `pipeline: table` (totals: `sql`) |
| An AI agent should use the knowledge base | `rag mcp --subject … --group …` |
| Typos, jargon, synonyms in questions | `chain: [normalize, {use: expand-terms, file: glossary.yaml}]` |
| Questions in other languages | Multilingual embedder; `translate` for keyword search |
| "Latest / current" questions | `recency` with `when: asked`; `self-query` for "in the last 6 months" |
| A UI that highlights sources, or printed answers | `answer_formatters: [{use: citations, style: footnotes}]` |
| Another program reads the answer | `answer_formatters: [json]` (+ `fields`) |
| Show how sure the answer is; suggest next questions | `confidence`, `follow-ups` |
| Several replicas re-embedding the same text | `cached` with `store: valkey` |
| Re-index hits the provider's rate limit | `batched` embedder inside `cached` |
| Keep the index in step with a share or bucket | `connector` + `rag sync --watch` |
| "Is B really better?" / "Which knob matters?" | `rag eval-compare` / `rag eval-sweep` |
| Too few test questions | `rag eval-generate` + review; `rag eval-candidates` from feedback |

See also: [decision guide](decision-guide.md) for when to use which, [coverage matrix](coverage-matrix.md)
for what is and isn't here, [glossary](../glossary.md) for every term, [catalogue](../catalogue.md) for every setting,
[architecture overview](../architecture/overview.md) for where each stage runs.
