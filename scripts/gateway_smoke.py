#!/usr/bin/env python3
"""End-to-end checks through the LiteLLM gateway, using the official OpenAI SDK.

Run: just with-secrets uv run --with openai scripts/gateway_smoke.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

from openai import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
)

BASE = "http://127.0.0.1:4000"
KEY = os.environ["LITELLM_MASTER_KEY"]
client = OpenAI(base_url=f"{BASE}/v1", api_key=KEY)
failures = 0

print("models       :", [m.id for m in client.models.list().data])

for role in ("qwen-fast", "qwen-quality"):
    r = client.chat.completions.create(
        model=role,
        max_tokens=60,
        temperature=0,
        messages=[{"role": "user", "content": "In one sentence, what is a vector database?"}],
    )
    tokens = r.usage.total_tokens if r.usage else "?"
    print(f"{role:13}:", (r.choices[0].message.content or "").strip()[:100], "|", tokens, "tokens")

print("stream       :", end=" ", flush=True)
for chunk in client.chat.completions.create(
    model="qwen-fast",
    max_tokens=30,
    stream=True,
    messages=[{"role": "user", "content": "Count to five."}],
):
    if chunk.choices:  # a final usage-only chunk has no choices
        print(chunk.choices[0].delta.content or "", end="", flush=True)
print()

emb = client.embeddings.create(model="embedder", input=["remote work policy", "car parking"])
print("embed        :", len(emb.data), "vectors of", len(emb.data[0].embedding), "dims")

req = urllib.request.Request(  # noqa: S310 - fixed localhost URL
    f"{BASE}/rerank",
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    data=json.dumps(
        {
            "model": "reranker",
            "query": "Can I work from home?",
            "top_n": 2,
            "documents": [
                "Remote work is allowed two days a week.",
                "Parking permits are issued by Facilities.",
            ],
        }
    ).encode(),
)
with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed localhost URL
    print(
        "rerank       :",
        [(x["index"], round(x["relevance_score"], 3)) for x in json.loads(resp.read())["results"]],
    )

# --- security checks: each of these MUST fail ---
for label, key, model in [("no/bad key", "sk-wrong", "qwen-fast"), ("unknown model", KEY, "gpt-5")]:
    try:
        OpenAI(base_url=f"{BASE}/v1", api_key=key, max_retries=0).chat.completions.create(
            model=model, max_tokens=5, messages=[{"role": "user", "content": "hi"}]
        )
        print(f"FAIL         : {label} was accepted!")
        failures += 1
    except (AuthenticationError, BadRequestError, NotFoundError) as e:
        print(f"ok           : {label} rejected ({type(e).__name__})")
    except (APIConnectionError, urllib.error.URLError) as e:
        print(f"error        : {e}")
        failures += 1

sys.exit(1 if failures else 0)
