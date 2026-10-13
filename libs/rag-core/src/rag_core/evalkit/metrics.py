"""Evaluation metrics (extension 04): small pure functions, offline, checked by hand in the tests.

Retrieval metrics take a RANKED list of document names and the set that answers the question
(binary relevance). Answer metrics are lexical stand-ins for what an LLM judge scores (Ragas'
faithfulness, answer relevance, context precision/recall, answer correctness): cruder, but free,
deterministic and good at catching regressions. A `judge: {use: llm}` replaces the lexical scores
with a model's where one is configured, and falls back to these when the model's reply is unusable.

    retrieval   hit_rate · recall · precision · reciprocal_rank (MRR) · average_precision (MAP) · ndcg
    answers     faithfulness · answer_relevance · context_precision · context_recall · correctness
                · citation_precision · citation_recall · abstention_correct
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from rag_core.text import content_words, sentences

_CITE = re.compile(r"\[(?:doc[^\]]*|\^?\d+)\]", re.I)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")

# ---------------------------------------------------------------------- retrieval (@k)


def hit_rate(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """1 if any relevant document is in the top k, else 0. 'Did we find anything useful?'"""
    return 1.0 if set(ranked[:k]) & relevant else 0.0


def recall(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Share of the relevant documents found in the top k. 'Did we find everything that matters?'"""
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 0.0


def precision(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Share of the top k that is relevant. 'How much noise reaches the prompt?' (k in the
    denominator even when fewer were returned: returning nothing is not precise.)"""
    return len(set(ranked[:k]) & relevant) / k if k else 0.0


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    """1 / position of the first relevant document (0 if none). Averaged over questions: MRR."""
    return next((1.0 / i for i, d in enumerate(ranked, 1) if d in relevant), 0.0)


def average_precision(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Mean of precision@i at each rank i (<= k) where a relevant document appears, divided by
    min(|relevant|, k). Averaged over questions: MAP. Rewards finding ALL of them, early."""
    if not relevant:
        return 0.0
    hits, total = 0, 0.0
    for i, d in enumerate(ranked[:k], 1):
        if d in relevant:
            hits += 1
            total += hits / i
    return total / min(len(relevant), k)


def ndcg(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Discounted cumulative gain over the ideal: relevant documents count more the higher."""
    dcg = sum(1 / math.log2(i + 1) for i, d in enumerate(ranked[:k], 1) if d in relevant)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def retrieval_scores(ranked: Sequence[str], relevant: set[str], k: int) -> dict[str, float]:
    return {"hit_rate": hit_rate(ranked, relevant, k), "recall": recall(ranked, relevant, k),
            "precision": precision(ranked, relevant, k), "mrr": reciprocal_rank(ranked, relevant),
            "map": average_precision(ranked, relevant, k), "ndcg": ndcg(ranked, relevant, k)}  # fmt: skip


# ---------------------------------------------------------------------- answers


def _claims(answer: str) -> list[str]:
    return [s for s in sentences(_CITE.sub("", answer)) if content_words(s)]


def supported(claim: str, context: str, min_support: float = 0.5) -> bool:
    """A claim is supported when most of its content words, and ALL its numbers, are in the context."""
    words = content_words(claim)
    src = set(content_words(context))
    share = sum(w in src for w in words) / (len(words) or 1)
    return share >= min_support and all(
        n in set(_NUM.findall(context)) for n in _NUM.findall(claim)
    )


def faithfulness(answer: str, contexts: Sequence[str], min_support: float = 0.5) -> float | None:
    """Share of the answer's claims (sentences) supported by the context: Ragas' faithfulness,
    lexically. None when there is nothing to check (an abstention, an empty answer)."""
    claims = _claims(answer)
    if not claims:
        return None
    ctx = "\n".join(contexts)
    return sum(supported(c, ctx, min_support) for c in claims) / len(claims)


def answer_relevance(question: str, answer: str) -> float | None:
    """Does the answer address the question? Share of the question's content words the answer
    uses (a lexical stand-in for Ragas' "generate questions from the answer and compare")."""
    q = set(content_words(question))
    if not q or not content_words(_CITE.sub("", answer)):
        return None
    return len(q & set(content_words(answer))) / len(q)


def context_precision(context_docs: Sequence[str], relevant: set[str]) -> float | None:
    """Are the relevant chunks ranked high in the context? Mean of precision@i over the positions
    holding a relevant document (Ragas' context precision, with labels instead of a judge)."""
    if not context_docs or not relevant:
        return None
    hits, total = 0, 0.0
    for i, d in enumerate(context_docs, 1):
        if d in relevant:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0


def context_recall(reference: str | None, contexts: Sequence[str], context_docs: Sequence[str] = (),
                   relevant: set[str] | None = None) -> float | None:  # fmt: skip
    """Could the answer be written from this context? With a reference answer: the share of its
    claims the context supports (Ragas). Without one: the share of relevant documents present."""
    if reference:
        claims = _claims(reference)
        if not claims:
            return None
        ctx = "\n".join(contexts)
        return sum(supported(c, ctx) for c in claims) / len(claims)
    if relevant:
        return len(set(context_docs) & relevant) / len(relevant)
    return None


def correctness(answer: str, reference: str | None) -> float | None:
    """Token F1 between the answer's and the reference's content words (SQuAD-style), with every
    number of the reference required: "18 weeks" for a reference of "16 weeks" scores 0."""
    if not reference:
        return None
    a, r = Counter(content_words(_CITE.sub("", answer))), Counter(content_words(reference))
    if not a or not r:
        return 0.0
    if any(n not in _NUM.findall(answer) for n in _NUM.findall(reference)):
        return 0.0
    common = sum((a & r).values())
    if not common:
        return 0.0
    p, rc = common / sum(a.values()), common / sum(r.values())
    return 2 * p * rc / (p + rc)


def citation_precision(cited: set[str], relevant: set[str]) -> float | None:
    """Share of the cited documents that are relevant (cited the right thing)."""
    return len(cited & relevant) / len(cited) if cited and relevant else None


def citation_recall(cited: set[str], relevant: set[str]) -> float | None:
    """Share of the relevant documents the answer cites (cited everything it should)."""
    return len(cited & relevant) / len(relevant) if relevant else None


def abstention_correct(abstained: bool, answerable: bool) -> float:
    """1 when the answer abstained exactly when it should (no relevant document = should abstain)."""
    return 1.0 if abstained != answerable else 0.0


def mean(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


__all__ = ["abstention_correct", "answer_relevance", "average_precision", "citation_precision",
           "citation_recall", "context_precision", "context_recall", "correctness", "faithfulness",
           "hit_rate", "mean", "ndcg", "precision", "recall", "reciprocal_rank", "retrieval_scores",
           "supported"]  # fmt: skip
