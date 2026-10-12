"""Unit tests for scripts/bench_models.py, using a fake OpenAI-compatible streaming server.

No GPU or real model is needed: a tiny local HTTP server replays the Server-Sent Events
(SSE) stream that mlx_lm.server sends for /v1/chat/completions with "stream": true.
"""

import importlib.util
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_models.py"


def _load_bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_models", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load_bench()


class FakeServer(BaseHTTPRequestHandler):
    """Streams whatever chunks the test puts in `events`, and records each request body."""

    events: ClassVar[list[dict[str, Any]]] = []
    bodies: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        FakeServer.bodies.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b": keep-alive comment, ignored by clients\n\n")
        for event in FakeServer.events:
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, format: str, *args: Any) -> None:  # silence test output
        pass


def _chunk(**delta: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": delta}]}


@pytest.fixture
def base_url() -> Iterator[str]:
    FakeServer.events = []
    FakeServer.bodies = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_counts_streamed_content_and_reasoning_pieces(base_url: str) -> None:
    FakeServer.events = [
        _chunk(role="assistant"),  # role-only first chunk: not a token
        _chunk(reasoning="Let me think."),
        _chunk(content="Hello"),
        _chunk(content=" world"),
    ]
    ttft, tps, pieces = bench.run(base_url, "Say hi.", 8)
    assert pieces == 3
    assert ttft >= 0
    assert tps > 0


def test_sends_a_streaming_request_with_thinking_off(base_url: str) -> None:
    FakeServer.events = [_chunk(content="ok")]
    bench.run(base_url, "Explain RAG.", 32)
    body = FakeServer.bodies[0]
    assert body["stream"] is True
    assert body["max_tokens"] == 32
    assert body["temperature"] == 0.0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"] == [{"role": "user", "content": "Explain RAG."}]


def test_no_tokens_returns_zero_speed(base_url: str) -> None:
    FakeServer.events = [_chunk(role="assistant")]
    elapsed, tps, pieces = bench.run(base_url, "Say hi.")
    assert elapsed >= 0
    assert (tps, pieces) == (0.0, 0)


def test_servers_are_the_two_localhost_ports() -> None:
    assert sorted(bench.SERVERS.values()) == ["http://127.0.0.1:8081", "http://127.0.0.1:8082"]
