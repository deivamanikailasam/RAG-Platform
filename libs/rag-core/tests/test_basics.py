"""Built-in components pass the same conformance checks every adapter must pass (Step 30)."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from rag_core.components.basics import (
    ApproxTokenCounter,
    GatewayLLM,
    HashingEmbedder,
    MemoryKeywordIndex,
    MemoryVectorStore,
)
from rag_core.testing.conformance import check_embedder, check_keyword_index, check_vector_store


def test_hashing_embedder_conforms() -> None:
    check_embedder(HashingEmbedder(128))
    e = HashingEmbedder(128)
    assert e.embed_query("Annual leave") == e.embed_query(
        "annual LEAVE"
    )  # deterministic, case-insensitive


def test_memory_vector_store_conforms() -> None:
    check_vector_store(MemoryVectorStore, HashingEmbedder(256))


def test_memory_bm25_conforms() -> None:
    check_keyword_index(MemoryKeywordIndex)


def test_approx_token_counter() -> None:
    t = ApproxTokenCounter()
    assert t.count("") == 0
    assert t.count("a b c d e") == 5  # never fewer tokens than words
    assert t.count("x" * 40) == 10


def test_gateway_llm_sends_the_key_as_a_header_and_retries_once() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    llm = GatewayLLM("qwen-fast", "http://gw/v1", SecretStr("sk-test"),
                     client=httpx.Client(base_url="http://gw/v1/", transport=httpx.MockTransport(handler)))  # fmt: skip
    assert llm.complete("system", "user") == "hi"
    assert len(calls) == 2
    assert calls[1].headers["Authorization"] == "Bearer sk-test"
    body = json.loads(calls[1].content)
    assert body["model"] == "qwen-fast"
    assert body["messages"][0] == {"role": "system", "content": "system"}


def test_gateway_llm_gives_up_with_a_clear_error() -> None:
    llm = GatewayLLM("m", "http://gw/v1", SecretStr("k"), max_retries=1,
                     client=httpx.Client(base_url="http://gw/v1/",
                                         transport=httpx.MockTransport(lambda r: httpx.Response(429))))  # fmt: skip
    with pytest.raises(RuntimeError, match="after 2 attempt"):
        llm.complete("s", "u")
