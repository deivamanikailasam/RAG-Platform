"""Credentials that change while the service runs (Step 28)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rag_common.secrets import CredentialsFile, CredentialsUnavailable, StaticCredentials


def write(path: Path, data: object) -> None:
    """Like OpenBao Agent: write a temporary file, then rename it over the old one."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def test_reads_the_pair(tmp_path: Path) -> None:
    f = tmp_path / "db.json"
    write(f, {"username": "v-approle-rag-api-abc", "password": "s3cret", "extra": 1})
    creds = CredentialsFile(f)
    assert creds() == ("v-approle-rag-api-abc", "s3cret")
    assert creds.changes == 1


def test_picks_up_a_new_pair_immediately(tmp_path: Path) -> None:
    f = tmp_path / "db.json"
    write(f, {"username": "user-1", "password": "pw-1"})
    creds = CredentialsFile(f)
    assert creds()[0] == "user-1"
    write(f, {"username": "user-2", "password": "pw-2"})  # same second, same size: inode differs
    assert creds() == ("user-2", "pw-2")
    assert creds() == ("user-2", "pw-2")
    assert creds.changes == 2


def test_unchanged_file_is_not_read_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "db.json"
    write(f, {"username": "u", "password": "p"})
    creds = CredentialsFile(f)
    creds()
    monkeypatch.setattr(Path, "read_text", lambda *_: pytest.fail("re-read an unchanged file"))
    assert creds() == ("u", "p")


@pytest.mark.parametrize(
    "content",
    ['{"username": "u", "password": "hunter2"', '{"username": "u"}', '["u", "hunter2"]',
     '{"username": "", "password": "hunter2"}', '{"username": "u", "password": 42}'],
)  # fmt: skip
def test_bad_files_fail_without_leaking_the_content(tmp_path: Path, content: str) -> None:
    f = tmp_path / "db.json"
    f.write_text(content)
    with pytest.raises(CredentialsUnavailable) as e:
        CredentialsFile(f)()
    assert "hunter2" not in str(e.value)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CredentialsUnavailable, match="No such file"):
        CredentialsFile(tmp_path / "nope.json")()


def test_static_credentials_never_show_the_password() -> None:
    creds = StaticCredentials("rag_app", "hunter2")
    assert creds() == ("rag_app", "hunter2")
    assert "hunter2" not in repr(creds)
