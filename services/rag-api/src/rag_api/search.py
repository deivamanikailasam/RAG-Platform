"""Permission-aware semantic search over the Step 11 tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
        self._dsn = (
            f"host={s.db_host} dbname=rag user=rag_app password={s.db_password.get_secret_value()}"
        )

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
        with psycopg.connect(self._dsn) as conn:
            register_vector(conn)
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
                hit=Hit(title=t, classification=c, score=sc),
            )
            for i, t, c, acl, sc in rows
        ]
