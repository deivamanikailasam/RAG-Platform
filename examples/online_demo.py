"""Online evaluation, end to end without a cluster (Step 37).

Writes a day of audit events like rag-api records them (no question or answer text: ids, outcomes,
citations, guard verdicts, the release) plus thumbs up/down, for a stable release and a canary
whose new prompt abstains too often, then runs `rag online-eval` on them like the canary's
analysis Job does.         Run:    uv run python examples/online_demo.py
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

from rag_core.cli import main

rnd = random.Random(37)  # noqa: S311 - reproducible demo data


def release(name: str, n: int, abstain: float, down: float, start: int) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for i in range(start, start + n):
        aid = f"{i:032x}"
        result = (
            "abstained"
            if rnd.random() < abstain
            else "blocked"
            if rnd.random() < 0.02
            else "answered"
        )
        flagged = result == "answered" and rnd.random() < 0.04
        events.append({"action": "answer", "outcome": "allowed", "resource": "documents", "trace_id": aid,
                       "details": {"answer_id": aid, "release": name, "result": result,
                                   "cited_ids": [7] if result == "answered" else [],
                                   "guards": [{"guard": "groundedness", "stage": "output", "action": "flag"}] if flagged else []}})  # fmt: skip
        if rnd.random() < 0.3:  # about a third of people rate an answer
            bad = rnd.random() < down
            events.append({"action": "feedback", "outcome": "allowed", "resource": f"answer:{aid}",
                           "details": {"rating": "down" if bad else "up", "reason": "wrong" if bad else None}})  # fmt: skip
    return events


folder = Path(tempfile.mkdtemp())
log = folder / "audit.jsonl"
rows = release("7d9f8c6b5", 900, 0.08, 0.10, 0) + release("5c4b3a291", 300, 0.22, 0.14, 10_000)
log.write_text("".join(json.dumps(e) + "\n" for e in rows))
print(
    "$ rag online-eval --events audit.jsonl --candidate 5c4b3a291 --baseline 7d9f8c6b5 --queue review.jsonl\n"
)
code = main(["online-eval", "--events", str(log), "--candidate", "5c4b3a291", "--baseline", "7d9f8c6b5",
             "--queue", str(folder / "review.jsonl")])  # fmt: skip
print(f"\nexit code {code}          (0 pass, 1 fail, 3 not enough data yet)")
first = json.loads((folder / "review.jsonl").read_text().splitlines()[0])
print("first answer to review:", json.dumps(first))
sys.exit(0)
