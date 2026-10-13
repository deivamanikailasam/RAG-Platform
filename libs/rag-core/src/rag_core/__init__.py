"""rag-core (Step 30): the reusable RAG core every project builds on.

types        the shared vocabulary: Source, Document, Element, Chunk, Query, Principal, Answer, ...
contracts    one small Protocol per kind of component (parser, chunker, embedder, vector store, ...)
registry     names -> factories, with validated parameters; the Container builds a profile
config       rag.yaml profiles with `extends`, "none" to switch a slot off, RAG__SLOT__PARAM overrides
components   the built-in implementations (Step 30: token counters, LLMs, embedders, in-memory stores)
testing      the conformance kit every implementation of a contract must pass
ingest       the ingestion pipeline and worker (Step 31)
search       the search pipeline: transform, retrieve, fuse, rerank, post-process (Step 32)
evaluate     recall@k, MRR, nDCG@k and leaks per search variant on a labelled dataset (Step 32)
cli          the `rag` command: components, config, ingest, search, eval-search, doctor
sdk          RagApp: ingest, search, answer, stream, check in a few lines (Step 38)
doctor       `rag doctor`: does a project meet the platform's standards? (Step 38)
profiles     the platform's tested rag.yaml profiles, for `include:` (Step 38)
"""

# The names a project's own components need (Step 38): `from rag_core import Container, register`.
# Part of the public API (semantic versioning, docs/standards/rag-standards.md).
from rag_core.registry import ComponentError, Container, register

__version__ = "1.0.0"
__all__ = ["ComponentError", "Container", "__version__", "register"]
