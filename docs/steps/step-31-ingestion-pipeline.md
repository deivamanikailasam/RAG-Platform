# Step 31 · Ingestion: from any document to searchable chunks

*Step 31 of 38 · Phase H · RAG core*

## At a glance

| | |
|---|---|
| **Goal** | Any document a project has (PDF, Word, web page, Markdown, spreadsheet, plain text) becomes clean, redacted, well-cut, well-labelled chunks in the stores, with its access rules attached, without re-doing work that's already done, and with every step traced. |
| **How, in one sentence** | An ingestion pipeline in rag-core (parse → clean → redact PII → chunk → enrich → embed → index) where every stage is a switchable component, a manifest that skips unchanged sources, replace-not-append writes so old chunks never linger, and a queue of jobs (Valkey Streams) that workers process with retries. |
| **Time** | About 4 hours. |
| **You'll end up with** | Parsers for Markdown, HTML, PDF (with page numbers, footer removal and scanned-page detection), DOCX, CSV and text; Apache Tika and IBM Docling as options · normalisers, and PII redaction with checksum validation (emails, cards, Australian TFN and ABN, IBAN, phones, IPs) by masking, keyed pseudonymisation or removal; Presidio as an option · six chunking strategies: fixed, recursive, structure-aware, sentence-window, semantic, parent-child · enrichers: context headers, LLM "contextual retrieval", hypothetical questions · embedders: the gateway (batched, dimension-checked) with a cache · stores: pgvector and Postgres full-text search on Step 11's tables, Qdrant (Step 12's design), OpenSearch BM25 and k-NN (Step 13's design), all passing the same conformance tests · a migration, a manifest, a job queue with dead letters, a `rag ingest \| delete \| enqueue \| worker` command line · 63 new tests (347 in total in the guide's count), including live runs against Postgres with pgvector and a real Qdrant; ADR-0031. |
| **New words** | ingestion, parsing, layout analysis, OCR, text layer, normalisation, boilerplate, deduplication, PII, pseudonymisation, chunk, chunking strategy, overlap, structure-aware chunking, sentence window, semantic chunking, parent-child (small-to-big), enrichment, contextual retrieval, hypothetical questions, embedding cache, idempotent upsert, manifest, pipeline hash, dead-letter queue, consumer group. |

## The big idea

> **ANALOGY · THE LIBRARY'S CATALOGUING ROOM**
> A library doesn't put donated boxes straight on the shelves. In the cataloguing room, each item is:
> - identified (a book, a map, a journal);
> - cleaned up (loose flyers and stickers removed);
> - checked for private material (a letter with someone's address tucked inside);
> - split into findable units (a journal's articles are catalogued one by one, each with its issue and section);
> - labelled (subject, section, who may borrow it);
> - shelved and indexed in the catalogue.
>
> And when a new edition arrives, the old one is taken off the shelf, not left beside it.
> Ingestion is that room. Skip it, or do it badly, and no amount of clever searching later can find what was
> never properly catalogued.

### The ingestion pipeline (Figure 98)

```
 source                 parse                  clean                  redact
 file:// or s3://   →   by detected type   →   unicode, footers,  →   PII: mask, pseudonymise
 + access, metadata     → structured elements  duplicates             or remove

 chunk                  enrich                 embed                  index
 strategy from      →   title > section,   →   batched, cached,   →   replace old chunks,
 rag.yaml               LLM context            dimension-checked      vector + keyword

 manifest: same bytes + same pipeline = skip         queue + workers (Valkey Streams): retries, dead letters
 change either → re-ingest; delete → gone everywhere every step is a trace span; every result an event
```

A source (with its access rules) is parsed by its detected type, cleaned, redacted, chunked, enriched,
embedded and indexed, replacing any older version. A manifest skips unchanged sources; a queue of jobs
lets workers retry and park failures; every step is traced and every result becomes an event for lineage
(Step 25) and audit (Step 23).

## What we're doing

1. Parse each format into structured elements: headings, paragraphs, lists, tables, code, with page numbers.
2. Clean: Unicode, hyphenation, running headers and footers, duplicates.
3. Redact PII before anything is stored.
4. Chunk, with six strategies to choose from.
5. Enrich what is embedded, without changing what is cited.
6. Embed through the gateway, batched and cached.
7. Index into Postgres, Qdrant or OpenSearch, replacing old versions, with the same access rules in all of them.
8. Remember what was ingested (manifest), run it as jobs on a queue, and test it all against real stores.

## Why we're doing this

> **WHY THIS MATTERS**
> Most disappointing RAG systems fail at ingestion, not at the model:
> - **The answer is in the document but not in the index:** a scanned page with no text layer, a table
>   flattened into word soup, a PDF footer repeated in every chunk.
> - **The answer is split in half:** a chunk boundary cut the sentence that matters.
> - **The chunk can't be found:** "It is 18 weeks." embeds as nothing in particular, because it doesn't say
>   *what* is 18 weeks.
> - **Stale or leaked content:** the old version of a policy is still indexed beside the new one; a
>   customer's phone number is now in the vector store for ever.

| Need | How this step meets it |
|---|---|
| Every common format | Parsers for Markdown, HTML, PDF, DOCX, CSV, text; Tika and Docling as options; type detected from the content |
| Structure kept | Elements with kind, level and page; tables and code kept whole by the structure chunker |
| No noise | Unicode normalisation, de-hyphenation, repeated header/footer removal, duplicate paragraphs dropped |
| No personal data in the index | PII found with checksums (few false positives) and masked, pseudonymised or removed before storing |
| Chunks that can be found and cited | Six strategies; section paths; context headers or LLM context in what is embedded |
| Same access rules in every store | Access copied to every chunk; each store filters by tenant, classification and groups inside its own query |
| No stale versions | Replace, not append: a source's old chunks are deleted from every store before the new ones are written |
| No wasted work | Manifest: same bytes + same pipeline settings = skipped; any change to either = re-ingested |
| Robust at scale | Valkey Streams queue with a consumer group, retries, a dead-letter stream, crash recovery |
| Know what happened | A trace span per stage; an event per source for lineage (Step 25) and audit (Step 23) |

> **IN A COMPANY**
> Data protection law treats an index like any other copy of personal data: GDPR, the Australian Privacy
> Principles (APP 11: security; APP 13: correction) and the EU AI Act's data-governance duties all apply to
> what you embed. Mature teams therefore redact or pseudonymise at ingestion, keep the original in controlled
> object storage (Step 14) with the index treated as a rebuildable copy, record lineage (which source became
> which chunks, under which pipeline version), and can delete a source from every store on request (Step 36
> makes that a tested procedure).

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Ingestion** | Everything that happens between "here is a file" and "its pieces can be searched": the cataloguing room. |
| **Parsing** | Turning a file's bytes into text with structure: which part is a heading, a table, page 3. |
| **Text layer, OCR** | A digital PDF contains its text; a scanned one is only a picture and needs OCR (optical character recognition) to get text. |
| **Layout analysis** | Working out reading order, columns, tables and figures on a page (Docling does this; plain text extraction doesn't). |
| **Normalisation** | Making text uniform: "ﬁ" → "fi", joining "infor-/mation", collapsing spaces. |
| **Boilerplate** | Text that repeats everywhere and means nothing: running headers, footers, "Page 3 of 9", cookie banners. |
| **Deduplication** | Dropping exact repeats (the same paragraph pasted twice) so they don't crowd out everything else in search results. |
| **PII, pseudonymisation** | Personal information. Pseudonymising replaces it with a keyed token: the same person always gets the same token, but nobody without the key can reverse it. |
| **Chunk, overlap** | A piece of a document that is embedded and retrieved on its own. Overlap repeats the end of one chunk at the start of the next, so a thought cut in half survives. |
| **Chunking strategy** | The rule that decides where the cuts go (every N tokens, at paragraph ends, at headings, where the topic changes…). |
| **Structure-aware chunking** | Cutting along the document's own structure: never across headings, tables kept whole. |
| **Sentence window** | Search single sentences (precise), then give the model the sentences around the match. |
| **Semantic chunking** | Cutting where the topic changes, detected by comparing neighbouring sentences' embeddings. |
| **Parent-child (small-to-big)** | Search small chunks; give the model the bigger section they belong to. |
| **Enrichment, contextual retrieval** | Adding context to what is embedded: the document title and section, or a short LLM-written description of where the chunk fits. |
| **Hypothetical questions** | Embedding, with a chunk, the questions it answers: users ask questions, documents state facts, and this brings the two closer. |
| **Embedding cache** | A memory of "this text, with this model, gave this vector", so the same text is never embedded twice. |
| **Idempotent upsert** | Writing the same chunk twice leaves one copy, because chunk ids are stable. |
| **Manifest, pipeline hash** | The record of what was ingested, when, from which bytes, with which settings. The pipeline hash is a fingerprint of the settings that shape the index. |
| **Dead-letter queue** | Where jobs that keep failing are parked for a person, instead of blocking the queue or retrying for ever. |
| **Consumer group** | Several workers reading one stream together: each job goes to exactly one of them, and a job a crashed worker held is claimed by another. |

### The six chunking strategies (Figure 99)

| Strategy | How it cuts | Good for |
|---|---|---|
| `fixed` | every N tokens, with overlap | simple; but cuts mid-thought |
| `recursive` | paragraph > sentence > word, only as fine as needed | fits, without crossing more than needed |
| `structure` | never crosses a heading; tables whole | the best default for documents with structure |
| `sentence-window` | one sentence per chunk, neighbours kept | precise match, context for the answer |
| `semantic` | cut where the topic changes | slower to ingest; good for long unstructured text |
| `parent-child` | search small, read big | children found, parents shown |

All six are in `rag.yaml` (`chunker: {use: …}`); Step 26's harness tells you which works best on *your*
documents.

### One chunk, three stores, one rule (Figure 100)

A chunk carries a stable id (`3f9a…`), the cited text, the embedded text (`title > section + text`), its
access rules (`internal · {hr} · tenant`) and metadata (page, section, PII kinds found, model). The same
chunk is stored in:

- **Postgres** (pgvector + full text): rows in `rag.documents` / `rag.chunks`; access joined in SQL;
- **Qdrant**: a point whose id is `uuid5(chunk id)`; a payload filter on tenant, classification and groups;
- **OpenSearch**: a document whose `_id` is the chunk id; BM25 and k-NN with a `bool` filter.

Each store applies the same access rule inside its own query, and all of them pass the same conformance
tests: ranking, idempotent upserts, deletes, metadata filters, and the access rule (no cross-group,
cross-clearance or cross-tenant result). A new store must pass them too.

## How to do it

Everything below is committed in this repository; the commands are the ones you run on your Mac.
Install the workspace first, as in every step:

```bash
uv sync --all-packages
```

### 1 · Parsers

**File: `libs/rag-core/src/rag_core/components/parsing.py`**: one parser per format, each with a
`mime_types` tuple and `parse(source) -> Document`, and a `ParserRouter` that picks one per source.

- `detect_mime(uri, data, declared)` trusts the **content first** (`%PDF-` at the start is a PDF whatever
  the file is called; `PK\x03\x04` with `word/` inside is a .docx; `<!doctype html` is HTML), then the
  **extension** (query strings ignored), then what the **sender declared**.
- `decode()` tries UTF-8 (with or without a byte-order mark), then UTF-16 when there's a UTF-16 BOM, and
  finally cp1252 with replacement characters: odd bytes never crash a run.
- **text**: paragraphs split on blank lines. **markdown**: headings (with their level), lists, tables and
  fenced code become their own elements; `[text](url)` becomes `text (url)` and `**bold**` becomes `bold`.
- **html**: headings, paragraphs, lists, captions and tables (as `cell | cell` rows); `script`, `style`,
  `nav`, `header`, `footer`, `aside`, `form`, `template`, `svg` are dropped. The `<title>` becomes the
  document title.
- **csv**: each row becomes `column: value; …` (empty cells left out) so a single row can be found and
  cited; `rows_per_element` groups N rows; the column names are kept in metadata.
- **pdf** (pypdf, extra `pdf`): text per page with the page number kept for "p. 12" citations. Lines that
  appear on at least half the pages (numbers ignored, so "page 3" equals "page 4") are running headers and
  footers and are dropped. A page with fewer than `min_chars_per_page` characters left is reported in
  `pages_without_text` (a scanned page that needs OCR), never silently indexed as empty. An encrypted,
  corrupt or entirely text-less PDF fails with a `ParseError` that says why.
- **docx** (python-docx, extra `docx`): `Heading N` styles become headings, `Title` the title, list styles
  list items, tables `cell | cell` rows; the title comes from the document properties.
- **tika** (`status: mocked`): sends legacy Office files, email, RTF and other formats to an Apache Tika
  server (`http://tika:9998`) and takes back plain text.
- **docling** (`status: reference`): IBM Docling's layout analysis, tables, reading order and OCR, converted
  to Markdown and parsed by the Markdown parser. Heavy (machine-learning models).

> **READING THE PARSERS**
> - The content decides the type, not the file name: `%PDF-` at the start is a PDF whatever it's called.
>   Then the extension, then what the sender declared.
> - Markdown and HTML keep structure: headings with levels, lists, tables as rows, code without its
>   fences. HTML drops navigation, scripts, footers and forms, the usual noise of web pages.
> - PDF: text per page with page numbers (for "p. 12" citations). Lines repeated on most pages (running
>   headers and footers, with numbers ignored so "page 3" equals "page 4") are dropped, and a page with
>   nothing else is reported in `pages_without_text`: a scanned page that needs OCR, never silently indexed
>   as empty. A PDF with no text at all, encrypted or corrupt fails with a reason.
> - CSV: each row becomes "column: value; …" so a single row can be found and cited.
> - Tika (Apache, a server handling ~1,000 formats) and Docling (IBM, layout analysis, tables, OCR) are
>   options for what the built-ins don't cover; Docling is heavy (machine-learning models) and marked
>   `reference`.
> - `ParserRouter` picks the first configured parser for each type, and says which types are configured
>   when one is missing.

### 2 · Cleaning and PII

**File: `libs/rag-core/src/rag_core/components/cleaning.py`**: normalisers (`normalize(document) ->
document`) and PII redactors (`redact(text) -> (text, kinds found)`).

- **unicode**: NFKC (ﬁ → fi, full-width → ASCII), control characters removed, words re-joined across
  line-break hyphens ("infor-\nmation" → "information"), whitespace collapsed; newlines in tables and code
  are kept.
- **boilerplate**: short elements (≤ `max_chars`, default 120) that repeat `min_repeats` times (default 3)
  are dropped (headings are never dropped), and exact duplicate paragraphs over 40 characters are kept
  once.
- **regex PII**: one pattern per kind, plus a validator that must agree before anything changes:

  | Kind | Pattern | Validator |
  |---|---|---|
  | `email` | `name@domain.tld` | none |
  | `credit_card` | 13-19 digits, spaces or dashes allowed | Luhn |
  | `au_tfn` | 9 digits (`123 456 782`) | TFN weights, mod 11 |
  | `au_abn` | 11 digits (`51 824 753 556`) | ABN weights, mod 89 |
  | `iban` | country, check digits, groups of 4 | mod 97 = 1 |
  | `phone` | Australian (`0412 345 678`, `+61 3 …`) or international (`+44 …`) | none |
  | `ipv4` | four 0-255 numbers | none |

  Strategies: `mask` → `[EMAIL]`; `pseudonymise` → `[EMAIL:3f1c…]`, an HMAC-SHA256 with a key from the
  environment variable named by `key_env` (default `RAG_PII_HMAC_KEY`); `remove` → nothing. Asking for
  pseudonymisation without a key fails at start-up with `pseudonymise needs a key`.
- **presidio** (`status: reference`, Microsoft Presidio): named-entity recognition for names and places
  plus rule-based recognisers including Australian IDs.
- `redact_document()` redacts every element and the title, and returns the kinds found (never the values).

> **READING THE PII REDACTOR**
> - Checksums before changes: a 16-digit number is only treated as a card if it passes the Luhn check; 9
>   digits only as a Tax File Number if they pass the TFN checksum; likewise ABN (mod 89) and IBAN (mod 97).
>   Precision matters: over-redaction destroys useful content ("ref 123 456 789" stays, tested).
> - Three strategies: mask ("[EMAIL]"), pseudonymise ("[EMAIL:3f1c…]", a keyed HMAC: the same address always
>   gives the same token, so "how many tickets did this customer open?" still works, but the token can't be
>   reversed without the key, which lives in OpenBao), remove.
> - What regexes can't do: names, addresses and free-text identifiers need named-entity recognition.
>   Presidio (Microsoft) adds that, including Australian recognisers; it needs a language model, so it's an
>   option, not the default.
> - Where it runs: after cleaning, before chunking, so no chunk, embedding, cache or log ever sees the
>   original. What was found is recorded on every chunk (`pii_redacted`), without the values.

### 3 · Chunkers

**File: `libs/rag-core/src/rag_core/components/chunking.py`**. Every chunker builds `Chunk`s with a stable
id (`Chunk.make_id(uri, index, text)`), the document's access, its token count (from the profile's
`token_counter`), and metadata: the title, the document's SHA-256, its language, its simple metadata
values, plus what the strategy adds. A shared `_windows()` packs units (words, sentences, paragraphs) into
windows of `max_tokens`, carries the last `overlap_tokens` worth of units into the next window, and
hard-splits a single unit that is too big by words. `overlap_tokens` must be smaller than `max_tokens`
(checked when the profile is validated).

| `use:` | Parameters (defaults) | What it does |
|---|---|---|
| `fixed` | `max_tokens: 400, overlap_tokens: 40` | every N tokens of the whole text |
| `recursive` | same | whole elements when they fit, sentences when they don't, words as a last resort |
| `structure` | same + `min_tokens: 60, heading_path: true` | per section; tables split by rows with the header repeated; tiny sections join the next one once; `section: "Leave policy > Parental leave"` |
| `sentence-window` | `window: 2` | one sentence per chunk, `metadata.window` = the sentences around it |
| `semantic` | `max_tokens, overlap_tokens, breakpoint_percentile: 90` | embeds every sentence (the profile's embedder) and cuts at the biggest similarity drops |
| `parent-child` | `parent_tokens: 1200, child_tokens: 200, child_overlap: 20` | structure-chunked parents; children carry `parent_id` and `parent_text` |

> **READING THE CHUNKERS**
> - Budgets in tokens, counted by the profile's `token_counter` (approximate by default; the embedding
>   model's own tokenizer as an option). No chunk exceeds `max_tokens` (tested for each strategy).
> - Overlap carries the tail of one chunk into the next, so a sentence cut at the boundary appears whole in
>   one of them.
> - Structure (the default): sections never mix; a table too big for one chunk is split by rows with its
>   header repeated in each part; a tiny section ("Purpose: …") joins the next one once, labelled with the
>   heading path they share. Our first version kept merging tiny sections into a snowball that crossed
>   several headings; the test caught it.
> - Sentence window and parent-child store context in metadata (`window`, `parent_text`), and Step 32 swaps
>   it in after retrieval: search precisely, read generously.
> - Semantic costs one embedding per sentence at ingestion; it pays off for long, unstructured text such as
>   transcripts.

### 4 · Enrichers and embedders

**File: `libs/rag-core/src/rag_core/components/enrichment.py`**. Enrichers decide *what is embedded* for a
chunk (`embed_text`); the chunk's own `text`, the part that is shown and cited, never changes. A chunk
saying "It is 18 weeks." embeds far better as "Leave policy > Parental leave: It is 18 weeks."

- **context-header** (`template: "{header}\n\n{text}"`): prepends "Title > Section > Subsection" (the title
  once, even when it's also the top heading). Free, and usually the best first improvement.
- **llm-context** (`max_document_chars: 24000`): Anthropic's "contextual retrieval" (2024). The profile's
  `llm` reads the document (a long one is cut to a window around the chunk) and writes one or two sentences
  placing the chunk in it; they're prepended to what is embedded and stored in `metadata.context`.
- **questions** (`n: 3`): asks the `llm` for N questions the chunk answers and appends them to what is
  embedded (`metadata.questions` keeps them).
- **gateway** embedder (`status: mocked`): `POST /embeddings` on the LiteLLM gateway (alias `embedder`,
  Qwen3-Embedding-0.6B on TEI, Step 8), `batch_size` texts per request, `Authorization: Bearer` from the
  variable named by `api_key_env` (`LLM_GATEWAY_KEY`), and a check that every vector has `dimensions`
  numbers. Queries get the asymmetric model's `query_instruction`.
- **cached** embedder: wraps any embedder (`inner: {use: gateway, …}`) with an LRU cache of `max_items`
  vectors keyed by model + kind (document or query) + SHA-256 of the text; it counts `hits` and `misses`.

> **READING THE ENRICHERS**
> - `context-header` prepends "Title > Section > Subsection" to what is embedded and keyword-indexed. It's
>   free and often the biggest single improvement: "It is 18 weeks." becomes findable for "parental leave".
> - `llm-context` is Anthropic's "contextual retrieval" (2024): an LLM writes one or two sentences placing
>   each chunk in its document. It costs one LLM call per chunk at ingestion; on the local models (Step 7)
>   that's affordable for thousands of chunks, and the cache means unchanged chunks are never redone.
> - `questions` adds the questions a chunk answers ("hypothetical question embeddings"), bridging how users
>   ask and how documents state.
> - The gateway embedder batches requests and checks the dimensions: if someone points the embedder alias
>   at another model, ingestion stops with a clear message instead of filling the index with incompatible
>   vectors (Step 36 covers the proper re-index).
> - The cache keys on model + text: re-ingesting unchanged chunks, or a repeated query, costs nothing.

### 5 · Postgres: one migration, two components

**File: `infra/db/rag/migrations/20261013000000_rag_core.sql`** (the guide names it
`<timestamp>_rag_core.sql`). On top of Step 11's tables it adds:

- `rag.documents.tenant` (default `'default'`) with a partial index on live documents;
- on `rag.chunks`: `chunk_key` (the stable chunk id; existing rows get their numeric id), `embed_text`,
  `parent_key`, `embedding_model`, and the constraint `UNIQUE (document_id, chunk_key)`;
- `embedding` may now be NULL (keyword-only rows written before their vectors);
- `content_tsv` regenerated over `coalesce(embed_text, content)`, so the title and section help keyword
  search too;
- `rag.ingest_manifest (collection, source_uri, content_sha256, pipeline_hash, chunk_count, status, detail,
  updated_at)` with `status IN ('indexed', 'failed', 'skipped')`.

The `migrate:down` half undoes each change (deleting keyword-only rows before making `embedding` NOT NULL
again). Apply it the usual way:

```bash
just db-migrate up
```

**File: `libs/rag-core/src/rag_core/components/pgstore.py`**: three components on one connection pool.

- `PgParams`: a DSN from the variable named by `dsn_env` (dev and tests) **or** `host`/`port`/`dbname` plus
  Step 28's OpenBao credentials file (`credentials_file: /run/bao/rag_db.json`, re-read for every new
  connection, so rotation needs no restart); `collection`; `dimensions`; `vector_type` (`halfvec`, or
  `vector` for pgvector older than 0.7); `ef_search` (HNSW recall/speed per query); `text_search_config`;
  `pool_size`. The collection row is created on first use.
- **pgvector**: upserts the document row (title, SHA-256, groups, classification, tenant: access lives on
  the document, as in Step 11) and the chunk rows (`ON CONFLICT (document_id, chunk_key)`); refuses vectors
  of the wrong size; searches with `ORDER BY embedding <=> query` joined to `rag.documents` and filtered by
  tenant, classification and groups **in the same statement**, after `SET LOCAL hnsw.ef_search`.
- **postgres-fts**: the same rows (keyword-only rows leave any existing embedding alone); searches with
  `ts_rank_cd`, the question's words OR-ed together (plain `websearch_to_tsquery` ANDs them and misses
  answers to long questions).
- **postgres** manifest: `rag.ingest_manifest`, durable and shared by every worker.
- Metadata filters are bound parameters (`metadata @> %s::jsonb`, or `metadata ->> key = ANY(%s)` for a
  list); the SQL text is built only from constant fragments, which is why ruff's S608 is waived in the file
  with that explanation.

> **READING THE POSTGRES STORE**
> - Step 11's tables, extended: a tenant per document; a stable `chunk_key`; `embed_text`, `parent_key` and
>   the embedding model per chunk; full-text search over what was embedded; and `rag.ingest_manifest`.
> - Access in SQL: the search joins `rag.documents` and filters by tenant, classification and groups in the
>   same statement, so a chunk someone may not see is never even returned by the database.
> - Two components, one table: `pgvector` (HNSW cosine search, `ef_search` per query) and `postgres-fts`
>   (stemmed full-text search, the words of a question OR-ed so long questions still match). Keyword-only
>   rows can exist before vectors arrive (tested).
> - Credentials come from a DSN variable (dev, tests) or Step 28's OpenBao credentials file, re-read per
>   connection.
> - A bug the tests caught: `chunk_key` was first unique across the whole table. The same source in two
>   collections (exactly what happens during a re-index) then overwrote the other collection's rows. It's
>   now unique per document.

### 6 · Qdrant and OpenSearch

**File: `libs/rag-core/src/rag_core/components/qdrant.py`**: the `qdrant` vector store over plain REST
(httpx, no client library). Step 12's design: the alias `rag_chunks`, the named vector `dense`, payload
fields `tenant_id` (a tenant index), `acl_groups`, `classification`, `source_uri`. Point ids are
`uuid5(namespace, chunk id)`, so a re-upsert overwrites. The access filter is a `must` list: tenant equals,
classification in the person's clearances, and a nested `should` (classification `public` OR a shared
group). `create_if_missing` is for dev and tests only: in production `scripts/qdrant_setup.py` (Step 12)
creates the collection with quantization and payload indexes, and the store refuses to invent one. The API
key comes from the variable named by `api_key_env` (`QDRANT_API_KEY`).

**File: `libs/rag-core/src/rag_core/components/opensearch.py`**: `opensearch` (BM25 over `text`,
`embed_text` and `title^2`, with Step 13's analyzers and synonyms) and `opensearch-knn` (Lucene HNSW on
`embedding`), on the alias `rag-chunks`. Writes are `_bulk` NDJSON with `refresh=wait_for` and `_id` = the
chunk id; deletes are `_delete_by_query` on `source_uri`. The access rule is a `bool` filter with
`minimum_should_match: 1`, and for k-NN it goes **inside** the `knn` query. The connection verifies
OpenSearch's CA (`/run/secrets/opensearch_ca.pem`); user and password come from the variables named by
`user_env`/`password_env`.

> **READING THE ENGINE ADAPTERS**
> - Step 12's and Step 13's designs: the alias names (`rag_chunks`, `rag-chunks`), the named vector `dense`,
>   the payload and keyword fields (`tenant_id`, `acl_groups`, `classification`, `source_uri`).
> - The same access rule, in each engine's language: a Qdrant filter with a nested "should" (public OR a
>   shared group); an OpenSearch bool filter with `minimum_should_match: 1`.
> - OpenSearch k-NN filters during the graph search (efficient filtering): a restricted user still gets k
>   results, not k minus the ones filtered away afterwards.
> - No client libraries: plain REST through httpx, so there's nothing extra to pin, and every request is
>   visible in tests.
> - Qdrant refuses to invent a production collection: `create_if_missing` is for tests; in production
>   `qdrant_setup.py` (Step 12) creates it with quantization and payload indexes.

### 7 · Queue, manifest and the pipeline

**File: `libs/rag-core/src/rag_core/components/queues.py`**

- `Job(op: "upsert" | "delete", uri, access, metadata, attempts, id)`, serialised as JSON.
- **memory** queue: in-process, same semantics as the real one (`put`, `get`, `ack`, `fail`, `size`); a job
  that has failed `max_attempts` times goes to the `dead` list with its error.
- **valkey-streams** queue (Step 15): `XADD` to `rag:ingest`; a consumer group `ingest-workers` (created
  once; a second worker finds it already there); `get()` first `XAUTOCLAIM`s jobs another worker has held
  for `claim_idle_ms` (5 minutes: it crashed), then `XREADGROUP`s a new one; `ack()` = `XACK` + `XDEL`;
  `fail()` re-adds the job with one more attempt, or adds it to `rag:ingest:dead` with the error. The
  Valkey URL comes from `url_env` (`VALKEY_URL`) or a file the OpenBao agent writes (`url_file:
  /run/bao/valkey_url`); the consumer name is the container's `HOSTNAME`.
- `ManifestEntry` and the **memory** manifest (the Postgres one is in `pgstore.py`).

**File: `libs/rag-core/src/rag_core/ingest.py`**

- `load_source(uri, access, metadata)`: `file:///path`, or `s3://bucket/key` from the object store (Step 14)
  through boto3 (credentials and endpoint from the standard AWS variables); anything else is refused.
- `pipeline_hash(config)`: a 16-character SHA-256 of the `parsers`, `normalizers`, `pii`, `chunker`,
  `enrichers`, `embedder` and `token_counter` settings.
- `IngestionPipeline(container, on_event)`: builds the stages from the profile (normalizers, pii and
  enrichers are optional; at least one of vector_store / keyword_index is required) and, per source:
  `unchanged` if the manifest has the same SHA-256 and pipeline hash (unless `force`); otherwise
  parse → normalise → redact → chunk → enrich → add `pii_redacted` to every chunk → embed (only if there is a
  vector store) → **delete the source's old chunks from every store** → write the new ones. Each stage is an
  OpenTelemetry span (`rag.ingest`, `rag.ingest.parse`, `rag.ingest.pii`, …); a `ParseError` becomes a
  `failed` result; an empty document becomes `skipped`. Every result goes to the manifest and to
  `on_event` (uri, status, chunks, sha256, pipeline, PII kinds, detail).
- `delete(uri)`: from every store and from the manifest.
- `Worker(pipeline, queue).run(forever)`: takes jobs until the queue is empty (or for ever); a parse
  failure is parked at once (`attempts` set past the limit); any other exception (a store down, a timeout,
  a missing file) is retried up to `max_attempts`.

> **READING THE PIPELINE**
> - Skip when nothing changed: the manifest compares the source's SHA-256 and a pipeline hash of the
>   settings that shape the index (parsers, cleaning, PII, chunker, enrichers, embedder). Change a chunk
>   size, and everything is re-ingested on the next run; change nothing, and nothing is redone.
> - Replace, not append: before writing a source's new chunks, its old ones are deleted from every store.
>   Without this, an edited policy leaves its old paragraphs searchable (tested: "18 weeks" is gone after the
>   edit).
> - Failures are results, not crashes: a corrupt PDF is recorded as `failed` with the reason and goes to the
>   dead-letter list at once (it won't fix itself); an I/O error or an unreachable store is retried up to
>   `max_attempts`.
> - Valkey Streams (Step 15): a consumer group shares jobs between workers; each job is acknowledged when
>   done; a job held by a crashed worker for 5 minutes is claimed by another.
> - Events (`on_event`) carry source, status, chunk count, hashes and PII kinds: the hook for Step 25's
>   lineage and Step 23's audit log.

### 8 · Profiles and the command line

**File: `rag.yaml`**: every ingestion slot is now filled.

```yaml
profiles:
  offline:          # runs anywhere, with nothing else running: tests, CI, demos, a new laptop
    token_counter: approx
    llm: {use: scripted, default: "I don't know."}
    parsers: [markdown, html, pdf, docx, csv, text]
    normalizers: [unicode, boilerplate]
    pii: {use: regex, strategy: mask}
    chunker: {use: structure, max_tokens: 400, overlap_tokens: 40, min_tokens: 60}
    enrichers: [context-header]
    embedder: {use: hashing, dimensions: 256}
    vector_store: memory
    keyword_index: memory-bm25
    manifest: memory
    queue: memory
  local:            # the platform on your Mac: real models and stores
    extends: offline
    pii: {use: regex, strategy: pseudonymise, key_env: RAG_PII_HMAC_KEY}
    embedder: {use: cached, inner: {use: gateway, model: embedder, dimensions: 1024, …}}
    vector_store / keyword_index / manifest: Postgres with credentials_file: /run/bao/rag_db.json
    queue: {use: valkey-streams, url_file: /run/bao/valkey_url}
  local-engines:    # the same, with Qdrant and OpenSearch instead of Postgres
    extends: local
    vector_store: {use: qdrant, …}
    keyword_index: {use: opensearch, …, user_env: OPENSEARCH_INDEXER_USER, password_env: OPENSEARCH_INDEXER_PASSWORD}
```

> **READING THE PROFILES**
> `offline` needs nothing running. `local` uses the platform: the gateway for models, Postgres for vectors,
> keywords and the manifest (credentials from OpenBao), Valkey for the queue, keyed pseudonymisation for
> PII. `local-engines` is the same with Qdrant and OpenSearch: two lines change, nothing else.

**File: `libs/rag-core/src/rag_core/cli.py`** gains four commands (each takes `--file` and `--profile`):

| Command | What it does |
|---|---|
| `rag ingest [--group g …] [--classification c] [--tenant t] [--force] URI…` | runs the pipeline on each source with that access; exit code 1 if any failed |
| `rag delete URI…` | removes each source from every store and the manifest |
| `rag enqueue [--group …] [--delete] URI…` | adds an upsert (or delete) job per URI to the profile's queue; prints the job id |
| `rag worker [--forever]` | takes jobs until the queue is empty, or for ever |

Each result line is `status  chunks  seconds  uri  [detail]  [pii: kinds]`.

**The image.** `services/rag-api/pyproject.toml` now depends on `rag-core[pdf,docx,postgres,valkey,s3]`,
and `services/rag-api/Dockerfile` copies `libs/rag-core` and `rag.yaml` (`ENV RAG_CONFIG=/app/rag.yaml`), so
the same image runs the API and the worker; `RAG_PROFILE` picks the profile per deployment.

**The worker's secrets.** The OpenBao agent (Step 28) renders two more files from `secret/rag-api`,
never environment variables. Both `infra/config/openbao/agent-rag-api.hcl` and
`deploy/base/rag-api/openbao-agent.hcl` gain:

```hcl
# Step 31: what the ingestion worker (same identity as rag-api, Step 37 separates them) needs
template {
  contents             = "{{ with secret \"secret/data/rag-api\" }}{{ .Data.data.valkey_url }}{{ end }}"
  destination          = "/openbao/out/valkey_url"
  perms                = "0400"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/rag-api\" }}[default]\naws_access_key_id = {{ .Data.data.s3_access_key }}\naws_secret_access_key = {{ .Data.data.s3_secret_key }}\n{{ end }}"
  destination          = "/openbao/out/aws_credentials"
  perms                = "0400"
  error_on_missing_key = true
}
```

**The service.** `infra/compose/compose.yaml` adds `ingestion-worker`: the `rag-platform/rag-api:dev` image
running `rag worker --forever` with `RAG_PROFILE: local`, `AWS_SHARED_CREDENTIALS_FILE:
/run/bao/aws_credentials` (the S3_INGEST identity from Step 14), `AWS_ENDPOINT_URL_S3:
http://object-store:8333`, its own `OTEL_SERVICE_NAME`, the agent's files mounted read-only at `/run/bao`,
a read-only root filesystem, `/tmp` in RAM, no capabilities, two replicas of 1 CPU / 1 GB, and logs to the
Collector.

Put the new values into OpenBao, then restart the agent:

```bash
just vault-put rag-api gateway_key=RAG_API_GATEWAY_KEY opa_token=RAG_API_OPA_TOKEN \
    valkey_url=RAG_API_VALKEY_URL s3_access_key=S3_INGEST_ACCESS_KEY s3_secret_key=S3_INGEST_SECRET_KEY
just vault-agent-start
```

Ingest:

```bash
uv run rag ingest --profile offline --group hr examples/corpus/*                            # try it with nothing running
uv run rag enqueue --profile local --group hr s3://rag-raw-docs/hr/leave-policy.pdf        # the platform way
docker compose -f infra/compose/compose.yaml logs -f ingestion-worker
```

Output with the offline profile (this repository's run):

```
$ uv run rag ingest --profile offline --group hr examples/corpus/*
failed       0 chunks   0.00s   file://…/examples/corpus/broken.pdf   unreadable PDF: Stream has ended unexpectedly
indexed      2 chunks   0.00s   file://…/examples/corpus/leave-policy.md   pii: email, phone
indexed      1 chunks   0.00s   file://…/examples/corpus/offices.csv   pii: phone
indexed      1 chunks   0.00s   file://…/examples/corpus/remote-work.html
indexed      1 chunks   0.02s   file://…/examples/corpus/security-policy.docx
indexed      1 chunks   0.01s   file://…/examples/corpus/travel-policy.pdf
```

Into Postgres with pgvector, then again with nothing changed:

```
indexed      2 chunks   0.05s   …/leave-policy.md   pii: email, phone
indexed      1 chunks   0.01s   …/remote-work.html
indexed      1 chunks   0.03s   …/travel-policy.pdf
indexed      1 chunks   0.04s   …/security-policy.docx

unchanged    2 chunks   0.03s   …/leave-policy.md
unchanged    1 chunks   0.00s   …/remote-work.html
unchanged    1 chunks   0.00s   …/travel-policy.pdf
unchanged    1 chunks   0.00s   …/security-policy.docx
```

What landed in `rag.chunks`:

```
 source               | n | acl_groups | class    | tokens | embedded text
----------------------+---+------------+----------+--------+--------------------------------------------
 leave-policy.md      | 0 | {hr}       | internal |     56 | Leave policy  All staff accrue leave from their
 leave-policy.md      | 1 | {hr}       | internal |     50 | Leave policy > Parental leave  Parental leave is
 remote-work.html     | 0 | {hr}       | internal |     30 | Remote work > Remote work policy  You may work f
 security-policy.docx | 0 | {hr}       | internal |     35 | Security policy > Passwords  Use a password mana
 travel-policy.pdf    | 0 | {hr}       | internal |     39 | Travel policy  Travel policy Economy class for f
```

Every chunk carries the source's access (`{hr}`, internal), its token count, and an embedded text that
starts with where it came from.

### 9 · Test it, against real stores

| File | What it covers |
|---|---|
| `libs/rag-core/tests/conftest.py` | sample documents in every format, generated in the test (Markdown, HTML, a three-page PDF via reportlab with a footer and a text-less page, a Word file, CSV, text): no binary files needed |
| `libs/rag-core/tests/test_parsing_cleaning.py` | 28 tests: structure per format, chrome dropped, pages and footers, scanned pages, broken PDFs, type detection, decoding, normalisers, every PII kind, checksums against false positives, the three strategies |
| `libs/rag-core/tests/test_chunking_enrichment.py` | 15 tests: budgets, overlap, stable ids, sections and tables, header repetition, tiny sections, windows, semantic cuts, parent-child, enrichers, the gateway embedder (batches, query instruction, wrong dimensions), the cache |
| `libs/rag-core/tests/test_stores.py` | 10 tests: pgvector and Postgres FTS on a real Postgres (the real migrations applied), Qdrant on a real `qdrant` binary, OpenSearch by its exact requests, the Postgres manifest |
| `libs/rag-core/tests/test_ingest.py` | 10 tests: every format with its access, redacted and enriched storage, skip/replace, pipeline changes, deletes, failures, events, file and S3 sources (moto), the worker's retries and dead letters, the Valkey Streams queue (fakeredis) |

The store tests need a Postgres with pgvector and the Qdrant binary. Both are already there: `just
audit-test`'s container is the pgvector image (Step 23), and Qdrant is pinned in `ci/tools.yaml` (1.19.2,
checksums for Linux and macOS):

```bash
just tools qdrant          # into .tools/bin (on PATH via .envrc)
just audit-test            # sets AUDIT_TEST_ADMIN_DSN and RAG_TEST_PGVECTOR_DSN on the same throwaway Postgres
```

In `ci.yml`, the checks job gets `RAG_TEST_PGVECTOR_DSN` (the same Postgres service) and installs `qdrant`
with the other pinned tools.

> **WHAT THE TESTS PROVE**
> - Parsers: every format keeps its structure; HTML drops chrome; PDF keeps pages, drops footers, reports
>   scanned pages and fails clearly on broken or text-less files; type detection trusts content first; odd
>   encodings never crash.
> - Cleaning and PII: each PII kind is found; checksums prevent false positives; the three strategies behave
>   (pseudonyms are stable per key and differ between keys).
> - Chunkers: no chunk exceeds its budget; overlap carries context; ids are stable; sections and tables are
>   respected, big tables repeat their header, tiny sections join once; windows, semantic cuts and parent
>   links are right.
> - Enrichers and embedders: what is embedded changes, what is cited doesn't; the gateway embedder batches,
>   adds the query instruction and refuses wrong dimensions; the cache never embeds twice.
> - Stores: pgvector, Postgres full-text search and Qdrant pass the conformance kit against the real
>   services, including the access-control checks; Qdrant needs its key; OpenSearch sends exactly the right
>   filtered requests; the manifest round-trips in Postgres.
> - Pipeline: every format is indexed with its access; stored text is redacted and enriched; unchanged
>   sources are skipped, edited ones replaced, pipeline changes re-index; deletes reach every store; failures
>   are recorded; the worker retries and parks jobs; the Valkey queue keeps its promises.

### 10 · Record the decision

`docs/adr/0031-ingest-through-a-replace-not-append-pipeline.md`: one rag-core pipeline that redacts before
storing, replaces instead of appending, copies access to every chunk and enforces it in every store, skips
unchanged sources with a manifest, and runs as jobs on Valkey Streams. Alternatives considered: one heavy
parser (Unstructured / Docling), fixed-size chunks only, append-only indexing, redaction at query time,
Kafka / RabbitMQ. Revisit when documents are mostly scanned, a project needs per-field encryption, or volume
needs a dedicated stream processor.

## Benefits

- Every common format, structure kept, with clear failures for what can't be read.
- Nothing personal in the index unless a project explicitly allows it.
- Chunking that fits the content, chosen per project, measurable with Step 26.
- Current, not stale: edits replace, deletes reach every store.
- Cheap to re-run: unchanged sources and texts cost nothing.
- One access rule in every store, proven against the real services.

## Drawbacks and risks

- **Parsing is never perfect:** complex layouts (multi-column PDFs, nested tables, forms) need Docling or
  manual fixes; scanned pages need OCR.
- **Regex PII has blind spots:** names, addresses, free-text identifiers. Measure on real samples before
  relying on it.
- **Enrichment costs:** LLM context and questions add one model call per chunk at ingestion.
- **Replace-not-append has a short gap:** between deleting old chunks and writing new ones, a search may miss
  that document. For zero-gap updates, ingest into a new collection and switch the alias (Step 36).
- **The manifest is per collection:** two collections ingest independently.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Built-in parsers (default) | Small, fast, dependency-light | Digital documents with ordinary layouts |
| Docling | Layout analysis, tables, OCR (IBM) | Complex PDFs, scans, forms |
| Unstructured | Many formats, partitioning, OCR (open source or API) | Mixed document estates |
| Apache Tika | Text from ~1,000 formats | Legacy Office, email, archives |
| LlamaParse / Azure Document Intelligence / AWS Textract / Google Document AI | Managed, high-quality parsing | Data may leave your environment; volume justifies the cost |
| Presidio | NER-based PII detection with many recognisers | Free-text personal data (names, addresses) |
| Late chunking | Embed the whole document with a long-context model, then pool token vectors per chunk | Long documents where chunks lose context; needs a model that supports it |
| ColBERT / multi-vector | One vector per token, matched late | Highest retrieval quality, at more storage |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Policies, handbooks, wikis (structured text) | Structure chunker + context headers (the default) |
| Transcripts, chats, long unstructured text | Semantic or recursive chunking + LLM context |
| FAQs, short precise facts | Sentence window or small chunks |
| Contracts, manuals (answers need surrounding detail) | Parent-child |
| Scanned archives | Docling with OCR; check `pages_without_text` |
| Personal data in documents | Pseudonymise (keyed) or remove; Presidio for names |
| Very large volumes | More workers on the Valkey stream; Qdrant or OpenSearch for the index |

## Common mistakes

- Indexing the old version beside the new one.
- Embedding before redacting (the vector store, caches and logs now hold the PII).
- One chunk size for every document type, never measured.
- Splitting tables into word soup or losing their headers.
- Silently indexing scanned pages as empty.
- Treating embedded text as citation text (show the reader the original chunk text).
- No access labels on chunks, "to be filtered later".
- Retrying a corrupt file for ever instead of parking it.

## Done when

- [ ] `uv run rag ingest --profile offline --group hr examples/corpus/*` indexes five files and reports the
      broken PDF as failed
- [ ] Migration applied; `rag config validate --profile local` and `--profile local-engines` report 0 problems
- [ ] With the platform up: `rag enqueue --profile local …` and the ingestion-worker logs show `indexed`; a
      second enqueue shows `unchanged`
- [ ] `select count(*) from rag.chunks` matches the worker's totals; `rag delete …` removes them
- [ ] `just audit-test` shows 347 passed in the guide's count (store tests run, not skipped)
- [ ] ADR-0031 is committed

## Recap

> **RECAP**
> Documents now reach the index the way they should:
> - parsed with structure (pages, headings, tables), cleaned, with scanned pages reported
> - redacted before storing, with checksums keeping false positives down
> - cut sensibly by one of six strategies and enriched so chunks can be found
> - embedded and indexed into Postgres, Qdrant or OpenSearch, with the same access rule in each, proven
>   against the real services
> - kept current and cheap: replace-not-append, a manifest, a queue with retries and dead letters
>
> Next, Step 32: finding the right chunks for a question: dense, keyword and hybrid search, query rewriting,
> reranking and more.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-core/src/rag_core/components/parsing.py` | Type detection, decoding, and the text, Markdown, HTML, CSV, PDF, DOCX, Tika and Docling parsers; `ParserRouter` |
| `libs/rag-core/src/rag_core/components/cleaning.py` | Unicode and boilerplate normalisers; checksummed regex PII redaction (mask, pseudonymise, remove); Presidio option; `redact_document` |
| `libs/rag-core/src/rag_core/components/chunking.py` | The six chunkers: fixed, recursive, structure, sentence-window, semantic, parent-child |
| `libs/rag-core/src/rag_core/components/enrichment.py` | Context-header, LLM-context and questions enrichers; the gateway embedder and the cached embedder |
| `libs/rag-core/src/rag_core/components/pgstore.py` | pgvector vector store, Postgres full-text keyword index and Postgres manifest on one pool |
| `libs/rag-core/src/rag_core/components/qdrant.py` | Qdrant vector store over REST with the access rule as a payload filter |
| `libs/rag-core/src/rag_core/components/opensearch.py` | OpenSearch BM25 keyword index and k-NN vector store over REST |
| `libs/rag-core/src/rag_core/components/queues.py` | Jobs, the memory and Valkey Streams queues (retries, dead letters, crash recovery), the memory manifest |
| `libs/rag-core/src/rag_core/ingest.py` | `load_source`, `pipeline_hash`, `IngestionPipeline` and `Worker` |
| `libs/rag-core/src/rag_core/cli.py` (changed) | `rag ingest`, `delete`, `enqueue`, `worker` |
| `libs/rag-core/pyproject.toml` (changed) | `opentelemetry-api`; `psycopg-pool` in the postgres extra; a new `s3` extra (boto3) |
| `libs/rag-core/tests/conftest.py` | Sample documents in every format, generated in the test |
| `libs/rag-core/tests/test_parsing_cleaning.py` | The guide's 28 parser, normaliser and PII tests |
| `libs/rag-core/tests/test_chunking_enrichment.py` | The guide's 15 chunker, enricher and embedder tests |
| `libs/rag-core/tests/test_stores.py` | The guide's 10 store tests (live Postgres and Qdrant, OpenSearch by its requests) |
| `libs/rag-core/tests/test_ingest.py` | The guide's 10 pipeline, worker and queue tests |
| `libs/rag-core/tests/test_cli_ingest.py` | 3 extra tests: the corpus matches its generator; `rag ingest/delete/enqueue/worker` on it |
| `libs/rag-core/tests/test_registry.py` (changed) | Step 30's two stand-in tests switched back to the guide's `pgvector` and `pii: regex` |
| `libs/rag-core/tests/test_core_contracts.py` (changed) | The embedder list now includes `cached` and `gateway` |
| `infra/db/rag/migrations/20261013000000_rag_core.sql` | Tenants, chunk keys, embedded text, parent keys, models, FTS over embedded text, `rag.ingest_manifest` |
| `rag.yaml` (changed) | The `offline`, `local` and `local-engines` profiles with every ingestion slot |
| `examples/corpus/*` | The sample corpus: Markdown, HTML, CSV, PDF, Word and a corrupt PDF |
| `scripts/make_corpus.py` | Writes `examples/corpus/` reproducibly (fixed dates) |
| `services/rag-api/pyproject.toml` (changed) | Depends on `rag-core[pdf,docx,postgres,valkey,s3]` |
| `services/rag-api/Dockerfile`, `.dockerignore` (changed) | The image contains rag-core and `rag.yaml` (`RAG_CONFIG`) |
| `infra/compose/compose.yaml` (changed) | The `ingestion-worker` service |
| `infra/config/openbao/agent-rag-api.hcl`, `deploy/base/rag-api/openbao-agent.hcl` (changed) | `valkey_url` and `aws_credentials` rendered into files |
| `scripts/new-dev-secrets.sh`, `.env.example` (changed) | `RAG_API_VALKEY_URL` and `RAG_PII_HMAC_KEY` |
| `ci/tools.yaml` (changed) | The pinned `qdrant` 1.19.2 binary |
| `justfile`, `.github/workflows/ci.yml` (changed) | `RAG_TEST_PGVECTOR_DSN` for the store tests; CI installs `qdrant` |
| `pyproject.toml`, `uv.lock` (changed) | Dev dependencies `reportlab` and `fakeredis`; mypy settings for the new files |
| `ci/licence-policy.yaml` (changed) | `MIT-CMU` (Pillow) allowed; reportlab's BSD-3-Clause recorded |
| `tests/test_ci_tools.py`, `tests/test_vault.py` (changed) | `qdrant` in the tool manifest; the agent test seeds and checks the new files |
| `docs/adr/0031-ingest-through-a-replace-not-append-pipeline.md` | ADR-0031 |

## Notes for this repository

- **Example bucket:** the chapter's examples name a `rag-originals` bucket, which nothing creates. Step 14's
  `scripts/s3_setup.py` creates `rag-raw-docs` for originals, and the `rag-ingest` / `rag-reader` identities are
  granted no other originals bucket, so the commands, docstrings and tests here use `s3://rag-raw-docs/…`
  (`tests/test_object_storage.py` checks that every example names a bucket that exists).
- **Code reconstructed from the PDF.** The guide's listings were extracted from the PDF and their
  indentation and line wraps rebuilt; the conftest's HTML sample lost its tags in extraction and was rebuilt
  from what the tests assert (title "Remote work", a `track()` script, a "Home | HR" nav, an Item/Budget
  table, a copyright footer). One literal changed: the Markdown parser keeps a line indented by two spaces
  (`"  "`) as part of the list item above it; the extracted text showed a run of spaces whose exact width was
  lost.
- **Two small additions to the guide's components and CLI.** `rag ingest`/`enqueue`/`delete` turn a local
  path into a `file://` URI (the guide's output shows `file://…/examples/corpus/…` for
  `examples/corpus/*`, which needs exactly that). `psycopg-pool` is in the `postgres` extra and `boto3` in
  a new `s3` extra, because `pgstore.py` and `load_source("s3://…")` import them; `opentelemetry-api` is
  declared because `ingest.py` imports it.
- **Docling and Presidio extras are not declared.** Their components name the extras `docling` and
  `presidio` (status `reference`); declaring them would add over a hundred heavy packages (PyTorch, spaCy…)
  to `uv.lock` for everyone. A project that wants them installs them itself (`uv add docling`, or
  `uv add presidio-analyzer presidio-anonymizer` plus a spaCy model); mypy is told to skip those imports.
- **The worker's two environment variables.** The `local` profile reads the gateway key and the PII key
  from environment variables (`api_key_env`, `key_env`), but the guide's Compose service sets neither, so
  the worker could not start. Here it gets `LLM_GATEWAY_KEY: ${INGESTION_GATEWAY_KEY:-}` (Step 10's
  ingestion virtual key) and `RAG_PII_HMAC_KEY: ${RAG_PII_HMAC_KEY:-}`, passed from SOPS by
  `just with-secrets docker compose up -d`, until Step 37 gives the worker its own OpenBao identity. The
  secrets generator now creates `RAG_PII_HMAC_KEY` and `RAG_API_VALKEY_URL` (built from
  `VALKEY_APP_PASSWORD`), so `just vault-put … valkey_url=RAG_API_VALKEY_URL` has a value to store.
- **The sample corpus is committed**, so the "Done when" command works straight after a clone;
  `scripts/make_corpus.py` regenerates it byte for byte (reportlab's invariant mode and a fixed date in the
  Word file), and a test checks the committed files match the generator.
- **mypy and two `conftest.py` files.** mypy refuses two top-level modules both called `conftest`
  (rag-api's and rag-core's test folders aren't packages), so rag-core's `conftest.py` (sample documents
  only) is excluded from mypy; every test that uses it is checked. One `type: ignore` in the guide's
  `test_stores.py` was unused under this repository's psycopg and was removed.
- **Licences.** reportlab (BSD-3-Clause, declared only as "BSD license") is recorded as an exception and
  Pillow's MIT-CMU added to the allowed list.
- **Validation here (Linux container):** ruff, ruff format, strict mypy and every pre-commit hook pass. The
  whole suite ran with a throwaway `pgvector/pgvector:0.8.7-pg17` container (the `just audit-test` setup)
  and the pinned `qdrant` binary: all 10 store tests and the 63 new guide tests pass (rag-core: 116 tests),
  including the live OpenBao agent test rendering the two new files. The corpus was ingested into a real
  Postgres with the migrations applied (the same chunk counts and token counts as the guide: 56, 50, 30,
  35, 39), re-run as `unchanged`, and deleted; `enqueue` + `worker` ran against a real Valkey with the
  broken PDF landing on `rag:ingest:dead`. Not run here: the Compose worker against the full stack (gateway,
  OpenBao, object store) on your Mac.
