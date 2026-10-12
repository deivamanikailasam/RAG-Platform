#!/usr/bin/env python3
"""Measure time-to-first-token (TTFT) and streaming speed of the local model servers.

Usage: uv run scripts/bench_models.py [--long]
"""

import json
import sys
import time
import urllib.request

SERVERS = {
    "qwen-quality :8081": "http://127.0.0.1:8081",
    "qwen-fast    :8082": "http://127.0.0.1:8082",
}
SHORT = "Explain retrieval-augmented generation to a new engineer in about 150 words."
FILLER = "Policy text paragraph about leave, travel, expenses and security. " * 600  # ~8k tokens


def run(base: str, prompt: str, max_tokens: int = 256) -> tuple[float, float, int]:
    body = json.dumps(
        {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310 - fixed localhost URL
        f"{base}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}
    )
    start = time.perf_counter()
    first: float | None = None
    pieces = 0
    with urllib.request.urlopen(req, timeout=900) as resp:  # noqa: S310 - fixed localhost URL
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            delta = json.loads(line[5:])["choices"][0].get("delta", {})
            if delta.get("content") or delta.get("reasoning"):
                first = first or time.perf_counter()
                pieces += 1
    end = time.perf_counter()
    if first is None:
        return end - start, 0.0, 0
    return first - start, pieces / max(end - first, 1e-9), pieces


if __name__ == "__main__":
    prompt = (
        FILLER + "\nSummarise the policy above in 5 bullet points."
        if "--long" in sys.argv
        else SHORT
    )
    print(f"{'server':20} {'TTFT (s)':>9} {'~tok/s':>8} {'tokens':>7}")
    for name, base in SERVERS.items():
        run(base, "Say hi.", 8)  # warm-up: first call loads weights into GPU memory
        ttft, tps, n = run(base, prompt)
        print(f"{name:20} {ttft:9.2f} {tps:8.1f} {n:7d}")
