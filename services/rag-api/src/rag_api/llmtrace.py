"""LLM-level tracing to Langfuse: what was asked and what was retrieved, for debugging and evaluation.

Three rules make this safe:
  1. Langfuse gets its OWN tracer provider, so content never flows into the normal telemetry
     pipeline (Collector -> Tempo), which has wider access and no content rules.
  2. Everything is masked in-process before it leaves (tokens, keys, emails).
  3. Content of confidential/restricted documents is never copied into Langfuse: people who can
     read traces must not gain a side door around the access policy (Step 18).
The Langfuse trace reuses the request's OpenTelemetry trace id, so Tempo and Langfuse line up.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from langfuse import Langfuse, propagate_attributes
from langfuse.types import TraceContext
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter

from rag_api.search import Candidate
from rag_common.auth import Principal

SECRET_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWTs
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # API keys
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email addresses
]
SENSITIVE = {"confidential", "restricted"}  # titles/content of these never go to Langfuse


def mask(*, data: Any, **_: Any) -> Any:
    """Langfuse's masking hook: runs in our process on every input, output and metadata value."""
    if isinstance(data, str):
        for pattern in SECRET_PATTERNS:
            data = pattern.sub("****", data)
        return data
    if isinstance(data, dict):
        return {k: mask(data=v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask(data=v) for v in data]
    return data


class SearchTrace:
    """Handle for one search's Langfuse trace (or a no-op when Langfuse is off)."""

    def __init__(self, client: Langfuse | None) -> None:
        self._client = client

    def retrieved(self, candidates: Sequence[Candidate], allowed: set[int]) -> None:
        if self._client is None:
            return
        docs = [
            {
                "id": c.ref.id,
                "classification": c.ref.classification,
                "score": c.hit.score,
                # Titles of sensitive documents are withheld: trace readers may lack clearance.
                "title": f"[withheld: {c.ref.classification}]"
                if c.ref.classification in SENSITIVE
                else c.hit.title,
                "returned": c.ref.id in allowed,
            }
            for c in candidates
        ]
        with self._client.start_as_current_observation(name="retrieve", as_type="retriever") as obs:
            obs.update(
                output=docs,
                metadata={
                    "candidates": len(candidates),
                    "returned": sum(d["returned"] for d in docs),
                    "dropped_by_policy": sum(not d["returned"] for d in docs),
                },
            )


class LlmTracer:
    def __init__(self, client: Langfuse | None, *, capture_question: bool = True) -> None:
        self._client = client
        self._capture_question = capture_question

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def search(self, p: Principal, question: str, k: int) -> Iterator[SearchTrace]:
        if self._client is None:
            yield SearchTrace(None)
            return
        ctx = trace.get_current_span().get_span_context()  # the request's OTel trace (Step 19)
        trace_context = (
            TraceContext(trace_id=format(ctx.trace_id, "032x")) if ctx.is_valid else None
        )
        with self._client.start_as_current_observation(
            name="rag-search",
            as_type="chain",
            trace_context=trace_context,
            input={"question": question if self._capture_question else "[not captured]", "k": k},
        ) as root:
            # user id = the stable pseudonymous "sub", never a name or email
            with propagate_attributes(user_id=p.subject, tags=["rag-api", "search"]):
                yield SearchTrace(self._client)
            root.update(output={"status": "done"})

    def flush(self) -> None:
        if self._client is not None:
            self._client.flush()  # send buffered spans now (Langfuse exports in batches)

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.shutdown()  # flush what's buffered


def build_llm_tracer(
    *,
    base_url: str | None,
    public_key: str | None,
    secret_key: str | None,
    environment: str = "dev",
    release: str | None = None,
    capture_question: bool = True,
    span_exporter: SpanExporter | None = None,
) -> LlmTracer:
    """Langfuse client on a PRIVATE tracer provider; disabled (no-op) when not configured."""
    if not (base_url and public_key and secret_key) and span_exporter is None:
        return LlmTracer(None)
    provider = TracerProvider(resource=Resource.create({"service.name": "rag-api"}))
    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        environment=environment,
        release=release,
        mask=mask,
        tracer_provider=provider,  # isolation: never the global provider
        span_exporter=span_exporter,  # tests inject an in-memory exporter
    )
    return LlmTracer(client, capture_question=capture_question)
