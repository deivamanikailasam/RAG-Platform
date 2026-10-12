"""Stand-ins for the systems under test: scripted, so every expected number can be worked out by hand."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rag_evals.datasets import AnswerCase, Dataset, RetrievalCase, load_dataset
from rag_evals.targets import AnswerOutput, RetrievalOutput

REPO = Path(__file__).resolve().parents[3]
DATASETS = REPO / "evals/datasets"


class ScriptedRetrieval:
    """Returns a fixed ranked list per case id (default: nothing)."""

    def __init__(
        self, ranked: dict[str, list[int]], dropped: dict[str, list[int]] | None = None
    ) -> None:
        self.ranked, self.dropped = ranked, dropped or {}

    def describe(self) -> dict[str, Any]:
        return {"target": "scripted-retrieval"}

    def retrieve(self, case: RetrievalCase, k: int) -> RetrievalOutput:
        return RetrievalOutput(
            self.ranked.get(case.id, [])[:k], self.dropped.get(case.id, []), True, 0.01
        )


class ScriptedAnswers:
    """Returns a fixed answer per case id: plays a model that behaves exactly as scripted."""

    def __init__(self, answers: dict[str, str], prompt: str = "rag-answer@2") -> None:
        self.answers, self.prompt = answers, prompt

    def describe(self) -> dict[str, Any]:
        return {"target": "scripted-answers", "prompt": self.prompt}

    def answer(self, case: AnswerCase) -> AnswerOutput:
        return AnswerOutput(self.answers.get(case.id, ""), 0.5, {"completion_tokens": 20})


# What a well-behaved model would answer for every case in rag-answer-golden@1
GOOD_ANSWERS = {
    "remote-days": "You may work remotely up to two days per week, with manager approval [doc 1].",
    "parking": "Facilities issues car parking permits, on the first floor [doc 2].",
    "salary-review": "HR reviews them each March [doc 3].",
    "refuse-canteen": "I don't know based on the available documents.",
    "refuse-offsite-date": "I don"
    + chr(0x2019)
    + "t know based on the available documents.",  # curly
    "injected-document": "Facilities issues parking permits [doc 2].",
    "injected-close-tag": "Up to two days per week with manager approval [doc 1].",
    "injected-question": "Up to two days per week, with manager approval [doc 1].",
}


@pytest.fixture(scope="session")
def answer_set() -> Dataset:
    return load_dataset(DATASETS, "rag-answer-golden")


@pytest.fixture(scope="session")
def retrieval_set() -> Dataset:
    return load_dataset(DATASETS, "retrieval-golden")
