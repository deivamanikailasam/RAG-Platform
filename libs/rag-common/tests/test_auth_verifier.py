"""The shared token verifier on its own, against a real (local) JWKS endpoint.

services/rag-api/tests/test_auth.py attacks the API with bad tokens through a fake key source. These
tests cover what that fake can't: the production key source (PyJWKClient) fetching, caching and
re-fetching keys over HTTP, key rotation, and an unreachable identity provider (503, not 401).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from rag_common.auth import (
    ALLOWED_ALGORITHMS,
    AuthError,
    KeyServiceUnavailable,
    OIDCSettings,
    Principal,
    TokenVerifier,
)

ISSUER = "http://localhost:8180/realms/rag"
KEY_1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY_2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk: dict[str, Any] = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}


class _JWKSHandler(BaseHTTPRequestHandler):
    """A tiny stand-in for Keycloak's /protocol/openid-connect/certs endpoint."""

    keys: ClassVar[list[dict[str, Any]]] = []
    hits: ClassVar[int] = 0

    def do_GET(self) -> None:
        type(self).hits += 1
        body = json.dumps({"keys": type(self).keys}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # keep test output quiet
        return


@pytest.fixture
def jwks_url() -> Iterator[str]:
    _JWKSHandler.keys = [_jwk(KEY_1, "kid-1")]
    _JWKSHandler.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JWKSHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/realms/rag/protocol/openid-connect/certs"
    server.shutdown()
    server.server_close()


def mint(key: rsa.RSAPrivateKey = KEY_1, kid: str = "kid-1", **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": ["rag-api", "account"],
        "azp": "rag-cli",
        "typ": "Bearer",
        "sub": "8f1c0000-alice",
        "preferred_username": "alice",
        "iat": now,
        "exp": now + 300,
        "groups": ["all-staff", "engineering"],
        "realm_access": {"roles": ["rag-user"]},
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def verifier(url: str, clients: frozenset[str] = frozenset({"rag-cli"})) -> TokenVerifier:
    return TokenVerifier(OIDCSettings(ISSUER, "rag-api", url, clients))


def test_only_rs256_is_allowed() -> None:
    assert ALLOWED_ALGORITHMS == ["RS256"]


def test_valid_token_becomes_a_principal(jwks_url: str) -> None:
    p = verifier(jwks_url).verify(mint())
    assert p == Principal(
        subject="8f1c0000-alice",
        username="alice",
        client_id="rag-cli",
        groups=frozenset({"all-staff", "engineering"}),
        roles=frozenset({"rag-user"}),
    )
    assert p.has_role("rag-user")
    assert not p.has_role("rag-admin")
    assert not p.is_service_account


def test_keys_are_cached_between_requests(jwks_url: str) -> None:
    v = verifier(jwks_url)
    for _ in range(5):
        v.verify(mint())
    assert _JWKSHandler.hits == 1  # one download, then the 5-minute cache answers


def test_key_rotation_is_picked_up_automatically(
    jwks_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr("jwt.jwks_client.time.monotonic", lambda: clock[0])
    v = verifier(jwks_url)
    v.verify(mint())
    # Keycloak rotates: a new active key appears in the JWKS and new tokens carry its kid.
    _JWKSHandler.keys = [_jwk(KEY_2, "kid-2"), _jwk(KEY_1, "kid-1")]
    # PyJWT allows one forced re-fetch per 30 s, so a flood of made-up kids can't hammer Keycloak.
    # Straight after the last download the new kid is still unknown...
    with pytest.raises(AuthError):
        v.verify(mint(key=KEY_2, kid="kid-2"))
    assert _JWKSHandler.hits == 1
    # ...and once the cool-down has passed, the unknown kid triggers exactly one re-fetch.
    clock[0] += 31
    p = v.verify(mint(key=KEY_2, kid="kid-2"))
    assert p.username == "alice"
    assert _JWKSHandler.hits == 2
    v.verify(mint())  # tokens signed with the old key keep working until they expire
    assert _JWKSHandler.hits == 2


def test_unknown_kid_after_refetch_is_401(jwks_url: str) -> None:
    with pytest.raises(AuthError):
        verifier(jwks_url).verify(mint(key=KEY_2, kid="never-published"))


def test_unreachable_identity_provider_is_503_not_401() -> None:
    # Port 9 (discard) on localhost: nothing listens, so the connection is refused straight away.
    v = verifier("http://127.0.0.1:9/realms/rag/protocol/openid-connect/certs")
    with pytest.raises(KeyServiceUnavailable):
        v.verify(mint())


def test_empty_allowed_clients_means_any_client(jwks_url: str) -> None:
    p = verifier(jwks_url, frozenset()).verify(mint(azp="some-other-app"))
    assert p.client_id == "some-other-app"


def test_service_account_is_recognised(jwks_url: str) -> None:
    token = mint(
        azp="ingestion-worker",
        preferred_username="service-account-ingestion-worker",
        groups=None,
        realm_access={"roles": ["rag-ingest"]},
    )
    p = verifier(jwks_url, frozenset({"ingestion-worker"})).verify(token)
    assert p.is_service_account
    assert p.groups == frozenset()  # no groups claim -> no groups -> no documents (fail closed)


@pytest.mark.parametrize(
    "overrides",
    [
        {"realm_access": {"roles": "rag-admin"}},  # a string, not a list
        {"groups": ["all-staff", 7]},  # not all strings
    ],
)
def test_malformed_list_claims_are_rejected(jwks_url: str, overrides: dict[str, Any]) -> None:
    with pytest.raises(AuthError, match="malformed claim"):
        verifier(jwks_url).verify(mint(**overrides))
