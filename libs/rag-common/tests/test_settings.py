from pathlib import Path

import pytest

from rag_common.settings import Settings


def test_secret_is_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_TOKEN", "super-secret-value")
    settings = Settings()
    assert "super-secret-value" not in repr(settings)  # shows SecretStr('**********')
    assert settings.demo_token.get_secret_value() == "super-secret-value"


def test_secret_is_read_from_a_secret_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Containers get /run/secrets/demo_token; here a temporary folder plays that role.
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    (tmp_path / "demo_token").write_text("from-a-file")
    settings = Settings(_secrets_dir=tmp_path)
    assert settings.demo_token.get_secret_value() == "from-a-file"
    assert "from-a-file" not in repr(settings)
