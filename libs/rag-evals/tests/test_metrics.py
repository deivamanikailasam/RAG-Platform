"""Every metric against a value worked out by hand."""

from __future__ import annotations

import math

import pytest

from rag_evals import metrics as m

RANKED = [7, 1, 9, 3, 5]  # what the system returned, best first
RELEVANT = {1, 3}


def test_recall_and_precision() -> None:
    assert m.recall_at_k(RANKED, RELEVANT, 5) == 1.0  # both relevant documents are in the top 5
    assert m.recall_at_k(RANKED, RELEVANT, 2) == 0.5  # only document 1 is in the top 2
    assert m.precision_at_k(RANKED, RELEVANT, 5) == 0.4  # 2 of 5 are relevant


def test_reciprocal_rank() -> None:
    assert m.reciprocal_rank(RANKED, RELEVANT) == 0.5  # first relevant at position 2
    assert m.reciprocal_rank([8, 9], RELEVANT) == 0.0


def test_ndcg() -> None:
    # relevant at positions 2 and 4: DCG = 1/log2(3) + 1/log2(5); ideal = 1/log2(2) + 1/log2(3)
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert m.ndcg_at_k(RANKED, RELEVANT, 5) == pytest.approx(expected)
    assert m.ndcg_at_k([1, 3], RELEVANT, 5) == 1.0  # perfect order


def test_leaks() -> None:
    assert m.leaked(RANKED, {3, 4}) == [3]


def test_citations_and_refusals() -> None:
    assert m.citations("Two days [doc 1], approval needed [Doc 12] [doc1].") == {1, 12}
    assert m.is_refusal("Sorry: I don" + chr(0x2019) + "t know based on the available documents.")
    assert not m.is_refusal("Two days [doc 1].")


def test_answer_checks() -> None:
    ok = m.answer_checks("Facilities [doc 2].", context_ids={2, 9}, must_cite={2},
                         should_refuse=False, must_not_contain=["PWNED"])  # fmt: skip
    assert all(ok.values())
    bad = m.answer_checks("PWNED [doc 4]", context_ids={2, 9}, must_cite={2},
                          should_refuse=False, must_not_contain=["pwned"])  # fmt: skip
    assert bad == {"refusal_correct": True, "no_invented_citations": False,
                   "cites_required": False, "no_forbidden_text": False}  # fmt: skip
    refusal = m.answer_checks("I don't know based on the available documents [doc 1].",
                              context_ids={1}, must_cite=set(), should_refuse=True,
                              must_not_contain=[])  # fmt: skip
    assert refusal["refusal_correct"] is True
    assert refusal["no_citations_when_refusing"] is False  # refusing AND citing is contradictory


def test_citation_precision() -> None:
    assert m.citation_precision("[doc 1] [doc 4]", {1, 2}) == 0.5
    assert m.citation_precision("no citations", {1}) == 1.0
