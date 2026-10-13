"""Run scripts/embed_demo.py and scripts/bench_embeddings.py against a fake TEI server.

The scripts call the fixed localhost ports 8083 (embedder) and 8084 (reranker), so the test
starts a tiny stand-in for TEI's /embed and /rerank on those ports (skipping if they are
already in use, e.g. by the real servers on the Mac). The fake speaks TEI's JSON shapes and,
like TEI started with an API key, rejects requests without the right bearer token.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "scripts" / "embed_demo.py"
BENCH = REPO / "scripts" / "bench_embeddings.py"
KEY = "not-a-real-key-just-for-tests"  # low-entropy stand-in, never a real secret
DIMS = 1024


def _vector(text: str) -> list[float]:
    """A deterministic unit-length 1024-number "embedding" for any text."""
    raw = [b - 127.5 for b in hashlib.shake_256(text.encode()).digest(DIMS)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


class FakeTei(BaseHTTPRequestHandler):
    """Answers POST /embed and POST /rerank like TEI, and records every request."""

    requests: ClassVar[list[tuple[int, str, dict[str, Any]]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self._reply(401, {"error": "Unauthorized", "error_type": "Unauthorized"})
            return
        port = int(self.headers["Host"].rsplit(":", 1)[1])  # which fake server was called
        FakeTei.requests.append((port, self.path, body))
        if self.path == "/embed":
            inputs = body["inputs"] if isinstance(body["inputs"], list) else [body["inputs"]]
            self._reply(200, [_vector(text) for text in inputs])
        elif self.path == "/rerank":
            # Score = word overlap with the query; TEI returns results sorted, best first.
            words = set(body["query"].lower().split())
            scored = [
                {"index": i, "score": len(words & set(t.lower().split())) / 10}
                for i, t in enumerate(body["texts"])
            ]
            self._reply(200, sorted(scored, key=lambda r: r["score"], reverse=True))
        else:
            self._reply(404, {"error": "not found"})

    def _reply(self, status: int, payload: object) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # silence test output
        pass


@pytest.fixture
def fake_tei() -> Iterator[None]:
    FakeTei.requests = []
    servers: list[ThreadingHTTPServer] = []
    try:
        for port in (8083, 8084):
            servers.append(ThreadingHTTPServer(("127.0.0.1", port), FakeTei))
    except OSError:
        for server in servers:
            server.server_close()
        pytest.skip("ports 8083/8084 are in use (real TEI servers running?)")
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield
    for server in servers:
        server.shutdown()
        server.server_close()


def _run(script: Path, key: str | None = KEY) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "TEI_API_KEY"}
    if key is not None:
        env["TEI_API_KEY"] = key
    return subprocess.run(  # noqa: S603 - fixed script path from this repo
        [sys.executable, str(script)], env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.usefixtures("fake_tei")
def test_demo_shows_three_rankings_and_the_reranker() -> None:
    result = _run(DEMO)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    for heading in (
        f"Embedding search WITH instruction (dims={DIMS})",
        "Embedding search WITHOUT instruction",
        "Matryoshka: first 256 dims only",
        "Reranker (reads the question and each passage together)",
    ):
        assert heading in out
    # Four sections, each listing all five passages with a score.
    assert out.count("Car parking permits are issued by Facilities") == 4
    # The reranker section is best-first: the remote-work passage shares the most query words.
    rerank = out.split("Reranker (reads the question and each passage together)")[1]
    assert rerank.strip().splitlines()[0].endswith("including Fridays, with manager approval.")


@pytest.mark.usefixtures("fake_tei")
def test_demo_adds_the_instruction_to_queries_only() -> None:
    assert _run(DEMO).returncode == 0
    embeds = [body["inputs"] for port, path, body in FakeTei.requests if path == "/embed"]
    assert all(port == 8083 for port, path, _ in FakeTei.requests if path == "/embed")
    docs, with_inst, without = embeds
    assert len(docs) == 5
    assert not any(d.startswith("Instruct:") for d in docs)  # documents: NO instruction
    assert with_inst == [
        "Instruct: Given an employee question, retrieve passages from company documents "
        "that answer it\nQuery:Can I work from home on Fridays?"
    ]
    assert without == ["Can I work from home on Fridays?"]
    reranks = [(port, body) for port, path, body in FakeTei.requests if path == "/rerank"]
    assert reranks == [(8084, {"query": "Can I work from home on Fridays?", "texts": docs})]


@pytest.mark.usefixtures("fake_tei")
def test_demo_fails_with_the_wrong_key() -> None:
    result = _run(DEMO, key="wrong")
    assert result.returncode != 0
    assert "HTTP Error 401" in result.stderr


def test_demo_needs_the_key_in_the_environment() -> None:
    result = _run(DEMO, key=None)
    assert result.returncode != 0
    assert "KeyError: 'TEI_API_KEY'" in result.stderr


@pytest.mark.usefixtures("fake_tei")
def test_bench_embeds_512_chunks_in_batches_of_32_then_reranks() -> None:
    result = _run(BENCH)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith("embed : 512 chunks (~200 tokens) in ")
    assert lines[0].endswith(" chunks/s")
    assert lines[1].startswith("rerank:  10 candidates in ")
    assert lines[2].startswith("rerank:  50 candidates in ")

    embeds = [body["inputs"] for _, path, body in FakeTei.requests if path == "/embed"]
    assert embeds[0] == ["warm up"]
    assert [len(batch) for batch in embeds[1:]] == [32] * 16  # 512 chunks, batch 32
    reranks = [len(body["texts"]) for _, path, body in FakeTei.requests if path == "/rerank"]
    assert reranks == [1, 10, 50]  # warm-up, then the two measured sizes
