"""Production readiness of a profile (Step 37)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_core import config, readiness
from rag_core.cli import main

ROOT = Path(__file__).resolve().parents[3]


def findings(profile: str) -> list[readiness.Finding]:
    return readiness.check(config.load(ROOT / "rag.yaml", profile, env={}).config)


def test_the_production_profile_is_ready() -> None:
    assert findings("production") == []


def test_offline_is_not_and_says_why() -> None:
    errors = {(f.slot, f.message.split(" ")[0]) for f in findings("offline") if f.level == "error"}
    assert ("vector_store", "'memory'") in errors
    assert ("embedder", "'hashing'") in errors
    assert ("llm", "'scripted'") in errors


@pytest.mark.parametrize(("change", "slot", "words"), [
    ({"guards": [{"use": "size"}]}, "guards", "missing 'injection'"),
    ({"pipeline": {"use": "standard", "uncited": "keep", "stream": "checked"}}, "pipeline", "cite nothing"),
    ({"llm": {"use": "gateway", "model": "m", "api_key": "sk-123"}}, "llm", "use api_key_file"),
    ({"vector_store": {"use": "pgvector", "dsn": "postgresql://rag:hunter2@db/rag"}}, "vector_store",
     "password in a URL"),
    ({"pii": {"use": "none"}}, "pii", "redaction"),
])  # fmt: skip
def test_each_rule(change: dict[str, object], slot: str, words: str) -> None:
    base = dict(config.load(ROOT / "rag.yaml", "production", env={}).config)
    found = readiness.check({**base, **change})
    assert any(f.slot == slot and words in f.message and f.level == "error" for f in found), found


def test_secret_references_are_fine() -> None:
    cfg = {"llm": {"use": "gateway", "api_key_file": "/run/bao/key", "password_env": "X"}}
    assert not [f for f in readiness.check(cfg) if "written into the file" in f.message]


def test_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["config", "readiness", "--file", str(ROOT / "rag.yaml"), "--profile", "production"])
        == 0
    )
    assert (
        main(["config", "readiness", "--file", str(ROOT / "rag.yaml"), "--profile", "offline"]) == 1
    )
    assert "7 error(s)" in capsys.readouterr().out
