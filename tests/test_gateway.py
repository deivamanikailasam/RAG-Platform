"""Step 9: the LiteLLM gateway config, its Compose service, and the smoke test.

The config and Compose tests read the committed files and check the rules the guide sets
(role names, exact model IDs, no keys in files, tag@digest pin, localhost port, read-only
config, file-based secrets, healthcheck, restart, no-new-privileges, limits).

The smoke-test tests run scripts/gateway_smoke.py against a tiny stand-in for LiteLLM on
127.0.0.1:4000 (skipped if the port is in use, e.g. by the real gateway). Like LiteLLM, the
fake speaks the OpenAI API, streams with Server-Sent Events, serves /rerank, rejects a wrong
key with 401 and an unknown model with 400.
"""

import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "infra" / "config" / "litellm" / "config.yaml"
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
SMOKE = REPO / "scripts" / "gateway_smoke.py"
JUSTFILE = REPO / "justfile"
KEY = "sk-not-a-real-key-just-for-tests"  # low-entropy stand-in, never a real secret
ROLES = {"qwen-quality": "chat", "qwen-fast": "chat", "embedder": "embedding", "reranker": "rerank"}


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


def _just_var(name: str) -> str:
    match = re.search(rf'^{name}\s*:=\s*"([^"]+)"', JUSTFILE.read_text(), re.MULTILINE)
    assert match, f"{name} not found in the justfile"
    return match.group(1)


# --- gateway config -------------------------------------------------------------------------


def _deployments() -> dict[str, dict[str, Any]]:
    return {m["model_name"]: m for m in _load(CONFIG)["model_list"]}


def test_config_defines_exactly_the_four_roles() -> None:
    deployments = _deployments()
    assert {name: d["model_info"]["mode"] for name, d in deployments.items()} == ROLES


def test_chat_roles_send_the_exact_ids_the_mlx_servers_loaded() -> None:
    deployments = _deployments()
    quality = deployments["qwen-quality"]["litellm_params"]
    fast = deployments["qwen-fast"]["litellm_params"]
    assert quality["model"] == f"openai/{_just_var('quality_model')}"
    assert fast["model"] == f"openai/{_just_var('fast_model')}"
    assert quality["api_base"] == "http://host.docker.internal:8081/v1"
    assert fast["api_base"] == "http://host.docker.internal:8082/v1"


def test_search_roles_point_at_tei_with_the_key_from_the_environment() -> None:
    deployments = _deployments()
    embedder = deployments["embedder"]["litellm_params"]
    reranker = deployments["reranker"]["litellm_params"]
    # The embedder's served name is the one serve-embed gives TEI (Step 8).
    assert "8083 9083 qwen3-embedding-0.6b" in JUSTFILE.read_text()
    assert embedder["model"] == "openai/qwen3-embedding-0.6b"
    assert embedder["api_base"] == "http://host.docker.internal:8083/v1"
    assert reranker["model"] == f"huggingface/{_just_var('rerank_model')}"
    assert reranker["api_base"] == "http://host.docker.internal:8084"
    assert embedder["api_key"] == reranker["api_key"] == "os.environ/TEI_API_KEY"


def test_config_holds_no_secrets() -> None:
    config = _load(CONFIG)
    assert config["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"
    for deployment in config["model_list"]:
        assert deployment["litellm_params"]["api_key"] in {"not-used", "os.environ/TEI_API_KEY"}
    assert config["litellm_settings"] == {
        "drop_params": True,
        "num_retries": 1,
        "request_timeout": 600,
    }


# --- Compose service ------------------------------------------------------------------------


def _litellm() -> dict[str, Any]:
    compose = _load(COMPOSE)
    assert compose["name"] == "rag-platform"
    service = compose["services"]["litellm"]
    assert isinstance(service, dict)
    return service


def test_image_is_pinned_by_tag_and_digest() -> None:
    assert re.fullmatch(
        r"ghcr\.io/berriai/litellm:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", _litellm()["image"]
    )


def test_gateway_is_hardened() -> None:
    service = _litellm()
    assert service["ports"] == ["127.0.0.1:4000:4000"]
    assert service["volumes"] == ["../config/litellm/config.yaml:/app/config.yaml:ro"]
    assert (COMPOSE.parent / "../config/litellm/config.yaml").resolve() == CONFIG
    assert service["extra_hosts"] == ["host.docker.internal:host-gateway"]
    assert service["restart"] == "unless-stopped"
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["deploy"]["resources"]["limits"] == {"memory": "2g", "cpus": "2"}
    health = service["healthcheck"]
    assert health["test"][:3] == ["CMD", "python", "-c"]
    assert "http://127.0.0.1:4000/health/liveliness" in health["test"][3]


def test_keys_come_from_secret_files_not_the_environment() -> None:
    service = _litellm()
    assert "environment" not in service  # would show the keys in `docker inspect`
    # Step 10 adds the salt key and the database password to the Step 9 pair.
    assert service["secrets"][:2] == ["litellm_master_key", "tei_api_key"]
    assert service["entrypoint"] == ["/bin/sh", "-c"]
    (command,) = service["command"]
    assert 'export LITELLM_MASTER_KEY="$$(cat /run/secrets/litellm_master_key)"' in command
    assert 'TEI_API_KEY="$$(cat /run/secrets/tei_api_key)"' in command
    assert "exec litellm --config /app/config.yaml --host 0.0.0.0 --port 4000" in command
    secrets = _load(COMPOSE)["secrets"]
    assert secrets["litellm_master_key"] == {"environment": "LITELLM_MASTER_KEY"}
    assert secrets["tei_api_key"] == {"environment": "TEI_API_KEY"}


# --- smoke test against a fake gateway --------------------------------------------------------


class FakeGateway(BaseHTTPRequestHandler):
    """Answers like LiteLLM on :4000 for the four roles, and records every request."""

    requests: ClassVar[list[tuple[str, str, dict[str, Any]]]] = []
    allow_any_model: ClassVar[bool] = False  # True = a broken gateway with no allow-list

    def do_GET(self) -> None:
        if not self._authorised("GET", {}):
            return
        if self.path == "/v1/models":
            models = [
                {"id": r, "object": "model", "created": 0, "owned_by": "openai"} for r in ROLES
            ]
            self._reply(200, {"object": "list", "data": models})
        else:
            self._reply(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not self._authorised("POST", body):
            return
        model = body.get("model")
        if model not in ROLES and not FakeGateway.allow_any_model:
            self._reply(400, {"error": {"message": f"Invalid model name passed in model={model}"}})
        elif self.path == "/v1/chat/completions" and body.get("stream"):
            self._stream(model)
        elif self.path == "/v1/chat/completions":
            message = {"role": "assistant", "content": f"  A database for vectors ({model}).  "}
            self._reply(
                200,
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "created": 0,
                    "model": model,
                    "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 9, "total_tokens": 29},
                },
            )
        elif self.path == "/v1/embeddings":
            data = [
                {"object": "embedding", "index": i, "embedding": [0.0] * 1024}
                for i, _ in enumerate(body["input"])
            ]
            usage = {"prompt_tokens": 4, "total_tokens": 4}
            self._reply(200, {"object": "list", "data": data, "model": model, "usage": usage})
        elif self.path == "/rerank":
            results = [
                {"index": 0, "relevance_score": 0.98765},
                {"index": 1, "relevance_score": 0.01},
            ]
            self._reply(200, {"id": "rerank-1", "results": results[: body["top_n"]]})
        else:
            self._reply(404, {"error": {"message": "not found"}})

    def _authorised(self, method: str, body: dict[str, Any]) -> bool:
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self._reply(401, {"error": {"message": "Authentication Error", "code": "401"}})
            return False
        FakeGateway.requests.append((method, self.path, body))
        return True

    def _stream(self, model: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for word in ["1, ", "2, ", "3, ", "4, ", "5."]:
            chunk = {
                "id": "chatcmpl-2",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": word}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.close_connection = True

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
def fake_gateway() -> Iterator[None]:
    FakeGateway.requests = []
    FakeGateway.allow_any_model = False
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 4000), FakeGateway)
    except OSError:
        pytest.skip("port 4000 is in use (real gateway running?)")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield
    server.shutdown()
    server.server_close()


def _run_smoke() -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    env["LITELLM_MASTER_KEY"] = KEY
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    return subprocess.run(  # noqa: S603 - fixed script path from this repo
        [sys.executable, str(SMOKE)], env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.usefixtures("fake_gateway")
def test_smoke_test_exercises_every_role_and_both_security_checks() -> None:
    result = _run_smoke()
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "models       : ['qwen-quality', 'qwen-fast', 'embedder', 'reranker']"
    assert lines[1] == "qwen-fast    : A database for vectors (qwen-fast). | 29 tokens"
    assert lines[2] == "qwen-quality : A database for vectors (qwen-quality). | 29 tokens"
    assert lines[3] == "stream       : 1, 2, 3, 4, 5."
    assert lines[4] == "embed        : 2 vectors of 1024 dims"
    assert lines[5] == "rerank       : [(0, 0.988), (1, 0.01)]"
    assert lines[6] == "ok           : no/bad key rejected (AuthenticationError)"
    assert lines[7] == "ok           : unknown model rejected (BadRequestError)"


@pytest.mark.usefixtures("fake_gateway")
def test_smoke_test_only_uses_role_names() -> None:
    assert _run_smoke().returncode == 0
    used = {body["model"] for _, _, body in FakeGateway.requests if "model" in body}
    assert used == set(ROLES) | {"gpt-5"}  # gpt-5 is the deliberately unknown model
    rerank = [body for _, path, body in FakeGateway.requests if path == "/rerank"]
    assert rerank == [
        {
            "model": "reranker",
            "query": "Can I work from home?",
            "top_n": 2,
            "documents": [
                "Remote work is allowed two days a week.",
                "Parking permits are issued by Facilities.",
            ],
        }
    ]


@pytest.mark.usefixtures("fake_gateway")
def test_smoke_test_fails_when_the_gateway_has_no_allow_list() -> None:
    FakeGateway.allow_any_model = True
    result = _run_smoke()
    assert result.returncode == 1
    assert "FAIL         : unknown model was accepted!" in result.stdout
