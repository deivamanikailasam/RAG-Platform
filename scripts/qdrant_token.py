#!/usr/bin/env python3
"""Mint a short-lived, read-only Qdrant token for one collection, and prove it can't write.

Run: just with-secrets uv run --with qdrant-client --with pyjwt scripts/qdrant_token.py
"""

import os
import time

import jwt
from qdrant_client import QdrantClient, models

COLLECTION = "rag_chunks_qwen3e06b_v1"  # scope tokens to the real collection name
token = jwt.encode(
    {
        "access": [{"collection": COLLECTION, "access": "r"}],
        "exp": int(time.time()) + 3600,  # valid for one hour
    },
    os.environ["QDRANT_API_KEY"],
    algorithm="HS256",
)

app = QdrantClient(url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"), api_key=token)
print("read  :", app.count(COLLECTION, exact=True).count, "points")
try:
    app.upsert(
        COLLECTION,
        points=[models.PointStruct(id=999999, vector={"dense": [0.0] * 1024}, payload={})],
    )
    print("write : ALLOWED (unexpected!)")
except Exception as e:  # broad on purpose: we expect a permission error here
    print("write : rejected ->", type(e).__name__)
