"""What gets evaluated ("targets"): retrieval as a given person, and answers from a prompt version.

Both reuse production code instead of re-implementing it:
  * PolicySearchTarget calls the same SearchBackend and PolicyEngine as rag-api's /v1/search,
    in the same order (policy filter -> search -> post-check). A test keeps the two in step.
  * GatewayAnswerTarget renders a REGISTERED prompt version (Step 24) and calls the gateway with
    the evaluation key (Step 10), so results name the exact prompt and model alias they measured.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI

from rag_api.policy import PolicyEngine
from rag_api.search import SearchBackend
from rag_common.auth import Principal
from rag_common.prompts import Registry, Rendered
from rag_evals.datasets import AnswerCase, Context, Persona, RetrievalCase


def principal_for(p: Persona) -> Principal:
    """A synthetic identity for an evaluation persona. Never a real person's account."""
    return Principal(subject=f"eval-{p.name}", username=f"eval-{p.name}", client_id="eval-harness",
                     groups=frozenset(p.groups), roles=frozenset(p.roles))  # fmt: skip


@dataclass(frozen=True)
class RetrievalOutput:
    ranked: list[int]  # what the person would receive, best first
    dropped: list[int]  # returned by the query but refused by the post-check (should be empty)
    allowed: bool  # did the policy allow searching at all?
    latency_s: float


@dataclass(frozen=True)
class AnswerOutput:
    text: str
    latency_s: float
    usage: dict[str, int] = field(default_factory=dict)


class RetrievalTarget(Protocol):
    def retrieve(self, case: RetrievalCase, k: int) -> RetrievalOutput: ...
    def describe(self) -> dict[str, Any]: ...


class AnswerTarget(Protocol):
    def answer(self, case: AnswerCase) -> AnswerOutput: ...
    def describe(self) -> dict[str, Any]: ...


class PolicySearchTarget:
    def __init__(self, backend: SearchBackend, policy: PolicyEngine, info: dict[str, Any]) -> None:
        self._backend, self._policy, self._info = backend, policy, info

    def describe(self) -> dict[str, Any]:
        return {"target": "policy-search", **self._info}

    def retrieve(self, case: RetrievalCase, k: int) -> RetrievalOutput:
        started = time.perf_counter()
        who = principal_for(case.persona)
        decision = self._policy.decide(who, "search")
        if not decision.allow:
            return RetrievalOutput([], [], False, time.perf_counter() - started)
        f = decision.filter
        candidates = self._backend.search(case.question, groups=f.groups,
                                          classifications=f.classifications, k=k, user=who.subject)  # fmt: skip
        allowed = self._policy.readable(who, [c.ref for c in candidates])
        return RetrievalOutput(
            ranked=[c.ref.id for c in candidates if c.ref.id in allowed],
            dropped=[c.ref.id for c in candidates if c.ref.id not in allowed],
            allowed=True,
            latency_s=time.perf_counter() - started,
        )


THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)  # Qwen3 reasoning, if a server leaves it on


def chat(client: OpenAI, r: Rendered) -> tuple[str, dict[str, int]]:
    """One chat call with a rendered prompt: its model alias, messages and parameters, nothing else."""
    completions: Any = client.chat.completions  # params come from the prompt file, so typed loosely
    resp = completions.create(model=r.model or "", messages=list(r.messages), **dict(r.params))
    text = THINK.sub("", resp.choices[0].message.content or "").strip()
    usage = ({"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens}
             if resp.usage else {})  # fmt: skip
    return text, usage


def format_contexts(contexts: tuple[Context, ...]) -> str:
    return "\n".join(f'<doc id="{c.id}">{c.text}</doc>' for c in contexts)


class GatewayAnswerTarget:
    def __init__(self, client: OpenAI, registry: Registry, prompt: str, *, label: str | None = None,
                 version: int | None = None) -> None:  # fmt: skip
        self._client, self._registry = client, registry
        self._prompt, self._label, self._version = prompt, label, version
        self._p, self._sha = registry.get(prompt, label=label, version=version)

    def describe(self) -> dict[str, Any]:
        return {"target": "gateway-answer", "prompt": self._p.ref, "prompt_sha256": self._sha,
                "model": self._p.model, "params": dict(self._p.params)}  # fmt: skip

    def answer(self, case: AnswerCase) -> AnswerOutput:
        r = self._registry.render(
            self._prompt, {"context": format_contexts(case.contexts), "question": case.question},
            label=self._label, version=self._version,
        )  # fmt: skip
        started = time.perf_counter()
        text, usage = chat(self._client, r)
        return AnswerOutput(text, time.perf_counter() - started, usage)
