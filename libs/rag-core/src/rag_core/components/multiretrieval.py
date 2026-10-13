"""Several retrievers at once (extension 01): the ensemble runs N of them in parallel and fuses
their lists; the router picks the right one (a collection, a profile, a retriever) per question.

    retriever:
      use: ensemble                                  # dense + keyword + a second collection, fused
      members:
        - {name: vectors,  retriever: {use: dense, candidates: 40}, weight: 1.0}
        - {name: keywords, retriever: {use: keyword}, weight: 0.7}
        - {name: archive,  retriever: {use: dense}, slots: {vector_store: {use: pgvector, collection: archive}}}

    retriever:
      use: router                                    # one index per department
      default: general
      routes:
        hr:      {keywords: [leave, payroll, parental], slots: {vector_store: {use: pgvector, collection: hr}}}
        it:      {keywords: [vpn, laptop, password], profile: it-helpdesk}
        general: {retriever: {use: hybrid}}

A member or route can change any slot (`slots`), use another profile of rag.yaml (`profile`), or
add a metadata filter (`filter`). Every slot it doesn't change is SHARED with the main profile
(same embedder, same stores), and the permission filter always applies: a route can narrow what
a person sees, never widen it.
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import partial
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core import filters as _filters
from rag_core.components.basics import words
from rag_core.components.retrieval import ReciprocalRankFusion, _run_all
from rag_core.registry import ComponentError, Container, Overlay, register, spec
from rag_core.types import Query, ScoredChunk

log = logging.getLogger("rag_core.multiretrieval")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(_Strict):
    """Where a member or a route searches: a retriever, on the main profile with some slots
    changed, or on another profile of a rag.yaml."""

    retriever: dict[str, Any] = Field(default_factory=lambda: {"use": "hybrid"})
    slots: dict[str, Any] = Field(
        default_factory=dict
    )  # e.g. {vector_store: {use: pgvector, collection: hr}}
    profile: str | None = None  # another profile of `file` (its own stores and settings)
    file: str | None = None  # default: $RAG_CONFIG or rag.yaml
    filter: dict[str, Any] = Field(default_factory=dict)  # a metadata filter added to every search

    @model_validator(mode="after")
    def _check(self) -> Target:
        if "use" not in self.retriever:
            raise ValueError("retriever: expected {use: <name>, …}")
        if self.profile and self.slots:
            raise ValueError("give a profile OR slots, not both")
        _filters.parse(self.filter)  # a bad filter fails at `rag config validate`
        return self


def _container(parent: Container, t: Target, name: str) -> Container:
    if t.profile:
        from rag_core import config as cfg

        return cfg.load(t.file or os.environ.get("RAG_CONFIG", "rag.yaml"), t.profile)
    return Overlay(parent, t.slots, f"{parent.profile}/{name}") if t.slots else parent


def _build_retriever(c: Container, raw: dict[str, Any]) -> Any:
    s = spec("retriever", str(raw["use"]))
    try:
        p = s.params.model_validate({k: v for k, v in raw.items() if k != "use"})
    except ValueError as e:
        raise ComponentError(f"retriever {s.name!r}: {e}") from None
    return s.factory(p, c)


class _Lazy:
    """A member/route's retriever, built on first use (a route that is never chosen costs nothing)."""

    def __init__(self, parent: Container, target: Target, name: str) -> None:
        self.parent, self.t, self.name = parent, target, name
        self._r: Any = None
        self._lock = threading.Lock()

    def get(self) -> Any:
        with self._lock:
            if self._r is None:
                self._r = _build_retriever(
                    _container(self.parent, self.t, self.name), self.t.retriever
                )
        return self._r

    def retrieve(self, query: Query, texts: Sequence[str]) -> list[ScoredChunk]:
        if self.t.filter:
            query = replace(query, filters=_filters.combine(query.filters, self.t.filter))
        hits: list[ScoredChunk] = self.get().retrieve(query, texts)
        return hits


class _Info(threading.local):
    """What the last retrieval in THIS thread did (which route, how many hits per member), for the
    search trace. Thread-local: rag-api serves many requests at once with one retriever."""

    last: dict[str, Any] | None = None


def _fuse(fusion: Any, lists: list[list[ScoredChunk]], weights: list[float]) -> list[ScoredChunk]:
    if "list_weights" in inspect.signature(fusion.fuse).parameters:
        fused: list[ScoredChunk] = fusion.fuse(lists, list_weights=weights)
    else:  # a project's own fusion without per-list weights
        fused = fusion.fuse(lists)
    return fused


# ================================================================ ensemble


class Member(Target):
    name: str | None = None
    weight: float = Field(1.0, ge=0)


class EnsembleParams(_Strict):
    members: list[Member] = Field(min_length=2, max_length=8)
    parallel: bool = True  # all members at once: latency = the slowest, not the sum

    @model_validator(mode="after")
    def _names(self) -> EnsembleParams:
        names = [m.name or str(m.retriever["use"]) for m in self.members]
        if len(set(names)) != len(names):
            raise ValueError(f"member names must be unique (got {names}); give each a name")
        return self


class EnsembleRetriever:
    """N retrievers run in parallel, their lists merged by the fusion slot (rrf by default) with
    one weight per member. Dense + keyword is the hybrid retriever; an ensemble adds more: a second
    collection, a second embedding model, a sparse (learned) index, a project's own retriever."""

    def __init__(self, c: Container, p: EnsembleParams) -> None:
        self.c, self.p = c, p
        self.members = [(m.name or str(m.retriever["use"]), m.weight, _Lazy(c, m, m.name or str(m.retriever["use"])))
                        for m in p.members]  # fmt: skip
        self._fusion: Any = None
        self._info = _Info()

    @property
    def fusion(self) -> Any:
        if self._fusion is None:
            self._fusion = self.c.get("fusion") if self.c.has("fusion") else ReciprocalRankFusion()
        return self._fusion

    def retrieve(self, query: Query, texts: Sequence[str]) -> list[ScoredChunk]:
        jobs: list[Callable[[], list[ScoredChunk]]] = [
            partial(m.retrieve, query, texts) for _, _, m in self.members
        ]
        lists = _run_all(jobs, self.p.parallel)
        self._info.last = {
            "members": {name: len(h) for (name, _, _), h in zip(self.members, lists, strict=True)}
        }
        kept = [(h, w) for (_, w, _), h in zip(self.members, lists, strict=True) if h]
        if not kept:
            return []
        if len(kept) == 1:
            return list(kept[0][0])
        return _fuse(self.fusion, [h for h, _ in kept], [w for _, w in kept])

    def last_info(self) -> dict[str, Any]:
        return dict(self._info.last or {})


@register("retriever", "ensemble", params=EnsembleParams,
          summary="N retrievers in parallel (other collections, models, profiles), fused with per-member weights")  # fmt: skip
def _ensemble(p: EnsembleParams, c: Container) -> EnsembleRetriever:
    return EnsembleRetriever(c, p)


# ================================================================ router


class Route(Target):
    description: str = ""  # what this route holds: what the LLM router reads
    keywords: list[str] = Field(default_factory=list)  # words or phrases that send a question here


class RouterParams(_Strict):
    routes: dict[str, Route] = Field(min_length=1)
    default: str | None = None  # no route matched: this one (default: the first)
    mode: Literal["rules", "llm"] = (
        "rules"  # llm: the model picks from the descriptions; rules if it fails
    )
    llm_slot: Literal["llm", "judge_llm"] = "llm"
    multi: bool = False  # search EVERY matching route and fuse (a question about two departments)

    @model_validator(mode="after")
    def _check(self) -> RouterParams:
        if self.default is not None and self.default not in self.routes:
            raise ValueError(f"default {self.default!r} is not a route ({', '.join(self.routes)})")
        bad = [n for n in self.routes if not re.fullmatch(r"[A-Za-z0-9_\-]+", n)]
        if bad:
            raise ValueError(f"route names may only hold letters, digits, _ and - (got {bad})")
        return self


ROUTER_PROMPT = (
    "Pick the collection(s) to search for the user's question. Collections:\n{routes}\n\n"
    "Reply with the collection name only{multi}. If none fits, reply {default}."
)


class Router:
    """Sends each question to the right index. Rules: the route whose keywords appear most in the
    question (ties: the first declared). LLM: the model reads the routes' descriptions and names
    one; an unusable reply falls back to the rules, so routing never takes search down."""

    def __init__(self, c: Container, p: RouterParams, llm: Any = None) -> None:
        self.c, self.p, self.llm = c, p, llm
        self.routes = {name: _Lazy(c, r, name) for name, r in p.routes.items()}
        self.default = p.default or next(iter(p.routes))
        self._fusion: Any = None
        self._info = _Info()

    def by_rules(self, question: str) -> list[str]:
        text = f" {' '.join(words(question))} "
        scores = {name: sum(f" {' '.join(words(k))} " in text for k in r.keywords if words(k))
                  for name, r in self.p.routes.items()}  # fmt: skip
        best = max(scores.values(), default=0)
        if best == 0:
            return [self.default]
        if self.p.multi:
            return [n for n, s in scores.items() if s > 0]
        return [next(n for n, s in scores.items() if s == best)]

    def by_llm(self, question: str) -> list[str] | None:
        routes = "\n".join(
            f"- {n}: {r.description or ', '.join(r.keywords) or n}"
            for n, r in self.p.routes.items()
        )
        system = ROUTER_PROMPT.format(routes=routes, default=self.default,
                                      multi=" (several, comma-separated, if the question needs them)" if self.p.multi else "")  # fmt: skip
        try:
            reply = str(self.llm.complete(system, question, max_tokens=40))
        except Exception as e:  # a helper must never take search down
            log.warning("LLM router failed, using the rules: %s", e)
            return None
        said = [w for w in re.findall(r"[A-Za-z0-9_\-]+", reply) if w in self.p.routes]
        said = list(dict.fromkeys(said))
        return (said if self.p.multi else said[:1]) or None

    def choose(self, question: str) -> tuple[list[str], str]:
        if self.p.mode == "llm" and self.llm is not None:
            picked = self.by_llm(question)
            if picked:
                return picked, "llm"
            return self.by_rules(question), "rules (llm fallback)"
        return self.by_rules(question), "rules"

    @property
    def fusion(self) -> Any:
        if self._fusion is None:
            self._fusion = self.c.get("fusion") if self.c.has("fusion") else ReciprocalRankFusion()
        return self._fusion

    def retrieve(self, query: Query, texts: Sequence[str]) -> list[ScoredChunk]:
        names, how = self.choose(query.text)
        self._info.last = {"route": names if self.p.multi else names[0], "how": how}
        lists = _run_all([partial(self.routes[n].retrieve, query, texts) for n in names], True)
        lists = [h for h in lists if h]
        if not lists:
            return []
        if len(lists) == 1:
            return list(lists[0])
        return _fuse(self.fusion, lists, [1.0] * len(lists))

    def last_info(self) -> dict[str, Any]:
        return dict(self._info.last or {})


@register("retriever", "router", params=RouterParams,
          summary="route each question to a named collection/profile/retriever (keyword rules, or an LLM)")  # fmt: skip
def _router(p: RouterParams, c: Container) -> Router:
    return Router(c, p, c.get(p.llm_slot) if p.mode == "llm" else None)


__all__ = ["EnsembleRetriever", "Router"]
