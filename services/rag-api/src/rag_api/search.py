"""Permission-aware semantic search over the Step 11 tables."""

from __future__ import annotations

from typing import Protocol

import psycopg
from openai import OpenAI
from pgvector import HalfVector
from pgvector.psycopg import register_vector
from pydantic import BaseModel

from rag_api.settings import Settings

INSTRUCTION = (
    "Instruct: Given an employee question, retrieve passages from company "
    "documents that answer it\nQuery:"
)
SQL = """
SELECT d.title, d.classification, round((1 - (c.embedding <=> %(q)s))::numeric, 3)::float AS score
FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
WHERE d.deleted_at IS NULL AND d.acl_groups && %(groups)s
ORDER BY c.embedding <=> %(q)s
LIMIT %(k)s
"""


class Hit(BaseModel):
    title: str
    classification: str
    score: float


class SearchBackend(Protocol):
    def search(self, query: str, *, groups: frozenset[str], k: int, user: str) -> list[Hit]: ...


class PgSearch:
    def __init__(self, s: Settings) -> None:
        self._gw = OpenAI(base_url=s.gateway_url, api_key=s.gateway_key.get_secret_value())
        self._dsn = (
            f"host={s.db_host} dbname=rag user=rag_app password={s.db_password.get_secret_value()}"
        )

    def search(self, query: str, *, groups: frozenset[str], k: int, user: str) -> list[Hit]:
        if not groups:
            return []  # fail closed: no groups, no documents
        # "user" lets the gateway attribute cost and logs to the real person (Step 10 spend tracking)
        emb = self._gw.embeddings.create(model="embedder", input=[INSTRUCTION + query], user=user)
        with psycopg.connect(self._dsn) as conn:
            register_vector(conn)
            rows = conn.execute(
                SQL, {"q": HalfVector(emb.data[0].embedding), "groups": sorted(groups), "k": k}
            ).fetchall()
        return [Hit(title=t, classification=c, score=sc) for t, c, sc in rows]
