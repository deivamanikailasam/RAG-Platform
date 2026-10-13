"""Judges (extension 04): who scores an answer during evaluation.

    judge: lexical                       # offline, deterministic: the evalkit.metrics functions
    judge: {use: llm, llm_slot: judge_llm}   # a model scores 0..1; lexical where its reply is unusable

LLM judges are useful and fallible: they prefer longer answers, can favour their own model's
style, and break the output format. So the reply must be one JSON object with numbers in [0, 1];
anything else is counted as a judge error (in the run file), never as a pass, and that metric
falls back to the lexical score. Keep the lexical score in your gates; read the judge's as a
second opinion, and spot-check it against people's ratings before trusting a threshold on it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core.evalkit import metrics as m
from rag_core.registry import Container, register

log = logging.getLogger("rag_core.judges")

METRICS = ("faithfulness", "answer_relevance", "correctness")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LexicalParams(_Strict):
    min_support: float = Field(0.5, ge=0, le=1)  # share of a claim's words found in the context


class LexicalJudge:
    name = "lexical"

    def __init__(self, p: LexicalParams) -> None:
        self.p = p
        self.errors = 0

    def score(self, question: str, answer: str, contexts: Sequence[str],
              reference: str | None = None) -> dict[str, float | None]:  # fmt: skip
        return {"faithfulness": m.faithfulness(answer, contexts, self.p.min_support),
                "answer_relevance": m.answer_relevance(question, answer),
                "correctness": m.correctness(answer, reference)}  # fmt: skip


@register("judge", "lexical", params=LexicalParams,
          summary="offline judge: faithfulness, relevance and correctness from word and number overlap")  # fmt: skip
def _lexical(p: LexicalParams, c: Container) -> LexicalJudge:
    return LexicalJudge(p)


JUDGE_PROMPT = """You grade one answer of a document assistant. Score each item from 0 to 1.
faithfulness: share of the answer's claims that the CONTEXT supports (unsupported claims lower it).
answer_relevance: how directly the answer addresses the QUESTION.
correctness: agreement with the REFERENCE answer (null if there is no reference).
Reply with one JSON object only, e.g. {"faithfulness": 1.0, "answer_relevance": 0.8, "correctness": null, "reason": "..."}"""


class LlmJudgeParams(_Strict):
    llm_slot: Literal["judge_llm", "llm"] = (
        "judge_llm"  # a different (stronger) model than the answerer
    )
    max_tokens: int = Field(300, ge=50)
    max_context_chars: int = Field(12_000, ge=1000)
    min_support: float = Field(0.5, ge=0, le=1)  # for the lexical fallback


def parse_scores(reply: str) -> dict[str, float | None]:
    """The judge's JSON reply -> scores; raises ValueError when it isn't usable."""
    found = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", reply, flags=re.S), re.S)
    if not found:
        raise ValueError("no JSON object in the judge's reply")
    data = json.loads(found.group(0))
    if not isinstance(data, dict):
        raise ValueError("the judge's reply is not a JSON object")
    out: dict[str, float | None] = {}
    for k in METRICS:
        v = data.get(k)
        if v is None:
            out[k] = None
        elif isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v <= 1:
            out[k] = float(v)
        else:
            raise ValueError(f"{k} must be a number between 0 and 1 or null, got {v!r}")
    return out


class LlmJudge:
    name = "llm"

    def __init__(self, llm: Any, p: LlmJudgeParams) -> None:
        self.llm, self.p = llm, p
        self.fallback = LexicalJudge(LexicalParams(min_support=p.min_support))
        self.errors = 0

    def score(self, question: str, answer: str, contexts: Sequence[str],
              reference: str | None = None) -> dict[str, float | None]:  # fmt: skip
        lexical = self.fallback.score(question, answer, contexts, reference)
        ctx = "\n\n".join(contexts)[: self.p.max_context_chars]
        user = (f"QUESTION:\n{question}\n\nCONTEXT:\n{ctx}\n\nANSWER:\n{answer}\n\n"
                f"REFERENCE:\n{reference or '(none)'}")  # fmt: skip
        try:
            got = parse_scores(
                str(self.llm.complete(JUDGE_PROMPT, user, max_tokens=self.p.max_tokens))
            )
        except Exception as e:  # an error is recorded and the lexical score used: never a pass
            self.errors += 1
            log.warning("judge reply unusable, using the lexical scores: %s", e)
            return lexical | {"judge_error": 1.0}
        # a metric the judge left null but the lexical judge can score (no reference -> both None)
        return {k: (got[k] if got[k] is not None or (reference is None and k == "correctness") else lexical[k])
                for k in METRICS}  # fmt: skip


@register("judge", "llm", params=LlmJudgeParams, status="mocked",
          summary="LLM-as-judge (JSON scores 0..1), lexical fallback per metric on an unusable reply")  # fmt: skip
def _llm_judge(p: LlmJudgeParams, c: Container) -> LlmJudge:
    return LlmJudge(c.get(p.llm_slot if c.has(p.llm_slot) else "llm"), p)


__all__ = ["JUDGE_PROMPT", "LexicalJudge", "LlmJudge", "parse_scores"]
