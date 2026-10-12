"""Cards and lineage: every rule, against a copy of the real catalogue with one thing broken."""

from __future__ import annotations

import datetime as dt
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_common.cards import CardError, Catalogue, documents

REPO = Path(__file__).resolve().parents[3]
TODAY = dt.date(2026, 10, 12)
NO_EVAL = "no evaluation results yet (Step 26 adds them)"
PLACEHOLDER = (
    "models.yaml revision is still a placeholder: pin the 40-character SHA "
    "from the snapshots folder (Steps 7-8)"
)


def pin_revisions(inventory: Path) -> None:
    """Stand-in SHAs, as on a Mac where Steps 7-8 were done (this repo ships placeholders)."""
    data = yaml.safe_load(inventory.read_text())
    for n, m in enumerate(data["models"]):
        if str(m.get("revision", "")).startswith("<"):
            m["revision"] = f"{n + 1:x}" * 40
    inventory.write_text(yaml.safe_dump(data, sort_keys=False))


# Only the files the catalogue reads: never the model-serving virtualenv (Step 7), if present.
SKIP = shutil.ignore_patterns(".venv", "__pycache__")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A private copy of everything the catalogue reads, with revisions pinned."""
    for rel in ("cards", "prompts", "infra/model-serving", "infra/config/litellm"):
        shutil.copytree(REPO / rel, tmp_path / rel, ignore=SKIP)
    pin_revisions(tmp_path / "infra/model-serving/models.yaml")
    return tmp_path


def load(root: Path) -> Catalogue:
    return Catalogue.load(root / "cards", inventory=root / "infra/model-serving/models.yaml",
                          gateway=root / "infra/config/litellm/config.yaml",
                          prompts=root / "prompts")  # fmt: skip


def edit(path: Path, change: Callable[[Any], None]) -> None:
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def errors(root: Path, today: dt.date = TODAY) -> list[str]:
    return [f"{f.where}: {f.message}" for f in load(root).check(today) if f.level == "error"]


def warnings(root: Path, today: dt.date = TODAY) -> list[str]:
    return [f"{f.where}: {f.message}" for f in load(root).check(today) if f.level == "warning"]


# ---- the real catalogue ------------------------------------------------------------------


def test_the_real_catalogue_passes() -> None:
    cat = load(REPO)
    assert len(cat.cards) == 10
    findings = cat.check(TODAY)
    assert [f for f in findings if f.level == "error"] == []
    # Placeholder revisions are allowed as warnings until the models are downloaded (Steps 7-8).
    assert NO_EVAL in {f.message for f in findings}
    assert {f.message for f in findings} <= {NO_EVAL, PLACEHOLDER}


def test_pinned_catalogue_only_lacks_evaluations(repo: Path) -> None:
    """With revisions pinned (as on the Mac), only the "no evaluation yet" warnings remain."""
    assert {f.message for f in load(repo).check(TODAY)} == {NO_EVAL}


def test_impact_of_changing_the_embedder() -> None:
    affected = {n: how for _, n, how in load(REPO).downstream("model:embedder")}
    assert affected == {
        "dataset:company-chunks": "input",  # every vector must be recomputed
        "prompt:query-instruction": "runs on",
        "system:rag-api": "input",
        "dataset:audit-log": "input",
        "dataset:llm-traces": "input",
    }


def test_fallbacks_are_part_of_the_lineage() -> None:
    """rag-answer is written for qwen-quality, but the gateway may send it to qwen-fast."""
    cat = load(REPO)
    assert ("model:qwen-fast", "prompt:rag-answer", "fallback") in cat.edges()
    assert "-.->|fallback|" in cat.mermaid()


def test_upstream_of_the_audit_log() -> None:
    assert load(REPO).upstream("dataset:audit-log") == [
        "dataset:company-chunks", "dataset:company-documents", "model:embedder",
        "prompt:query-instruction", "system:rag-api",
    ]  # fmt: skip


def test_generated_docs() -> None:
    docs = documents(load(REPO))
    assert set(docs) >= {"README.md", "model-embedder.md", "dataset-company-documents.md"}
    page = docs["model-embedder.md"]
    assert "do not edit" in page
    assert "| **Fallback allowed** | no |" in page
    assert "- dataset:company-chunks (input)" in page
    assert "```mermaid\nflowchart LR" in docs["README.md"]


# ---- format traps --------------------------------------------------------------------------


def test_yaml_on_trap_is_caught(repo: Path) -> None:
    """In YAML 1.1 a bare `on` is the boolean true: `{by: x, on: 2026-01-01}` silently breaks."""
    card = repo / "cards/models/reranker.yaml"
    card.write_text(
        card.read_text().replace("{by: you, date: 2026-10-12", "{by: you, on: 2026-10-12")
    )
    with pytest.raises(CardError, match="date"):
        load(repo)


def test_id_must_match_file_name(repo: Path) -> None:
    shutil.move(repo / "cards/models/reranker.yaml", repo / "cards/models/re-ranker.yaml")
    with pytest.raises(CardError, match="must match the file name"):
        load(repo)


def test_unknown_fields_are_refused(repo: Path) -> None:
    edit(repo / "cards/models/reranker.yaml", lambda d: d.update(licence_ok=True))
    with pytest.raises(CardError, match="Extra inputs"):
        load(repo)


# ---- rules ---------------------------------------------------------------------------------


def test_inputs_must_exist(repo: Path) -> None:
    edit(repo / "cards/datasets/company-chunks.yaml", lambda d: d["inputs"].append("model:bge-m3"))
    assert "dataset:company-chunks: input 'model:bge-m3' has no card" in errors(repo)


def test_approved_needs_a_recorded_approval(repo: Path) -> None:
    edit(repo / "cards/systems/rag-api.yaml", lambda d: d.update(approvals=[]))
    assert "system:rag-api: approved, but no approval is recorded" in errors(repo)


def test_overdue_review_is_a_warning(repo: Path) -> None:
    assert (
        "dataset:company-documents: review overdue since 2027-01-10 (last 2026-10-12)"
        in warnings(repo, dt.date(2027, 2, 1))
    )


def test_licences(repo: Path) -> None:
    path = repo / "cards/models/reranker.yaml"
    edit(path, lambda d: d["licence"].update(id="cc-by-nc-4.0"))
    assert "model:reranker: licence 'cc-by-nc-4.0' is not on the allowed list" in errors(repo)
    edit(path, lambda d: d["licence"].update(id="apache-2.0", verified_on=None))
    assert "model:reranker: approved, but nobody has verified the licence" in errors(repo)
    edit(path, lambda d: d["licence"].update(verified_on=dt.date(2025, 1, 1)))
    assert "model:reranker: licence last verified 2025-01-01: re-check it" in warnings(repo)


def test_inventory_must_pin_a_revision(repo: Path) -> None:
    inv = repo / "infra/model-serving/models.yaml"
    edit(inv, lambda d: d["models"][3].update(revision="main"))  # a branch moves: not pinned
    assert "model:reranker: models.yaml has no pinned 40-character revision" in errors(repo)


def test_placeholder_revision_is_a_warning(repo: Path) -> None:
    """The unfilled template value from Steps 7-8 warns (and fails the weekly strict run)."""
    inv = repo / "infra/model-serving/models.yaml"
    edit(inv, lambda d: d["models"][3].update(revision="<40-char SHA>"))
    assert f"model:reranker: {PLACEHOLDER}" in warnings(repo)
    assert errors(repo) == []


def test_every_served_model_has_a_card(repo: Path) -> None:
    (repo / "cards/models/reranker.yaml").unlink()
    found = errors(repo)
    assert "gateway:reranker: served by the gateway, but has no model card" in found
    assert "models.yaml:reranker: in the inventory, but has no model card" in found


def test_retired_model_still_served(repo: Path) -> None:
    edit(repo / "cards/models/reranker.yaml", lambda d: d.update(status="retired"))
    assert "gateway:reranker: served, but its card says 'retired'" in errors(repo)


def test_embedder_must_never_fall_back(repo: Path) -> None:
    edit(repo / "infra/config/litellm/config.yaml",
         lambda d: d["litellm_settings"]["fallbacks"].append({"embedder": ["qwen-fast"]}))  # fmt: skip
    assert ("model:embedder: must never fall back, but the gateway sends it to ['qwen-fast']"
            in errors(repo))  # fmt: skip


def test_fallback_target_must_be_approved(repo: Path) -> None:
    edit(repo / "cards/models/qwen-fast.yaml", lambda d: d.update(status="candidate"))
    found = errors(repo)
    assert "gateway:qwen-quality: falls back to qwen-fast, which is not approved" in found


def test_prompts_need_an_approved_model(repo: Path) -> None:
    edit(repo / "cards/models/qwen-quality.yaml", lambda d: d.update(status="candidate"))
    assert ("prompt:rag-answer@1: 'production' runs it on qwen-quality, which has no approved "
            "model card") in errors(repo)  # fmt: skip


def test_query_instruction_must_match_the_embedding_contract(repo: Path) -> None:
    inv = repo / "infra/model-serving/models.yaml"
    edit(inv, lambda d: d["models"][2]["contract"].update(query_instruction="Query:"))
    assert any("text differs from the embedder's contract" in e for e in errors(repo))


def test_personal_data_needs_a_legal_basis(repo: Path) -> None:
    edit(repo / "cards/datasets/llm-traces.yaml", lambda d: d.update(legal_basis=""))
    assert "dataset:llm-traces: holds personal data: state what, and the legal basis" in errors(
        repo
    )


def test_evaluation_sets_hold_no_personal_data(repo: Path) -> None:
    edit(repo / "cards/datasets/rag-answer-golden.yaml",
         lambda d: d.update(personal_data=True, personal_data_notes="real questions",
                            legal_basis="consent"))  # fmt: skip
    assert any("evaluation sets must not contain personal data" in e for e in errors(repo))


def test_derived_data_names_its_sources(repo: Path) -> None:
    edit(repo / "cards/datasets/company-chunks.yaml", lambda d: d.update(inputs=[]))
    assert ("dataset:company-chunks: a derived dataset must name what it was derived from"
            in errors(repo))  # fmt: skip


def test_dependency_on_a_deprecated_card_warns(repo: Path) -> None:
    edit(repo / "cards/datasets/company-chunks.yaml", lambda d: d.update(status="deprecated"))
    assert "system:rag-api: depends on deprecated dataset:company-chunks" in warnings(repo)


def test_cycles_are_refused(repo: Path) -> None:
    edit(
        repo / "cards/datasets/company-documents.yaml",
        lambda d: d.update(inputs=["system:rag-api"]),
    )
    assert any(e.startswith("lineage: cycle: ") for e in errors(repo))
