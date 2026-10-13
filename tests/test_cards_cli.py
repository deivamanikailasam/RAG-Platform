"""The cards command line: lint exit codes, generated docs staying in step, impact questions."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cards_cli", ROOT / "scripts/cards.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cards_cli"] = module
    spec.loader.exec_module(module)
    return module


cli = _load()


# Only the files the catalogue reads: never the model-serving virtualenv (Step 7), if present.
SKIP = shutil.ignore_patterns(".venv", "__pycache__")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for rel in ("cards", "prompts", "infra/model-serving", "infra/config/litellm", "docs/cards"):
        shutil.copytree(ROOT / rel, tmp_path / rel, ignore=SKIP)
    # Pin stand-in revisions, as on a Mac where Steps 7-8 were done (this repo ships placeholders).
    inv = tmp_path / "infra/model-serving/models.yaml"
    data = yaml.safe_load(inv.read_text())
    for n, m in enumerate(data["models"]):
        m["revision"] = f"{n + 1:x}" * 40
    inv.write_text(yaml.safe_dump(data, sort_keys=False))
    return tmp_path


def run(root: Path, *args: str) -> int:
    return int(cli.main(["--root", str(root), *args]))


def test_committed_docs_are_up_to_date() -> None:
    """CI runs this: someone changed a card but forgot `just cards docs`."""
    assert run(ROOT, "docs", "--check") == 0


def test_lint_exit_codes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "lint", "--today", "2026-10-12") == 0  # warnings only
    assert run(repo, "lint", "--today", "2026-10-12", "--strict") == 1  # weekly job: warnings fail
    assert "0 errors, 4 warnings (strict: warnings fail too)" in capsys.readouterr().out
    (repo / "cards/models/reranker.yaml").unlink()
    assert run(repo, "lint", "--today", "2026-10-12") == 1
    assert (
        "gateway:reranker: served by the gateway, but has no model card" in capsys.readouterr().out
    )


def test_docs_follow_the_cards(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    card = repo / "cards/models/reranker.yaml"
    card.write_text(card.read_text().replace("keep k small", "keep k at 50 or fewer"))
    assert run(repo, "docs", "--check") == 1
    assert "model-reranker.md" in capsys.readouterr().out
    assert run(repo, "docs") == 0
    assert "keep k at 50 or fewer" in (repo / "docs/cards/model-reranker.md").read_text()
    (repo / "cards/datasets/rag-answer-golden.yaml").unlink()  # a removed card loses its page
    assert run(repo, "docs") == 0
    assert not (repo / "docs/cards/dataset-rag-answer-golden.md").exists()


def test_impact_and_lineage(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "impact", "model:qwen-quality") == 0
    assert "- prompt:rag-answer (runs on)" in capsys.readouterr().out
    assert run(repo, "impact", "model:gpt-9") == 1
    assert "unknown: model:gpt-9" in capsys.readouterr().err
    assert run(repo, "lineage", "dataset:company-chunks") == 0
    assert capsys.readouterr().out.splitlines()[1:] == [
        "  - dataset:company-documents", "  - model:embedder"]  # fmt: skip
