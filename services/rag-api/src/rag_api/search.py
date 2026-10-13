"""Permission-aware search: Step 11's single SQL query ("legacy"), or rag-core's search pipeline
("core", Step 32: hybrid retrieval, fusion, reranking), chosen by RAG_API_SEARCH_BACKEND."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Any, Protocol, cast

import psycopg
from openai import OpenAI
from opentelemetry import trace
from pgvector import HalfVector
from pgvector.psycopg import register_vector
from pydantic import BaseModel

from rag_api.policy import DocumentRef
from rag_api.settings import Settings
from rag_common.prompts import Registry

# The filter VALUES come from the policy (OPA); this query only applies them.
SQL = """
SELECT d.id, d.title, d.classification, d.acl_groups,
       round((1 - (c.embedding <=> %(q)s))::numeric, 3)::float AS score
FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
WHERE d.deleted_at IS NULL
  AND d.classification = ANY(%(classifications)s)
  AND (d.classification = 'public' OR d.acl_groups && %(groups)s)
ORDER BY c.embedding <=> %(q)s
LIMIT %(k)s
"""

tracer = trace.get_tracer("rag_api.search")


class Hit(BaseModel):
    """What the caller sees."""

    id: int  # the document id: needed to cite it (rag-answer@2) and to evaluate retrieval (Step 26)
    title: str
    classification: str
    score: float


@dataclass(frozen=True)
class Candidate:
    """What the database returned: the visible hit plus the facts the policy re-checks."""

    ref: DocumentRef
    hit: Hit


class SearchBackend(Protocol):
    def search(
        self,
        query: str,
        *,
        groups: frozenset[str],
        classifications: frozenset[str],
        k: int,
        user: str,
    ) -> list[Candidate]: ...


class PgSearch:
    def __init__(self, s: Settings, prompts: Registry) -> None:
        # The query instruction is a registered prompt (Step 24), part of the embedding contract.
        self._prompts, self._label = prompts, s.prompt_label
        self._gw = OpenAI(base_url=s.gateway_url, api_key=s.gateway_key.get_secret_value())
        # The role is configurable, so the evaluation harness can read with rag_readonly (Step 26).
        # Read for EVERY connection: with OpenBao the username and password change over time (Step 28)
        self._host, self._credentials = s.db_host, s.db_credentials()
        self._tenant = s.tenant  # Step 36: row-level security shows the database only this tenant

    def search(
        self,
        query: str,
        *,
        groups: frozenset[str],
        classifications: frozenset[str],
        k: int,
        user: str,
    ) -> list[Candidate]:
        if not classifications:
            return []  # fail closed: no clearance, no documents
        # "user" lets the gateway attribute cost and logs to the real person (Step 10 spend tracking)
        # A GenAI span named the OpenTelemetry way ("{operation} {model}"). The HTTP call inside
        # carries the trace id to LiteLLM, which continues the same trace.
        with tracer.start_as_current_span(
            "embeddings embedder",
            kind=trace.SpanKind.CLIENT,
            attributes={"gen_ai.operation.name": "embeddings", "gen_ai.request.model": "embedder"},
        ) as span:
            text = self._prompts.render(
                "query-instruction", {"query": query}, label=self._label
            ).text
            emb = self._gw.embeddings.create(model="embedder", input=[text or ""], user=user)
            span.set_attribute("gen_ai.usage.input_tokens", emb.usage.prompt_tokens)
        user_name, password = self._credentials()
        with psycopg.connect(host=self._host, dbname="rag", user=user_name, password=password,
                             application_name="rag-api") as conn:  # fmt: skip
            register_vector(conn)
            # Step 36: row-level security. Local to this transaction, so a reused connection can't
            # carry it into another request; without it the database returns no rows at all.
            conn.execute("SELECT set_config('rag.tenant', %s, true)", (self._tenant,))
            rows = conn.execute(
                SQL,
                {
                    "q": HalfVector(emb.data[0].embedding),
                    "groups": sorted(groups),
                    "classifications": sorted(classifications),
                    "k": k,
                },
            ).fetchall()
        return [
            Candidate(
                ref=DocumentRef(id=i, classification=c, acl_groups=tuple(acl)),
                hit=Hit(id=i, title=t, classification=c, score=sc),
            )
            for i, t, c, acl, sc in rows
        ]


class CoreSearch:
    """The same contract as PgSearch, answered by rag-core's search pipeline (Step 32). OPA still
    decides WHAT may be seen (the filter); rag-core decides HOW to find it (rag.yaml)."""

    def __init__(self, s: Settings, pipeline: Any = None) -> None:
        from rag_core import config
        from rag_core.search import SearchPipeline

        self._pipeline = pipeline or SearchPipeline(config.load(s.rag_config, s.rag_profile))
        self._tenant = s.tenant

    def search(
        self,
        query: str,
        *,
        groups: frozenset[str],
        classifications: frozenset[str],
        k: int,
        user: str,
    ) -> list[Candidate]:
        from rag_core.types import Classification, Query
        from rag_core.types import Principal as CorePrincipal

        if not classifications:
            return []  # fail closed, exactly like PgSearch
        # OPA only returns known classification names
        levels = cast(tuple[Classification, ...], tuple(sorted(classifications)))
        who = CorePrincipal(user, tuple(sorted(groups)), levels, self._tenant)
        # Ask for more chunks than documents: several chunks often come from one document
        result = self._pipeline.search(Query(query, who, k=k * 3))
        trace.get_current_span().set_attribute("rag.search.texts", len(result.texts))
        best: dict[int, Candidate] = {}
        for h in result.hits:
            doc_id = document_id(h.chunk)
            if doc_id in best:
                continue  # hits are best-first: the first chunk of a document carries its score
            a = h.chunk.access
            best[doc_id] = Candidate(
                ref=DocumentRef(id=doc_id, classification=a.classification, acl_groups=a.groups),
                hit=Hit(id=doc_id, title=str(h.chunk.metadata.get("title", "")),
                        classification=a.classification, score=round(h.score, 3)),
            )  # fmt: skip
        return list(best.values())[:k]


def document_id(chunk: Any) -> int:
    """Step 11's numeric id when the store has one (Postgres); a stable number otherwise."""
    value = chunk.metadata.get("document_id")
    if isinstance(value, int):
        return value
    return zlib.crc32(chunk.document_uri.encode())
