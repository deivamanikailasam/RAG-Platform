# ADR-0040: Chunk trees, extracted metadata, exact sections, a compression slot and more embedding options

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** deivamanikailasam

## Context
Step 31 cut every document one way and embedded each chunk once; Step 33 sent every retrieved chunk
to the model whole. Projects need answers at several levels of detail (a summary, a section, one
fact), exact references ("section 4.2"), metadata to filter on when sources provide none, shorter
contexts, and the settings real embedding models require (instruction prefixes, Matryoshka
dimensions, sparse and multi-vector representations, late chunking). Three risks shape the design:
LLM output stored in the index (summaries, propositions, metadata) can be wrong and then looks
authoritative; compression could hide text from the guards or break citations; and every embedding
option silently changes the embedding contract.

## Decision
We will:
1. Add tree-shaped chunking: a `hierarchical` chunker whose leaves carry their ancestors (id, kind,
   heading, child count and, under a size cap, text), an `auto-merge` post-processor that needs no
   extra lookup, RAPTOR's `summary-tree` and a document `summary` enricher, per document (so a
   document is still replaced as a unit, Step 31), and `summary-expand`.
2. Accept LLM output into the index only when it passes a deterministic check: summaries and
   propositions must be grounded in their source (content-word overlap), `llm-metadata` values must
   match a declared schema (types, allowed values, ISO dates; one retry for required fields),
   `llm-extract` sentences must occur in the chunk. Otherwise fall back to the offline method
   (extractive summary, rule-based propositions) or store nothing.
3. Record `heading`, `section_path` and `section_numbers` on structured chunks, and implement
   section lookup as an ordinary filtered search (Extension 01's filter language), so it works on
   every store and permissions always apply: a `section` retriever and a `section-expand`
   post-processor.
4. Add a `compressors` slot (a list) in the answer pipeline, after the OPA post-check and the context
   guards and before the context builder, rather than more post-processors: post-processors run
   inside search, whose results are cached and returned to API callers, while compression is
   answer-only, question-specific and must not hide text from the guards. Compressors keep chunk
   ids, documents and access; the trace records tokens before and after each.
5. Add embedding options as wrappers or new components: `instructed` (query/passage prefixes, tagged
   into the model name), `matryoshka` (and `request_dimensions` on the gateway embedder),
   `late-chunking` (ingestion calls `embed_chunks(document, chunks)` when an embedder has it), a
   `sparse_embedder` slot (`bm25`, `splade-tei`) used by the `sparse` and `qdrant-sparse` keyword
   indexes (so hybrid search fuses them unchanged), and `maxsim` / `colbert` rerankers. Heavy models
   (LLMLingua, PyLate ColBERT) are references, not locked dependencies.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| A separate document store for parent nodes | Small leaf metadata | One more store to run, back up, secure and keep in sync | Ancestors on each leaf (capped); filtered search for the rest |
| RAPTOR across the whole collection | The paper's design; cross-document themes | Every ingestion re-clusters everything; no clean per-document replace or erasure | Per document; revisit with a scheduled corpus-level job |
| Compression as post-processors | No new slot | Runs before OPA post-check and guards; pollutes the search cache and `/v1/search` | A `compressors` slot in the answer pipeline |
| Trusting LLM summaries/metadata as returned | Simplest | Refusals and inventions indexed as facts | Grounded / schema checks with offline fallbacks |
| A dedicated sparse slot in the retriever | Explicit | Duplicates hybrid's fusion and the keyword-index contract | Sparse indexes are keyword indexes |
| LlamaIndex / LangChain node parsers and compressors | Ready-made | Their abstractions and dependencies; no access model | Our contracts; their names and ideas credited in the docs |

## Consequences
+ Broad, narrow and exact-reference questions each have a technique; filters work on documents that
  arrived without metadata; contexts shrink with measured savings; new embedding models can be
  adopted with their correct settings.
+ Every new component has an offline implementation, so CI evaluates them (nine new variants).
- More ingestion work and storage (summaries, ancestors, propositions); more settings to evaluate.
- Grounded checks are lexical: they reject obvious strangers, not subtle paraphrase errors.
- Each embedding option is a new embedding contract (re-index into a new collection).

## Revisit when
A corpus-level summary job is needed (cross-document themes); a store offers native multi-vector or
hierarchical retrieval we can push down; or a learned compressor proves better than extractive plus
LLM extraction on our answer evaluation.
