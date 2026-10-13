"""Similarity metrics and the vector index settings every vector store shares (extension 01).

How "close" two vectors are can be measured four ways. Which one is right is decided by the
EMBEDDING MODEL, not by taste: use the metric the model was trained for (its model card says).

    cosine  the angle between them, ignoring length. The safe default; most text models.
    dot     inner product: angle AND length. For models trained for it (e.g. some e5/GTE variants
            or "maximum inner product" retrieval); equal to cosine when vectors are normalised.
    l2      straight-line (Euclidean) distance. Some image and older models.
    l1      Manhattan distance (sum of absolute differences). Rare; supported by pgvector
            (>= 0.7) and Qdrant; OpenSearch only with the nmslib engine (2.x).

Every store reports a score where HIGHER = MORE SIMILAR, whatever the metric:
    cosine -> cosine similarity (-1..1)    dot -> the inner product (unbounded)
    l2, l1 -> 1 / (1 + distance) (0..1]
so thresholds, fusion and evaluation behave the same on every store. A score is only comparable
with scores of the same metric (and model): never set one threshold for two metrics.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Metric = Literal["cosine", "dot", "l2", "l1"]
IndexType = Literal["hnsw", "flat", "ivfflat"]
METRICS: tuple[Metric, ...] = ("cosine", "dot", "l2", "l1")


class ContractError(RuntimeError):
    """The index was built under another contract (metric, dimensions) than the profile asks for."""


def similarity(metric: str, a: Sequence[float], b: Sequence[float]) -> float:
    """Exact similarity of two vectors, higher = more similar (the in-memory store's ranking)."""
    if metric == "cosine":
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0
    if metric == "dot":
        return float(sum(x * y for x, y in zip(a, b, strict=True)))
    if metric == "l2":
        return from_distance(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True))))
    if metric == "l1":
        return from_distance(sum(abs(x - y) for x, y in zip(a, b, strict=True)))
    raise ValueError(f"unknown metric {metric!r} (use one of: {', '.join(METRICS)})")


def from_distance(distance: float) -> float:
    """A distance (0 = identical) as a similarity in (0, 1]: 1 / (1 + d)."""
    return 1.0 / (1.0 + max(0.0, float(distance)))


def check_contract(store: str, want: dict[str, object], have: dict[str, object]) -> None:
    """Compare what the profile asks for with what the index was built with; raise on a mismatch."""
    wrong = {
        k: (have[k], v)
        for k, v in want.items()
        if k in have and have[k] is not None and have[k] != v
    }
    if wrong:
        detail = "; ".join(
            f"{k}: index has {h!r}, profile asks for {w!r}" for k, (h, w) in wrong.items()
        )
        raise ContractError(
            f"{store}: the index was built under another embedding contract ({detail}). "
            "Change the profile to match, or re-index into a new collection (rag reindex)."
        )


class VectorIndexParams(BaseModel):
    """The settings every vector store shares. Not every store supports every combination; each
    store's validator says which it doesn't (at `rag config validate`, before anything runs)."""

    model_config = ConfigDict(extra="forbid")
    metric: Metric = "cosine"  # what the embedding model was trained for (see the module doc)
    index_type: IndexType = "hnsw"  # hnsw = approximate, fast; flat = exact (brute force), slow
    hnsw_m: int = Field(16, ge=2, le=128)  # links per node: more = better recall, more memory
    ef_construction: int = Field(
        64, ge=4, le=4096
    )  # build-time candidate list: better graph, slower build
    ef_search: int = Field(
        80, ge=1, le=4096
    )  # query-time candidate list: recall/speed knob per query

    @model_validator(mode="after")
    def _ef(self) -> VectorIndexParams:
        if self.ef_construction < 2 * self.hnsw_m:
            raise ValueError(
                "ef_construction must be at least 2 x hnsw_m (pgvector, Qdrant, OpenSearch all assume it)"
            )
        return self


__all__ = ["METRICS", "ContractError", "IndexType", "Metric", "VectorIndexParams", "check_contract",
           "from_distance", "similarity"]  # fmt: skip
