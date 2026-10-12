"""The rest of the service, beyond the token attacks in test_auth.py: 503 vs 401, settings from
secret files, request validation, and the search backend's fail-closed and per-user behaviour."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from rag_api import search as search_module
from rag_api.main import app, get_search, get_verifier
from rag_api.search import INSTRUCTION, PgSearch
from rag_api.settings import Settings
from rag_common.auth import KeyServiceUnavailable, Principal


class DownKeys:
    """Keycloak is unreachable and no key is cached."""

    def verify(self, token: str) -> Principal:
        raise KeyServiceUnavailable("connection refused")


class NeverSearch:
    def search(self, query: str, *, groups: frozenset[str], k: int, user: str) -> list[Any]:
        raise AssertionError("the backend must not be reached")


@pytest.fixture
def down_client() -> Iterator[TestClient]:
    app.dependency_overrides[get_verifier] = lambda: DownKeys()
    app.dependency_overrides[get_search] = lambda: NeverSearch()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_identity_provider_down_is_503_not_401(down_client: TestClient) -> None:
    r = down_client.get("/v1/me", headers={"Authorization": "Bearer x.y.z"})
    assert r.status_code == 503  # our problem, not the caller's: they must not throw the token away
    assert "WWW-Authenticate" not in r.headers


def test_bad_token_challenge_names_invalid_token(down_client: TestClient) -> None:
    # A wrong scheme (Basic instead of Bearer) never reaches the verifier: plain 401 challenge.
    r = down_client.get("/v1/me", headers={"Authorization": "Basic YWxpY2U6c2VjcmV0"})
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Bearer realm="rag-api"'


def test_openapi_lists_the_four_endpoints() -> None:
    paths = set(TestClient(app).get("/openapi.json").json()["paths"])
    assert paths == {"/healthz", "/v1/me", "/v1/search", "/v1/admin/ping"}


def test_search_request_has_no_groups_field() -> None:
    schema = TestClient(app).get("/openapi.json").json()["components"]["schemas"]["SearchRequest"]
    assert set(schema["properties"]) == {"query", "k"}  # the caller can't even ask for groups


# ------------------------------------------------------------------ settings


def test_settings_read_env_and_secret_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Compose mounts secrets as /run/secrets/<name>; the names match the env prefix + field name.
    (tmp_path / "rag_api_gateway_key").write_text("sk-virtual-key")
    (tmp_path / "rag_api_db_password").write_text("app-password")
    monkeypatch.setenv("RAG_API_OIDC_ISSUER", "http://localhost:8180/realms/rag")
    monkeypatch.setenv(
        "RAG_API_OIDC_JWKS_URL", "http://keycloak:8080/realms/rag/protocol/openid-connect/certs"
    )
    s = Settings(_secrets_dir=tmp_path)
    assert s.oidc_audience == "rag-api"
    assert s.allowed_clients == ["rag-web", "rag-cli", "ingestion-worker"]
    assert s.gateway_key.get_secret_value() == "sk-virtual-key"
    assert s.db_password.get_secret_value() == "app-password"
    assert "sk-virtual-key" not in repr(s)  # secrets never print


# ------------------------------------------------------------------ the Postgres search backend


def _settings(secrets_dir: Path) -> Settings:
    return Settings(
        _secrets_dir=secrets_dir,  # an empty folder: every value is given here
        oidc_issuer="http://localhost:8180/realms/rag",
        oidc_jwks_url="http://keycloak:8080/realms/rag/protocol/openid-connect/certs",
        gateway_key=SecretStr("sk-test"),
        db_password=SecretStr("pw"),
    )


def test_no_groups_returns_nothing_without_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **kw: Any) -> None:
        raise AssertionError("no database call expected")

    monkeypatch.setattr("rag_api.search.psycopg.connect", boom)
    backend = PgSearch(_settings(tmp_path))
    assert backend.search("anything", groups=frozenset(), k=5, user="sub-1") == []


def test_search_tags_the_gateway_call_with_the_user_and_filters_by_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class FakeEmbeddings:
        def create(self, **kw: Any) -> Any:
            seen["embed"] = kw
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.5] * 4)])

    class FakeConn:
        def __enter__(self) -> FakeConn:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: dict[str, Any]) -> Any:
            seen["sql"], seen["params"] = sql, params
            return SimpleNamespace(fetchall=lambda: [("Remote work policy", "internal", 0.71)])

    def fake_connect(dsn: str) -> FakeConn:
        seen["dsn"] = dsn
        return FakeConn()

    monkeypatch.setattr("rag_api.search.psycopg.connect", fake_connect)
    monkeypatch.setattr(search_module, "register_vector", lambda conn: None)
    backend = PgSearch(_settings(tmp_path))
    monkeypatch.setattr(backend, "_gw", SimpleNamespace(embeddings=FakeEmbeddings()))

    hits = backend.search("hybrid work", groups=frozenset({"hr", "all-staff"}), k=3, user="sub-1")

    assert [h.title for h in hits] == ["Remote work policy"]
    assert seen["embed"]["user"] == "sub-1"  # cost and logs per person at the gateway
    assert seen["embed"]["model"] == "embedder"
    assert seen["embed"]["input"] == [INSTRUCTION + "hybrid work"]
    assert seen["params"]["groups"] == ["all-staff", "hr"]
    assert seen["params"]["k"] == 3
    assert "d.acl_groups && %(groups)s" in seen["sql"]
    assert "d.deleted_at IS NULL" in seen["sql"]
    assert "user=rag_app" in seen["dsn"]  # least-privilege role from Step 11, never the superuser
