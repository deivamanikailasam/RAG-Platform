#!/usr/bin/env python3
"""Embeddings, query instructions, Matryoshka truncation and reranking on a tiny example.

Run: just with-secrets uv run scripts/embed_demo.py
"""

import json
import math
import os
import urllib.request
from typing import Any

KEY = os.environ["TEI_API_KEY"]
INSTRUCTION = (
    "Instruct: Given an employee question, retrieve passages from company "
    "documents that answer it\nQuery:"
)
QUERY = "Can I work from home on Fridays?"
DOCS = [
    "Staff may work remotely up to two days per week, including Fridays, with manager approval.",
    "Hybrid working: each team agrees its core office days every quarter.",
    "Friday afternoons are reserved for in-office team learning sessions.",
    "Car parking permits are issued by Facilities on the first floor.",
    "Taxi fares are reimbursed only for travel after 10pm.",
]


def post(port: int, path: str, payload: object) -> Any:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - fixed localhost URL
        return json.loads(resp.read())


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are unit length, so dot = cosine


def shrink(v: list[float], dims: int) -> list[float]:
    # Matryoshka: keep the first dims, then re-normalise to unit length
    cut = v[:dims]
    norm = math.sqrt(sum(x * x for x in cut))
    return [x / norm for x in cut]


def show(title: str, qv: list[float], dvs: list[list[float]]) -> None:
    print(f"\n{title}")
    for score, text in sorted(
        ((dot(qv, d), t) for d, t in zip(dvs, DOCS, strict=True)), reverse=True
    ):
        print(f"  {score:6.3f}  {text}")


docs = post(8083, "/embed", {"inputs": DOCS})  # documents: NO instruction
q_inst = post(8083, "/embed", {"inputs": [INSTRUCTION + QUERY]})[0]
q_raw = post(8083, "/embed", {"inputs": [QUERY]})[0]

show(f"Embedding search WITH instruction (dims={len(q_inst)})", q_inst, docs)
show("Embedding search WITHOUT instruction", q_raw, docs)
show("Matryoshka: first 256 dims only", shrink(q_inst, 256), [shrink(d, 256) for d in docs])

print("\nReranker (reads the question and each passage together)")
for r in post(8084, "/rerank", {"query": QUERY, "texts": DOCS}):
    print(f"  {r['score']:6.3f}  {DOCS[r['index']]}")
