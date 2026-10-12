"""rag-api: the platform's front door. Every request except /healthz needs a valid Keycloak token."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from rag_api.policy import Decision, OpaClient, PolicyEngine, PolicyUnavailable
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


@lru_cache
def get_policy() -> PolicyEngine:
    s = get_settings()
    return OpaClient(s.opa_url, s.opa_token.get_secret_value())


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


@dataclass(frozen=True)
class Authorized:
    principal: Principal
    decision: Decision


def authorize(action: str) -> Callable[[Principal, PolicyEngine], Authorized]:
    """The API names the ACTION; the policy decides. No role names or rules live in this code."""

    def check(
        principal: Annotated[Principal, Depends(current_principal)],
        policy: Annotated[PolicyEngine, Depends(get_policy)],
    ) -> Authorized:
        try:
            decision = policy.decide(principal, action)
        except PolicyUnavailable as e:
            log.error("policy engine unavailable: %s", e)  # fail closed: no decision, no access
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Policy engine unavailable"
            ) from e
        if not decision.allow:
            log.warning(
                "forbidden: sub=%s action=%s reasons=%s",
                principal.subject,
                action,
                decision.reasons,
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "; ".join(decision.reasons) or "Forbidden"
            )
        return Authorized(principal, decision)

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
    auth: Annotated[Authorized, Depends(authorize("search"))],
    backend: Annotated[SearchBackend, Depends(get_search)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
) -> list[Hit]:
    p, f = auth.principal, auth.decision.filter
    # 1. PRE-filter inside the database query, using the filter the POLICY computed (fast).
    candidates = backend.search(
        req.query, groups=f.groups, classifications=f.classifications, k=req.k, user=p.subject
    )
    # 2. POST-check every candidate with the policy's full rule (safe). If the two ever disagree,
    #    the document is dropped and we log it: that's a bug in the query, never a leak.
    refs = [c.ref for c in candidates]
    try:
        allowed = policy.readable(p, refs)
    except PolicyUnavailable as e:
        log.error("policy engine unavailable: %s", e)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Policy engine unavailable") from e
    dropped = [c.ref.id for c in candidates if c.ref.id not in allowed]
    if dropped:
        log.error("query/policy mismatch: dropped documents %s for sub=%s", dropped, p.subject)
    return [c.hit for c in candidates if c.ref.id in allowed]


@app.get("/v1/admin/ping")
def admin_ping(auth: Annotated[Authorized, Depends(authorize("admin:ping"))]) -> dict[str, str]:
    return {"status": "ok", "admin": auth.principal.username}
