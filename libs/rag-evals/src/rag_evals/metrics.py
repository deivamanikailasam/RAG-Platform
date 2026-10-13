"""Metrics: small pure functions, each checked against hand-computed values in the tests.

Retrieval works on a RANKED list of document ids. Answers are checked deterministically first
(citations, refusals, forbidden text); an LLM judge only adds an opinion on top (judge.py).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from statistics import mean

# ---------------------------------------------------------------------- retrieval


def recall_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    """Share of the relevant documents found in the top k. 'Did we find what matters?'"""
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    """Share of the top k that is relevant. 'How much noise reaches the prompt?'"""
    return len(set(ranked[:k]) & relevant) / k


def reciprocal_rank(ranked: Sequence[int], relevant: set[int]) -> float:
    """1 / position of the first relevant document (0 if none). Averaged, this is MRR."""
    for position, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return 1 / position
    return 0.0


def ndcg_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    """Rank-aware score in [0, 1]: relevant documents count more the higher they appear."""
    dcg = sum(1 / math.log2(i + 1) for i, d in enumerate(ranked[:k], start=1) if d in relevant)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def leaked(ranked: Sequence[int], forbidden: set[int]) -> list[int]:
    """Documents this person must never receive. Anything here is a security failure."""
    return sorted(set(ranked) & forbidden)


# ---------------------------------------------------------------------- answers

CITATION = re.compile(r"\[doc\s*(\d+)\]", re.IGNORECASE)
REFUSAL = "i don't know based on the available documents"


def citations(answer: str) -> set[int]:
    return {int(n) for n in CITATION.findall(answer)}


def is_refusal(answer: str) -> bool:
    # models often write a curly apostrophe (U+2019) in "don't"
    normalised = answer.lower().replace(chr(0x2019), "'")
    return REFUSAL in normalised


def answer_checks(
    answer: str, *, context_ids: set[int], must_cite: set[int], should_refuse: bool,
    must_not_contain: Sequence[str],
) -> dict[str, bool]:  # fmt: skip
    """Deterministic checks: cheap, repeatable, explainable. Every one must pass."""
    cited = citations(answer)
    checks = {
        "refusal_correct": is_refusal(answer) == should_refuse,
        "no_invented_citations": cited <= context_ids,  # never cite what wasn't provided
        "cites_required": must_cite <= cited,
        "no_forbidden_text": not any(t.lower() in answer.lower() for t in must_not_contain),
    }
    if should_refuse:
        checks["no_citations_when_refusing"] = not cited
    return checks


def citation_precision(answer: str, context_ids: set[int]) -> float:
    cited = citations(answer)
    return len(cited & context_ids) / len(cited) if cited else 1.0


# ---------------------------------------------------------------------- summaries


def avg(values: Sequence[float]) -> float | None:
    return round(mean(values), 4) if values else None
