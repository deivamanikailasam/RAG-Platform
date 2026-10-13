"""Online evaluation (Step 37): rates per release from audit events, and a fair comparison."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from rag_core import online
from rag_core.cli import main


def answer(i: int, release: str, result: str = "answered", *, cited: bool = True, flagged: bool = False,
           stream: bool = False) -> list[dict[str, Any]]:  # fmt: skip
    aid = f"{i:032x}"
    guards = [{"guard": "groundedness", "stage": "output", "action": "flag"}] if flagged else []
    first = {"action": "answer", "outcome": "allowed", "resource": "documents", "trace_id": aid,
             "details": {"answer_id": aid, "result": "streaming" if stream else result, "release": release,
                         "cited_ids": [1] if cited else [], "guards": guards, "context_ids": [1, 2]}}  # fmt: skip
    if not stream:
        return [first]
    done = {
        "action": "answer.completed",
        "outcome": "allowed",
        "resource": "documents",
        "details": {
            "answer_id": aid,
            "result": result,
            "cited_ids": [1] if cited else [],
            "guards": guards,
        },
    }
    return [first, done]


def rating(i: int, value: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "action": "feedback",
        "outcome": "allowed",
        "resource": f"answer:{i:032x}",
        "details": json.dumps({"rating": value, "reason": reason}),
    }  # stored as text by some exports


def test_events_are_joined_per_release_and_nothing_needs_text() -> None:
    events = (answer(1, "v1") + answer(2, "v1", "abstained") + answer(3, "v1", flagged=True)
              + answer(4, "v2", stream=True) + answer(5, "v2", "blocked") + answer(6, "v2", stream=True)[:1]
              + [rating(1, "up"), rating(3, "down", "wrong"), rating(4, "down", "outdated")])  # fmt: skip
    groups, queue = online.collect(events)
    v1, v2 = groups["v1"], groups["v2"]
    assert (v1.answers, v1.answered, v1.abstained, v1.ungrounded, v1.rated, v1.down) == (
        3,
        2,
        1,
        1,
        2,
        1,
    )
    assert v1.reasons == {"wrong": 1}
    # a stream that started and never completed counts as an error, not as an answer
    assert (v2.answers, v2.answered, v2.blocked, v2.errors) == (3, 1, 1, 1)
    assert v2.rates()["down_rate"] == 1.0
    assert {q["answer_id"][-1]: q["why"] for q in queue} == {
        "3": ["thumbs down (wrong)", "groundedness flagged"],
        "4": ["thumbs down (outdated)"],
    }
    # ids and reasons only: a reviewer opens the trace for the words
    assert {k for q in queue for k in q} == {
        "answer_id",
        "trace_id",
        "group",
        "why",
        "context_ids",
        "cited_ids",
    }


def _release(name: str, n: int, p_abstain: float, p_down: float, seed: int) -> list[dict[str, Any]]:
    rnd = random.Random(seed)  # noqa: S311 - reproducible test data, not security
    out: list[dict[str, Any]] = []
    for i in range(n):
        idx = seed * 100000 + i
        out += answer(idx, name, "abstained" if rnd.random() < p_abstain else "answered")
        if rnd.random() < 0.5:
            out.append(rating(idx, "down" if rnd.random() < p_down else "up"))
    return out


def test_a_clearly_worse_canary_fails_and_a_similar_one_passes() -> None:
    stable = _release("stable", 600, 0.10, 0.10, 1)
    worse = _release("worse", 600, 0.25, 0.10, 2)
    same = _release("same", 600, 0.11, 0.11, 3)
    groups, _ = online.collect(stable + worse + same)
    v = online.compare(groups["worse"], groups["stable"])
    assert v.status == "fail"
    assert [c.metric for c in v.checks if c.status == "fail"] == ["abstain_rate"]
    assert online.compare(groups["same"], groups["stable"]).status == "pass"


def test_too_few_answers_is_insufficient_not_a_verdict() -> None:
    groups, _ = online.collect(_release("a", 30, 0.5, 0.5, 4) + _release("b", 600, 0.1, 0.1, 5))
    v = online.compare(groups["a"], groups["b"], min_n=50)
    assert v.status == "insufficient"


def test_absolute_limits_apply_whatever_the_baseline() -> None:
    bad = online.Stats(answers=200, answered=180, errors=10, cited=180, rated=100)
    base = online.Stats(answers=200, answered=180, errors=9, cited=180, rated=100)
    v = online.compare(bad, base, limits={"error_rate": 0.02})
    assert v.status == "fail"
    assert "above the limit" in next(c for c in v.checks if c.metric == "error_rate").detail


@pytest.mark.parametrize(("flag", "code"), [("wait", 3), ("pass", 0), ("fail", 1)])
def test_cli_exit_codes_drive_the_gates(tmp_path: Path, flag: str, code: int) -> None:
    events = tmp_path / "audit.jsonl"
    events.write_text(
        "".join(
            json.dumps(e) + "\n"
            for e in _release("a", 20, 0.1, 0.1, 6) + _release("b", 20, 0.1, 0.1, 7)
        )
    )
    args = [
        "online-eval",
        "--events",
        str(events),
        "--candidate",
        "a",
        "--baseline",
        "b",
        "--on-insufficient",
        flag,
    ]
    assert main(args) == code


def test_cli_writes_the_review_queue_and_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "audit.jsonl"
    rows = _release("stable", 400, 0.1, 0.1, 8) + _release("canary", 400, 0.3, 0.1, 9)
    events.write_text("".join(json.dumps(e) + "\n" for e in rows))
    queue, verdict = tmp_path / "review.jsonl", tmp_path / "verdict.json"
    assert main(["online-eval", "--events", str(events), "--candidate", "canary", "--baseline", "stable",
                 "--queue", str(queue), "--json", str(verdict)]) == 1  # fmt: skip
    out = capsys.readouterr().out
    assert "canary vs stable: FAIL" in out
    assert json.loads(verdict.read_text())["status"] == "fail"
    assert all(json.loads(line)["why"] for line in queue.read_text().splitlines())
