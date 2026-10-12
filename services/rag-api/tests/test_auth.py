"""Authentication: every way a token can be bad gets 401. Authorisation is in test_policy.py."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

if TYPE_CHECKING:  # type hints only: the objects themselves arrive as fixtures
    from conftest import FakeIdP


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_valid_token_gives_the_principal(client: TestClient, idp: FakeIdP) -> None:
    r = client.get("/v1/me", headers=bearer(idp.mint()))
    assert r.status_code == 200
    assert r.json()["groups"] == ["all-staff", "engineering"]
    assert r.json()["roles"] == ["rag-user"]


def test_small_clock_skew_is_tolerated(client: TestClient, idp: FakeIdP) -> None:
    now = int(time.time())
    token = idp.mint(exp=now - 10, iat=now - 310)  # expired 10 s ago: within the 30 s leeway
    assert client.get("/v1/me", headers=bearer(token)).status_code == 200


# ------------------------------------------------------------------ every way a token can be bad


def _tamper(idp: FakeIdP) -> str:
    header, payload, sig = idp.mint().split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data["groups"].append("executives")  # try to grant ourselves executive access
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    return f"{header}.{forged}.{sig}"


def _alg_none(idp: FakeIdP) -> str:
    return jwt.encode(idp.claims(), None, algorithm="none", headers={"kid": idp.kid})  # type: ignore[arg-type]


def _hs256_with_public_key(idp: FakeIdP) -> str:
    # The classic "algorithm confusion" attack: sign with HMAC, using the PUBLIC key as the secret.
    # Recent PyJWT refuses to even create this, so we build the token by hand.
    pem = idp.key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    hdr = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": idp.kid}).encode())
    body = b64(json.dumps(idp.claims()).encode())
    sig = b64(hmac.new(pem, hdr + b"." + body, hashlib.sha256).digest())
    return b".".join([hdr, body, sig]).decode()


BAD_TOKENS: dict[str, Callable[[FakeIdP], str]] = {
    "expired": lambda i: i.mint(exp=int(time.time()) - 120, iat=int(time.time()) - 500),
    "wrong audience": lambda i: i.mint(aud="account"),
    "wrong issuer": lambda i: i.mint(iss="http://evil.example/realms/rag"),
    "missing expiry": lambda i: i.mint(exp=None),
    "tampered payload": _tamper,
    "signed by another key": lambda i: i.mint(key=i.other_key),
    "unknown key id": lambda i: i.mint(kid="not-ours"),
    "alg none": _alg_none,
    "alg confusion HS256": _hs256_with_public_key,
    "ID token, not access token": lambda i: i.mint(typ="ID"),
    "client not allowed": lambda i: i.mint(azp="some-other-app"),
    "malformed groups claim": lambda i: i.mint(groups="executives"),
    "garbage": lambda i: "not-a-jwt",
}


@pytest.mark.parametrize("make", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
def test_bad_tokens_get_401(
    client: TestClient, idp: FakeIdP, make: Callable[[FakeIdP], str]
) -> None:
    r = client.get("/v1/me", headers=bearer(make(idp)))
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


def test_no_token_gets_401_with_challenge(client: TestClient) -> None:
    r = client.get("/v1/me")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Bearer realm="rag-api"'
