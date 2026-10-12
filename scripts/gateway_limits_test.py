#!/usr/bin/env python3
"""Prove allow-list, rate limit and budget enforcement on the gateway.

Creates throwaway teams/keys, tests them, then blocks the keys. Run: just gateway-test
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000")
MASTER = os.environ["LITELLM_MASTER_KEY"]


def call(path: str, payload: dict[str, Any], key: str = MASTER) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(  # noqa: S310 - fixed gateway URL
        BASE + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310 - fixed gateway URL
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:160]}


def chat(key: str, model: str, max_tokens: int = 20) -> int:
    return call(
        "/v1/chat/completions",
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": "Write a short poem about search."}],
        },
        key,
    )[0]


def new_key(alias: str, team: str, **limits: object) -> str:
    return str(
        call(
            "/key/generate",
            {
                "key_alias": alias,
                "team_id": team,
                "models": ["qwen-fast"],
                "duration": "1h",
                **limits,
            },
        )[1]["key"]
    )


limits_team = {"team_alias": "test-limits", "max_budget": 100, "models": ["qwen-fast"]}
budget_team = {"team_alias": "test-budget", "max_budget": 0.0005, "models": ["qwen-fast"]}
big = call("/team/new", limits_team)[1]["team_id"]
tiny = call("/team/new", budget_team)[1]["team_id"]
k_rate = new_key("test-rpm", big, rpm_limit=2)
k_budget = new_key("test-budget", tiny)

print(
    "1. allow-list : qwen-quality with a qwen-fast-only key ->",
    chat(k_rate, "qwen-quality"),
    "(expect 401/403)",
)
print("2. rate limit :", [chat(k_rate, "qwen-fast") for _ in range(3)], "(expect 200, 200, 429)")
codes = []
for _ in range(6):  # spend is recorded slightly after each call, so allow a few tries
    codes.append(chat(k_budget, "qwen-fast", max_tokens=200))
    if codes[-1] != 200:
        break
    time.sleep(3)
print("3. budget     :", codes, "(expect some 200s, then a budget rejection)")

for k in (k_rate, k_budget):
    call("/key/block", {"key": k})
print("test keys blocked. Delete the test-* teams in the admin UI when you like.")
