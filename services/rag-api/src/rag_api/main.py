"""rag-api: the platform's front door. Every request except /healthz needs a valid Keycloak token."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Literal, cast

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.metrics import CallbackOptions, Observation
from pydantic import BaseModel, Field

from rag_api.audit import (
    AuditEvent,
    AuditLog,
    AuditUnavailable,
    Outcome,
    PgAuditLog,
    current_trace_id,
)
from rag_api.llmtrace import LlmTracer, build_llm_tracer
from rag_api.policy import Decision, DocumentRef, OpaClient, PolicyEngine, PolicyUnavailable
from rag_api.search import CoreSearch, Hit, PgSearch, SearchBackend, document_id
from rag_api.settings import Settings
from rag_common.auth import AuthError, KeyServiceUnavailable, OIDCSettings, Principal, TokenVerifier
from rag_common.prompts import PromptError, Registry
from rag_common.telemetry import setup_logging, setup_telemetry
from rag_core import config as rag_config
from rag_core.answer import AnswerPipeline
from rag_core.components.generation import PackedContext
from rag_core.registry import Container
from rag_core.search import SearchPipeline
from rag_core.types import Answer, Classification, ScoredChunk
from rag_core.types import Principal as CorePrincipal

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
AUDIT_FAILURES = meter.create_counter(
    "rag.audit.write_failures",
    unit="{event}",
    description="Audit events that could not be stored (should be 0)",
)

# Answers (Step 33): outcomes, time to the first byte of the response, and user feedback
ANSWERS = meter.create_counter(
    "rag.answer.requests", unit="{request}", description="Answers by outcome"
)
ANSWER_TIME = meter.create_histogram(
    "rag.answer.duration",
    unit="s",
    description="Answer time: whole answers, or until the stream starts (time to first token)",
    explicit_bucket_boundaries_advisory=SEARCH_BUCKETS,
)
FEEDBACK = meter.create_counter(
    "rag.answer.feedback", unit="{rating}", description="Thumbs up/down by reason"
)
# Guardrails (Step 34): every verdict other than allow, by guard, stage and action
GUARD_VERDICTS = meter.create_counter(
    "rag.guard.verdicts", unit="{verdict}", description="Guard verdicts other than allow (Step 34)"
)

REQUIRED_PROMPTS = ("query-instruction",)  # prompts this service can't run without


def check_prompts(registry: Registry, label: str) -> None:
    """Refuse to start if this environment's label leaves a required prompt without a version."""
    if missing := [n for n in REQUIRED_PROMPTS if n not in registry.active(label)]:
        raise PromptError(f"no '{label}' version of required prompt(s) {missing}")


def prompt_info(registry: Registry, label: str) -> list[Observation]:
    """One "info" series per active prompt: value 1, the facts in the labels (a Prometheus idiom)."""
    return [
        Observation(1, {"prompt": name, "version": p.version, "sha": sha[:12], "label": label})
        for name, (p, sha) in sorted(registry.active(label).items())
    ]


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
    for outcome in ("answered", "abstained", "blocked", "error"):
        ANSWERS.add(0, {"outcome": outcome})
    for outcome in ("allowed", "denied"):
        AUDIT_FAILURES.add(0, {"outcome": outcome})
    # Load and check the prompt registry now: a broken or edited prompt stops the start-up,
    # instead of failing the first user request.
    registry, label = get_prompts(), get_prompt_label()
    check_prompts(registry, label)
    log.info("prompts (%s): %s", label, {n: p.ref for n, (p, _) in registry.active(label).items()})

    def observe(_: CallbackOptions) -> list[Observation]:
        return prompt_info(registry, label)

    meter.create_observable_gauge(
        "rag.prompt.info", callbacks=[observe], description="Active prompt versions (value 1)"
    )
    yield
    if get_audit.cache_info().currsize:
        get_audit().close()  # close the pool's connections cleanly
    if get_llm.cache_info().currsize:  # only if it was ever created
        get_llm().shutdown()  # flush buffered Langfuse traces
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
def get_prompts() -> Registry:
    return Registry.load(get_settings().prompts_dir)  # verifies every file against the lock


def get_prompt_label() -> str:
    return get_settings().prompt_label


@lru_cache
def get_core() -> Container:
    """rag-core's components for this deployment (rag.yaml + profile), built once, shared by
    search and answers (Steps 32-33)."""
    s = get_settings()
    return rag_config.load(s.rag_config, s.rag_profile)


@lru_cache
def get_search() -> SearchBackend:
    s = get_settings()
    if s.search_backend == "core":
        return CoreSearch(s, SearchPipeline(get_core()))  # rag-core pipeline (Step 32)
    return PgSearch(s, get_prompts())


@lru_cache
def get_answerer() -> AnswerPipeline:
    return AnswerPipeline(get_core())


def get_tenant() -> str:
    return get_settings().tenant


@lru_cache
def get_llm() -> LlmTracer:
    s = get_settings()
    return build_llm_tracer(
        base_url=s.langfuse_base_url,
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key.get_secret_value() if s.langfuse_secret_key else None,
        capture_question=s.langfuse_capture_question,
    )


@lru_cache
def get_audit() -> AuditLog:
    s = get_settings()
    return PgAuditLog(
        host=s.audit_db_host, port=s.audit_db_port, credentials=s.audit_db_credentials()
    )


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


def audit_event(
    p: Principal, action: str, outcome: Outcome, resource: str, **details: Any
) -> AuditEvent:
    return AuditEvent(
        actor=p.subject, client_id=p.client_id, action=action, outcome=outcome,
        resource=resource, details=details, trace_id=current_trace_id(),
    )  # fmt: skip


def record_or_refuse(audit: AuditLog, event: AuditEvent) -> None:
    """Fail closed: if we can't record that data was handed out, we don't hand it out."""
    try:
        audit.record(event)
    except AuditUnavailable as e:
        AUDIT_FAILURES.add(1, {"outcome": event.outcome})
        log.error("audit log unavailable, refusing %s: %s", event.action, e)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Audit log unavailable") from e


def record_best_effort(audit: AuditLog, event: AuditEvent) -> None:
    """For refusals: nothing is handed out, so a failed write must not turn a 403 into a 503."""
    try:
        audit.record(event)
    except AuditUnavailable as e:
        AUDIT_FAILURES.add(1, {"outcome": event.outcome})
        log.error("audit log unavailable, %s event for sub=%s lost: %s",
                  event.outcome, event.actor, e)  # fmt: skip


@dataclass(frozen=True)
class Authorized:
    principal: Principal
    decision: Decision


def authorize(action: str) -> Callable[[Principal, PolicyEngine, AuditLog], Authorized]:
    """The API names the ACTION; the policy decides. No role names or rules live in this code."""

    def check(
        principal: Annotated[Principal, Depends(current_principal)],
        policy: Annotated[PolicyEngine, Depends(get_policy)],
        audit: Annotated[AuditLog, Depends(get_audit)],
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
            record_best_effort(
                audit,
                audit_event(principal, action, "denied", action, reasons=list(decision.reasons)),
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
    llm: Annotated[LlmTracer, Depends(get_llm)],
    audit: Annotated[AuditLog, Depends(get_audit)],
    prompts: Annotated[Registry, Depends(get_prompts)],
    label: Annotated[str, Depends(get_prompt_label)],
) -> list[Hit]:
    p, f = auth.principal, auth.decision.filter
    started, outcome = time.perf_counter(), "error"
    query_prompt, _ = prompts.get("query-instruction", label=label)
    # Langfuse trace (Step 22): same trace id as the OTel trace, content masked, kept separate.
    with llm.search(p, req.query, req.k, {"query-instruction": query_prompt.ref}) as llm_trace:
        try:
            # 1. PRE-filter inside the database query, using the filter the POLICY computed (fast).
            with tracer.start_as_current_span("rag.retrieve") as span:
                # Facts about the request, never its content: the question itself may hold
                # personal or confidential data, so only its length is recorded.
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
            llm_trace.retrieved(candidates, allowed)
            if dropped:
                DROPPED.add(len(dropped))
                log.error(
                    "query/policy mismatch: dropped documents %s for sub=%s", dropped, p.subject
                )
            returned = [c for c in candidates if c.ref.id in allowed]
            # 3. Record WHO received WHICH documents, before handing anything out (Step 23).
            #    Ids and counts only: never the question or the text.
            record_or_refuse(
                audit,
                audit_event(
                    p, "search", "allowed", "documents",
                    returned_ids=[c.ref.id for c in returned], dropped_by_policy=len(dropped),
                    k=req.k, query_chars=len(req.query), prompts=[query_prompt.ref],
                ),
            )  # fmt: skip
            outcome = "ok"
            return [c.hit for c in returned]
        finally:
            SEARCHES.add(1, {"outcome": outcome})
            SEARCH_TIME.record(time.perf_counter() - started, {"outcome": outcome})


@app.get("/v1/admin/ping")
def admin_ping(
    auth: Annotated[Authorized, Depends(authorize("admin:ping"))],
    audit: Annotated[AuditLog, Depends(get_audit)],
) -> dict[str, str]:
    record_or_refuse(audit, audit_event(auth.principal, "admin:ping", "allowed", "rag-api"))
    return {"status": "ok", "admin": auth.principal.username}


# ---------------------------------------------------------------- answers (Step 33)


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # A conversation: earlier turns are remembered per person AND session (Step 33)
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    stream: bool = False


class CitationOut(BaseModel):
    n: int  # the [doc n] in the text
    document_id: int
    title: str


class AnswerOut(BaseModel):
    answer_id: str  # send it back with /v1/feedback; it is also the trace id (Steps 19-23)
    text: str
    abstained: bool
    blocked: (
        bool  # a guard stopped it (Step 34); the text is a fixed message, the reason is audited
    )
    citations: list[CitationOut]


def _answer_id() -> str:
    return current_trace_id() or uuid.uuid4().hex


def _citations(a: Answer, context_ids: dict[str, int]) -> list[CitationOut]:
    return [
        CitationOut(n=c.marker, document_id=context_ids.get(c.chunk_id, -1), title=c.title)
        for c in a.citations
    ]


def _outcome(a: Answer) -> str:
    return "blocked" if a.blocked else "abstained" if a.abstained else "answered"


def _verdicts(a: Answer | None) -> list[dict[str, Any]]:
    """Guard verdicts for the audit log and metrics: names, stages, actions, reasons. Never text."""
    found = list(a.trace.get("guards", [])) if a is not None else []
    for v in found:
        GUARD_VERDICTS.add(1, {"guard": v["guard"], "stage": v["stage"], "action": v["action"]})
    return found


@app.post("/v1/answer", response_model=None)
def answer(
    req: AnswerRequest,
    auth: Annotated[Authorized, Depends(authorize("answer"))],
    answerer: Annotated[AnswerPipeline, Depends(get_answerer)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    audit: Annotated[AuditLog, Depends(get_audit)],
    tenant: Annotated[str, Depends(get_tenant)],
) -> AnswerOut | StreamingResponse:
    """Retrieve (as this person), answer with citations, record it. Same token, policy and audit
    rules as /v1/search; the question and answer text are never written to the audit log."""
    p, f = auth.principal, auth.decision.filter
    # OPA only returns known classification names
    levels = cast(tuple[Classification, ...], tuple(sorted(f.classifications)))
    who = CorePrincipal(p.subject, tuple(sorted(f.groups)), levels, tenant)
    started, answer_id = time.perf_counter(), _answer_id()
    context_ids: dict[str, int] = {}
    completed: dict[str, bool] = {}  # was the answer itself in the first audit record?

    def post_check(hits: list[ScoredChunk]) -> list[ScoredChunk]:
        """OPA re-checks every document before it can reach the model (as /v1/search does)."""
        if not f.classifications:
            return []  # fail closed: no clearance, no documents
        refs = {document_id(h.chunk): DocumentRef(document_id(h.chunk), h.chunk.access.classification,
                                                  h.chunk.access.groups) for h in hits}  # fmt: skip
        try:
            allowed = policy.readable(p, list(refs.values()))
        except PolicyUnavailable as e:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Policy engine unavailable"
            ) from e
        if dropped := [i for i in refs if i not in allowed]:
            DROPPED.add(len(dropped))
            log.error("query/policy mismatch: dropped documents %s for sub=%s", dropped, p.subject)
        return [h for h in hits if document_id(h.chunk) in allowed]

    def record(
        context: PackedContext | None, early: Answer | None, final: Answer | None = None
    ) -> None:
        """Before anything is handed out: who, which documents went to the model, which prompt."""
        if context is not None:
            context_ids.update({h.chunk.id: document_id(h.chunk) for h in context.chunks})
        a = final or early
        completed["recorded"] = a is not None
        record_or_refuse(audit, audit_event(
            p, "answer", "allowed", "documents", answer_id=answer_id,
            context_ids=sorted(set(context_ids.values())),
            cited_ids=sorted({context_ids.get(c.chunk_id, -1) for c in a.citations}) if a else None,
            result=_outcome(a) if a else "streaming", cache=(a.trace.get("cache") if a else None),
            prompts=[str(getattr(answerer.generator, "prompt_ref", "?"))],
            model=str(getattr(answerer.generator, "model", "?")), question_chars=len(req.question),
            session=req.session_id is not None, usage=dict(a.usage) if a else {},
            guards=_verdicts(a), blocked=a.blocked if a else None,
        ))  # fmt: skip

    if not req.stream:
        seen: dict[str, PackedContext | None] = {}
        try:
            a = answerer.answer(req.question, who, session_id=req.session_id, post_check=post_check,
                                before_generation=lambda ctx, early: seen.update(ctx=ctx))  # fmt: skip
            record(seen.get("ctx"), None, final=a)  # recorded BEFORE the answer is returned
        except HTTPException:
            ANSWERS.add(1, {"outcome": "error"})
            raise
        ANSWERS.add(1, {"outcome": _outcome(a)})
        ANSWER_TIME.record(time.perf_counter() - started, {"stream": False})
        return AnswerOut(answer_id=answer_id, text=a.text, abstained=a.abstained, blocked=bool(a.blocked),
                         citations=_citations(a, context_ids))  # fmt: skip

    events = answerer.stream(req.question, who, session_id=req.session_id, post_check=post_check,
                             before_generation=lambda ctx, early: record(ctx, early))  # fmt: skip
    try:
        # search, OPA post-check and the audit record happen HERE: errors are real HTTP errors
        first = next(events)
    except HTTPException:
        ANSWERS.add(1, {"outcome": "error"})
        raise
    ANSWER_TIME.record(time.perf_counter() - started, {"stream": True})

    def sse() -> Iterator[str]:
        def frame(kind: str, data: object) -> str:
            return f"event: {kind}\ndata: {json.dumps(data)}\n\n"

        yield frame("meta", {"answer_id": answer_id, **first.data})
        try:
            for ev in events:
                if ev.kind == "delta":
                    yield frame("delta", {"text": ev.data})
                elif ev.kind == "done":
                    a: Answer = ev.data
                    ANSWERS.add(1, {"outcome": _outcome(a)})
                    yield frame("done", AnswerOut(answer_id=answer_id, text=a.text, abstained=a.abstained,
                                                  blocked=bool(a.blocked), citations=_citations(a, context_ids)).model_dump())  # fmt: skip
                    if not completed.get("recorded"):
                        # streaming: after "done", the record is completed (best effort: the text is
                        # already sent). Output guard verdicts, the citations and usage land here.
                        record_best_effort(audit, audit_event(
                            p, "answer.completed", "allowed", "documents", answer_id=answer_id,
                            cited_ids=sorted({context_ids.get(c.chunk_id, -1) for c in a.citations}),
                            result=_outcome(a), guards=_verdicts(a), blocked=a.blocked, usage=dict(a.usage),
                        ))  # fmt: skip
        # the model failed mid-answer: tell the client, never a half answer as "done"
        except Exception:
            ANSWERS.add(1, {"outcome": "error"})
            log.exception("answer stream failed")
            yield frame(
                "error", {"answer_id": answer_id, "message": "The answer could not be completed."}
            )

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})  # fmt: skip


class FeedbackRequest(BaseModel):
    answer_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    rating: Literal["up", "down"]
    # A fixed list, not free text: free text would collect personal data into the audit log
    reason: Literal["wrong", "incomplete", "outdated", "not_relevant", "unsafe", "other"] | None = (
        None
    )


@app.post("/v1/feedback", status_code=status.HTTP_202_ACCEPTED)
def feedback(
    req: FeedbackRequest,
    auth: Annotated[Authorized, Depends(authorize("feedback"))],
    audit: Annotated[AuditLog, Depends(get_audit)],
) -> dict[str, str]:
    """Thumbs up/down on an answer: the raw material for Step 37's online evaluation."""
    record_or_refuse(audit, audit_event(auth.principal, "feedback", "allowed", f"answer:{req.answer_id}",
                                        rating=req.rating, reason=req.reason))  # fmt: skip
    FEEDBACK.add(1, {"rating": req.rating, "reason": req.reason or "none"})
    return {"status": "recorded"}
