# Extension 02 · Chunking, indexing, metadata, sections, compression and embedding options

*Extension 02 · after the 38 guide steps · RAG core (ingestion, search and answers)*

## At a glance

| | |
|---|---|
| **Goal** | Make every remaining "how documents become searchable, and how much of them the model reads" choice a switch in `rag.yaml`: chunk trees and summaries at several levels, atomic facts, source code, metadata for filters, exact sections, shorter contexts, and the embedding options real models need. |
| **How, in one sentence** | New chunkers (`hierarchical`, `proposition`, `code`), enrichers (`summary-tree`, `summary`, `metadata`, `llm-metadata`), post-processors (`auto-merge`, `section-expand`, `summary-expand`), a `section` retriever, a new `compressors` slot run just before the context is packed, and embedding components (`instructed`, `matryoshka`, `late-chunking`, a `sparse_embedder` slot with `sparse` / `qdrant-sparse` indexes, `maxsim` / `colbert` rerankers), each with an offline implementation tested in CI. |
| **You'll end up with** | chunkers `hierarchical`, `proposition`, `code` · structure chunks that record `heading`, `section_path` and `section_numbers` · enrichers `summary-tree` (RAPTOR), `summary` (document summary index), `metadata` (dates, language, doc type, keywords, entities), `llm-metadata` (a declared, validated schema) · post-processors `auto-merge`, `section-expand`, `summary-expand` · retriever `section` · slot `compressors`: `extractive`, `embedding-filter`, `llm-extract`, `summarize`, `llmlingua`, with token savings in the answer trace · embedders `instructed`, `matryoshka`, `late-chunking`, and `request_dimensions` on `gateway` · slot `sparse_embedder`: `bm25`, `splade-tei` · keyword indexes `sparse`, `qdrant-sparse` (tested live on Qdrant) · rerankers `maxsim`, `colbert` · conformance checks `check_chunker`, `check_compressor`, `check_sparse_embedder` · nine new evaluation variants · ADR-0040. |
| **New words** | chunk tree, auto-merging, RAPTOR, document summary index, proposition, decontextualisation, late chunking, token embedding, Matryoshka embedding, instruction prefix, sparse vector, SPLADE, learned sparse retrieval, multi-vector retrieval, ColBERT, MaxSim, late interaction, context compression, LLMLingua, grounded check, section path, YAKE, TF-IDF. |

## In plain English

> **IN PLAIN ENGLISH**
> Step 31 cut every document into passages of one size and embedded each passage once. That is a
> good default, and it leaves several questions open:
> 1. **"What is this policy about?" and "how many weeks?" need different sizes.** A big question
>    matches a summary or a whole section; a small one matches a sentence. Keep both, as a tree.
> 2. **"What does section 4.2 say?"** isn't a similarity question at all. The answer is exactly one
>    section, found by its number or its title.
> 3. **"Only contracts from 2025"** needs facts *about* each passage (type, dates, language,
>    entities) that nobody typed in. Extract them while ingesting.
> 4. **The model reads too much.** Of five retrieved passages, maybe six sentences matter. Cutting
>    the rest makes answers cheaper, faster and often better.
> 5. **Embedding models differ.** Some need "query:" and "passage:" in front of the text, some can
>    shrink their vectors, some give one vector per word, some give a weight per word.
>
> This extension makes each of those a named, tested switch, with a free offline version you can try
> on a laptop and the model-backed version for production.

> **ANALOGY · THE LIBRARY, REORGANISED**
> The librarian from Step 32 now also has:
> - **a table of contents for every book** (the chunk tree): when you bring back three pages from
>   the same chapter, they hand you the whole chapter instead (auto-merging);
> - **a one-page summary of each book and of each group of chapters** (RAPTOR, the document summary),
>   filed next to the pages, so a broad question finds a summary and a narrow one finds a page;
> - **index cards with one fact each** (propositions);
> - **labels on every spine**: type, date, language, names mentioned (metadata extraction);
> - **the habit of opening at "section 4.2"** when you ask for section 4.2 (the section retriever);
> - **a highlighter** (compression): they photocopy only the highlighted sentences for you;
> - **different catalogues** for different kinds of search: by meaning (dense), by exact words
>   (sparse), and word by word (multi-vector).

## What we're doing

1. Chunk trees: the `hierarchical` chunker, `auto-merge`, RAPTOR's `summary-tree`, the document
   `summary` enricher and `summary-expand`.
2. More chunkers: `proposition` and `code` (what `structure` and `fixed` already covered is listed
   below, and was not duplicated).
3. Metadata extraction at ingestion: `metadata` (rules) and `llm-metadata` (a declared schema).
4. Exact sections: section metadata on every structured chunk, the `section` retriever,
   `section-expand`, and filters on `section_path` / `section_numbers`.
5. Context compression: the `compressors` slot with five compressors and token-savings metrics.
6. Embedding options: instruction prefixes, Matryoshka truncation, late chunking, sparse vectors
   (BM25 offline, SPLADE via TEI, in memory or Qdrant), and multi-vector (ColBERT-style) reranking;
   plus how to choose and switch embedding models.

## Why this matters

- **Chunk size is a compromise until you stop choosing one.** A tree lets search find the small
  piece and the model read the bigger one; summaries answer the questions no single chunk can.
- **Exact references are common in real use** ("clause 7.1", "the Escalation section"). Similarity
  search returns *something near* 7.1; a section lookup returns 7.1.
- **Filters need metadata,** and most documents arrive with almost none. Extracting dates, type,
  language and entities at ingestion is what makes Extension 01's filters useful.
- **Context costs money and attention.** Compression routinely removes half the tokens; models
  answer better when the relevant sentence isn't buried in four irrelevant paragraphs.
- **The right embedding settings are worth several points of recall for free** (the right prefix),
  or 4× less memory (Matryoshka), or exact-term robustness (sparse), or context for pronouns (late
  chunking). Getting them wrong costs as much, silently.

## How it works

### 1. Chunk trees: hierarchical, auto-merge, RAPTOR, document summaries

```
 document "Staff handbook"                       ← root (stored, if small enough)
 ├── section "4 Leave"
 │   ├── section "4.1 Annual leave"
 │   │   ├── leaf  "Full-time staff get 20 days…"          ← indexed, searched
 │   │   └── leaf  "Book annual leave in the HR portal…"
 │   └── section "4.2 Parental leave"
 │       ├── leaf  "Parental leave is 18 weeks at full pay…"
 │       └── leaf  "Partners get four weeks…"
 └── section "5 Expenses" …
```

- **`hierarchical`** builds that tree from heading levels, to any depth, and packs paragraphs into
  leaves of `leaf_tokens`. Each leaf carries `parent_id` and its `ancestors`: id, kind, heading,
  number of children and, when the node is at most `max_node_tokens`, its full text. So nothing has
  to be looked up at query time. `index_sections: true` also indexes the section nodes themselves
  (search at several granularities).
- **`auto-merge`** (LlamaIndex's auto-merging retriever as a post-processor): if at least
  `threshold` (default half) of a parent's children were retrieved, they are replaced by the parent;
  then again one level up, up to `max_levels`. Three fragments of 4.2 become 4.2.
- **`summary-tree`** is RAPTOR (Sarthi et al., 2024) per document: embed the chunks, group them
  with k-means (`cluster_size` per group), summarise each group, then group and summarise the
  summaries, up to a root. Summaries are indexed next to the chunks (`node_kind: summary`,
  `tree_level`, `children`).
- **`summary`** adds one summary chunk per document (`node_kind: document-summary`), LlamaIndex's
  "document summary index"; `attach: true` also stores it on every chunk as `doc_summary`.
- **`summary-expand`**: when a summary is retrieved, the document's best detailed chunks for the
  question are added right after it.

Both summarisers use the `llm` slot **only if the summary is grounded** (at least `min_overlap` of
its content words appear in the text); otherwise (offline, a refusal, an invention) they use an
extractive summary: the most central sentences, chosen by word frequency. Original RAPTOR clusters
across the whole collection; per document fits a pipeline that ingests one document at a time and
replaces it cleanly (ADR-0040).

### 2. More chunkers, and what already existed

| Need | Component | Status |
|---|---|---|
| Markdown headers | `structure` (the parsers turn `#`/`<h2>`/Word headings into heading elements) | already covered |
| Tables | `structure` keeps a table whole, or splits it by rows **repeating the header** | already covered |
| Fenced code blocks | `structure` keeps them whole; now cuts an oversized block **between lines** | fixed here |
| Token-based sliding window | `fixed` (N tokens with overlap; exact with `token_counter: hf-tokenizer`) | already covered |
| Atomic facts | **`proposition`** | new |
| Source files | **`code`** | new |

- **`proposition`** (Dense X Retrieval, Chen et al., 2023) indexes one fact per chunk: "Parental
  leave is 18 weeks at full pay." An LLM decomposes each passage; every proposition must be
  grounded in its passage or it is dropped, and a passage with none falls back to the **rule-based
  split**: sentences, then clauses at `;`, with a leading pronoun replaced by the section's subject
  ("It can start…" → "Parental leave: It can start…"); tables stay whole. Each proposition keeps
  its passage in `metadata.window`, so `window-expand` gives the model the full passage.
- **`code`** cuts source files at top-level definitions (Python, JS/TS, Go, Rust, Ruby, SQL, shell,
  Java-like languages by pattern; blank-line blocks otherwise), keeps the comments and decorators
  above a definition with it, packs small definitions together, and records `code_language`,
  `symbols`, `line_start`, `line_end` (and `section` = the first symbol).

### 3. Metadata extraction at ingestion

| Enricher | Extracts | Cost |
|---|---|---|
| `metadata` | `dates` + `date_latest` (ISO), `language` (stop-word detection, en/de/fr/es/nl/it/pt), `doc_type` (policy, procedure, contract, invoice, minutes, faq, guide, report, specification, release-notes, code, table), `keywords` (TF-IDF across the document's chunks) and `doc_keywords` (TF-IDF or YAKE), `entities` + `entity_kinds` (codes like POL-117, money, percentages, URLs, organisations, capitalised names; emails only if asked) | Free, offline |
| `llm-metadata` | Exactly the fields **you declare** (`keyword` with allowed values, `string`, `number`, `integer`, `boolean`, `date`, `list`), per document or per chunk | One LLM call per document (or chunk) |

Every `llm-metadata` value is converted and checked against the schema before it is stored: an
unknown department, a non-date or a list item outside the allowed values is dropped; a missing
`required` field gets one more try with the error message, then nothing from that call is stored.
Values never go into what is embedded; they are for filters (Extension 01), routing and the trace.
A source's own metadata wins unless `overwrite: true` (except the parser's placeholder `language:
en`, which detection may correct). Use the same field names in a `self-query` schema so users can
ask "contracts from 2025" in plain words.

### 4. Exact sections

Every `structure`, `parent-child`, `proposition` and `hierarchical` chunk now records:

```
section          "Staff handbook > 4 Leave > 4.2 Parental leave"
heading          "4.2 Parental leave"
section_path     ["Staff handbook", "Staff handbook > 4 Leave", "Staff handbook > 4 Leave > 4.2 Parental leave"]
section_numbers  ["4", "4.2"]          (when headings are numbered: 4.2, Section 3, Appendix B)
```

Because `section_path` and `section_numbers` are lists, Extension 01's filter "eq means contains"
gives section filters for free: `{"section_path": "Staff handbook > 4 Leave"}` is the whole of
chapter 4; `{"section_numbers": "4.2"}` is 4.2 and its subsections.

- **`section` retriever** wraps the usual retriever. "What does **section 4.2** say?" (also §, clause,
  chapter, part, article, appendix) → every chunk with that number, in the document that ranks best
  for the question, joined into **one** candidate at the top (within `max_tokens`), then the usual
  results. "Show me the **Parental leave section**" → the deepest heading among the top hits whose
  words are all in the question (`require_cue: true` means only when the question says "section",
  "chapter", "heading"…). The trace says what was looked up.
- **`section-expand`** replaces each hit by the whole section it belongs to (`include_subsections`
  optional), within `max_tokens` (over budget: the chunks nearest the hit), merging hits of the same
  section. Hierarchical chunks carry their section text already; others are fetched with a filtered
  search on `document` + `section`, so permissions and the request's filter always apply.

### 5. Context compression

```
search hits ─▶ post-check (OPA) ─▶ context guards ─▶ compressors ─▶ context builder ─▶ model
                                                      │
                                       trace.compression: tokens_before, tokens_after,
                                       tokens_saved, ratio, steps[] (one per compressor)
```

| Compressor | Keeps | Cost | Notes |
|---|---|---|---|
| `extractive` | Sentences sharing the question's content words (`method: overlap`) or similar to it (`method: embedding`), optional `neighbours` | Free / one embedding per sentence | Never invents; the default choice |
| `embedding-filter` | Chunks (or sentences, `level: sentence`) with cosine ≥ `threshold` | One embedding per chunk/sentence | LangChain's EmbeddingsFilter; `min_keep` protects the best |
| `llm-extract` | What an LLM copies as relevant; `NO_OUTPUT` drops the chunk | One LLM call per chunk | LangChain's LLMChainExtractor; `verify` keeps only sentences really in the chunk |
| `summarize` | A question-focused LLM summary of long chunks (`min_tokens`) | One LLM call per long chunk | Discarded (chunk kept) if not grounded or not shorter |
| `llmlingua` | Tokens a small model rates informative (`rate`) | A local model | Reference: `pip install llmlingua` (pulls PyTorch) |

A compressor keeps each chunk's id, document, access and metadata (`metadata.compressed` lists what
ran), so citations still point at the right source. Search results (`rag search`, `/v1/search`) are
not compressed: compression is for the model's context, not for ranking.

**Why a slot, not post-processors:** post-processors run inside search, whose results are cached
(Extension 01) and returned to API callers; compression must happen after the OPA post-check and
the context guards, only for answers, and report token savings. ADR-0040 records this.

### 6. Embedding options

**Instruction prefixes** (`instructed`). Asymmetric models were trained with a marker saying what
the text is. Without it they lose several points of recall, silently.

| Preset | Query | Passage | Models |
|---|---|---|---|
| `e5` | `query: ` | `passage: ` | intfloat/e5-*, multilingual-e5-* |
| `bge` | `Represent this sentence for searching relevant passages: ` | (none) | BAAI/bge-*-en-v1.5 |
| `nomic` | `search_query: ` | `search_document: ` | nomic-embed-text v1/v1.5/v2 |
| `qwen3` | `Instruct: Given a web search query, retrieve relevant passages…\nQuery: ` | (none) | Qwen3-Embedding, gte-Qwen2-instruct |
| `mxbai`, `snowflake` | the bge sentence | (none) | mxbai-embed-large, arctic-embed |
| `gte`, `none` | (none) | (none) | gte-base/large, OpenAI, Cohere/Voyage (they take `input_type` instead) |

The prefixes are part of the embedding contract: the model name recorded with every vector gets a
`+prefix-…` tag, so a changed prefix means a re-index, like a changed model. (The platform's own
`gateway` embedder already adds Qwen3's query instruction from the prompt registry, Step 24.)

**Matryoshka** (`matryoshka`). Models trained with Matryoshka Representation Learning put the most
important information in the first numbers: keep 256 of 1024 and the index is 4× smaller and faster,
for a few points of quality. *Only* for models trained that way (OpenAI text-embedding-3,
nomic v1.5, Qwen3-Embedding, jina v3, mxbai, Gemini, Voyage 3.5, Cohere v4): our evaluation's
`matryoshka-128` variant cuts the hashing embedder, which is **not** Matryoshka-trained, and recall
drops from 0.92 to 0.75: that's what happens to the wrong model. APIs that cut server-side:
`embedder: {use: gateway, dimensions: 256, request_dimensions: true}`.

**Late chunking** (`late-chunking`; Günther et al., Jina AI, 2024). Normally each chunk is embedded
alone, so "It lasts 18 weeks." doesn't know what "it" is. Late chunking runs the long-context model
over the **whole document** once, then averages the token vectors inside each chunk: every chunk's
vector carries its context. Ingestion calls the embedder's `embed_chunks(document, chunks)` when it
has one; questions are embedded alone. Documents longer than `max_tokens` are processed in
overlapping windows; chunks not in the text (summaries) are embedded alone.
- `backend: hashing` (offline, CI): token vectors = hashed word + decayed neighbours + a share of the
  window's average. On the handbook evaluation, dense recall goes from 0.917 to 0.979.
- `backend: tei` (reference, tested against a stand-in): TEI's `/tokenize` (character offsets) and
  `/embed_all` (one vector per token) for a long-context model such as `jinaai/jina-embeddings-v3`
  or `BAAI/bge-m3`. Use the model's mean pooling and the same model for questions.

**Sparse vectors** (the `sparse_embedder` slot). A sparse vector is a weight per word ID: most are
zero. `bm25` writes BM25's term-frequency part and lets the index apply IDF at search time (Qdrant's
`modifier: idf`), so it stays right as the collection grows. `splade-tei` asks a SPLADE model (via
TEI's `/embed_sparse`) for learned weights that also light up *related* words ("car" → "vehicle"):
keyword precision with some meaning. They are searched by the keyword indexes `sparse` (in memory)
or `qdrant-sparse` (a Qdrant collection with a named sparse vector, with the same tenant/ACL payload
filter and metadata filters as the dense store; tested live). Both are `keyword_index`es, so
`retriever: hybrid` fuses them with dense search unchanged.

**Multi-vector / ColBERT** (`maxsim`, `colbert`). One vector **per token**; a passage's score is, for
each question token, its best match in the passage, averaged (MaxSim, "late interaction"). Finer than
one vector per passage, cheaper than a cross-encoder at scale. `maxsim` is the offline version over
hashed token vectors (a reranker); `colbert` runs a real model in-process with PyLate (reference).
At large scale, store the token vectors in Qdrant's multivector field (`comparator: max_sim`) and
retrieve with them; reranking 30 candidates is the simple start.

### 7. Choosing an embedding model, and switching it through the gateway

| Criterion | Ask | Guidance |
|---|---|---|
| Quality on *your* data | Recall@k on your own questions (`rag eval-search`) | MTEB's retrieval scores are a shortlist, not a decision |
| Language | Which languages, mixed in one collection? | Multilingual models (bge-m3, multilingual-e5, Qwen3-Embedding, Cohere multilingual, jina v3) for anything beyond English |
| Domain | Legal, medical, code, finance? | Domain models (voyage-law, voyage-code) or fine-tuning beat general ones there |
| Context length | Longest chunk (or whole document for late chunking) | 512 tokens (e5, bge-en) vs 8k (bge-m3, jina v3, nomic, OpenAI) vs 32k (Qwen3, Voyage) |
| Dimensions | Memory = chunks × dimensions × bytes | 1024 float32 = 4 KB per chunk; Matryoshka or quantization (Extension 01) to shrink |
| Cost | Per million tokens (API) or GPU hours (local) | Re-embedding the corpus is the big bill; caching (`cached`) the small one |
| Local vs API | Can documents leave your network? Latency? | Local (TEI, mlx) keeps data in; APIs are zero-ops |
| Asymmetry | Does the model card mention prefixes or `input_type`? | Use `instructed` with the right preset |
| Metric | Cosine, dot or L2 on the model card? | `metric:` on the vector store (Extension 01) |

Every model is reached the same way: an alias in LiteLLM's config (Step 9), then the embedder names it.

```yaml
# infra/config/litellm/config.yaml (a new alias; the key comes from a secret file, never this file)
- model_name: embedder-openai
  litellm_params: {model: openai/text-embedding-3-large, api_key: os.environ/OPENAI_API_KEY}
# others: cohere/embed-v4.0 · voyage/voyage-3.5 · jina_ai/jina-embeddings-v3 · mistral/mistral-embed
#         gemini/gemini-embedding-001 · bedrock/amazon.titan-embed-text-v2:0
#         local TEI (bge-m3, e5, nomic, gte, Qwen3-Embedding): openai/<name> with api_base: http://tei:80/v1
```

```yaml
# rag.yaml: a NEW collection, because a new model is a new embedding contract (Step 36)
embedder:
  use: cached
  inner: {use: gateway, model: embedder-openai, dimensions: 1024, request_dimensions: true,
          query_instruction: "{query}"}            # OpenAI needs no prefix
# e5 / nomic / bge on TEI: wrap with the preset, and let the wrapper own the prefixes
# embedder: {use: instructed, preset: e5, inner: {use: gateway, model: embedder-e5, dimensions: 1024, query_instruction: "{query}"}}
vector_store: {use: pgvector, …, collection: kb_openai, metric: cosine}
```

Then `rag reindex --profile local --to local-openai --apply`, compare with `rag eval-search`, and
switch by PR, exactly as Step 36 describes.

## How to switch it on

```yaml
profiles:
  my-project:
    extends: platform/local
    # 1 · a chunk tree, merged back at query time; summaries for broad questions
    chunker: {use: hierarchical, leaf_tokens: 200, max_node_tokens: 2000}
    enrichers:
      - context-header
      - {use: summary-tree, cluster_size: 5, max_levels: 3}          # RAPTOR
      - {use: summary, attach: false}                                 # document summary index
      - {use: metadata, keywords: 5}                                  # dates, language, type, entities
      - use: llm-metadata
        fields:
          department: {type: keyword, values: [hr, finance, it], required: true}
          effective:  {type: date, description: "the date the document takes effect"}
    postprocessors:
      - {use: auto-merge, threshold: 0.5}
      - summary-expand
      - {use: max-per-document, n: 3}
    # 2 · "section 4.2" and heading titles, exactly
    retriever: {use: section, inner: {use: hybrid}}
    # 3 · send the model only what matters
    compressors:
      - {use: embedding-filter, threshold: 0.3}
      - {use: extractive, threshold: 0.3, neighbours: 1}
    # 4 · embedding options
    embedder: {use: instructed, preset: e5, inner: {use: gateway, model: embedder-e5, dimensions: 1024, query_instruction: "{query}"}}
    sparse_embedder: {use: splade-tei, url: "http://tei-splade:80"}
    keyword_index: {use: qdrant-sparse, url: "http://qdrant:6333", collection: rag_sparse}
    reranker: {use: gateway, top_n: 30}                               # or maxsim / colbert
```

Other combinations:

```yaml
chunker: {use: proposition}                       # + postprocessors: [window-expand] to read the passage
chunker: {use: code, max_tokens: 400}             # a source-code profile
postprocessors: [{use: section-expand, max_tokens: 1200}]
embedder: {use: late-chunking, backend: tei, url: "http://tei-long:80", dimensions: 1024, max_tokens: 8192}
embedder: {use: matryoshka, dimensions: 256, inner: {use: gateway, model: embedder, dimensions: 1024}}
compressors: [{use: llm-extract, llm_slot: llm}]  # or summarize; llmlingua after `pip install llmlingua`
```

Filters by section and by extracted metadata:

```bash
# section numbers are strings; key=value matches the text as typed too (extension 03)
uv run rag search "parental leave" --profile offline --group hr --classification internal \
    --ingest handbook.md --filter section_numbers=4.2
uv run rag search "leave" --filter '{"section_path": "Staff handbook > 4 Leave"}' …
uv run rag search "contract terms" --filter doc_type=contract --filter 'date_latest>=2025-01-01' …
# one word switches the retriever (its candidates/parallel settings are accepted as they are)
RAG__RETRIEVER__USE=section RAG__CHUNKER__MIN_TOKENS=0 \
    uv run rag search "What does section 4.2 say?" --profile offline --group hr --classification internal --ingest handbook.md
```

## When to use which

Measured on the handbook evaluation (`uv run rag eval-search examples/eval/handbook.yaml --profile
offline`, offline hashing embedder, 25 questions; your corpus and models will differ: measure them):

| Variant | recall@5 | MRR | Reading |
|---|---:|---:|---|
| dense | 0.917 | 0.865 | the baseline for embedding options |
| late-chunking (dense) | 0.979 | 0.948 | context helps short, pronoun-heavy chunks |
| matryoshka-128 (dense) | 0.750 | 0.535 | the WRONG model to truncate: hashing isn't Matryoshka-trained |
| hybrid-rrf | 1.000 | 0.972 | the baseline for everything else |
| sparse-bm25 (hybrid) | 1.000 | 0.969 | same as BM25, now as sparse vectors (portable to Qdrant/SPLADE) |
| hierarchical+merge | 1.000 | 0.917 | tiny documents: merging rarely needed; shines on long manuals |
| proposition (rules) | 1.000 | 0.903 | many tiny chunks; the LLM version decontextualises better |
| summary-tree | 1.000 | 0.972 | no cost to precise questions; helps broad ones |
| metadata+summary | 0.958 | 0.958 | a summary chunk can crowd out a detail with k = 5 |
| section-retriever | 1.000 | 0.972 | unchanged when no section is asked for, as designed |
| hybrid+maxsim | 0.979 | 0.951 | the offline MaxSim is a stand-in; a real ColBERT model is far stronger |

| Situation | Choose |
|---|---|
| Long manuals, policies with deep headings; answers need the whole subsection | `hierarchical` + `auto-merge` (or `section-expand`) |
| "What is this about?", "summarise the policy", questions spanning sections | `summary-tree` (RAPTOR) or `summary` + `summary-expand` |
| Precise factual questions over dense prose | `proposition` + `window-expand` (LLM in production) |
| Source code, scripts, SQL | `code` |
| Tables, Markdown headers, fenced code | `structure` (already) |
| Users cite numbers or headings ("clause 7.1", "the Escalation section") | `retriever: section` |
| Answers need the whole rule, not one fragment | `section-expand` |
| You need filters but documents have no metadata | `metadata` (free); `llm-metadata` for business fields |
| Context is long, answers are short | `extractive` (free) → `embedding-filter` → `llm-extract` if budget allows |
| Very long chunks (reports) | `summarize` |
| Maximum token savings, can host a model | `llmlingua` after `extractive` |
| e5 / bge / nomic / Qwen3 models | `instructed` with the matching preset |
| Index too big or slow, model is Matryoshka-trained | `matryoshka` or `request_dimensions` |
| Chunks full of "it", "this", "the above" | `late-chunking` with a long-context model |
| Exact codes and names matter; want them in Qdrant | `sparse_embedder: bm25` + `qdrant-sparse` |
| Keyword search misses synonyms | `splade-tei` |
| Reranker too slow at scale, want token-level matching | `maxsim` / `colbert` (or Qdrant multivectors) |

## Trade-offs

- **Trees and summaries cost ingestion time and storage.** RAPTOR embeds every level and (with an
  LLM) summarises every cluster; `ancestors` copies section text into each leaf's metadata (capped
  by `max_node_tokens`). Summaries can crowd details out of a small k: pair with `summary-expand`, a
  larger k or `max-per-document`.
- **Auto-merge** gives the model more text: merged parents use more of the context budget.
- **Propositions** multiply the number of chunks (often 3-5×) and, with an LLM, cost one call per
  passage; rule-based propositions are cheap but only resolve pronouns at the start of a sentence.
- **Section lookup** relies on headings: documents without headings have nothing to look up, and
  heading-title matching only uses the words in the top hits' headings. The section is returned as
  one candidate at the top, but a reranker after it re-scores it like any other candidate: with a
  weak reranker, check it stays in the top k (or let `section-expand` do the expanding instead).
- **Metadata rules** are predictable but shallow (stop-word language detection, regex entities);
  `llm-metadata` understands more and costs a call per document; both only help if you filter on
  what they extract.
- **Compression** can remove a sentence the answer needed (term overlap misses paraphrases; tune the
  threshold, add `neighbours`); LLM compressors add latency per chunk; `llmlingua` makes the text
  less fluent (models cope, people reading citations may not).
- **Embedding options** all change the embedding contract (a new collection and a re-index): prefixes,
  truncation, late chunking and sparse encoders alike. Late chunking needs a long-context model and
  more GPU memory per document; SPLADE vectors are larger than BM25's; ColBERT stores one vector per
  token (10-100× the storage) if used for retrieval rather than reranking.

## Common mistakes

> **WATCH OUT**
> - **Truncating a model that wasn't trained for it.** `matryoshka` on a non-Matryoshka model ruins
>   recall (see the 0.75 above). Check the model card.
> - **Prefixes added twice.** The `gateway` embedder adds its `query_instruction`; set it to
>   `"{query}"` when `instructed` owns the prefixes.
> - **Wrapping late chunking in `cached`.** The cache doesn't pass `embed_chunks` through, so chunks
>   would be embedded alone: use `late-chunking` as the outermost embedder.
> - **Expecting `section` to work on unstructured text.** It needs headings (Markdown, HTML, Word,
>   Docling); plain text has none.
> - **`--filter section_numbers=4.2` before extension 03.** `key=value` read 4.2 as a number, while
>   section numbers are stored as text. Fixed in extension 03 (equality matches the text as typed and
>   its number reading); the JSON form `--filter '{"section_numbers": "4.2"}'` works everywhere.
> - **`structure` with `min_tokens` and numbered sections.** Tiny sections are joined to the next one
>   under their *common* path, so a short 4.1 and 4.2 become one chunk labelled "4". For section
>   lookups set `min_tokens: 0` (or use `hierarchical`).
> - **Filtering on `section` with a prefix.** `section` is one string (equality); use `section_path`
>   for "this section and everything under it".
> - **Trusting LLM metadata without a schema.** Declare the values; anything outside them is dropped,
>   which is the point.
> - **Compressing before the guards.** The slot runs after the context guards on purpose: a guard
>   must see the original text, not a summary of an injection attempt.
> - **Judging by token savings alone.** Compare `rag eval-answers` before and after: saved tokens that
>   cost the answer are not savings.
> - **A sparse index with the wrong IDF setting.** BM25 vectors need `idf: true` (the default for
>   `bm25`); SPLADE vectors must not get it. `qdrant-sparse` refuses a collection whose modifier
>   doesn't match.

## What was added to the repo

| Where | What |
|---|---|
| `libs/rag-core/src/rag_core/text.py` | Offline helpers: sentences, content words, grounded check, extractive summary, TF-IDF and YAKE keywords, language detection, dates, entities, document type |
| `components/chunking.py` | `section_meta` / `section_number`: `heading`, `section_path`, `section_numbers` on structure and parent-child chunks; code blocks cut between lines |
| `components/hierarchy.py` | `hierarchical` chunker; `auto-merge`, `section-expand`, `summary-expand` post-processors; `summary-tree` and `summary` enrichers; `section` retriever |
| `components/chunkers.py` | `proposition` and `code` chunkers |
| `components/metadata.py` | `metadata` and `llm-metadata` enrichers |
| `components/compression.py` | the `compressor` kind: `extractive`, `embedding-filter`, `llm-extract`, `summarize`, `llmlingua`; `compress_all` |
| `components/embeddings.py` | `instructed`, `matryoshka`, `late-chunking` embedders; `bm25`, `splade-tei` sparse embedders; `sparse`, `qdrant-sparse` keyword indexes; `maxsim`, `colbert` rerankers |
| `components/enrichment.py`, `components/qdrant.py` | `request_dimensions` on the gateway embedder; shared Qdrant payload helpers |
| `contracts.py`, `registry.py` | `Compressor`, `DocumentEmbedder`, `SparseEmbedder`; slots `compressors` (a list) and `sparse_embedder` |
| `ingest.py`, `answer.py` | `embed_chunks` for document-aware embedders; compression before the context builder, `trace.compression` and a `rag.compress` span |
| `testing/conformance.py` | `check_chunker`, `check_compressor`, `check_sparse_embedder`, `sample_document` |
| `rag.yaml`, `profiles/platform.yaml`, `examples/eval/handbook.yaml` | the options listed in comments; nine evaluation variants |
| Tests | `test_chunking_indexing_ext.py`, `test_compression_embeddings_ext.py`, a live Qdrant sparse test in `test_stores.py` |
| Docs | this page, ADR-0040, handbook sections 5-8, 10, 12, 20, glossary, catalogue |
