"""Results land in the model card, comments intact, and the card checker sees them."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from rag_common.cards import Catalogue
from rag_evals.record import record_results

from .conftest import REPO


def test_results_are_written_into_the_card(tmp_path: Path) -> None:
    for rel in ("cards", "prompts", "infra/model-serving", "infra/config/litellm"):
        shutil.copytree(REPO / rel, tmp_path / rel, ignore=shutil.ignore_patterns(".venv"))
    card = tmp_path / "cards/models/embedder.yaml"
    before = card.read_text()
    record_results(
        card, {"recall@5": 0.9, "mrr": 0.8333333}, "retrieval-golden@1", dt.date(2026, 10, 12)
    )
    record_results(
        card, {"recall@5": 1.0}, "retrieval-golden@2", dt.date(2026, 10, 13)
    )  # newer: replaces
    text = card.read_text()
    assert "# another embedder = another vector space: never fall back" in text  # comments survive
    assert "- {metric: mrr, value: 0.8333, dataset: retrieval-golden@1, date: 2026-10-12}" in text
    assert "- {metric: recall@5, value: 1.0, dataset: retrieval-golden@2, date: 2026-10-13}" in text
    assert "value: 0.9," not in text
    assert "&id" not in text  # no YAML anchors in a reviewed file
    assert text.startswith(before.split("evaluation")[0][:200])  # the rest is untouched

    cat = Catalogue.load(tmp_path / "cards", inventory=tmp_path / "infra/model-serving/models.yaml",
                         gateway=tmp_path / "infra/config/litellm/config.yaml", prompts=tmp_path / "prompts")  # fmt: skip
    messages = {(f.where, f.message) for f in cat.check(dt.date(2026, 10, 13))}
    assert ("model:embedder", "no evaluation results yet (Step 26 adds them)") not in messages
    assert ("model:reranker", "no evaluation results yet (Step 26 adds them)") in messages
