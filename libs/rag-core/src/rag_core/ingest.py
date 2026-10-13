"""The ingestion pipeline (Step 31): source → parse → clean → redact → chunk → enrich → embed →
index, with unchanged sources skipped, replaced sources cleaned up, and every step traced.

    pipeline = IngestionPipeline(config.load("rag.yaml", "local"))
    result = pipeline.ingest(load_source("s3://rag-originals/policies/leave.pdf", access=…))
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from opentelemetry import trace

from rag_core.components.cleaning import redact_document
from rag_core.components.parsing import ParseError, ParserRouter
from rag_core.components.queues import Job, ManifestEntry
from rag_core.registry import Container
from rag_core.types import Access, Chunk, Source

tracer = trace.get_tracer("rag_core.ingest")


@dataclass(frozen=True)
class IngestResult:
    uri: str
    status: Literal["indexed", "unchanged", "deleted", "failed", "skipped"]
    chunks: int = 0
    detail: str = ""
    pii: tuple[str, ...] = ()
    seconds: float = 0.0
    chunk_ids: tuple[str, ...] = field(default=(), repr=False)


def load_source(uri: str, access: Access | None = None, metadata: dict[str, Any] | None = None,
                s3_client: Any = None) -> Source:  # fmt: skip
    """file:///path or s3://bucket/key (Step 14's object store holds every original)."""
    if uri.startswith("file://"):
        data = Path(uri[len("file://") :]).read_bytes()
    elif uri.startswith("s3://"):
        bucket, _, key = uri[len("s3://") :].partition("/")
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        data = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    else:
        raise ValueError(f"unsupported source {uri!r}: use file:// or s3://")
    return Source(uri=uri, data=data, access=access or Access(), metadata=metadata or {})


def pipeline_hash(config: dict[str, Any]) -> str:
    """Changes when anything that shapes the index changes: then every source is re-ingested."""
    relevant = {
        k: config.get(k)
        for k in (
            "parsers",
            "normalizers",
            "pii",
            "chunker",
            "enrichers",
            "embedder",
            "token_counter",
        )
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()[
        :16
    ]


class IngestionPipeline:
    def __init__(
        self, container: Container, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        self.c = container
        self.router = ParserRouter(container.get("parsers"))
        self.normalizers = container.get("normalizers") if container.has("normalizers") else []
        self.pii = container.get("pii") if container.has("pii") else None
        self.chunker = container.get("chunker")
        self.enrichers = container.get("enrichers") if container.has("enrichers") else []
        self.embedder = container.get("embedder")
        self.vectors = container.get("vector_store") if container.has("vector_store") else None
        self.keywords = container.get("keyword_index") if container.has("keyword_index") else None
        self.manifest = container.get("manifest") if container.has("manifest") else None
        if self.vectors is None and self.keywords is None:
            raise ValueError("ingestion needs a vector_store and/or a keyword_index")
        self.hash = pipeline_hash(dict(container.config))
        # lineage / audit hook: Step 25's OpenLineage emitter or Step 23's audit log plug in here
        self.on_event = on_event or (lambda e: None)
        # Step 33: any change to the index starts a new cache epoch, so no cached answer outlives
        # the documents it was based on (a Valkey cache does this for every replica at once)
        self.cache = container.get("cache") if container.has("cache") else None
        # Step 35: GraphRAG's entity store is one more place a document lives
        self.graph = container.get("graph_store") if container.has("graph_store") else None

    def ingest(self, source: Source, force: bool = False) -> IngestResult:
        start = time.monotonic()
        with tracer.start_as_current_span(
            "rag.ingest", attributes={"rag.source": source.uri}
        ) as span:
            previous = self.manifest.get(source.uri) if self.manifest else None
            if (not force and previous and previous.status == "indexed"
                    and previous.content_sha256 == source.sha256 and previous.pipeline_hash == self.hash):  # fmt: skip
                span.set_attribute("rag.ingest.status", "unchanged")
                return IngestResult(
                    source.uri, "unchanged", previous.chunk_count, seconds=time.monotonic() - start
                )
            try:
                with tracer.start_as_current_span("rag.ingest.parse"):
                    doc = self.router.parse(source)
                for n in self.normalizers:
                    doc = n.normalize(doc)
                found: list[str] = []
                if self.pii is not None:
                    with tracer.start_as_current_span("rag.ingest.pii"):
                        doc, found = redact_document(doc, self.pii)
                with tracer.start_as_current_span("rag.ingest.chunk"):
                    chunks: list[Chunk] = self.chunker.chunk(doc)
                if not chunks:
                    return self._done(
                        source,
                        IngestResult(source.uri, "skipped", 0, "no text after cleaning"),
                        start,
                    )
                if self.graph is not None:  # before enrichers re-add this source's entities
                    self.graph.delete_document(source.uri)
                for e in self.enrichers:
                    with tracer.start_as_current_span(f"rag.ingest.enrich.{type(e).__name__}"):
                        chunks = e.enrich(doc, chunks)
                chunks = [replace(c, metadata={**c.metadata, "pii_redacted": sorted(set(found))}) if found else c
                            for c in chunks]  # fmt: skip
                with tracer.start_as_current_span(
                    "rag.ingest.embed", attributes={"rag.chunks": len(chunks)}
                ):
                    vectors = (
                        self.embedder.embed_documents([c.indexed_text for c in chunks])
                        if self.vectors
                        else None
                    )
                with tracer.start_as_current_span("rag.ingest.index"):
                    # replace, don't append: chunks of the old version that no longer exist must go
                    self._delete_everywhere(source.uri)
                    if self.vectors is not None and vectors is not None:
                        self.vectors.upsert(chunks, vectors)
                    if self.keywords is not None:
                        self.keywords.index(chunks)
            except ParseError as e:
                return self._done(source, IngestResult(source.uri, "failed", 0, str(e)), start)
            span.set_attribute("rag.ingest.chunks", len(chunks))
            result = IngestResult(source.uri, "indexed", len(chunks), pii=tuple(sorted(set(found))),
                                chunk_ids=tuple(c.id for c in chunks))  # fmt: skip
            return self._done(source, result, start)

    def _delete_everywhere(self, uri: str) -> int:
        n = 0
        if self.vectors is not None:
            n = self.vectors.delete_document(uri)
        if self.keywords is not None:
            n = max(n, self.keywords.delete_document(uri))
        return n

    def _forget_graph(self, uri: str) -> None:
        """The graph store (Step 35) keeps chunks too: a deleted document leaves it as well."""
        if self.graph is not None:
            self.graph.delete_document(uri)

    def delete(self, uri: str) -> IngestResult:
        """A source was deleted or must be forgotten: remove it from every store (Step 36: erasure)."""
        start = time.monotonic()
        n = self._delete_everywhere(uri)
        self._forget_graph(uri)
        if self.manifest:
            self.manifest.delete(uri)
        result = IngestResult(uri, "deleted", n, seconds=time.monotonic() - start)
        if self.cache is not None:
            self.cache.invalidate()
        self.on_event({"event": "rag.ingest", "uri": uri, "status": "deleted", "chunks": n})
        return result

    def _done(self, source: Source, result: IngestResult, start: float) -> IngestResult:
        result = replace(result, seconds=round(time.monotonic() - start, 3))
        if self.cache is not None and result.status == "indexed":
            self.cache.invalidate()
        if self.manifest is not None and result.status in ("indexed", "failed", "skipped"):
            self.manifest.put(
                ManifestEntry(
                    source.uri,
                    source.sha256,
                    self.hash,
                    result.chunks,
                    result.status,
                    result.detail,
                )
            )
        self.on_event({"event": "rag.ingest", "uri": source.uri, "status": result.status, "chunks": result.chunks,
                        "sha256": source.sha256, "pipeline": self.hash, "pii": list(result.pii), "detail": result.detail})  # fmt: skip
        return result


class Worker:
    """Takes jobs from the queue until it's empty (or forever with run(forever=True))."""

    def __init__(
        self, pipeline: IngestionPipeline, queue: Any, loader: Callable[[Job], Source] | None = None
    ) -> None:
        self.pipeline, self.queue = pipeline, queue
        self.loader = loader or (
            lambda j: load_source(j.uri, Access(**j.access) if j.access else None, j.metadata)
        )

    def run(self, forever: bool = False, block_ms: int = 1000) -> list[IngestResult]:
        results: list[IngestResult] = []
        while True:
            job = self.queue.get(block_ms)
            if job is None:
                if forever:
                    continue
                return results
            try:
                if job.op == "delete":
                    results.append(self.pipeline.delete(job.uri))
                else:
                    r = self.pipeline.ingest(self.loader(job))
                    results.append(r)
                    if (
                        r.status == "failed"
                    ):  # a parse failure won't fix itself: park it, don't retry
                        self.queue.fail(Job(**{**job.__dict__, "attempts": 10**6}), r.detail)
                        continue
                self.queue.ack(job)
            except Exception as e:  # anything else (store down, timeout) is retried
                self.queue.fail(job, f"{type(e).__name__}: {e}")
