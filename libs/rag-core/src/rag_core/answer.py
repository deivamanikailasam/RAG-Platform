"""The answer pipeline (Step 33): question in, a cited answer (or an honest "I don't know") out.

    pipeline = AnswerPipeline(config.load("rag.yaml", "local"))
    answer = pipeline.answer("How many leave days do I get?", principal, session_id="s-42")
    for event in pipeline.stream(...): ...   # ("meta", …), ("delta", "Full"), …, ("done", Answer)

Order of work, and why:
   memory   → the conversation so far, so follow-ups make sense
   guards   → input checks (Step 34) before anything is spent: a block returns a fixed message
   cache    → same question, same access, same index and prompt: reuse
   retrieve → the architecture in the `pipeline` slot (Step 35) gathers context: by default
              Step 32's search; naive, corrective, adaptive, agentic, graph or sql otherwise, and
              extension 03's vector, keyword, pageindex, rag-fusion, hyde, flare, speculative,
              graph-global, long-context, table and conversational
   check    → the caller's own post-check (e.g. OPA in rag-api), via context_for
   guards   → context checks (Step 34): documents that give orders are dropped
   compress → extension 02: keep only what matters for the question (token savings in the trace)
   abstain  → nothing relevant found: say so, without calling a model
   context  → numbered <doc> blocks within a token budget
   generate → the registered prompt, the answer model; streamed or whole
   cite     → keep only citations that point at a document that was shown
   guards   → output checks (Step 34): groundedness, personal data, secrets, toxicity
   format   → extension 04: citation style and quotes, confidence, follow-ups, a JSON object
   review   → a reviewing architecture (self-reflective) may retrieve again and regenerate
   remember, cache, return (with a trace of everything above): once, after any review, so a
              replaced draft is never remembered or cached
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

from rag_core.components.architectures import Standard
from rag_core.components.basics import ApproxTokenCounter
from rag_core.components.compression import compress_all
from rag_core.components.conversation import cache_key
from rag_core.components.formatting import format_all
from rag_core.components.generation import (
    AnswerParams,
    ContextParams,
    NumberedContext,
    PackedContext,
    check_citations,
    is_abstention,
)
from rag_core.components.guards import GeneratedAnswer
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
        # Step 35: the pipeline slot holds an architecture; its params are the answer settings
        self.arch: Any = (
            container.get("pipeline") if container.has("pipeline") else Standard(AnswerParams())
        )
        self.p: AnswerParams = self.arch.params
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
        # extension 02: shorten the retrieved chunks for the question before the context is built
        self.compressors = container.get("compressors") if container.has("compressors") else []
        self.counter = counter
        # extension 04: shape the checked answer (citation style, confidence, follow-ups, JSON)
        self.formatters = (
            container.get("answer_formatters") if container.has("answer_formatters") else []
        )

    # ------------------------------------------------------------------ guards (Step 34)

    def _guard(self, stage: str, query: Query, payload: Any, trace_data: dict[str, Any],
               usage: Mapping[str, int] | None = None) -> tuple[Any, Answer | None]:  # fmt: skip
        """Run one stage's guards. Returns the (possibly redacted) payload, or a blocked Answer.
        Every verdict that isn't "allow" goes into the trace: guard, stage, action, reasons."""
        for g in self.guards:
            if g.stage != stage:
                continue
            with tracer.start_as_current_span(
                f"rag.guard.{g.name}", attributes={"rag.guard.stage": stage}
            ) as span:
                v = g.check(query, payload)
                span.set_attribute("rag.guard.action", v.action)
            if v.action == "allow":
                continue
            trace_data.setdefault("guards", []).append(
                {"guard": g.name, "stage": stage, "action": v.action, "reasons": list(v.reasons)}
            )
            if v.action == "block":
                reason = "; ".join(v.reasons) or g.name
                # the person sees a fixed, helpful message; the reason goes to the trace and audit only
                message = v.replacement if isinstance(v.replacement, str) else self.p.blocked_text
                return payload, Answer(
                    text=message, blocked=reason, usage=dict(usage or {}), trace=trace_data
                )
            if v.action == "redact" and v.replacement is not None:
                # output guards may hand back just the corrected Answer: keep its sources with it
                if isinstance(payload, GeneratedAnswer) and isinstance(v.replacement, Answer):
                    payload = replace(payload, answer=v.replacement)
                else:
                    payload = v.replacement
            trace_data.setdefault("flags", []).extend(
                [f"{g.name}: {r}" for r in v.reasons] or [g.name]
            )
        return payload, None

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

        trace_data.setdefault("flags", [])
        text, blocked = self._guard("input", query, question, trace_data)
        if blocked is not None:
            return query, blocked, None
        query = replace(query, text=text)

        key = None
        if self.cache is not None:
            key = cache_key(principal, query.text, history,
                            _version(self.c, self.generator, self.cache), query.filters)  # fmt: skip
            # semantic lookups only for questions without a conversation (follow-ups depend on it)
            hit = self.cache.get(key, principal, "" if history else query.text)
            if hit is not None:
                trace_data["cache"] = "hit"
                return query, replace(hit, trace={**hit.trace, **trace_data, "cache": "hit"}), None
            trace_data["cache"] = "miss"
        trace_data["cache_key"] = key

        retrieval = self.arch.retrieve(self, query)
        trace_data["architecture"] = self.arch.name
        trace_data["search"] = retrieval.info
        if retrieval.direct is not None:
            # e.g. adaptive's reply to small talk: no retrieval, no model
            direct = replace(retrieval.direct, trace={**retrieval.direct.trace, **trace_data})
            return query, format_all(self.formatters, query, direct, (), trace_data), None
        context, stop = self.context_for(query, retrieval.hits, post_check, trace_data)
        return query, stop, context

    def context_for(self, query: Query, hits: list[ScoredChunk], post_check: PostCheck | None,
                    trace_data: dict[str, Any]) -> tuple[PackedContext | None, Answer | None]:  # fmt: skip
        """Post-check, context guards, abstain-if-empty, pack. Architectures that retrieve again
        (self-reflective) come back through here, so no check is ever skipped."""
        if post_check is not None:  # e.g. rag-api's OPA re-check of every document
            before = len(hits)
            hits = post_check(hits)
            trace_data["post_check_dropped"] = (
                trace_data.get("post_check_dropped", 0) + before - len(hits)
            )
        hits, stop = self._guard("context", query, hits, trace_data)
        if stop is not None:
            return None, stop
        if self.compressors and hits:
            with tracer.start_as_current_span("rag.compress") as span:
                hits, info = compress_all(self.compressors, query, hits, self.counter)
                span.set_attributes({"rag.compress.tokens_before": info["tokens_before"],
                                     "rag.compress.tokens_after": info["tokens_after"]})  # fmt: skip
            trace_data["compression"] = info
        if not hits and self.p.abstain_without_hits:
            trace_data["abstained_reason"] = "no relevant documents"
            empty = Answer(text=self.p.abstain_text, abstained=True, trace=trace_data)
            return None, format_all(self.formatters, query, empty, (), trace_data)
        with tracer.start_as_current_span("rag.context") as span:
            context = self.builder.build(query, hits)
            span.set_attributes({"rag.context.chunks": len(context.chunks), "rag.context.tokens": context.tokens,
                                 "rag.context.dropped": context.dropped})  # fmt: skip
        trace_data["context"] = {"chunks": [h.chunk.id for h in context.chunks], "tokens": context.tokens,
                                 "dropped": context.dropped,
                                 "documents": sorted({h.chunk.document_uri for h in context.chunks})}  # fmt: skip
        return context, None

    def generate(self, query: Query, context: PackedContext, trace_data: dict[str, Any]) -> Answer:
        """Generate and check one answer (citations, output guards). Not remembered or cached yet:
        a reviewing architecture may still replace it."""
        with tracer.start_as_current_span(
            "rag.generate", attributes={"gen_ai.operation.name": "chat"}
        ) as g:
            # extension 03: an architecture may write the answer itself (speculative: drafts from
            # evidence subsets, a verifier picks one); citations and guards below still apply
            draft = getattr(self.arch, "draft", None)
            generated = (
                draft(self, query, context, trace_data)
                if draft is not None
                else self.generator.generate(query, context)
            )
            g.set_attribute("gen_ai.request.model", str(getattr(self.generator, "model", "?")))
            for k, v in generated.usage.items():
                g.set_attribute(f"gen_ai.usage.{k}", v)
        return self._finish(query, generated.text, generated.usage, context, trace_data)

    def _finish(self, query: Query, raw: str, usage: Mapping[str, int], context: PackedContext,
                trace_data: dict[str, Any]) -> Answer:  # fmt: skip
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
        # output guards see the answer AND the documents it was given (groundedness needs both)
        out, blocked = self._guard(
            "output", query, GeneratedAnswer(answer, context.chunks), trace_data, usage
        )
        if blocked is not None:
            return blocked
        final = out.answer if isinstance(out, GeneratedAnswer) else answer
        return format_all(self.formatters, query, final, context.chunks, trace_data)

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
            answer = self.generate(query, context, trace_data)
            if not answer.blocked:  # a reviewing architecture may retrieve again and regenerate
                answer = self.arch.review(self, query, answer, context, trace_data, post_check)
            self._remember(query, answer, session_id, trace_data)
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
        if self.arch.reviews:  # the first answer may be replaced: never stream it as a draft
            done = self.generate(query, context, trace_data)
            if not done.blocked:
                done = self.arch.review(self, query, done, context, trace_data, post_check)
            self._remember(query, done, session_id, trace_data)
            yield Event("delta", done.text)
            yield Event("done", done)
            return
        if self.p.stream == "checked":  # generate fully, check, then send: never unchecked text
            parts = list(self.generator.stream(query, context, usage))
            done = self._finish(query, "".join(parts), usage, context, trace_data)
            self._remember(query, done, session_id, trace_data)
            yield Event("delta", done.text)
            yield Event("done", done)
            return
        parts = []
        for delta in self.generator.stream(query, context, usage):
            parts.append(delta)
            yield Event("delta", delta)
        done = self._finish(query, "".join(parts), usage, context, trace_data)
        self._remember(query, done, session_id, trace_data)
        yield Event("done", done)


def answer_dict(a: Answer) -> dict[str, Any]:
    out = {"text": a.text, "abstained": a.abstained, "blocked": a.blocked, "usage": dict(a.usage),
           "citations": [{"n": c.marker, "chunk_id": c.chunk_id, "document": c.document_uri, "title": c.title}
                         for c in a.citations]}  # fmt: skip
    if a.extras:  # extension 04: what the answer formatters added
        out["extras"] = dict(a.extras)
    return out
