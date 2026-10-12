"""rag-api: the platform's front door. Every request except /healthz needs a valid Keycloak token."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from rag_api.search import Hit, PgSearch, SearchBackend
from rag_api.settings import Settings
from rag_common.auth import AuthError, KeyServiceUnavailable, OIDCSettings, Principal, TokenVerifier

log = logging.getLogger("rag_api")
app = FastAPI(title="rag-api", version="0.1.0")
bearer = HTTPBearer(auto_error=False)  # we build the 401 ourselves, with the standard header


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from env vars and /run/secrets


@lru_cache
def get_verifier() -> TokenVerifier:
    s = get_settings()
    return TokenVerifier(
        OIDCSettings(
            issuer=s.oidc_issuer,
            audience=s.oidc_audience,
            jwks_url=s.oidc_jwks_url,
            allowed_clients=frozenset(s.allowed_clients),
        )
    )


@lru_cache
def get_search() -> SearchBackend:
    return PgSearch(get_settings())


def unauthorized(error: str = "invalid_token") -> HTTPException:
    # RFC 6750: tell the client it needs a (new) bearer token, but don't say what exactly was wrong
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": f'Bearer realm="rag-api", error="{error}"'},
    )


def current_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> Principal:
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": 'Bearer realm="rag-api"'},
        )
    try:
        return verifier.verify(creds.credentials)
    except KeyServiceUnavailable as e:
        log.error("cannot fetch signing keys: %s", e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Identity provider unavailable"
        ) from e
    except AuthError as e:
        log.warning("rejected token: %s", e)  # the reason, never the token itself
        raise unauthorized() from e


def require_role(role: str) -> Callable[[Principal], Principal]:
    def check(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.has_role(role):
            log.warning("forbidden: sub=%s lacks role %s", principal.subject, role)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role {role}")
        return principal

    return check


# ---------------------------------------------------------------- endpoints


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}  # public on purpose: Docker and Kubernetes probes have no token


class Me(BaseModel):
    subject: str
    username: str
    client_id: str
    groups: list[str]
    roles: list[str]
    service_account: bool


@app.get("/v1/me")
def me(p: Annotated[Principal, Depends(current_principal)]) -> Me:
    return Me(
        subject=p.subject,
        username=p.username,
        client_id=p.client_id,
        groups=sorted(p.groups),
        roles=sorted(p.roles),
        service_account=p.is_service_account,
    )


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)


@app.post("/v1/search")
def search(
    req: SearchRequest,
    p: Annotated[Principal, Depends(require_role("rag-user"))],
    backend: Annotated[SearchBackend, Depends(get_search)],
) -> list[Hit]:
    # The groups come ONLY from the verified token, never from the request body.
    return backend.search(req.query, groups=p.groups, k=req.k, user=p.subject)


@app.get("/v1/admin/ping")
def admin_ping(p: Annotated[Principal, Depends(require_role("rag-admin"))]) -> dict[str, str]:
    return {"status": "ok", "admin": p.username}
