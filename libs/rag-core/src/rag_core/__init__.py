"""rag-core (Step 30): the reusable RAG core every project builds on.

types        the shared vocabulary: Source, Document, Element, Chunk, Query, Principal, Answer, ...
contracts    one small Protocol per kind of component (parser, chunker, embedder, vector store, ...)
registry     names -> factories, with validated parameters; the Container builds a profile
config       rag.yaml profiles with `extends`, "none" to switch a slot off, RAG__SLOT__PARAM overrides
components   the built-in implementations (Step 30: token counters, LLMs, embedders, in-memory stores)
testing      the conformance kit every implementation of a contract must pass
cli          the `rag` command: components, config check | validate | show
"""
