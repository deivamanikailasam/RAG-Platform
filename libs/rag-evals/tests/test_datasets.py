"""Datasets: validated case by case, and frozen by hash once released."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rag_evals.datasets import AnswerCase, Dataset, EvalError, RetrievalCase, load_dataset, release

from .conftest import DATASETS


def test_the_real_datasets_load(retrieval_set: Dataset, answer_set: Dataset) -> None:
    assert retrieval_set.ref == "retrieval-golden@1"
    assert len(retrieval_set.cases) == 10
    assert all(isinstance(c, RetrievalCase) for c in retrieval_set.cases)
    assert answer_set.ref == "rag-answer-golden@1"
    assert {c.id for c in answer_set.cases if isinstance(c, AnswerCase) and "injection" in c.tags} == {
        "injected-document", "injected-close-tag", "injected-question"}  # fmt: skip
    assert answer_set.card == "dataset:rag-answer-golden"  # linked to its card (Step 25)


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    shutil.copytree(DATASETS, tmp_path / "datasets")
    return tmp_path / "datasets"


def test_edited_release_is_refused(copy: Path) -> None:
    f = copy / "rag-answer-golden/v1.jsonl"
    f.write_text(f.read_text().replace("each March", "each April"))
    with pytest.raises(EvalError, match="changed after release: create v2"):
        load_dataset(copy, "rag-answer-golden")
    with pytest.raises(EvalError, match="has been edited"):
        release(copy, "rag-answer-golden")


def test_new_version_is_released_and_becomes_latest(copy: Path) -> None:
    folder = copy / "retrieval-golden"
    shutil.copy(folder / "v1.jsonl", folder / "v2.jsonl")
    with (folder / "v2.jsonl").open("a") as f:
        f.write(json.dumps({"kind": "retrieval", "id": "parking-carol", "question": "parking?",
                            "persona": {"name": "carol", "groups": ["all-staff"]}, "relevant": [2]}) + "\n")  # fmt: skip
    assert release(copy, "retrieval-golden") == [2]
    assert load_dataset(copy, "retrieval-golden").ref == "retrieval-golden@2"
    assert (
        len(load_dataset(copy, "retrieval-golden", 1).cases) == 10
    )  # old results stay reproducible


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ({"kind": "answer", "id": "x1", "question": "q", "contexts": [{"id": 1, "text": "t"}],
          "should_refuse": True, "must_cite": [1]}, "refusal case has no citations"),
        ({"kind": "answer", "id": "x2", "question": "q", "contexts": [{"id": 1, "text": "t"}],
          "reference": "r", "must_cite": [5]}, "must be among the contexts"),
        ({"kind": "retrieval", "id": "x3", "question": "q", "persona": {"name": "a", "groups": []},
          "relevant": [1], "forbidden": [1]}, "both relevant and forbidden"),
        ({"kind": "search", "id": "x4"}, "does not match any of the expected tags"),
    ],
)  # fmt: skip
def test_bad_cases_are_refused(copy: Path, line: dict[str, object], message: str) -> None:
    folder = copy / "retrieval-golden"
    (folder / "v2.jsonl").write_text(json.dumps(line) + "\n")
    with pytest.raises(EvalError, match=message):
        release(copy, "retrieval-golden")
