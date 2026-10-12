#!/usr/bin/env python3
"""Admin tool for LiteLLM teams and virtual keys (uses the MASTER key).

Run: just gateway-admin <command> ...      e.g.   just gateway-admin team rag-apps --budget 50 --models qwen-fast
"""

import argparse
import json
import os
import urllib.request
from typing import Any, cast

BASE = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000")
MASTER = os.environ["LITELLM_MASTER_KEY"]


def call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(  # noqa: S310 - fixed gateway URL
        BASE + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed gateway URL
        return cast(dict[str, Any], json.loads(resp.read()))


parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="cmd", required=True)
t = sub.add_parser("team", help="create a team with a budget")
t.add_argument("alias")
t.add_argument("--budget", type=float, required=True)
t.add_argument("--period", default="30d")
t.add_argument("--models", nargs="+", required=True)
k = sub.add_parser("key", help="create a virtual key in a team")
k.add_argument("alias")
k.add_argument("--team-id", required=True)
k.add_argument("--models", nargs="+", required=True)
k.add_argument("--rpm", type=int)
k.add_argument("--tpm", type=int)
k.add_argument("--parallel", type=int)
k.add_argument("--budget", type=float)
k.add_argument("--expires", default="90d")
i = sub.add_parser("info", help="show a key's limits and spend")
i.add_argument("key")
b = sub.add_parser("block", help="block a key immediately")
b.add_argument("key")
args = parser.parse_args()

if args.cmd == "team":
    r = call(
        "POST",
        "/team/new",
        {
            "team_alias": args.alias,
            "max_budget": args.budget,
            "budget_duration": args.period,
            "models": args.models,
        },
    )
    print("team_id:", r["team_id"])
elif args.cmd == "key":
    body = {
        "key_alias": args.alias,
        "team_id": args.team_id,
        "models": args.models,
        "duration": args.expires,
        "rpm_limit": args.rpm,
        "tpm_limit": args.tpm,
        "max_parallel_requests": args.parallel,
        "max_budget": args.budget,
        "metadata": {"created_by": "gateway_admin.py"},
    }
    r = call("POST", "/key/generate", {f: v for f, v in body.items() if v is not None})
    print("key (shown ONCE - store it now with `just secrets-edit`):", r["key"])
elif args.cmd == "info":
    info = call("GET", f"/key/info?key={args.key}")
    info = info.get("info", info)
    fields = (
        "key_alias",
        "team_id",
        "models",
        "spend",
        "max_budget",
        "rpm_limit",
        "tpm_limit",
        "max_parallel_requests",
        "expires",
        "blocked",
    )
    print(json.dumps({f: info.get(f) for f in fields}, indent=2, default=str))
else:
    print(call("POST", "/key/block", {"key": args.key}))
