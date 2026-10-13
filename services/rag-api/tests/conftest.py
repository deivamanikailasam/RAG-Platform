"""Shared test doubles: fake identity provider, search backend, policy engine and audit log."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag_api.audit import AuditEvent, AuditUnavailable
from rag_api.llmtrace import LlmTracer
from rag_api.main import (
    app,
    get_audit,
    get_llm,
    get_policy,
    get_prompt_label,
    get_prompts,
    get_search,
    get_verifier,
)
from rag_api.policy import Decision, DocumentRef, PolicyUnavailable, SearchFilter
from rag_api.search import Candidate, Hit
from rag_common.auth import OIDCSettings, Principal, TokenVerifier
from rag_common.prompts import Registry
from rag_common.telemetry import setup_telemetry

ISSUER = "http://localhost:8180/realms/rag"
PROMPTS = Path(__file__).resolve().parents[3] / "prompts"  # the REAL registry, as shipped (Step 24)


class FakeIdP:
    """Plays Keycloak: owns a signing key and mints tokens with it."""

    kid = "test-key-1"

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Acts as the JWKS client too (SigningKeySource protocol)
    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if jwt.get_unverified_header(token).get("kid") != self.kid:
            raise jwt.PyJWKClientError("Unable to find a signing key that matches")
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return jwt.PyJWK({**jwk, "kid": self.kid, "alg": "RS256", "use": "sig"})

    def claims(self, **overrides: Any) -> dict[str, Any]:
        now = int(time.time())
        base = {
            "iss": ISSUER, "aud": ["rag-api", "account"], "azp": "rag-cli", "typ": "Bearer",
            "sub": "8f1c0000-alice", "preferred_username": "alice", "iat": now, "exp": now + 300,
            "groups": ["all-staff", "engineering"], "realm_access": {"roles": ["rag-user"]},
        }  # fmt: skip
        base.update(overrides)
        return {k: v for k, v in base.items() if v is not None}

    def mint(self, key: Any = None, alg: str = "RS256", kid: str | None = None, **kw: Any) -> str:
        headers = {"kid": kid or self.kid}
        return jwt.encode(self.claims(**kw), key or self.key, algorithm=alg, headers=headers)


class FakeSearch:
    """Returns fixed candidates and records what the API asked for."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.candidates = [
            Candidate(DocumentRef(1, "internal", ("all-staff",)), Hit(id=1, title="Remote work policy", classification="internal", score=0.71)),
        ]  # fmt: skip

    def search(self, query: str, *, groups: frozenset[str], classifications: frozenset[str],
               k: int, user: str, filters: Any = None) -> list[Candidate]:  # fmt: skip
        self.calls.append({"groups": groups, "classifications": classifications, "user": user,
                           "filters": filters})  # fmt: skip
        return self.candidates


class FakePolicy:
    """A policy engine whose answers each test sets explicitly. Records what it was asked."""

    def __init__(self) -> None:
        self.allow = True
        self.reasons: tuple[str, ...] = ()
        self.readable_ids: set[int] | None = None  # None = everything offered is readable
        self.down = False
        self.asked: list[tuple[str, Principal]] = []

    def decide(self, principal: Principal, action: str) -> Decision:
        if self.down:
            raise PolicyUnavailable("connection refused")
        self.asked.append((action, principal))
        filt = SearchFilter(
            groups=principal.groups, classifications=frozenset({"public", "internal"})
        )
        return Decision(allow=self.allow, reasons=self.reasons, filter=filt)

    def readable(self, principal: Principal, docs: list[DocumentRef]) -> set[int]:
        ids = {d.id for d in docs}
        return ids if self.readable_ids is None else ids & self.readable_ids


class FakeAudit:
    """An audit log in a list. Set .down = True to simulate the audit database being unreachable."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self.down = False

    def record(self, event: AuditEvent) -> int:
        if self.down:
            raise AuditUnavailable("PoolTimeout")
        self.events.append(event)
        return len(self.events)

    def close(self) -> None:
        pass


@pytest.fixture(scope="session")
def otel() -> tuple[InMemorySpanExporter, InMemoryMetricReader]:
    """The process-wide OpenTelemetry setup (it can only be installed once), kept in memory."""
    spans, reader = InMemorySpanExporter(), InMemoryMetricReader()
    setup_telemetry("rag-api-test", span_exporter=spans, metric_reader=reader)
    return spans, reader


@pytest.fixture(scope="session")
def idp() -> FakeIdP:
    return FakeIdP()


@pytest.fixture
def search() -> FakeSearch:
    return FakeSearch()


@pytest.fixture
def policy() -> FakePolicy:
    return FakePolicy()


@pytest.fixture
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture
def client(
    idp: FakeIdP, search: FakeSearch, policy: FakePolicy, audit: FakeAudit
) -> Iterator[TestClient]:
    allowed = frozenset({"rag-web", "rag-cli", "ingestion-worker"})
    settings = OIDCSettings(ISSUER, "rag-api", "unused", allowed)
    app.dependency_overrides[get_verifier] = lambda: TokenVerifier(settings, idp)
    app.dependency_overrides[get_search] = lambda: search
    app.dependency_overrides[get_policy] = lambda: policy
    app.dependency_overrides[get_audit] = lambda: audit
    # Langfuse is off unless a test switches it on (test_llmtrace.py)
    app.dependency_overrides[get_llm] = lambda: LlmTracer(None)
    # The real prompt registry (Step 24): every API test also proves the shipped prompts load
    registry = Registry.load(PROMPTS)
    app.dependency_overrides[get_prompts] = lambda: registry
    app.dependency_overrides[get_prompt_label] = lambda: "production"
    yield TestClient(app)
    app.dependency_overrides.clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
