"""Verify OIDC access tokens from Keycloak and turn them into a Principal.

Framework-free on purpose: every service (API, workers, evaluation) uses the same checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import jwt

# Only the algorithm Keycloak actually uses. Never "none", never HS256: accepting HS256 would let an
# attacker sign a token with our PUBLIC key as the shared secret (the "algorithm confusion" attack).
ALLOWED_ALGORITHMS = ["RS256"]
SERVICE_ACCOUNT_PREFIX = "service-account-"  # Keycloak's username for client-credentials identities


class AuthError(Exception):
    """The token is missing or not acceptable. Maps to HTTP 401."""


class KeyServiceUnavailable(Exception):  # noqa: N818 - reads better than ...Error here
    """The identity provider's keys could not be fetched. Maps to HTTP 503, not 401."""


class SigningKeySource(Protocol):
    """Anything that finds the public key for a token: PyJWKClient in production, a fake in tests."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str  # must equal the token's "iss" exactly
    audience: str  # this API's name; must appear in the token's "aud"
    jwks_url: str  # where the public keys are published
    allowed_clients: frozenset[str] = frozenset()  # apps allowed to call us ("azp"); empty = any
    leeway_seconds: int = 30  # tolerance for small clock differences


@dataclass(frozen=True)
class Principal:
    """Who is calling: the facts every authorisation decision is based on."""

    subject: str  # stable user id ("sub"); use this in logs and the database, not the username
    username: str
    client_id: str  # the app the token was issued to ("azp")
    groups: frozenset[str]
    roles: frozenset[str]

    @property
    def is_service_account(self) -> bool:
        return self.username.startswith(SERVICE_ACCOUNT_PREFIX)

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _str_set(value: Any, claim: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AuthError(f"malformed claim {claim}")
    return frozenset(value)


class TokenVerifier:
    def __init__(self, settings: OIDCSettings, keys: SigningKeySource | None = None) -> None:
        self._s = settings
        # Caches keys for 5 minutes and re-fetches automatically when it sees an unknown key id,
        # which is what happens right after Keycloak rotates its signing key.
        self._keys = keys or jwt.PyJWKClient(
            settings.jwks_url, cache_keys=True, lifespan=300, timeout=5
        )

    def verify(self, token: str) -> Principal:
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._s.audience,
                issuer=self._s.issuer,
                leeway=self._s.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWKClientConnectionError as e:
            raise KeyServiceUnavailable(str(e)) from e
        except jwt.PyJWTError as e:
            # bad signature, expired, wrong audience or issuer, unknown key, malformed token…
            raise AuthError(type(e).__name__) from e

        # Keycloak marks access tokens "Bearer"; ID tokens ("ID") must never be used to call APIs.
        if claims.get("typ") != "Bearer":
            raise AuthError("not an access token")
        client_id = str(claims.get("azp", ""))
        if self._s.allowed_clients and client_id not in self._s.allowed_clients:
            raise AuthError(f"client {client_id!r} may not call this API")

        realm_access = claims.get("realm_access") or {}
        return Principal(
            subject=str(claims["sub"]),
            username=str(claims.get("preferred_username", "")),
            client_id=client_id,
            groups=_str_set(claims.get("groups"), "groups"),
            roles=_str_set(realm_access.get("roles"), "realm_access.roles"),
        )
