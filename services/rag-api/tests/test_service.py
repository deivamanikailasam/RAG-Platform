"""The rest of the service, beyond the token attacks in test_auth.py and the policy wiring in
test_policy.py: 503 vs 401, settings from secret files, request validation, the search backend's
fail-closed and per-user behaviour, and the OPA client treating every odd answer as "no"."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from rag_api import search as search_module
from rag_api.main import app, get_search, get_verifier
from rag_api.policy import DocumentRef, OpaClient, PolicyUnavailable
from rag_api.search import PgSearch
from rag_api.settings import Settings
from rag_common.auth import KeyServiceUnavailable, Principal
from rag_common.prompts import Registry

# The REAL registry, as shipped (the same path as conftest.PROMPTS)
PROMPTS = Path(__file__).resolve().parents[3] / "prompts"

# The query instruction now lives in the prompt registry (Step 24); the text must not have changed.
INSTRUCTION = (
    "Instruct: Given an employee question, retrieve passages from company "
    "documents that answer it\nQuery:"
)


class DownKeys:
    """Keycloak is unreachable and no key is cached."""

    def verify(self, token: str) -> Principal:
        raise KeyServiceUnavailable("connection refused")


class NeverSearch:
    def search(
        self,
        query: str,
        *,
        groups: frozenset[str],
        classifications: frozenset[str],
        k: int,
        user: str,
    ) -> list[Any]:
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


def test_openapi_lists_the_endpoints() -> None:
    paths = set(TestClient(app).get("/openapi.json").json()["paths"])
    assert paths == {
        "/healthz",
        "/v1/me",
        "/v1/search",
        "/v1/admin/ping",
        "/v1/answer",
        "/v1/feedback",
    }  # Step 33 added /v1/answer and /v1/feedback


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
    (tmp_path / "rag_api_opa_token").write_text("opa-token")
    (tmp_path / "rag_api_audit_db_password").write_text("audit-writer")  # Step 23
    monkeypatch.setenv("RAG_API_OIDC_ISSUER", "http://localhost:8180/realms/rag")
    monkeypatch.setenv(
        "RAG_API_OIDC_JWKS_URL", "http://keycloak:8080/realms/rag/protocol/openid-connect/certs"
    )
    s = Settings(_secrets_dir=tmp_path)
    assert s.oidc_audience == "rag-api"
    assert s.allowed_clients == ["rag-web", "rag-cli", "ingestion-worker"]
    assert s.gateway_key.get_secret_value() == "sk-virtual-key"
    assert s.db_password is not None
    assert s.db_password.get_secret_value() == "app-password"
    assert s.opa_url == "http://opa:8181"  # Step 18 default: the Compose service name
    assert s.opa_token.get_secret_value() == "opa-token"
    # Step 23: the audit database, written as audit_writer
    assert (s.audit_db_host, s.audit_db_port) == ("rag-db", 5432)
    assert s.audit_db_password is not None
    assert s.audit_db_password.get_secret_value() == "audit-writer"
    assert "sk-virtual-key" not in repr(s)  # secrets never print


# ------------------------------------------------------------------ the Postgres search backend


def _settings(secrets_dir: Path) -> Settings:
    return Settings(
        _secrets_dir=secrets_dir,  # an empty folder: every value is given here
        oidc_issuer="http://localhost:8180/realms/rag",
        oidc_jwks_url="http://keycloak:8080/realms/rag/protocol/openid-connect/certs",
        gateway_key=SecretStr("sk-test"),
        db_password=SecretStr("pw"),
        opa_token=SecretStr("opa"),
        audit_db_password=SecretStr("audit"),
    )


def test_no_clearance_returns_nothing_without_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **kw: Any) -> None:
        raise AssertionError("no database call expected")

    monkeypatch.setattr("rag_api.search.psycopg.connect", boom)
    backend = PgSearch(_settings(tmp_path), Registry.load(PROMPTS))
    # The policy found no clearance at all (e.g. a service account without groups).
    no_clearance = backend.search(
        "anything", groups=frozenset({"all-staff"}), classifications=frozenset(), k=5, user="sub-1"
    )
    assert no_clearance == []


def test_search_tags_the_gateway_call_with_the_user_and_applies_the_policy_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class FakeEmbeddings:
        def create(self, **kw: Any) -> Any:
            seen["embed"] = kw
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.5] * 4)],
                usage=SimpleNamespace(prompt_tokens=12),  # read by the GenAI span (Step 19)
            )

    class FakeConn:
        def __enter__(self) -> FakeConn:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: dict[str, Any]) -> Any:
            seen["sql"], seen["params"] = sql, params
            row = (1, "Remote work policy", "internal", ["all-staff"], 0.71)
            return SimpleNamespace(fetchall=lambda: [row])

    def fake_connect(**kw: Any) -> FakeConn:
        # Step 28: credentials are asked for per connection, not baked into a DSN
        seen["connect"] = kw
        return FakeConn()

    monkeypatch.setattr("rag_api.search.psycopg.connect", fake_connect)
    monkeypatch.setattr(search_module, "register_vector", lambda conn: None)
    backend = PgSearch(_settings(tmp_path), Registry.load(PROMPTS))
    monkeypatch.setattr(backend, "_gw", SimpleNamespace(embeddings=FakeEmbeddings()))

    found = backend.search(
        "hybrid work",
        groups=frozenset({"hr", "all-staff"}),
        classifications=frozenset({"public", "internal", "confidential"}),
        k=3,
        user="sub-1",
    )

    assert [c.hit.title for c in found] == ["Remote work policy"]
    assert found[0].ref == DocumentRef(1, "internal", ("all-staff",))  # facts for the post-check
    assert seen["embed"]["user"] == "sub-1"  # cost and logs per person at the gateway
    assert seen["embed"]["model"] == "embedder"
    assert seen["embed"]["input"] == [INSTRUCTION + "hybrid work"]
    assert seen["params"]["groups"] == ["all-staff", "hr"]
    assert seen["params"]["classifications"] == ["confidential", "internal", "public"]
    assert seen["params"]["k"] == 3
    assert "d.acl_groups && %(groups)s" in seen["sql"]
    assert "d.classification = ANY(%(classifications)s)" in seen["sql"]
    assert "d.classification = 'public' OR" in seen["sql"]
    assert "d.deleted_at IS NULL" in seen["sql"]
    # least-privilege role from Step 11, never the superuser
    assert seen["connect"]["user"] == "rag_app"
    assert seen["connect"]["password"] == "pw"  # noqa: S105 - the throwaway value from _settings()


# ------------------------------------------------------------------ the OPA client


def _opa(handler: Any) -> OpaClient:
    client = OpaClient("http://opa:8181", "tok")
    client._http = httpx.Client(  # swap the network for a scripted OPA
        base_url="http://opa:8181",
        headers={"Authorization": "Bearer tok"},
        transport=httpx.MockTransport(handler),
    )
    return client


ALICE = Principal(
    "sub-alice", "alice", "rag-cli", frozenset({"all-staff"}), frozenset({"rag-user"})
)
GOOD = {
    "allow": True,
    "reasons": [],
    "filter": {"groups": ["all-staff"], "classifications": ["public"]},
}


def test_client_sends_only_token_facts_with_its_bearer_token() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["auth"] = request.url.path, request.headers["Authorization"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"result": GOOD})

    d = _opa(handler).decide(ALICE, "search")
    assert d.allow
    assert d.filter.classifications == {"public"}
    assert seen["path"] == "/v1/data/rag/authz/decision"
    assert seen["auth"] == "Bearer tok"
    assert b'"groups":["all-staff"]' in seen["body"].replace(b" ", b"")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"code": "unauthorized"}),  # wrong token
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={}),  # undefined: policy not loaded
        httpx.Response(200, json={"result": {"allow": True}}),  # missing fields
    ],
    ids=["401", "500", "not json", "undefined", "wrong shape"],
)
def test_odd_answers_are_errors_never_a_yes(response: httpx.Response) -> None:
    with pytest.raises(PolicyUnavailable):
        _opa(lambda request: response).decide(ALICE, "search")


def test_only_a_literal_true_allows() -> None:
    truthy = {**GOOD, "allow": "yes"}
    d = _opa(lambda request: httpx.Response(200, json={"result": truthy})).decide(ALICE, "search")
    assert d.allow is False


def test_readable_skips_the_call_for_no_documents_and_checks_the_shape() -> None:
    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no call expected")

    assert _opa(never).readable(ALICE, []) == set()
    docs = [DocumentRef(1, "internal", ("all-staff",))]
    ok = _opa(lambda request: httpx.Response(200, json={"result": [1]}))
    assert ok.readable(ALICE, docs) == {1}
    odd = _opa(lambda request: httpx.Response(200, json={"result": {"1": True}}))
    with pytest.raises(PolicyUnavailable):
        odd.readable(ALICE, docs)


def test_opa_unreachable_is_policy_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(PolicyUnavailable):
        _opa(refuse).decide(ALICE, "search")
