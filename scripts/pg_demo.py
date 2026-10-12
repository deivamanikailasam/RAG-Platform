#!/usr/bin/env python3
"""Load a few documents (embedded via the gateway) and run permission-aware semantic search.

Run: just with-secrets uv run --with "psycopg[binary]" --with pgvector --with openai scripts/pg_demo.py
"""

import hashlib
import os

import psycopg
from openai import OpenAI
from pgvector import HalfVector
from pgvector.psycopg import register_vector

INSTRUCTION = (
    "Instruct: Given an employee question, retrieve passages from company "
    "documents that answer it\nQuery:"
)
DOCS = [  # (title, text, acl_groups, classification)
    (
        "Remote work policy",
        "Staff may work remotely up to two days per week with manager approval.",
        ["all-staff"],
        "internal",
    ),
    (
        "Parking",
        "Car parking permits are issued by Facilities on the first floor.",
        ["all-staff"],
        "internal",
    ),
    (
        "Salary bands 2026",
        "Engineering salary bands for 2026 are reviewed each March by HR.",
        ["hr"],
        "confidential",
    ),
    (
        "Exec offsite",
        "The leadership offsite agenda covers the 2027 hybrid-work strategy.",
        ["executives"],
        "restricted",
    ),
]

gw = OpenAI(
    base_url=os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000") + "/v1",
    api_key=os.environ["INGESTION_GATEWAY_KEY"],
)
dsn = f"postgresql://rag_app:{os.environ['RAG_DB_APP_PASSWORD']}@127.0.0.1:5432/rag"


def embed(texts: list[str]) -> list[HalfVector]:
    return [
        HalfVector(d.embedding) for d in gw.embeddings.create(model="embedder", input=texts).data
    ]


def returned_id(cur: psycopg.Cursor[tuple[int]]) -> int:
    """The id from an INSERT ... RETURNING id (fails loudly if no row came back)."""
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING id returned no row")
    return row[0]


with psycopg.connect(dsn, autocommit=False) as conn:
    register_vector(conn)
    cur = conn.cursor()
    cur.execute("SELECT id FROM rag.collections WHERE name = 'demo'")
    row = cur.fetchone()
    if row is None:
        cur.execute(
            """INSERT INTO rag.collections (name, embedding_model, embedding_revision, dimensions,
                                            query_instruction, max_chunk_tokens)
               VALUES ('demo', 'Qwen/Qwen3-Embedding-0.6B', %s, 1024, %s, 1024) RETURNING id""",
            (os.environ.get("EMBED_REVISION", "see models.yaml"), INSTRUCTION),
        )
        coll = returned_id(cur)
        for (title, text, acl, cls), vec in zip(DOCS, embed([d[1] for d in DOCS]), strict=True):
            cur.execute(
                """INSERT INTO rag.documents (collection_id, source_uri, title, content_sha256,
                                              acl_groups, classification)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    coll,
                    f"demo://{title}",
                    title,
                    hashlib.sha256(text.encode()).hexdigest(),
                    acl,
                    cls,
                ),
            )
            doc_id = returned_id(cur)
            cur.execute(
                """INSERT INTO rag.chunks (document_id, chunk_index, content, token_count, embedding)
                   VALUES (%s, 0, %s, %s, %s)""",
                (doc_id, text, len(text.split()), vec),
            )
        conn.commit()
        print("loaded", len(DOCS), "documents")

    question = "What is the plan for hybrid work?"
    qvec = embed([INSTRUCTION + question])[0]
    sql = """SELECT d.title, d.classification, round((1 - (c.embedding <=> %(q)s))::numeric, 3) AS similarity
             FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
             WHERE d.deleted_at IS NULL AND d.acl_groups && %(groups)s
             ORDER BY c.embedding <=> %(q)s LIMIT 3"""
    for groups in (["all-staff"], ["all-staff", "executives"]):
        cur.execute(sql, {"q": qvec, "groups": groups})
        print(f"\nuser in {groups}:")
        for title, cls, sim in cur.fetchall():
            print(f"    {sim}  [{cls}]  {title}")
