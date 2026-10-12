"""The prompt workflow end to end: new version -> release -> promote -> roll back."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prompts_cli", ROOT / "scripts/prompts.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prompts_cli"] = module
    spec.loader.exec_module(module)
    return module


cli = _load()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A copy of the real registry to play with."""
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    return tmp_path / "prompts"


def run(root: Path, *args: str) -> int:
    return int(cli.main(["--root", str(root), *args]))


def test_new_version_release_promote_and_roll_back(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old_lock = root / "old.lock.json"
    shutil.copy(root / "prompts.lock.json", old_lock)

    assert run(root, "new", "rag-answer") == 0  # v3, copied from v2
    v3 = root / "rag-answer/v3.yaml"
    assert "version: 3" in v3.read_text()
    v3.write_text(v3.read_text().replace("Be concise.", "Be concise and friendly.")
                  .replace("changelog: TODO describe what changed and why", "changelog: Friendlier tone."))  # fmt: skip
    assert run(root, "lint") == 1  # not released yet
    assert "rag-answer@3 is not released yet" in capsys.readouterr().err

    assert run(root, "lock") == 0
    assert "released: rag-answer@3" in capsys.readouterr().out
    assert run(root, "lint", "--against", str(old_lock)) == 0  # the lock only grew

    assert run(root, "promote", "rag-answer", "3", "staging") == 0
    assert "rag-answer.staging: 2 -> 3" in capsys.readouterr().out
    assert (
        run(root, "promote", "rag-answer", "1", "staging") == 0
    )  # roll back = point the label back
    assert (
        run(root, "promote", "rag-answer", "9", "staging") == 1
    )  # can't promote what doesn't exist
    assert "rag-answer@9 does not exist" in capsys.readouterr().err
    assert run(root, "list") == 0
    assert "labels: production=1, staging=1" in capsys.readouterr().out


def test_editing_a_released_version_is_caught_three_ways(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old_lock = root / "old.lock.json"
    shutil.copy(root / "prompts.lock.json", old_lock)
    v1 = root / "rag-answer/v1.yaml"
    v1.write_text(v1.read_text().replace("Be concise.", "Be verbose."))
    assert run(root, "lint") == 1  # 1. the registry refuses to load it
    assert "rag-answer@1 changed after release" in capsys.readouterr().err
    assert run(root, "lock") == 1  # 2. it can't be re-released
    assert "has been edited" in capsys.readouterr().err
    # 3. Someone "fixes" the lock by hand with the new hash: locally everything looks fine…
    lock = json.loads((root / "prompts.lock.json").read_text())
    lock["rag-answer"]["1"] = hashlib.sha256(v1.read_bytes()).hexdigest()
    (root / "prompts.lock.json").write_text(json.dumps(lock))
    assert run(root, "lint") == 0
    # …but CI compares with the lock on main, where entries may only be added
    assert run(root, "lint", "--against", str(old_lock)) == 1
    assert "rag-answer@1 was released and can't be changed" in capsys.readouterr().err


def test_render_shows_exactly_what_the_model_would_get(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(root, "render", "rag-answer", "--label", "staging",
               "--var", 'context=<doc id="7">Office: 3 days a week.</doc>',
               "--var", "question=How many office days?") == 0  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert out["ref"] == "rag-answer@2"
    assert out["model"] == "qwen-quality"
    assert out["params"] == {"temperature": 0.2, "max_tokens": 800}
    assert [m["role"] for m in out["messages"]] == ["system", "user"]
    assert '<doc id="7">Office: 3 days a week.</doc>' in out["messages"][1]["content"]


def test_diff_between_versions(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(root, "diff", "rag-answer", "1", "2") == 0
    out = capsys.readouterr().out
    assert "+      After every claim, cite the document it came from as [doc <id>]" in out
