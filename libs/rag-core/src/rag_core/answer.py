"""The answer pipeline (Step 33): question in, a cited answer (or an honest "I don't know") out.

    pipeline = AnswerPipeline(config.load("rag.yaml", "local"))
    answer = pipeline.answer("How many leave days do I get?", principal, session_id="s-42")
    for event in pipeline.stream(...): ...   # ("meta", …), ("delta", "Full"), …, ("done", Answer)

Order of work, and why:
   memory   → the conversation so far, so follow-ups make sense
   guards   → input checks (Step 34) before anything is spent
   cache    → same question, same access, same index and prompt: reuse
   search   → Step 32's pipeline (+ the caller's own post-check, e.g. OPA in rag-api)
   abstain  → nothing relevant found: say so, without calling a model
   context  → numbered <doc> blocks within a token budget
   generate → the registered prompt, the answer model; streamed or whole
   cite     → keep only citations that point at a document that was shown
   guards   → output checks (Step 34)
   remember, cache, return (with a trace of everything above)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from opentelemetry import trace

from rag_core.components.basics import ApproxTokenCounter
from rag_core.components.conversation import cache_key
from rag_core.components.generation import (
    AnswerParams,
    ContextParams,
    NumberedContext,
    PackedContext,
    check_citations,
    is_abstention,
)
from rag_core.registry import Container
from rag_core.search import SearchPipeline
from rag_core.types import Answer, Principal, Query, ScoredChunk, Turn

log = logging.getLogger("rag_core.answer")
tracer = trace.get_tracer("rag_core.answer")

PostCheck = Callable[[list[ScoredChunk]], list[ScoredChunk]]


@dataclass(frozen=True)
class Event:
    kind: Literal["meta", "delta", "done"]
    data: Any


def _version(c: Container, generator: Any, cache: Any) -> str:
    """Everything that changes an answer: settings, prompt, model, and the index epoch."""
    raw = json.dumps(dict(c.config), sort_keys=True, default=str)
    parts = [hashlib.sha256(raw.encode()).hexdigest()[:12], str(getattr(generator, "prompt_ref", "")),
             str(getattr(generator, "model", "")), cache.epoch() if cache is not None else "0"]  # fmt: skip
    return "|".join(parts)


class AnswerPipeline:
    def __init__(self, container: Container) -> None:
        self.c = container
        self.search = SearchPipeline(container)
        self.p: AnswerParams = (
            container.get("pipeline") if container.has("pipeline") else AnswerParams()
        )
        counter = (
            container.get("token_counter")
            if container.has("token_counter")
            else ApproxTokenCounter()
        )
        self.builder = (container.get("context_builder") if container.has("context_builder")
                        else NumberedContext(ContextParams(), counter))  # fmt: skip
        self.generator = container.get("generator")
        self.memory = container.get("memory") if container.has("memory") else None
        self.cache = container.get("cache") if container.has("cache") else None
        self.guards = container.get("guards") if container.has("guards") else []

    # ------------------------------------------------------------------ guards (Step 34)

    def _guard(self, stage: str, query: Query, payload: Any) -> tuple[Any, str | None, list[str]]:
        """Run the guards for one stage. Returns (payload, block reason or None, flags)."""
        flags: list[str] = []
        for g in self.guards:
            if g.stage != stage:
                continue
            with tracer.start_as_current_span(
                f"rag.guard.{g.name}", attributes={"rag.guard.stage": stage}
            ) as span:
                v = g.check(query, payload)
                span.set_attribute("rag.guard.action", v.action)
            if v.action == "block":
                return payload, "; ".join(v.reasons) or g.name, flags
            if v.action == "redact" and v.replacement is not None:
                payload = v.replacement
            if v.action in ("redact", "flag"):
                flags += [f"{g.name}: {r}" for r in v.reasons] or [g.name]
        return payload, None, flags

    # ------------------------------------------------------------------ the steps

    def _prepare(self, question: str, principal: Principal, session_id: str | None,
                 filters: Mapping[str, Any] | None, post_check: PostCheck | None,
                 trace_data: dict[str, Any]) -> tuple[Query, Answer | None, PackedContext | None]:  # fmt: skip
        history: tuple[Turn, ...] = ()
        if self.memory is not None and session_id:
            history = (
                self.memory.history(principal, session_id)[-self.p.history_turns :]
                if self.p.history_turns
                else ()
            )
        query = Query(question, principal, filters or {}, history, k=self.p.search_k)

        text, blocked, flags = self._guard("input", query, question)
        trace_data["flags"] = flags
        if blocked:
            return query, Answer(text="", blocked=blocked, trace=trace_data), None
        query = replace(query, text=text)

        key = None
        if self.cache is not None:
            key = cache_key(
                principal, query.text, history, _version(self.c, self.generator, self.cache)
            )
            # semantic lookups only for questions without a conversation (follow-ups depend on it)
            hit = self.cache.get(key, principal, "" if history else query.text)
            if hit is not None:
                trace_data["cache"] = "hit"
                return query, replace(hit, trace={**hit.trace, **trace_data, "cache": "hit"}), None
            trace_data["cache"] = "miss"
        trace_data["cache_key"] = key

        result = self.search.search(query)
        hits = result.hits
        trace_data["search"] = result.trace
        if post_check is not None:  # e.g. rag-api's OPA re-check of every document
            before = len(hits)
            hits = post_check(hits)
            trace_data["post_check_dropped"] = before - len(hits)

        hits, blocked, flags = self._guard("context", query, hits)
        trace_data["flags"] += flags
        if blocked:
            return query, Answer(text="", blocked=blocked, trace=trace_data), None
        if not hits and self.p.abstain_without_hits:
            trace_data["abstained_reason"] = "no relevant documents"
            return query, Answer(text=self.p.abstain_text, abstained=True, trace=trace_data), None

        with tracer.start_as_current_span("rag.context") as span:
            context = self.builder.build(query, hits)
            span.set_attributes({"rag.context.chunks": len(context.chunks), "rag.context.tokens": context.tokens,
                                 "rag.context.dropped": context.dropped})  # fmt: skip
        trace_data["context"] = {"chunks": [h.chunk.id for h in context.chunks], "tokens": context.tokens,
                                 "dropped": context.dropped}  # fmt: skip
        return query, None, context

    def _finish(self, query: Query, raw: str, usage: Mapping[str, int], context: PackedContext,
                session_id: str | None, trace_data: dict[str, Any]) -> Answer:  # fmt: skip
        checked = check_citations(raw, context)
        text, abstained = checked.text, is_abstention(raw)
        trace_data |= {"model": getattr(self.generator, "model", "?"),
                       "prompt": getattr(self.generator, "prompt_ref", "?"), "invalid_citations": checked.invalid}  # fmt: skip
        if not abstained and not checked.citations and self.p.uncited != "keep":
            trace_data["uncited"] = True
            if self.p.uncited == "abstain":
                text, abstained = self.p.abstain_text, True
        answer = Answer(text=text, citations=() if abstained else checked.citations, abstained=abstained,
                        usage=dict(usage), trace=trace_data)  # fmt: skip
        out, blocked, flags = self._guard("output", query, answer)
        trace_data["flags"] += flags
        if blocked:
            return Answer(text="", blocked=blocked, usage=dict(usage), trace=trace_data)
        answer = out if isinstance(out, Answer) else answer
        self._remember(query, answer, session_id, trace_data)
        return answer

    def _remember(
        self, query: Query, answer: Answer, session_id: str | None, trace_data: dict[str, Any]
    ) -> None:
        if self.memory is not None and session_id and not answer.blocked:
            self.memory.append(
                query.principal,
                session_id,
                Turn("user", query.text),
                Turn("assistant", answer.text),
            )
        key = trace_data.get("cache_key")
        if self.cache is not None and key and not answer.blocked:
            self.cache.put(key, answer, query.principal, "" if query.history else query.text)

    # ------------------------------------------------------------------ public

    def answer(self, question: str, principal: Principal, *, session_id: str | None = None,
               filters: Mapping[str, Any] | None = None, post_check: PostCheck | None = None,
               before_generation: Callable[[PackedContext | None, Answer | None], None] | None = None,
               ) -> Answer:  # fmt: skip
        started = time.perf_counter()
        trace_data: dict[str, Any] = {}
        with tracer.start_as_current_span("rag.answer") as span:
            query, early, context = self._prepare(
                question, principal, session_id, filters, post_check, trace_data
            )
            if before_generation is not None:
                before_generation(context, early)
            if early is not None:
                if early.abstained and not early.blocked and trace_data.get("cache") != "hit":
                    self._remember(query, early, session_id, trace_data)
                span.set_attributes(
                    {
                        "rag.answer.abstained": early.abstained,
                        "rag.answer.blocked": bool(early.blocked),
                    }
                )
                return replace(
                    early,
                    trace={**early.trace, "ms": round((time.perf_counter() - started) * 1000, 1)},
                )
            if context is None:  # pragma: no cover - _prepare returns one or the other
                raise RuntimeError("no context and no early answer")
            with tracer.start_as_current_span(
                "rag.generate", attributes={"gen_ai.operation.name": "chat"}
            ) as g:
                generated = self.generator.generate(query, context)
                g.set_attribute("gen_ai.request.model", str(getattr(self.generator, "model", "?")))
                for k, v in generated.usage.items():
                    g.set_attribute(f"gen_ai.usage.{k}", v)
            answer = self._finish(
                query, generated.text, generated.usage, context, session_id, trace_data
            )
            span.set_attributes({"rag.answer.abstained": answer.abstained, "rag.answer.citations": len(answer.citations),
                                 "rag.answer.blocked": bool(answer.blocked)})  # fmt: skip
        return replace(
            answer, trace={**answer.trace, "ms": round((time.perf_counter() - started) * 1000, 1)}
        )

    def stream(self, question: str, principal: Principal, *, session_id: str | None = None,
               filters: Mapping[str, Any] | None = None, post_check: PostCheck | None = None,
               before_generation: Callable[[PackedContext | None, Answer | None], None] | None = None,
               ) -> Iterator[Event]:  # fmt: skip
        """Events: one "meta" (what the answer will be based on), "delta"s of text, one "done" with
        the checked Answer. `before_generation` runs before any text is produced: rag-api records
        its audit event there, so nothing reaches the user that wasn't recorded first."""
        trace_data: dict[str, Any] = {}
        query, early, context = self._prepare(
            question, principal, session_id, filters, post_check, trace_data
        )
        if before_generation is not None:
            before_generation(context, early)
        if early is not None:
            if early.abstained and not early.blocked and trace_data.get("cache") != "hit":
                self._remember(query, early, session_id, trace_data)
            yield Event("meta", {"documents": [], "cache": trace_data.get("cache")})
            if early.text:
                yield Event("delta", early.text)
            yield Event("done", early)
            return
        if context is None:  # pragma: no cover - _prepare returns one or the other
            raise RuntimeError("no context and no early answer")
        yield Event("meta", {"documents": [{"n": i, "document": h.chunk.document_uri, "title": h.chunk.metadata.get("title", "")}
                                           for i, h in enumerate(context.chunks, 1)]})  # fmt: skip
        usage: dict[str, int] = {}
        parts: list[str] = []
        for delta in self.generator.stream(query, context, usage):
            parts.append(delta)
            yield Event("delta", delta)
        yield Event(
            "done", self._finish(query, "".join(parts), usage, context, session_id, trace_data)
        )


def answer_dict(a: Answer) -> dict[str, Any]:
    return {"text": a.text, "abstained": a.abstained, "blocked": a.blocked, "usage": dict(a.usage),
            "citations": [{"n": c.marker, "chunk_id": c.chunk_id, "document": c.document_uri, "title": c.title}
                          for c in a.citations]}  # fmt: skip
