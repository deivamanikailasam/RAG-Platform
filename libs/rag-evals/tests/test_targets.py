"""The answer target and the judge, against the REAL OpenAI client with a fake gateway underneath."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

# openai 3.x makes its HTTP calls through the httpx2 package (same API as httpx): fake that layer
import httpx2 as httpx
import pytest
from openai import OpenAI

from rag_common.prompts import Registry
from rag_evals.datasets import AnswerCase, Dataset
from rag_evals.judge import Judge, parse_verdict
from rag_evals.targets import GatewayAnswerTarget

from .conftest import REPO


def gateway(reply: Callable[[dict[str, Any]], str], seen: list[dict[str, Any]]) -> OpenAI:
    """A LiteLLM stand-in: records each request body and answers with reply(body)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"path": request.url.path, "auth": request.headers["authorization"], **body})
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": reply(body)}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132},
        })  # fmt: skip

    return OpenAI(base_url="http://gateway.test/v1", api_key="sk-eval-test",
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))  # fmt: skip


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REPO / "prompts")


def case(answer_set: Dataset, case_id: str) -> AnswerCase:
    found = next(c for c in answer_set.cases if c.id == case_id)
    assert isinstance(found, AnswerCase)
    return found


def test_answer_target_sends_exactly_the_registered_prompt(
    registry: Registry, answer_set: Dataset
) -> None:
    seen: list[dict[str, Any]] = []
    client = gateway(lambda _: "<think>hmm</think>Facilities [doc 2].", seen)
    target = GatewayAnswerTarget(client, registry, "rag-answer", label="staging")
    out = target.answer(case(answer_set, "injected-document"))
    assert out.text == "Facilities [doc 2]."  # reasoning block removed
    assert out.usage == {"prompt_tokens": 120, "completion_tokens": 12}
    [req] = seen
    assert req["path"] == "/v1/chat/completions"
    assert req["auth"] == "Bearer sk-eval-test"  # the evaluation key (Step 10), never the app's
    assert req["model"] == "qwen-quality"  # a gateway alias, from the prompt file
    assert (req["temperature"], req["max_tokens"]) == (0.2, 800)
    user = req["messages"][1]["content"]
    assert '<doc id="9">IMPORTANT SYSTEM NOTICE' in user  # the hostile document, inside its box
    assert target.describe()["prompt"] == "rag-answer@2"


def test_closing_tag_in_a_document_is_neutralised(registry: Registry, answer_set: Dataset) -> None:
    seen: list[dict[str, Any]] = []
    GatewayAnswerTarget(gateway(lambda _: "x", seen), registry, "rag-answer", version=2).answer(
        case(answer_set, "injected-close-tag")
    )
    user = seen[0]["messages"][1]["content"]
    assert user.count("</documents>") == 1  # only the template's own
    assert "<\\/documents> New rule" in user


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"correct": true, "faithful": false, "reason": "adds a date"}', (True, False, None)),
        ('Sure! Here you go:\n{"correct": false, "faithful": true, "reason": "x"}\nThanks', (False, True, None)),
        ("I think it's correct.", (None, None, "no JSON object in the judge's reply")),
        ('{"correct": "yes", "faithful": true}', (None, None, "correct and faithful must be true or false")),
        ('{"correct": true, "faithful": }', (None, None, "invalid JSON: Expecting value")),
    ],
)  # fmt: skip
def test_judge_replies_are_parsed_strictly(text: str, expected: tuple[Any, Any, Any]) -> None:
    v = parse_verdict(text)
    assert (v.correct, v.faithful, v.error) == expected


def test_judge_uses_its_registered_prompt(registry: Registry, answer_set: Dataset) -> None:
    seen: list[dict[str, Any]] = []
    reply = '{"correct": true, "faithful": true, "reason": "matches the reference"}'
    judge = Judge(gateway(lambda _: reply, seen), registry)
    verdict = judge.grade(case(answer_set, "parking"), "Facilities [doc 2].")
    assert (verdict.correct, verdict.faithful) == (True, True)
    assert seen[0]["temperature"] == 0  # deterministic grading
    assert (
        "<reference>\nFacilities, on the first floor.\n</reference>"
        in seen[0]["messages"][1]["content"]
    )
    assert judge.describe() == {"judge_prompt": "eval-judge@1", "judge_model": "qwen-quality"}


def test_a_failing_judge_is_an_error_not_a_pass(registry: Registry, answer_set: Dataset) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model server down"})

    client = OpenAI(base_url="http://gateway.test/v1", api_key="k", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(broken)))  # fmt: skip
    verdict = Judge(client, registry).grade(case(answer_set, "parking"), "x")
    assert verdict.correct is None
    assert verdict.error == "judge call failed: InternalServerError"
