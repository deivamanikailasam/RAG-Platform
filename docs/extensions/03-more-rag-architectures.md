# Extension 03 · More RAG architectures, GraphRAG global search and MCP tools for agents

*Extension 03 · after the 38 guide steps · RAG core (answers and agents)*

## At a glance

| | |
|---|---|
| **Goal** | Every RAG architecture people ask for by name is one word in the `pipeline` slot, tested offline and compared on the same questions; GraphRAG can answer "big picture" questions and keep its graph in Postgres; agents can use the platform's search and answer as tools, under the same permissions. |
| **How, in one sentence** | Eleven new `pipeline` components (plus two second names), a `toc_store` slot that keeps each document's contents page, an `llm-entities` enricher and a `postgres` graph store (new migration), and a `rag mcp` command that speaks the Model Context Protocol over stdio with an identity fixed at launch. |
| **You'll end up with** | pipelines `vector`, `keyword`, `pageindex` (also `vectorless`), `rag-fusion` (also `multi-query`), `hyde`, `conversational`, `long-context`, `table`, `flare`, `speculative`, `graph-global` · slot `toc_store: memory` · enricher `llm-entities` · graph store `postgres` (migration `20261016000000_graph_store.sql`, row-level security per tenant) · `rag mcp` with `search` and `answer` tools · `--filter key=value` that matches text such as section "4.2" · nine new rows in `rag eval-answers` · ADR-0041. |
| **New words** | vector RAG, vectorless RAG, reasoning-based retrieval, PageIndex, table-of-contents tree, RAG-Fusion, active retrieval, FLARE, speculative RAG, drafter, verifier, community detection, label propagation, community summary, global search, long-context routing, table QA, MCP, MCP tool, stdio transport, launch identity. |

## In plain English

> **IN PLAIN ENGLISH**
> Step 35 made "how the platform gathers context and checks an answer" a switch with eight
> positions. People keep asking for others by name: "vector RAG", "vectorless RAG", "RAG-Fusion",
> "HyDE", "FLARE", "speculative RAG", "GraphRAG global search", "long context instead of RAG". Some
> of those were already possible as a *combination* of settings; some were not possible at all.
> This extension gives each one its own name in the same slot, so trying one is a one-word change
> and `rag eval-answers` puts them side by side. Nothing else changes when you switch: the same
> permission filter, guards, citation checks, cache, memory and audit apply to every one.
>
> It also opens the platform to **agents**: an assistant such as Claude Desktop or an IDE agent can
> start `rag mcp` and call two tools, *search* and *answer*. Who is asking is decided by whoever
> starts the server, never by the model, so an agent can't read more than its user could.

> **ANALOGY · ONE LIBRARY, MORE WAYS TO USE IT**
> The library from Step 32 now offers more services at the same desk, under the same rules about
> who may read what:
> - **the card catalogue only** (`vector`), or **the word index only** (`keyword`);
> - **the contents pages** (`pageindex`): the librarian reads each book's table of contents and
>   opens the right chapter, without any catalogue at all;
> - **asking four ways** (`rag-fusion`): the same question, reworded four times, and the books
>   that come up most often win;
> - **imagining the answer first** (`hyde`), then looking for pages that read like it;
> - **writing a draft and checking it** (`flare`): wherever the draft sounds unsure, go back to the
>   shelves for that sentence;
> - **three assistants, one editor** (`speculative`): each assistant drafts from a different pile of
>   pages, the senior editor picks the best draft;
> - **the subject map** (`graph-global`): which topics cluster together, with a one-paragraph
>   summary of each cluster, for "what are the main themes?";
> - **the whole booklet** (`long-context`): if the right booklets are short, hand over the
>   booklets, not photocopied pages;
> - **the price list** (`table`): look the row up in the spreadsheet;
> - **a phone line for robots** (`rag mcp`): a robot assistant can call the desk, but it must say
>   on whose library card, and that card was checked when the line was set up.

## What we're doing

1. One-retriever pipelines: `vector` (dense only, still reranked) and `keyword` (BM25 only).
2. Vectorless, reasoning-based retrieval: `pageindex` (also `vectorless`) with a `toc_store`.
3. Named presets for query-side techniques: `rag-fusion` (also `multi-query`), `hyde`,
   `conversational`.
4. Generation-side techniques: `flare` (active retrieval) and `speculative` (drafts + verifier).
5. GraphRAG upgrades: `llm-entities`, `graph-global` (communities and summaries), the `postgres`
   graph store; Neo4j, Microsoft GraphRAG and LightRAG as references.
6. Routing by size and by data type: `long-context`, `table`; multimodal notes.
7. Agents: `rag mcp`, and its trust model.
8. A papercut: `rag search --filter section_numbers=4.2` now finds section 4.2.

## Why this matters

- **Names are how people compare.** A team that read about RAG-Fusion or PageIndex wants to try it on
  *their* questions this afternoon, not assemble it from five settings. One word, one evaluation row.
- **Different questions need different strategies.** "What does E-1107 mean?" (one exact fact),
  "what are our main security rules?" (a summary across documents), "what is the per diem in
  London?" (a table row) and "how do I fix it?" (a follow-up) are answered best by different
  pipelines; the router-style ones here (`graph-global`, `long-context`) choose per question.
- **Embeddings are not always available or wanted.** Air-gapped sites, tiny corpora, well-structured
  manuals and legal texts often do as well or better with keywords or contents pages, and avoid an
  embedding model, a vector index and re-indexing when the model changes.
- **Agents are becoming a main way people reach knowledge.** Exposing search through MCP lets them
  use the platform instead of copying documents into prompts, and the permission model goes with it.

## How it works

### 1. `vector` and `keyword`: one retriever, everything else as configured

| Pipeline | Retrieval | Transformer, reranker, post-processors | Differs from |
|---|---|---|---|
| `naive` (Step 35) | dense top-k | **none**: the textbook baseline | |
| `vector` | dense only | **as configured** | `naive` (reranked, rewritten, filtered) and `standard` (no keyword search) |
| `keyword` | keyword (BM25) only | as configured | `standard` (no embeddings at query time) |

`vector` refuses to start without a `vector_store`; `keyword` without a `keyword_index`. A profile
with **no vector store and no embedder at all** now ingests (keyword index and/or contents store
only): that is a fully vectorless deployment.

### 2. Vectorless RAG by contents pages: `pageindex`

PageIndex (VectifyAI, 2025) showed that for long, structured documents a model can find the answer
the way a person does: read the table of contents, open the right chapter, read the right section.
No chunk embeddings, no similarity search.

```
ingest:  parse ─▶ … ─▶ toc_store.add(document)   one passage per heading, with its heading path
query:   the documents THIS person may see ─▶ a tree
            [12] Remote work
              [12.1] How many days
              [12.2] Home office allowance — Staff can claim up to 500 AUD once…
            [16] VPN troubleshooting
              [16.1] Error E-4021   [16.2] Error E-1107   [16.3] Error E-3003
         step 1 (model): {"open": ["16"]}            which documents to open
         step 2 (model): {"read": ["16.2"]}          which sections to read
         ─▶ the sections' text, cited like any chunk ─▶ the usual answer steps
```

- **The tree comes from the parsed document's headings** (Markdown, HTML, Word, Docling), the same
  heading paths the `structure` and `hierarchical` chunkers record (`section`, `section_path`,
  `section_numbers`), but independent of how the document was chunked for search: small sections
  that `structure` merged for search stay separate in the contents. A document without headings
  becomes one node (its own chunks).
- **The model's walk** (`navigator: llm`): two short calls. Its replies are JSON lists of ids,
  checked against the tree (an unknown id is ignored); the contents are wrapped in `<toc>` and
  marked as data. A huge tree is first narrowed by the heuristic (`max_toc_lines`).
- **The offline walk** (`navigator: heuristic`, and the fallback whenever the model's reply is
  unusable or the model is down): score every node by term overlap between the question and its
  heading path (plus a little on the first sentence of a leaf); keep the best `max_sections`, never
  a section and its own parent, ignore matches below `min_score`.
- **Nothing chosen:** `fallback: keyword` searches the keyword index; `none` abstains.
- **Permissions:** the tree is built per question from the documents the person may see, and the
  request's metadata filter narrows it: a hidden document's headings are never shown to the model.
  Delete and `rag reacl` reach the contents store like every other store.

### 3. Query-side presets: `rag-fusion`, `hyde`, `conversational`

These were possible before as a `query_transformer` in `standard`; as pipelines they carry their
own settings, a trace that says what they did, and a no-model mode.

- **`rag-fusion`** (also `multi-query`; Raudaschl, 2023): one call to the fast model writes
  `variants` rephrasings; refusals and repeats are dropped. **Each** text (the question first) goes
  through the configured retriever on its own, in parallel; the lists are fused with reciprocal
  rank fusion (`rrf_k`), then reranked against the **original** question. `variant_source:
  heuristic` (or no model) uses the question's content words and the parts of a compound question.
- **`hyde`** (Gao et al., 2022): the model writes the passage it expects to find; the passage is
  embedded like a document and searched with the question (`keep_question`). Keyword search skips the
  invented text; the reranker never sees it; a refusal is not used as a passage.
- **`conversational`**: with `memory:` configured, a follow-up ("how do I fix it?") is rewritten into
  a standalone question by the fast model, and both are searched. A first question costs no call.
  `rewriter: heuristic` (or a failed call) searches "last question + this question" instead. The
  trace says which rewrite ran and whether memory is on.

### 4. Generation-side: `flare` and `speculative`

```
flare:        answer ─▶ weak sentences? ─▶ search FOR them ─▶ new evidence first ─▶ answer again
               (no citation, unsupported,            │                     keep the answer with
                or hedged: might, probably…)          └ access, post-check, guards as always
                                                                          fewer weak sentences

speculative:  context [1 2 3 4 5 6] ─▶ subsets [1 4] [2 5] [3 6]  (dealt round-robin)
              fast model ─▶ draft A, draft B, draft C              (in parallel)
              quality model ─▶ "2"                                 (reads, doesn't write)
              draft B, its [doc n] renumbered to the full context ─▶ citation check, guards
```

- **`flare`** is the "check the draft" form of FLARE (Jiang et al., 2023): rather than predicting each
  next sentence, it finds the answer's low-confidence sentences after the fact, searches with each
  one (anchored to the question when short), and regenerates with the new evidence placed first.
  Up to `max_rounds` answers; the one with fewer weak sentences wins. `self-reflective` (Step 35)
  re-searches with the *question* more widely; `flare` searches for *what the answer is unsure of*.
- **`speculative`** (Wang et al., 2024): `drafts` subsets, one draft each by the fast model
  (`drafter: llm`, slot `drafter_slot`; `generator` uses the profile's own generator), then the
  quality model picks one (`verifier: llm`, slot `verifier_slot`, falling back to `answer_llm`, then
  `llm`). Offline or if the verifier's reply is unusable, `verifier: support` picks the draft with
  the most supported, cited sentences. One failed draft is skipped; if all fail, one ordinary
  answer is written over all the evidence. The quality model reads short drafts instead of
  writing a long answer over everything.
- Both are **never streamed as a draft** (the first text may be replaced), like `self-reflective`.

### 5. GraphRAG: `llm-entities`, `graph-global`, the `postgres` graph store

- **`llm-entities`** (enricher): the model returns `{"entities": [{name, type}], "relations":
  [{source, type, target}]}` for each chunk. It is **validated**: names normalised, types limited
  to `entity_types` (others become `concept`), relation types to `relation_types` if given, and
  a relation whose ends aren't listed entities is dropped. An unusable reply (or no model) falls
  back to the offline extractor (codes, acronyms, Title Case phrases, your `terms`) with
  `mentioned_with` relations between entities named in the same sentence. Counts of each path are
  in `stats`.
- **`graph-global`** (pipeline), Microsoft GraphRAG's "global search", simplified:

```
the graph THIS person may see ─▶ entities linked by co-mentions (+2 per explicit relation)
   ─▶ communities by label propagation (deterministic: sorted order, ties to the smallest label)
      or connected components
   ─▶ per community: its chunks, a summary (extractive, or the model's with `summarizer: llm`),
      its relations ─▶ cached until the graph changes
   ─▶ the communities closest to the question (+ a little for size) ─▶ a summary passage per
      community ("graph://community/…") + its best source chunks ─▶ the usual answer steps
```

  `route: auto` sends only "big picture" questions here ("main themes", "summarise", "overview",
  "across all…"); a question about one named thing takes the local `graph` path. Communities are
  computed **per person** from chunks they may see, so a restricted document's entities never shape,
  name or summarise a community; a summary passage carries the access of its most restricted source.
- **`graph_store: postgres`**: chunks (with the same access columns as documents), mentions and
  relations in three tables, deleted with their chunk (`ON DELETE CASCADE`), reads filtered by
  access **in SQL**, and row-level security per tenant (Step 36's pattern). Durable, shared by
  every API replica. `memory` stays the default for tests and demos.

**Reference alternatives** (not bundled; plug in as a `graph_store` or a `pipeline` plugin):

| Tool | What it adds | Consider when |
|---|---|---|
| Neo4j (with its vector index and GDS library) | A real graph database: Cypher queries, Leiden/Louvain communities, multi-hop traversals at scale | Large graphs, multi-hop questions, an existing Neo4j |
| Microsoft GraphRAG | The full pipeline: LLM extraction, hierarchical Leiden communities, community reports, map-reduce global search, DRIFT search | Corpus-wide "sensemaking" questions, budget for heavy indexing |
| LightRAG | Graph + vector dual-level retrieval with cheap incremental updates | Graph benefits with frequent document changes |

### 6. Routing by size and by data: `long-context`, `table`, multimodal

- **`long-context`**: search as usual to find the right documents, then decide per question. If the
  top `max_documents` documents fit the context budget **whole** (`budget_tokens`, by default the
  context builder's `max_tokens`), the model gets every chunk of them in document order; otherwise
  the usual best chunks. The trace says which route and how many tokens. Each document is fetched
  with a filtered search, so permissions and the request's filter apply.
- **`table`**: question about rows of a CSV table ("the per diem for an international trip"): the
  rows sharing the most words with the question (best matches only) become one cited passage with the
  header row. No model, so it works offline and can't write bad SQL; it can't add up or compare
  (use `sql`, Step 35's text-to-SQL, for totals, counts and comparisons). Tables carry access like
  documents.
- **Multimodal** (notes; nothing new to switch): the `docling` parser (reference, `pip install
  docling`) reads PDFs with layout, OCR, tables and figures; tables become table elements that
  `structure` keeps whole (split by rows with the header repeated), and figures can be captioned by a
  vision model during parsing so the caption is what gets indexed. Answering *about* images needs a
  vision-capable answer model behind the gateway; the retrieval side stays text.

### 7. Agents: `rag mcp`

```
agent (Claude Desktop, IDE) ──stdin/stdout, JSON-RPC 2.0──▶ rag mcp --subject ann --group all-staff
   initialize · tools/list ─▶ search, answer (read-only)
   tools/call search {"question": "...", "k": 5, "filter": {...}}
        └─▶ identity (fixed at launch) ─▶ SearchPipeline / AnswerPipeline ─▶ result + stderr log line
```

A minimal implementation of what a tool server needs (initialize, ping, tools/list, tools/call;
protocol versions 2025-06-18, 2025-03-26, 2024-11-05), with no new dependency. The official `mcp`
Python SDK is the reference for resources, prompts or the HTTP transport.

**Trust model:**

| Rule | Why |
|---|---|
| The identity is fixed when the server starts: `--subject` + `--group` + `--classification`, or `--token-file` with an OIDC access token **verified on every call** (issuer, audience, signature, expiry: `rag_common.auth`, as rag-api), groups from the token, classifications capped by the launcher | The model never chooses who it is; an expired token stops working at once |
| No identity, no server (exit 2) | No anonymous default to forget about |
| The tools take no identity arguments; unknown arguments are rejected | A prompt-injected agent can't ask "as the CFO" |
| Every search goes through the same access filter, guards and citation checks; a `filter` only narrows | Same rules as `/v1/search` and `/v1/answer` |
| One JSON line per call on stderr: tool, subject, documents, outcome; never the question or answer text | Accountability without collecting content |
| stdio = the user's own machine and the user's own permissions | For many users over a network, put MCP behind rag-api (tokens, OPA, the audit log), not this command |

## How to switch it on

```yaml
profiles:
  offline:
    # one word each (same answer steps, same guards):
    pipeline: vector                                  # or keyword
    pipeline: {use: rag-fusion, variants: 4}          # or multi-query; variant_source: heuristic offline
    pipeline: {use: hyde, keep_question: true}
    pipeline: {use: conversational}                   # with memory: {use: memory}
    pipeline: {use: long-context, max_documents: 3}   # budget_tokens: the context builder's by default
    pipeline: {use: flare, max_rounds: 2}
    pipeline: {use: speculative, drafts: 3, drafter_slot: llm, verifier_slot: judge_llm}

    # vectorless: contents pages (no embedder, no vector store needed)
    pipeline: {use: pageindex, navigator: llm, max_sections: 3}   # navigator: heuristic offline
    toc_store: memory

    # GraphRAG global search, with model-extracted relations, durable in Postgres
    pipeline: {use: graph-global, route: auto, max_communities: 4, summarizer: llm}
    graph_store: {use: postgres, dsn_env: null, credentials_file: /run/bao/rag_db.json, collection: default}
    enrichers: [context-header, {use: llm-entities, entity_types: [system, policy, team, error]}]

    # table lookup (sql for aggregates)
    pipeline: {use: table, tables: {expense_limits: {path: examples/tables/expense_limits.csv, groups: [all-staff]}}}
```

A fully vectorless profile (keyword index + contents, nothing embedded):

```yaml
  vectorless:
    extends: offline
    vector_store: none
    embedder: none
    retriever: keyword
    toc_store: memory
    pipeline: {use: pageindex, navigator: heuristic}
```

For one run, and the comparison:

```bash
RAG__PIPELINE__USE=rag-fusion uv run rag ask "How many days can I WFH?" --corpus examples/eval/handbook.yaml --group all-staff
uv run rag eval-answers examples/eval/handbook.yaml --profile offline     # every architecture, same questions
uv run rag eval-answers examples/eval/handbook.yaml --variant standard --variant pageindex --variant graph-global

# agents: Claude Desktop's claude_desktop_config.json (or any MCP client)
#   {"mcpServers": {"rag": {"command": "uv", "args": ["run", "--directory", "/path/to/RAG-Platform",
#     "rag", "mcp", "--profile", "local", "--subject", "ann", "--group", "all-staff",
#     "--classification", "public", "--classification", "internal"]}}}
uv run rag mcp --profile offline --subject ann --group all-staff --corpus examples/eval/handbook.yaml

# the filter fix: equality matches the text as typed and its number reading
uv run rag search "parental leave" --filter section_numbers=4.2 …
```

## When to use which

Measured on the handbook (`uv run rag eval-answers examples/eval/handbook.yaml --profile offline`,
25 questions, offline: hashing embedder, extractive answers, the model-based steps in their no-model
mode). The handbook is small and every document is short, so most architectures tie here; the rows
show the plumbing works and costs, not which is best on your corpus. Run it on your own questions.

| Architecture | ctx recall | answered | abstain ok | leaks | p50 ms | Reading |
|---|---:|---:|---:|---:|---:|---|
| naive | 0.854 | 0.833 | 1.000 | 0 | 5.6 | the baseline |
| standard | 1.000 | 0.917 | 1.000 | 0 | 11.4 | the default |
| vector | 1.000 | 0.917 | 1.000 | 0 | 8.6 | reranking is what `naive` lacked |
| keyword | 1.000 | 0.917 | 1.000 | 0 | 5.5 | no embeddings, same result on this corpus |
| pageindex (heuristic) | 0.938 | 0.875 | 1.000 | 0 | 4.3 | headings say what's under them; misses when they don't ("Flights" for "business class") |
| rag-fusion (heuristic) | 1.000 | 0.917 | 1.000 | 0 | 19.2 | twice the searches; a model writes better variants |
| conversational (heuristic) | 1.000 | 0.917 | 1.000 | 0 | 14.1 | the two follow-up questions still found |
| long-context | 1.000 | 0.917 | 1.000 | 0 | 13.5 | short documents fit whole |
| flare | 1.000 | 0.917 | 1.000 | 0 | 14.2 | extractive answers are always cited: no second round |
| speculative (offline) | 1.000 | 0.917 | 1.000 | 0 | 13.9 | the support score picks a draft |
| graph-global | 1.000 | 0.917 | 1.000 | 0 | 14.1 | specific questions route to local graph search |

| Situation | Choose |
|---|---|
| Measure what the extras are worth | `naive` vs `vector` vs `standard` |
| No embedding model allowed, or exact codes and names dominate | `keyword` |
| Long, well-structured documents (manuals, policies, filings, standards); explainable retrieval | `pageindex` (model walk in production) |
| Users word things very differently from the documents | `rag-fusion`, then `hyde`; measure the extra calls |
| Chat with follow-ups | `conversational` (+ `memory`) |
| A few short documents answer most questions; a model with a long context | `long-context` |
| Lookups in spreadsheets / CSV exports | `table`; totals and comparisons: `sql` |
| Answers that hedge or leave claims uncited | `flare` |
| Answers over many passages; a fast + a quality model | `speculative` |
| "What are the main themes / risks / rules across…?" | `graph-global` (+ `llm-entities`) |
| Questions about named things and their neighbours | `graph` (local) |
| Graph must survive restarts or be shared by replicas | `graph_store: postgres` |
| An agent should search the knowledge base | `rag mcp` (one user); behind rag-api for many |

## Trade-offs

- **`vector` / `keyword`** each miss what the other finds (Step 32): use them to measure, or when one
  kind of search is all you can run.
- **`pageindex`** depends on headings: flat text, scanned pages without structure, or headings that
  don't describe their content ("General", "Other") make it guess. The model walk costs two calls
  and their latency per question, and a large collection needs the heuristic pre-filter; the
  heuristic alone is term overlap and misses synonyms.
- **`rag-fusion`** multiplies searches by `variants + 1` and adds a model call; `hyde` adds a longer
  call (a passage) and can pull in what the model *imagines*; `conversational` adds a call per
  follow-up.
- **`flare`** and **`speculative`** add generations (flare only when the first answer is weak;
  speculative always writes `drafts` short answers plus one verification) and can't stream a draft.
  The offline weak-sentence check is lexical; a model-based judge is better at "unsupported".
- **`graph-global`** recomputes communities per person and graph version (cached), which is fine for
  thousands of entities and not for millions (use Neo4j GDS or Microsoft GraphRAG's precomputed
  reports there, with their own permission design). Label propagation is simple and deterministic;
  Leiden finds better, hierarchical communities. Summaries with a model cost a call per community.
- **`postgres` graph store** stores a copy of each chunk's text and access (so graph search works
  with any vector store); `rag reacl` and deletion update it like the other stores.
- **`long-context`** sends more tokens per question (cost, latency, "lost in the middle"); it routes
  back to chunks when the documents don't fit.
- **`table`** answers lookups only; ambiguous questions can match several rows (all best matches are
  shown).
- **`rag mcp`** is single-identity and local: one server per user. It is not a multi-user network
  service.

## Common mistakes

> **WATCH OUT**
> - **`pageindex` without `toc_store`.** It refuses to start. Adding a `toc_store` changes the
>   ingestion pipeline's hash, so the next ingestion run re-reads every source into it; until then
>   the contents are empty (the keyword fallback answers).
> - **Judging `pageindex` on documents without headings.** Plain text is one node per document. Use a
>   parser that keeps structure (Markdown, HTML, Word, Docling).
> - **`rag-fusion` with a model that refuses.** "I don't know" lines are dropped; if nothing is left it
>   falls back to the heuristic variants (the trace says `source: heuristic`). Check the trace.
> - **`conversational` without `memory`.** There is no history to rewrite: the trace shows
>   `memory: false`.
> - **Treating `hyde`'s passage as evidence.** It is only a search text; it is never shown or cited.
> - **`speculative` with the same model as drafter and verifier.** It still works, but the point is a
>   cheap drafter and a strong verifier: set `drafter_slot: llm` (fast) and `verifier_slot: judge_llm`.
> - **`graph-global` without entities.** It needs `graph_store` and an entity enricher
>   (`graph-entities` or `llm-entities`); with no communities it falls back to standard search.
> - **Expecting a global summary to cite documents.** A community summary is cited as
>   `graph://community/…`; its source chunks are in the context next to it and can be cited too.
> - **Giving `rag mcp` an identity from the model.** Put `--subject`/`--group` (or `--token-file`) in
>   the MCP client's launch configuration, never in a prompt; for shared use, go through rag-api.
> - **Printing to stdout in a plugin used by `rag mcp`.** stdout carries the protocol; log to stderr.

## What was added to the repo

| Where | What |
|---|---|
| `libs/rag-core/src/rag_core/components/presets.py` | `vector`, `keyword`, `rag-fusion` / `multi-query`, `hyde`, `conversational`, `long-context`, `table` pipelines |
| `components/pageindex.py` | `toc_store: memory`, contents trees from headings, the `pageindex` / `vectorless` pipeline |
| `components/active.py` | `flare` and `speculative` pipelines |
| `components/graphrag.py` | `llm-entities` enricher, label propagation and connected components, `graph-global` pipeline, `postgres` graph store |
| `components/architectures.py` | the memory graph store gains relations, types, access updates, per-person snapshots; local `graph` uses access-aware lookups |
| `search.py`, `answer.py`, `ingest.py`, `registry.py` | `search_with` (own texts / retriever, same reranker and checks); an architecture may write the answer (`draft`); ingestion without an embedder and into the `toc_store`; the `toc_store` slot |
| `infra/db/rag/migrations/20261016000000_graph_store.sql` | `rag.graph_chunks`, `rag.graph_mentions`, `rag.graph_relations` with row-level security |
| `libs/rag-core/src/rag_core/mcp.py`, `cli.py` | `rag mcp`: MCP over stdio, identities, tools; the `--filter key=value` fix |
| `rag.yaml`, `profiles/platform.yaml`, `examples/eval/handbook.yaml` | the options in comments; nine architectures in `rag eval-answers` |
| Tests | `test_architectures_ext.py` (incl. a live Postgres graph-store test), `test_mcp.py`, filter tests in `test_filters.py` |
| Docs | this page, ADR-0041, handbook sections 11, 18 and 20, glossary, catalogue |
