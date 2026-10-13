#!/usr/bin/env python3
"""Mirror live chunks from Postgres (source of truth) into Qdrant, then run a permission-aware search.

Run: just with-secrets uv run --with qdrant-client --with "psycopg[binary]" --with pgvector --with openai \
         scripts/qdrant_sync.py
"""

import os

import psycopg
from openai import OpenAI
from pgvector.psycopg import register_vector
from qdrant_client import QdrantClient, models

ALIAS = "rag_chunks"
TENANT = "acme"  # single tenant for now; Step 31 adds real tenants
INSTRUCTION = (
    "Instruct: Given an employee question, retrieve passages from company "
    "documents that answer it\nQuery:"
)

qd = QdrantClient(
    url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"), api_key=os.environ["QDRANT_API_KEY"]
)
dsn = f"postgresql://rag_readonly:{os.environ['RAG_DB_READONLY_PASSWORD']}@127.0.0.1:5432/rag"

points = []
with psycopg.connect(dsn) as conn:
    # Step 36: row-level security. A maintenance script works across tenants ('*', whole session)
    conn.execute("SELECT set_config('rag.tenant', '*', false)")
    register_vector(conn)
    rows = conn.execute("""
        SELECT c.id, c.embedding, c.content, d.id, d.title, d.source_uri, d.acl_groups, d.classification
        FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id
        WHERE d.deleted_at IS NULL""").fetchall()
for cid, emb, text, did, title, uri, acl, cls in rows:
    points.append(
        models.PointStruct(
            id=cid,  # same id as Postgres: easy to reconcile
            vector={"dense": emb.to_list()},
            payload={
                "tenant_id": TENANT,
                "document_id": did,
                "title": title,
                "source_uri": uri,
                "acl_groups": acl,
                "classification": cls,
                "text": text,
            },
        )
    )
qd.upsert(collection_name=ALIAS, points=points, wait=True)
print("synced", len(points), "points; Qdrant count =", qd.count(ALIAS, exact=True).count)

gw = OpenAI(
    base_url=os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000") + "/v1",
    api_key=os.environ["RAG_API_GATEWAY_KEY"],
)
question = "What is the plan for hybrid work?"
qvec = gw.embeddings.create(model="embedder", input=[INSTRUCTION + question]).data[0].embedding

for groups in (["all-staff"], ["all-staff", "executives"]):
    hits = qd.query_points(
        collection_name=ALIAS,
        query=qvec,
        using="dense",
        limit=3,
        with_payload=True,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(key="tenant_id", match=models.MatchValue(value=TENANT)),
                models.FieldCondition(key="acl_groups", match=models.MatchAny(any=groups)),
            ]
        ),
        search_params=models.SearchParams(
            hnsw_ef=64, quantization=models.QuantizationSearchParams(rescore=True)
        ),
    ).points
    print(f"\nuser in {groups}:")
    for h in hits:
        payload = h.payload or {}
        print(f"    {h.score:.3f}  [{payload['classification']}]  {payload['title']}")
