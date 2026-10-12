"""rag-api and the prompt registry: what each environment runs, and how that's made visible."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_api.main import check_prompts, prompt_info
from rag_common.prompts import PromptError, Registry

# The REAL registry, as shipped (the same path as conftest.PROMPTS)
PROMPTS = Path(__file__).resolve().parents[3] / "prompts"


def test_prompt_info_metric_shows_what_production_runs() -> None:
    obs = prompt_info(Registry.load(PROMPTS), "production")
    series = {(o.attributes or {})["prompt"]: dict(o.attributes or {}) for o in obs}
    assert {n: s["version"] for n, s in series.items()} == {
        "eval-judge": 1,  # Step 26: the evaluation judge is a registered prompt too
        "query-instruction": 1,
        "rag-answer": 1,
    }
    assert all(o.value == 1 for o in obs)  # an "info" metric: the facts are in the labels
    assert len(str(series["rag-answer"]["sha"])) == 12


def test_staging_runs_the_candidate() -> None:
    obs = prompt_info(Registry.load(PROMPTS), "staging")
    assert {(o.attributes or {})["prompt"]: (o.attributes or {})["version"] for o in obs} == {
        "eval-judge": 1,
        "query-instruction": 1,
        "rag-answer": 2,
    }


def test_start_up_refuses_a_label_without_the_required_prompts() -> None:
    registry = Registry.load(PROMPTS)
    check_prompts(registry, "production")  # fine
    with pytest.raises(
        PromptError, match=r"no 'canary' version of required prompt\(s\) \['query-instruction'\]"
    ):
        check_prompts(registry, "canary")
