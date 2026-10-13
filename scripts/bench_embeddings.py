#!/usr/bin/env python3
"""Embedding throughput (chunks/s) and rerank latency. Run: just with-secrets uv run scripts/bench_embeddings.py"""

import json
import os
import time
import urllib.request
from typing import Any

KEY = os.environ["TEI_API_KEY"]
CHUNK = (
    "Employees must complete security awareness training annually. Laptops must use full-disk "
    "encryption and screen locks. Report suspected phishing to the security team immediately. "
) * 6  # ~200 tokens


def post(port: int, path: str, payload: object) -> Any:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310 - fixed localhost URL
        return json.loads(resp.read())


post(8083, "/embed", {"inputs": ["warm up"]})
post(8084, "/rerank", {"query": "warm up", "texts": ["warm up"]})

total, batch = 512, 32
start = time.perf_counter()
for _ in range(total // batch):
    post(8083, "/embed", {"inputs": [CHUNK] * batch})
elapsed = time.perf_counter() - start
print(f"embed : {total} chunks (~200 tokens) in {elapsed:.1f}s  ->  {total / elapsed:.0f} chunks/s")

for k in (10, 50):
    start = time.perf_counter()
    post(8084, "/rerank", {"query": "How do I report phishing?", "texts": [CHUNK] * k})
    print(f"rerank: {k:3d} candidates in {(time.perf_counter() - start) * 1000:.0f} ms")
