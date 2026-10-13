#!/usr/bin/env python3
"""Add 2 docs to Postgres, sync all live chunks into OpenSearch, then compare BM25, vector and hybrid search.

Run: just with-secrets uv run --with opensearch-py --with "psycopg[binary]" --with pgvector --with openai \
         scripts/os_demo.py
"""

import hashlib
import os
from typing import Any

import psycopg
from openai import OpenAI
from opensearchpy import OpenSearch, helpers
from pgvector import HalfVector
from pgvector.psycopg import register_vector

ALIAS, TENANT = "rag-chunks", "acme"
INSTRUCTION = (
    "Instruct: Given an employee question, retrieve passages from company "
    "documents that answer it\nQuery:"
)
NEW_DOCS = [  # (title, text, acl_groups, classification)
    (
        "Travel policy POL-117",
        "POL-117: economy class flights only for trips under six hours; "
        "business class needs CFO approval.",
        ["all-staff"],
        "internal",
    ),
    (
        "WFH requests",
        "WFH requests are approved by your line manager in the HR portal.",
        ["all-staff"],
        "internal",
    ),
]


def os_client(user: str, pw_env: str) -> OpenSearch:
    return OpenSearch(
        hosts=[{"host": "127.0.0.1", "port": 9200}],
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
        http_auth=(user, os.environ[pw_env]),
    )


def first(row: tuple[Any, ...] | None) -> Any:
    """The first column of a row that must exist (fails loudly if the query returned nothing)."""
    if row is None:
        raise RuntimeError("expected a row (has the Step 11 demo collection been loaded?)")
    return row[0]


gateway = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000") + "/v1"
ingest_gw = OpenAI(base_url=gateway, api_key=os.environ["INGESTION_GATEWAY_KEY"])
search_gw = OpenAI(base_url=gateway, api_key=os.environ["RAG_API_GATEWAY_KEY"])
app_dsn = f"postgresql://rag_app:{os.environ['RAG_DB_APP_PASSWORD']}@127.0.0.1:5432/rag"

# 1) source of truth first: insert new docs into Postgres (idempotent by source_uri)
with psycopg.connect(app_dsn) as conn:
    # Step 36: row-level security. A maintenance script works across tenants ('*', whole session)
    conn.execute("SELECT set_config('rag.tenant', '*', false)")
    register_vector(conn)
    coll = first(conn.execute("SELECT id FROM rag.collections WHERE name = 'demo'").fetchone())
    for title, text, acl, cls in NEW_DOCS:
        uri = f"demo://{title}"
        if conn.execute("SELECT 1 FROM rag.documents WHERE source_uri = %s", (uri,)).fetchone():
            continue
        vec = HalfVector(
            ingest_gw.embeddings.create(model="embedder", input=[text]).data[0].embedding
        )
        doc_id = first(
            conn.execute(
                """INSERT INTO rag.documents (collection_id, source_uri, title, content_sha256,
                                              acl_groups, classification)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (coll, uri, title, hashlib.sha256(text.encode()).hexdigest(), acl, cls),
            ).fetchone()
        )
        conn.execute(
            """INSERT INTO rag.chunks (document_id, chunk_index, content, token_count, embedding)
               VALUES (%s, 0, %s, %s, %s)""",
            (doc_id, text, len(text.split()), vec),
        )
    rows = conn.execute("""SELECT c.id, c.embedding, c.content, d.id, d.title, d.source_uri,
                                  d.acl_groups, d.classification
                           FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
                           WHERE d.deleted_at IS NULL""").fetchall()

# 2) sync into OpenSearch as the indexer user (chunk id = document _id)
indexer = os_client("rag_indexer", "OPENSEARCH_INDEXER_PASSWORD")
actions = [
    {
        "_index": ALIAS,
        "_id": cid,
        "_source": {
            "text": text,
            "title": title,
            "embedding": emb.to_list(),
            "tenant_id": TENANT,
            "document_id": did,
            "source_uri": uri,
            "acl_groups": acl,
            "classification": cls,
        },
    }
    for cid, emb, text, did, title, uri, acl, cls in rows
]
helpers.bulk(indexer, actions, refresh=True)
print("synced", len(actions), "chunks")

# 3) search as the read-only user, ALWAYS with the permission filter
search = os_client("rag_search", "OPENSEARCH_SEARCH_PASSWORD")
groups = ["all-staff"]
perm = [{"term": {"tenant_id": TENANT}}, {"terms": {"acl_groups": groups}}]


def bm25(q: str) -> dict[str, Any]:
    return {"bool": {"must": [{"match": {"text": q}}], "filter": perm}}


def knn(q: str) -> dict[str, Any]:
    v = search_gw.embeddings.create(model="embedder", input=[INSTRUCTION + q]).data[0].embedding
    return {"knn": {"embedding": {"vector": v, "k": 10, "filter": {"bool": {"filter": perm}}}}}


def show(label: str, body: dict[str, Any], pipeline: str | None = None) -> None:
    params = {"search_pipeline": pipeline} if pipeline else {}
    hits = search.transport.perform_request("POST", f"/{ALIAS}/_search", params=params, body=body)[
        "hits"
    ]["hits"]
    print(
        f"    {label:7}",
        " | ".join(f"{h['_source']['title']} ({h['_score']:.2f})" for h in hits[:3]),
    )


for question in [
    "POL-117 business class",
    "Can I do my job from my house on Fridays?",
    "WFH approval",
]:
    print(f"\nQ: {question}")
    show("BM25", {"size": 3, "query": bm25(question)})
    show("vector", {"size": 3, "query": knn(question)})
    show(
        "hybrid",
        {"size": 3, "query": {"hybrid": {"queries": [bm25(question), knn(question)]}}},
        "rag-hybrid",
    )

# 4) why did the top BM25 hit score that way?
top = search.search(
    index=ALIAS, body={"size": 1, "explain": True, "query": bm25("POL-117 business class")}
)
print("\nexplain:", top["hits"]["hits"][0]["_explanation"]["description"])
