# Coverage matrix: do we have it?

> **IN PLAIN ENGLISH**
> One row per RAG concept, technique or tool, answering one question: **is it in this platform?**
> ✅ **In repo** means a component you switch on in `rag.yaml` (with tests; the catalogue says whether
> they run against the real service, a stand-in, or offline). 📘 **Reference** means the code and its
> settings are here and validated, but it needs an extra installed or a service you implement, so CI
> doesn't run it end to end. ❌ **Not included** means it isn't here, with the reason and how to plug it
> in. For *when* to use each, see the [decision guide](decision-guide.md).

How the answers are kept honest: every component named here exists in the generated
[catalogue](../catalogue.md), and `just doc-coverage` (in CI) fails when a registered component is not
explained in the [decision guide](decision-guide.md) and in a step or extension write-up, or when a
link in the docs is broken.

Abbreviations: **E01–E04** = extensions [01](../extensions/01-retrieval-math-filters-fusion.md),
[02](../extensions/02-chunking-indexing-compression.md), [03](../extensions/03-more-rag-architectures.md),
[04](../extensions/04-evaluation-loops-and-remaining-techniques.md); **DG** = the
[decision guide](decision-guide.md); **HB** = the [RAG handbook](rag-handbook.md).

## The owner's checklist

| # | Item | Status | Component / how to switch it on | Read |
|---:|---|---|---|---|
| 1 | Hybrid search | ✅ In repo | `retriever: {use: hybrid}` (default): dense + keyword in parallel, fused | [DG](decision-guide.md#hybrid-search), [Step 32](../steps/step-32-retrieval-and-ranking.md) |
| 2 | Hierarchical chunking | ✅ In repo | `chunker: hierarchical` + `auto-merge` / `section-expand`; also `parent-child` | [DG](decision-guide.md#chunking), [E02 §1](../extensions/02-chunking-indexing-compression.md#1-chunk-trees-hierarchical-auto-merge-raptor-document-summaries) |
| 3 | Metadata filtering | ✅ In repo | `--filter`, `"filter"` in the API, `filters=` in the SDK; pushed into every store, ANDed with permissions | [DG](decision-guide.md#metadata-filtering-and-self-query), [E01 §2](../extensions/01-retrieval-math-filters-fusion.md#2-metadata-filters) |
| 4 | Reranking | ✅ In repo | `reranker: gateway` (cross-encoder), `tei`, `llm` (listwise), `maxsim`; 📘 `cross-encoder`, `colbert` | [DG](decision-guide.md#reranking), [Step 32](../steps/step-32-retrieval-and-ranking.md) |
| 5 | Evaluation loops | ✅ In repo | `rag eval-search / eval-answers / eval-guards / eval-compare / eval-sweep / eval-generate / eval-review / eval-candidates / eval-export`, `rag online-eval`; CI gates | [DG](decision-guide.md#evaluation), [E04](../extensions/04-evaluation-loops-and-remaining-techniques.md) |
| 6 | Context compression | ✅ In repo | `compressors: [extractive \| embedding-filter \| llm-extract \| summarize]`; 📘 `llmlingua` | [DG](decision-guide.md#context-compression), [E02 §5](../extensions/02-chunking-indexing-compression.md#5-context-compression) |
| 7 | Query transformation | ✅ In repo | `query_transformer:` `rewrite`, `multi-query`, `hyde`, `step-back`, `decompose`, `expand-terms`, `normalize`, `translate`, `self-query`, `with-history`, `chain` | [DG](decision-guide.md#query-transformation) |
| 8 | Embedding | ✅ In repo | `embedder: gateway` (any model), wrappers `cached`, `batched`, `instructed`, `matryoshka`; `late-chunking`; `hashing` offline | [DG](decision-guide.md#embeddings) |
| 9 | Top-k retrieval | ✅ In repo | `candidates`, `top_n`, `search_k` | [DG](decision-guide.md#retrieval-and-top-k) |
| 10 | Graph RAG | ✅ In repo | `pipeline: graph` (local) / `graph-global` (communities); `graph_store: memory \| postgres`; `graph-entities` / `llm-entities` | [DG](decision-guide.md#rag-architectures), [E03 §5](../extensions/03-more-rag-architectures.md#5-graphrag-llm-entities-graph-global-the-postgres-graph-store) |
| 11 | Multi-query RAG | ✅ In repo | `pipeline: rag-fusion` (= `multi-query`); transformer `multi-query` | [DG](decision-guide.md#rag-architectures) |
| 12 | Agentic RAG | ✅ In repo | `pipeline: agentic` (multi-hop planner); `rag mcp` for external agents | [DG](decision-guide.md#agents-and-mcp) |
| 13 | Vector RAG | ✅ In repo | `pipeline: vector` (dense only, reranked); `naive` as a baseline | [DG](decision-guide.md#rag-architectures) |
| 14 | Vectorless RAG | ✅ In repo | `pipeline: keyword` (BM25 only) and `pageindex` (= `vectorless`, contents-page navigation) | [E03 §2](../extensions/03-more-rag-architectures.md#2-vectorless-rag-by-contents-pages-pageindex) |
| 15 | Fusion | ✅ In repo | `fusion: rrf \| relative-score \| weighted \| dbsf \| combsum \| combmnz \| borda` | [DG](decision-guide.md#fusion) |
| 16 | Parallel retrieval | ✅ In repo | `parallel: true` on retrievers; `ensemble`; `rag-fusion` searches in parallel | [DG](decision-guide.md#parallel-ensemble-and-routed-retrieval) |
| 17 | Precise section retrieval | ✅ In repo | `retriever: section`, `section-expand`, filters on `section_numbers` / `section_path` | [E02 §4](../extensions/02-chunking-indexing-compression.md#4-exact-sections) |
| 18 | Indexing | ✅ In repo | `rag ingest`, `rag enqueue` + `rag worker`, `rag sync`; manifest; HNSW / IVF / flat; `rag reindex` | [Step 31](../steps/step-31-ingestion-pipeline.md), [DG](decision-guide.md#vector-indexes) |
| 19 | Parsing | ✅ In repo | `markdown`, `html`, `pdf`, `docx`, `csv`, `text`; `tika` (mocked); 📘 `docling` | [DG](decision-guide.md#parsing) |
| 20 | Citations | ✅ In repo | Checked `[n]` markers, `uncited: abstain`; `answer_formatters: [citations]` (footnotes, quotes with offsets) | [DG](decision-guide.md#citations-and-answer-formats) |
| 21 | Reciprocal rank fusion | ✅ In repo | `fusion: {use: rrf, k: 60}` (default) | [DG](decision-guide.md#fusion) |
| 22 | Relative (score) fusion | ✅ In repo | `fusion: {use: relative-score, alpha: 0.7}` (also `weighted`, `dbsf`) | [E01 §3](../extensions/01-retrieval-math-filters-fusion.md#3-fusion-the-result-cache-and-the-ensemble) |
| 23 | Cosine similarity | ✅ In repo | `metric: cosine` (default) on every vector store | [DG](decision-guide.md#similarity-metrics) |
| 24 | Dot product | ✅ In repo | `metric: dot` | [DG](decision-guide.md#similarity-metrics) |
| 25 | Euclidean distance | ✅ In repo | `metric: l2` (and Manhattan `l1`) | [DG](decision-guide.md#similarity-metrics) |
| 26 | Different embedding models | ✅ In repo | Any model as a gateway alias (local TEI or OpenAI, Cohere, Voyage, Jina, Mistral, Gemini, Bedrock); `instructed` presets; new collection + `rag reindex` | [E02 §7](../extensions/02-chunking-indexing-compression.md#7-choosing-an-embedding-model-and-switching-it-through-the-gateway) |
| 27 | Caching | ✅ In repo | `cached` embedder (Valkey), `search_cache`, answer `cache: memory \| valkey` | [DG](decision-guide.md#caching) |
| 28 | Semantic caching | ✅ In repo | `cache: {use: semantic, threshold: 0.95}`, per access set, never for follow-ups | [DG](decision-guide.md#caching) |

## Every other technique in the decision guide

### Sources, parsing, cleaning

| Item | Status | Component / how | Notes |
|---|---|---|---|
| Folder sync | ✅ In repo | `connector: filesystem` + `rag sync [--watch]` | Never deletes after a failed listing |
| Bucket sync | ✅ In repo | `connector: s3` | ETag versions |
| Web crawler, Confluence, SharePoint, Google Drive | 📘 Reference | `web`, `confluence`, `sharepoint`, `google-drive`: settings validated; implement `list()`/`fetch()` with permission mapping | [E04 §12](../extensions/04-evaluation-loops-and-remaining-techniques.md#12-connectors-and-rag-sync) |
| Event-driven ingestion | ✅ In repo | `rag enqueue` from bucket events; `valkey-streams` queue | [Step 31](../steps/step-31-ingestion-pipeline.md) |
| Incremental ingestion (skip unchanged) | ✅ In repo | `manifest: postgres` | |
| OCR and layout parsing | 📘 Reference | `docling` | `pip install docling` |
| Cloud document AI (Textract, Document Intelligence, Document AI), Unstructured, LlamaParse | ❌ Not included | Write a `parser` plugin or pre-convert to Markdown | Keeps the parser layer dependency-light (ADR-0031) |
| Text normalisation, boilerplate removal | ✅ In repo | `unicode`, `boilerplate` | |
| PII redaction (rules) | ✅ In repo | `pii: regex` (mask, pseudonymise, remove) | Checksum-validated |
| PII redaction (names, NER) | 📘 Reference | `pii: presidio` | extra `presidio` |
| Exact token counting | 📘 Reference | `token_counter: hf-tokenizer` | `approx` is the default |

### Chunking, metadata, enrichment

| Item | Status | Component / how | Notes |
|---|---|---|---|
| Fixed, recursive chunking | ✅ In repo | `fixed`, `recursive` | |
| Structure-aware chunking | ✅ In repo | `structure` (default) | |
| Sentence-window | ✅ In repo | `sentence-window` + `window-expand` | |
| Semantic chunking | ✅ In repo | `semantic` | |
| Parent-child (small-to-big) | ✅ In repo | `parent-child` + `parent-expand` | |
| Auto-merging retrieval | ✅ In repo | `auto-merge` with `hierarchical` | |
| RAPTOR | ✅ In repo | `summary-tree` + `summary-expand` | |
| Document summary index | ✅ In repo | `summary` | |
| Proposition chunking | ✅ In repo | `proposition` | |
| Late chunking | ✅ In repo | `late-chunking` (offline hashing; TEI token embeddings as reference) | |
| Code chunking | ✅ In repo | `code` | Pattern-based, not a full parser |
| Agentic / LLM chunking | ❌ Not included | A `chunker` plugin | Not shown to beat `structure`; costly and non-deterministic |
| Metadata extraction (rules) | ✅ In repo | `metadata` | |
| Metadata extraction (LLM, schema-checked) | ✅ In repo | `llm-metadata` | |
| Contextual headers | ✅ In repo | `context-header` | |
| Contextual retrieval (LLM context per chunk) | ✅ In repo | `llm-context` | |
| Hypothetical questions per chunk | ✅ In repo | `questions` | |
| Entity extraction for graphs | ✅ In repo | `graph-entities` (rules), `llm-entities` (model, relations) | |

### Embeddings, metrics, indexes, stores

| Item | Status | Component / how | Notes |
|---|---|---|---|
| Instruction prefixes | ✅ In repo | `instructed` (presets e5, bge, nomic, qwen3, gte, mxbai, snowflake) | |
| Matryoshka dimensions | ✅ In repo | `matryoshka`, `request_dimensions` | |
| Quantization | ✅ In repo | pgvector `halfvec` / `binary`; Qdrant `scalar` / `binary` with rescoring | |
| Embedding cache, batching, rate limits | ✅ In repo | `cached` (`store: valkey`), `batched` | |
| Sparse vectors (BM25, SPLADE) | ✅ In repo | `sparse_embedder: bm25 \| splade-tei`, `keyword_index: sparse \| qdrant-sparse` | `splade-tei` tested with a stand-in |
| Multi-vector / ColBERT | ✅ In repo / 📘 | `maxsim` (offline) / `colbert` (reference) as rerankers | Not as a first-stage index |
| Manhattan distance | ✅ In repo | `metric: l1` | OpenSearch: flat only |
| Flat, HNSW, IVF indexes | ✅ In repo | `index_type: flat \| hnsw \| ivfflat` + knobs | |
| DiskANN, IVF-PQ, ScaNN | ❌ Not included | pgvectorscale, Milvus, Vertex AI Vector Search as plugins | Needed only at hundreds of millions of vectors |
| pgvector, Qdrant, OpenSearch k-NN | ✅ In repo | `pgvector`, `qdrant`, `opensearch-knn` (+ `memory`) | Same conformance and leak tests |
| Weaviate, Milvus/Zilliz, Pinecone, Chroma, LanceDB, Elasticsearch, Vespa, Redis, MongoDB Atlas, Azure AI Search, Vertex AI Vector Search, Bedrock Knowledge Bases, Turbopuffer | ❌ Not included | A `vector_store` plugin passing `rag_core.testing.conformance` | Postgres + derived indexes cover the platform's needs ([DG](decision-guide.md#vector-databases)) |
| Embedding fine-tuning | ❌ Not included | sentence-transformers training offline, then a new gateway alias + `rag reindex` | Worth it only after hybrid and reranking are tuned |
| Image / multimodal embeddings (CLIP, ColPali) | ❌ Not included | A new embedder + store collection | Retrieval stays text; figures can be captioned at parsing ([E03 §6](../extensions/03-more-rag-architectures.md#6-routing-by-size-and-by-data-long-context-table-multimodal)) |

### Search and ranking

| Item | Status | Component / how | Notes |
|---|---|---|---|
| BM25 keyword search | ✅ In repo | `postgres-fts`, `opensearch`, `memory-bm25` | |
| Engine-native hybrid query | ❌ Not included | OpenSearch hybrid query / Qdrant Query API as a retriever plugin | Fusion stays in rag-core to keep engines switchable ([ADR-0032](../adr/0032-search-through-a-switchable-hybrid-pipeline.md)) |
| Self-query (filters from the question) | ✅ In repo | `self-query` (rules or LLM) | |
| HyDE | ✅ In repo | transformer `hyde`, `pipeline: hyde` | |
| Step-back prompting | ✅ In repo | `step-back` | |
| Query decomposition | ✅ In repo | `decompose`; `adaptive` splits compound questions | |
| Query expansion (synonyms, acronyms) | ✅ In repo | `expand-terms` | |
| Spelling / normalisation | ✅ In repo | `normalize` | |
| Query translation | ✅ In repo | `translate` | |
| Query routing | ✅ In repo | `router` retriever; `adaptive` pipeline | |
| Ensemble retrieval | ✅ In repo | `ensemble` | |
| DBSF, CombSUM, CombMNZ, Borda, weighted | ✅ In repo | `dbsf`, `combsum`, `combmnz`, `borda`, `weighted` | |
| Cross-encoder reranking | ✅ In repo | `gateway`, `tei`; 📘 `cross-encoder` | |
| LLM listwise reranking | ✅ In repo | `reranker: llm` | |
| API rerankers (Cohere, Voyage, Jina) | ✅ In repo (via gateway) | A gateway alias used by `reranker: gateway` | No separate component needed |
| MMR diversity | ✅ In repo | `mmr` | |
| Deduplication | ✅ In repo | `dedupe` | |
| Recency boosting | ✅ In repo | `recency` (`when: asked`) | |
| Score thresholds | ✅ In repo | `min-score` | |
| Per-document caps | ✅ In repo | `max-per-document` | |

### Context, generation, answers

| Item | Status | Component / how | Notes |
|---|---|---|---|
| Context packing with budgets | ✅ In repo | `context_builder: numbered` | |
| Lost-in-the-middle ordering | ✅ In repo | `order: lost-in-middle` | |
| Prompt registry and versions | ✅ In repo | `just prompts …` | [Step 24](../steps/step-24-prompt-registry.md) |
| Extractive (no-model) answers | ✅ In repo | `generator: extractive` | |
| JSON / structured answers | ✅ In repo | `answer_formatters: [json]` | |
| Confidence scores | ✅ In repo | `confidence` | |
| Follow-up suggestions | ✅ In repo | `follow-ups` | |
| Abstention | ✅ In repo | `abstain_without_hits`, `uncited: abstain`, `min-score` | |
| Streaming (live and checked) | ✅ In repo | `pipeline.stream: live \| checked` | |
| Conversation memory | ✅ In repo | `memory: memory \| valkey` | |
| Long-term user memory | ❌ Not included | A separate, consented store | Out of scope for privacy |
| Provider prompt / KV caching | 📘 Reference (notes) | Model-server feature; keep prompt prefixes stable | [E04 §11](../extensions/04-evaluation-loops-and-remaining-techniques.md#11-prompt-caching-and-kv-caching-notes-for-providers) |
| Prompt optimisation (DSPy) | ❌ Not included | Optimise offline; register the result as a prompt version | |

### Architectures

| Item | Status | Component | Notes |
|---|---|---|---|
| Naive RAG | ✅ In repo | `naive` | Baseline |
| Standard / advanced RAG | ✅ In repo | `standard` | Default |
| Conversational RAG | ✅ In repo | `conversational` | |
| RAG-Fusion | ✅ In repo | `rag-fusion` | |
| Corrective RAG (CRAG) | ✅ In repo | `corrective` | No web-search fallback, on purpose |
| Self-RAG (self-reflective) | ✅ In repo | `self-reflective` | |
| Adaptive RAG | ✅ In repo | `adaptive` | |
| FLARE (active retrieval) | ✅ In repo | `flare` | |
| Speculative RAG | ✅ In repo | `speculative` | |
| PageIndex (contents navigation) | ✅ In repo | `pageindex` + `toc_store: memory` | |
| SQL / structured RAG | ✅ In repo | `sql` | Read-only, permitted tables only |
| Table QA | ✅ In repo | `table` | |
| Long-context RAG | ✅ In repo | `long-context` | |
| Graph database (Neo4j), Microsoft GraphRAG, LightRAG | ❌ Not included | `graph_store` or `pipeline` plugin | `graph_store: postgres` covers durability and RLS |
| Web search fallback | ❌ Not included | A retriever plugin calling a search API | Answers stay inside your documents by design |
| MCP tools for agents | ✅ In repo | `rag mcp` | Identity fixed at launch |

### Guardrails

| Item | Status | Component / how | Notes |
|---|---|---|---|
| Input: size, injection, PII, topics | ✅ In repo | `size`, `injection`, `pii`, `topics` | |
| Context: indirect injection | ✅ In repo | `context-injection` | |
| Output: groundedness, PII, secrets, toxicity | ✅ In repo | `groundedness`, `pii`, `secrets`, `toxicity` | |
| Model-based safety classifier | ✅ In repo | `llm-judge` (Llama Guard style; point `judge_llm` at Llama Guard) | |
| External guard services | ✅ In repo (interface) | `webhook` | |
| NeMo Guardrails, Guardrails AI, Lakera, Azure AI Content Safety, Bedrock Guardrails | ❌ Not included | A small adapter to the `webhook` contract | Vendor choice stays outside rag-core |

### Evaluation and operations

| Item | Status | Component / how | Notes |
|---|---|---|---|
| Retrieval metrics (recall, MRR, nDCG, hit rate, precision, MAP, leaks) | ✅ In repo | `rag eval-search` | |
| Answer metrics (faithfulness, relevance, context precision, correctness, citation P/R) | ✅ In repo | `rag eval-answers` | |
| LLM-as-judge | ✅ In repo | `judge: llm` (and `lexical`) | |
| Synthetic test generation with review | ✅ In repo | `rag eval-generate`, `rag eval-review` | |
| A/B with significance | ✅ In repo | `rag eval-compare`; `rag online-eval` per release | |
| Sweeps / ablations | ✅ In repo | `rag eval-sweep` | |
| Ragas, DeepEval, promptfoo, TruLens, Phoenix | ✅ In repo (export) | `rag eval-export --to …` | |
| LangSmith | ❌ Not included | Upload the exported JSONL as a dataset | Langfuse fills that role here |
| Traces, metrics, logs, LLM traces | ✅ In repo | OpenTelemetry, Prometheus/Grafana, Loki/Tempo, Langfuse | Steps 19–22 |
| Audit log, retention, erasure | ✅ In repo | Steps 23 and 36 | |
| Canaries, gates, HA/DR | ✅ In repo | Step 37 | |
| Frameworks (LlamaIndex, LangChain/LangGraph, Haystack, DSPy, Semantic Kernel) | ❌ Not included (by design) | Call rag-api / `rag mcp`, or wrap as plugins | [DG](decision-guide.md#frameworks) |
| Local and API LLMs | ✅ In repo | Gateway aliases; `llm`, `answer_llm`, `judge_llm` slots; `scripted` offline | [DG](decision-guide.md#model-choices) |

## What is genuinely missing

The ❌ rows above, grouped by why:

- **Deliberately out of scope** (the platform's rules): web-search fallback (answers stay inside your
  documents), long-term user memory (privacy), vendor guard services and vector databases as built-ins
  (each is a plugin, so the core stays vendor-neutral), framework dependencies.
- **Worth adding when a project needs it:** a vector-database adapter beyond the three in-repo engines
  (each is a `vector_store` plugin plus a conformance run), engine-native hybrid queries, image /
  multimodal retrieval, embedding fine-tuning, a Neo4j graph store, a LangSmith exporter, real
  implementations of the four reference connectors with permission mapping.
