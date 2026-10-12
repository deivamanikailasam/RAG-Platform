"""Token checks, tested without Keycloak: we play the identity provider with our own test key."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from rag_api.main import app, get_search, get_verifier
from rag_api.search import Hit
from rag_common.auth import OIDCSettings, TokenVerifier

ISSUER = "http://localhost:8180/realms/rag"
KID = "test-key-1"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # an attacker's key


class FakeKeys:
    """Stands in for Keycloak's JWKS endpoint: knows exactly one public key."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if jwt.get_unverified_header(token).get("kid") != KID:
            raise jwt.PyJWKClientError("Unable to find a signing key that matches")
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
        return jwt.PyJWK({**jwk, "kid": KID, "alg": "RS256", "use": "sig"})


class FakeSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search(self, query: str, *, groups: frozenset[str], k: int, user: str) -> list[Hit]:
        self.calls.append({"groups": groups, "user": user})
        return [Hit(title="Remote work policy", classification="internal", score=0.71)]


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "iss": ISSUER, "aud": ["rag-api", "account"], "azp": "rag-cli", "typ": "Bearer",
        "sub": "8f1c0000-alice", "preferred_username": "alice", "iat": now, "exp": now + 300,
        "groups": ["all-staff", "engineering"], "realm_access": {"roles": ["rag-user"]},
    }  # fmt: skip
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def mint(key: Any = KEY, alg: str = "RS256", kid: str = KID, **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), key, algorithm=alg, headers={"kid": kid})


@pytest.fixture
def search() -> FakeSearch:
    return FakeSearch()


@pytest.fixture
def client(search: FakeSearch) -> Iterator[TestClient]:
    settings = OIDCSettings(
        ISSUER, "rag-api", "unused", frozenset({"rag-web", "rag-cli", "ingestion-worker"})
    )
    app.dependency_overrides[get_verifier] = lambda: TokenVerifier(settings, FakeKeys())
    app.dependency_overrides[get_search] = lambda: search
    yield TestClient(app)
    app.dependency_overrides.clear()


def call(client: TestClient, token: str | None, path: str = "/v1/me") -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get(path, headers=headers)


# ------------------------------------------------------------------ the happy path


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_valid_token_gives_the_principal(client: TestClient) -> None:
    r = call(client, mint())
    assert r.status_code == 200
    assert r.json()["groups"] == ["all-staff", "engineering"]
    assert r.json()["roles"] == ["rag-user"]


def test_search_uses_groups_from_the_token_only(client: TestClient, search: FakeSearch) -> None:
    body = {"query": "hybrid work", "groups": ["executives"]}  # a sneaky extra field is ignored
    r = client.post("/v1/search", json=body, headers={"Authorization": f"Bearer {mint()}"})
    assert r.status_code == 200
    assert search.calls == [
        {"groups": frozenset({"all-staff", "engineering"}), "user": "8f1c0000-alice"}
    ]


# ------------------------------------------------------------------ every way a token can be bad


def _tamper(token: str) -> str:
    header, payload, sig = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data["groups"].append("executives")  # try to grant ourselves executive access
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    return f"{header}.{forged}.{sig}"


def _alg_none() -> str:
    return jwt.encode(claims(), None, algorithm="none", headers={"kid": KID})  # type: ignore[arg-type]


def _hs256_with_public_key() -> str:
    # The classic "algorithm confusion" attack: sign with HMAC, using the PUBLIC key as the secret.
    # Recent PyJWT refuses to even create this, so we build the token by hand.
    pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    hdr = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode()
    ).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(claims()).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(
        hmac.new(pem, hdr + b"." + body, hashlib.sha256).digest()
    ).rstrip(b"=")
    return b".".join([hdr, body, sig]).decode()


BAD_TOKENS = {
    "expired": lambda: mint(exp=int(time.time()) - 120, iat=int(time.time()) - 500),
    "wrong audience": lambda: mint(aud="account"),
    "wrong issuer": lambda: mint(iss="http://evil.example/realms/rag"),
    "missing expiry": lambda: mint(exp=None),
    "tampered payload": lambda: _tamper(mint()),
    "signed by another key": lambda: mint(key=OTHER_KEY),
    "unknown key id": lambda: mint(kid="not-ours"),
    "alg none": _alg_none,
    "alg confusion HS256": _hs256_with_public_key,
    "ID token, not access token": lambda: mint(typ="ID"),
    "client not allowed": lambda: mint(azp="some-other-app"),
    "malformed groups claim": lambda: mint(groups="executives"),
    "garbage": lambda: "not-a-jwt",
}


@pytest.mark.parametrize("make", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
def test_bad_tokens_get_401(client: TestClient, make: Any) -> None:
    r = call(client, make())
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


def test_no_token_gets_401_with_challenge(client: TestClient) -> None:
    r = call(client, None)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Bearer realm="rag-api"'


# ------------------------------------------------------------------ valid token, wrong permissions


def test_missing_role_gets_403(client: TestClient) -> None:
    assert call(client, mint(), "/v1/admin/ping").status_code == 403


def test_admin_role_allows_admin_endpoint(client: TestClient) -> None:
    token = mint(realm_access={"roles": ["rag-user", "rag-admin"]})
    assert call(client, token, "/v1/admin/ping").status_code == 200


def test_service_account_cannot_search(client: TestClient) -> None:
    token = mint(azp="ingestion-worker", preferred_username="service-account-ingestion-worker",
                 groups=None, realm_access={"roles": ["rag-ingest"]})  # fmt: skip
    r = client.post("/v1/search", json={"query": "x"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_small_clock_skew_is_tolerated(client: TestClient) -> None:
    now = int(time.time())
    assert call(client, mint(exp=now - 10, iat=now - 310)).status_code == 200  # within 30 s leeway
