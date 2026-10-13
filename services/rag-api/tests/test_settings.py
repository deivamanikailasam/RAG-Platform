"""Where rag-api gets its database logins from (Step 28): OpenBao Agent's files, or fixed passwords."""

# Throwaway values: these tests are about WHERE settings come from.
# ruff: noqa: S106

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rag_api.settings import Settings
from rag_common.secrets import CredentialsFile, StaticCredentials

BASE = {"oidc_issuer": "i", "oidc_jwks_url": "j", "gateway_key": "g", "opa_token": "o"}


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("RAG_API_DB_PASSWORD", "RAG_API_AUDIT_DB_PASSWORD",
                "RAG_API_DB_CREDENTIALS_FILE", "RAG_API_AUDIT_DB_CREDENTIALS_FILE"):  # fmt: skip
        monkeypatch.delenv(var, raising=False)


def test_static_passwords_still_work() -> None:
    s = Settings(**BASE, db_password="a", audit_db_password="w", _secrets_dir=[])  # type: ignore[arg-type]
    assert isinstance(s.db_credentials(), StaticCredentials)
    assert s.db_credentials()() == ("rag_app", "a")
    assert s.audit_db_credentials()() == ("audit_writer", "w")


def test_openbao_files_win(tmp_path: Path) -> None:
    (tmp_path / "rag_db.json").write_text(json.dumps({"username": "v-1", "password": "p"}))
    s = Settings(**BASE, db_password="old", audit_db_password="old",  # type: ignore[arg-type]
                 db_credentials_file=tmp_path / "rag_db.json",
                 audit_db_credentials_file=tmp_path / "audit_db.json", _secrets_dir=[])  # fmt: skip
    assert isinstance(s.db_credentials(), CredentialsFile)
    assert s.db_credentials()() == ("v-1", "p")


def test_a_login_is_required() -> None:
    with pytest.raises(ValidationError, match="db_credentials_file"):
        Settings(**BASE, audit_db_password="w", _secrets_dir=[])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="audit_db_credentials_file"):
        Settings(**BASE, db_password="a", _secrets_dir=[])  # type: ignore[arg-type]


def test_agent_folder_overrides_docker_secrets(tmp_path: Path) -> None:
    """/run/bao comes after /run/secrets in secrets_dir: when both have a file, OpenBao's wins."""
    docker, bao = tmp_path / "secrets", tmp_path / "bao"
    docker.mkdir()
    bao.mkdir()
    (docker / "rag_api_gateway_key").write_text("from-sops")
    (bao / "rag_api_gateway_key").write_text("from-openbao")
    s = Settings(oidc_issuer="i", oidc_jwks_url="j", opa_token="o", db_password="a",  # type: ignore[arg-type,unused-ignore]
                 audit_db_password="w", _secrets_dir=[docker, bao])  # fmt: skip
    assert s.gateway_key.get_secret_value() == "from-openbao"
