"""`rag doctor` (Step 38): the platform meets its own standards; gaps are named with a fix."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rag_core import doctor
from rag_core.cli import main

ROOT = Path(__file__).resolve().parents[3]


def failed(results: list[doctor.Result]) -> set[str]:
    return {r.rule for r in results if not r.ok and r.level == "MUST"}


def test_the_platform_meets_every_must() -> None:
    results = doctor.run(ROOT)
    assert failed(results) == set()
    assert {r.rule for r in results} >= {
        "CFG-1",
        "CFG-5",
        "EVL-3",
        "EVL-4",
        "EVL-5",
        "CI-1",
        "CI-3",
        "GOV-4",
    }


def test_an_empty_folder_fails_and_says_what_to_do(tmp_path: Path) -> None:
    results = doctor.run(tmp_path)
    assert "CFG-1" in failed(results)
    assert "EVL-1" in failed(results)
    assert all(r.fix for r in results if not r.ok)


def test_missing_abstention_and_access_questions(tmp_path: Path) -> None:
    shutil.copy(ROOT / "rag.yaml", tmp_path / "rag.yaml")
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval/q.yaml").write_text(
        "version: 1\nquestions:\n  - {id: a, question: x, relevant: [a.md]}\n"
    )
    assert {"EVL-3", "EVL-4", "EVL-5", "CI-1"} <= failed(doctor.run(tmp_path))


def test_a_production_profile_with_stand_ins_fails(tmp_path: Path) -> None:
    (tmp_path / "rag.yaml").write_text(
        "version: 1\ninclude: {platform: rag-core:platform.yaml}\n"
        "profiles:\n  offline: {extends: platform/offline}\n  production: {extends: platform/offline}\n"
    )
    r = next(x for x in doctor.run(tmp_path) if x.rule == "CFG-5")
    assert not r.ok
    assert "keeps data in one process" in r.message or "stand-in" in r.message


def test_cli(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["doctor", str(ROOT)]) == 0
    assert "0 MUST failed" in capsys.readouterr().out
    assert main(["doctor", str(tmp_path)]) == 1
