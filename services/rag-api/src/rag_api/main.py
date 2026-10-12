"""rag-api: the platform's front door. Every request except /healthz needs a valid Keycloak token."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from pydantic import BaseModel, Field

from rag_api.policy import Decision, OpaClient, PolicyEngine, PolicyUnavailable
from rag_api.search import Hit, PgSearch, SearchBackend
from rag_api.settings import Settings
from rag_common.auth import AuthError, KeyServiceUnavailable, OIDCSettings, Principal, TokenVerifier
from rag_common.telemetry import setup_logging, setup_telemetry

log = logging.getLogger("rag_api")
tracer = trace.get_tracer("rag_api")
meter = metrics.get_meter("rag_api")

# Metrics: a few numbers you'd put on a dashboard or alert on (Step 20).
SEARCHES = meter.create_counter(
    "rag.search.requests", unit="{request}", description="Searches by outcome"
)
# Bucket edges in SECONDS. The SDK's defaults (0, 5, 10, 25 … 10000) assume milliseconds: with them,
# every search lands in the 0-5 bucket and p95 is reported as ~4.75 s. Put an edge at the 2 s objective.
SEARCH_BUCKETS = [0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30]
SEARCH_TIME = meter.create_histogram(
    "rag.search.duration",
    unit="s",
    description="End-to-end search time",
    explicit_bucket_boundaries_advisory=SEARCH_BUCKETS,
)
DECISIONS = meter.create_counter(
    "rag.authz.decisions", unit="{decision}", description="Policy decisions"
)
DROPPED = meter.create_counter(
    "rag.search.dropped_documents",
    unit="{document}",
    description="Query/policy mismatches (should be 0)",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    shutdown_telemetry = setup_telemetry("rag-api")
    HTTPXClientInstrumentor().instrument()  # calls to OPA and the gateway: spans + traceparent header
    PsycopgInstrumentor().instrument()  # one span per SQL statement (text only, never parameters)
    # Start alert-worthy counters at 0. Otherwise a counter is born at its first value, and
    # Prometheus' increase() can't see the jump from "nothing" to 1: the first incident is missed.
    for outcome in ("ok", "error"):
        SEARCHES.add(0, {"outcome": outcome})
    DROPPED.add(0)
    yield
    shutdown_telemetry()  # on stop: send what's still buffered


app = FastAPI(title="rag-api", version="0.1.0", lifespan=lifespan)
# One server span per request. Excluded: health checks (most of the traffic, no value) and the
# tiny internal "receive"/"send" spans (noise).
FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz", exclude_spans=["receive", "send"])
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
        with tracer.start_as_current_span("rag.authz.decide") as span:
            span.set_attribute("rag.authz.action", action)
            try:
                decision = policy.decide(principal, action)
            except PolicyUnavailable as e:
                log.error("policy engine unavailable: %s", e)  # fail closed: no decision, no access
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "Policy engine unavailable"
                ) from e
            span.set_attribute("rag.authz.allow", decision.allow)
            DECISIONS.add(1, {"action": action, "allow": decision.allow})
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
    started, outcome = time.perf_counter(), "error"
    try:
        # 1. PRE-filter inside the database query, using the filter the POLICY computed (fast).
        with tracer.start_as_current_span("rag.retrieve") as span:
            # Facts about the request, never its content: the question itself may hold personal
            # or confidential data, so only its length is recorded.
            span.set_attributes(
                {
                    "enduser.id": p.subject,
                    "rag.query.chars": len(req.query),
                    "rag.k": req.k,
                    "rag.filter.classifications": sorted(f.classifications),
                    "rag.filter.group_count": len(f.groups),
                }
            )
            candidates = backend.search(
                req.query,
                groups=f.groups,
                classifications=f.classifications,
                k=req.k,
                user=p.subject,
            )
            span.set_attribute("rag.candidates", len(candidates))
        # 2. POST-check every candidate with the policy's full rule (safe). If the two ever
        #    disagree, the document is dropped and we log it: a bug in the query, never a leak.
        with tracer.start_as_current_span("rag.authz.post_check") as span:
            try:
                allowed = policy.readable(p, [c.ref for c in candidates])
            except PolicyUnavailable as e:
                log.error("policy engine unavailable: %s", e)
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "Policy engine unavailable"
                ) from e
            dropped = [c.ref.id for c in candidates if c.ref.id not in allowed]
            span.set_attributes(
                {"rag.returned": len(candidates) - len(dropped), "rag.dropped": len(dropped)}
            )
        if dropped:
            DROPPED.add(len(dropped))
            log.error("query/policy mismatch: dropped documents %s for sub=%s", dropped, p.subject)
        outcome = "ok"
        return [c.hit for c in candidates if c.ref.id in allowed]
    finally:
        SEARCHES.add(1, {"outcome": outcome})
        SEARCH_TIME.record(time.perf_counter() - started, {"outcome": outcome})


@app.get("/v1/admin/ping")
def admin_ping(auth: Annotated[Authorized, Depends(authorize("admin:ping"))]) -> dict[str, str]:
    return {"status": "ok", "admin": auth.principal.username}
