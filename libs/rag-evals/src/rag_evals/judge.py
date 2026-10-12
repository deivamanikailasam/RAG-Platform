"""An LLM judge: a second opinion on correctness and faithfulness, from a registered prompt.

Judges are useful and fallible. They prefer longer answers, can favour their own model's style,
and sometimes break the output format. So: temperature 0, a strict JSON reply, failures counted
as errors (never as passes), and the deterministic checks in metrics.py stay the gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from rag_common.prompts import Registry
from rag_evals.datasets import AnswerCase
from rag_evals.targets import THINK, chat, format_contexts

JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class Verdict:
    correct: bool | None
    faithful: bool | None
    reason: str
    error: str | None = None


def parse_verdict(text: str) -> Verdict:
    """Accept exactly {"correct": bool, "faithful": bool, "reason": str}, possibly with chatter around it."""
    match = JSON_OBJECT.search(THINK.sub("", text))
    if not match:
        return Verdict(None, None, "", "no JSON object in the judge's reply")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return Verdict(None, None, "", f"invalid JSON: {e.msg}")
    if not isinstance(data, dict):
        return Verdict(None, None, "", "the judge's reply is not a JSON object")
    if not isinstance(data.get("correct"), bool) or not isinstance(data.get("faithful"), bool):
        return Verdict(None, None, "", "correct and faithful must be true or false")
    return Verdict(data["correct"], data["faithful"], str(data.get("reason", ""))[:300])


class Judge:
    def __init__(self, client: OpenAI, registry: Registry, *, label: str = "production") -> None:
        self._client, self._registry, self._label = client, registry, label
        self.prompt, self.sha = registry.get("eval-judge", label=label)

    def describe(self) -> dict[str, Any]:
        return {"judge_prompt": self.prompt.ref, "judge_model": self.prompt.model}

    def grade(self, case: AnswerCase, answer: str) -> Verdict:
        r = self._registry.render("eval-judge", {
            "question": case.question, "context": format_contexts(case.contexts),
            "reference": case.reference, "answer": answer[:8000],
        }, label=self._label)  # fmt: skip
        try:
            text, _ = chat(self._client, r)
        except Exception as e:  # any failure is recorded as a judge error, never as a pass
            return Verdict(None, None, "", f"judge call failed: {type(e).__name__}")
        return parse_verdict(text)
