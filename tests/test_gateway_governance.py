"""Step 10: budgets, rate limits and fallbacks on the LiteLLM gateway.

The config tests read the committed files and check the rules the guide sets: a private,
digest-pinned Postgres with no published port; the salt key and database URL from secret
files; non-zero shadow prices that match docs/finops/shadow-pricing.md; retries, cooldown and
chat-only fallbacks (never for the embedder or reranker); models only in git
(store_model_in_db: false); and an access policy that names every key.

The script tests run scripts/gateway_admin.py and scripts/gateway_limits_test.py against a
small stand-in for LiteLLM's management API on a free local port (LLM_GATEWAY_URL). Like
LiteLLM, the fake creates teams and hashed-once virtual keys, refuses models outside a key's
allow-list (401), enforces RPM (429), records spend at the shadow price just after each call
and rejects a team over budget (400 budget_exceeded), and blocks keys.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "infra" / "config" / "litellm" / "config.yaml"
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
PRICING = REPO / "docs" / "finops" / "shadow-pricing.md"
POLICY = REPO / "docs" / "security" / "gateway-access-policy.md"
ADMIN = REPO / "scripts" / "gateway_admin.py"
LIMITS = REPO / "scripts" / "gateway_limits_test.py"
JUSTFILE = REPO / "justfile"
MASTER = "sk-not-a-real-master-key-for-tests"  # low-entropy stand-in, never a real secret


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


# --- the gateway's private database ------------------------------------------------------------


def test_gateway_database_is_private_pinned_and_hardened() -> None:
    db = _load(COMPOSE)["services"]["litellm-db"]
    assert re.fullmatch(r"postgres:17-alpine@sha256:[0-9a-f]{64}", db["image"])
    assert "ports" not in db  # only containers on the Compose network can reach it
    assert db["environment"] == {
        "POSTGRES_DB": "litellm",
        "POSTGRES_USER": "litellm",
        "POSTGRES_PASSWORD_FILE": "/run/secrets/litellm_db_password",
    }
    assert db["secrets"] == ["litellm_db_password"]
    assert db["volumes"] == ["litellm-db-data:/var/lib/postgresql/data"]
    assert db["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U litellm -d litellm"]
    assert db["restart"] == "unless-stopped"
    assert db["security_opt"] == ["no-new-privileges:true"]
    assert db["deploy"]["resources"]["limits"] == {"memory": "512m", "cpus": "1"}
    assert "litellm-db-data" in _load(COMPOSE)["volumes"]


def test_gateway_gets_database_url_and_salt_key_from_secret_files() -> None:
    compose = _load(COMPOSE)
    litellm = compose["services"]["litellm"]
    assert not any(k.startswith(("DATABASE", "LITELLM")) for k in litellm.get("environment", {}))
    assert litellm["secrets"] == [
        "litellm_master_key",
        "tei_api_key",
        "litellm_salt_key",
        "litellm_db_password",
        "valkey_litellm_password",  # Step 15: the response cache's Valkey user
    ]
    assert litellm["depends_on"] == {
        "litellm-db": {"condition": "service_healthy"},
        "valkey": {"condition": "service_healthy"},  # Step 15
    }
    (command,) = litellm["command"]
    assert 'LITELLM_SALT_KEY="$$(cat /run/secrets/litellm_salt_key)"' in command
    assert (
        'DATABASE_URL="postgresql://litellm:$$(cat /run/secrets/litellm_db_password)'
        '@litellm-db:5432/litellm"' in command
    )
    assert compose["secrets"]["litellm_salt_key"] == {"environment": "LITELLM_SALT_KEY"}
    assert compose["secrets"]["litellm_db_password"] == {"environment": "LITELLM_DB_PASSWORD"}


def test_new_secrets_are_generated_and_documented() -> None:
    generator = (REPO / "scripts" / "new-dev-secrets.sh").read_text()
    assert "LITELLM_DB_PASSWORD=$(rand)" in generator  # letters/digits only: safe inside a URL
    assert "LITELLM_SALT_KEY=$(openssl rand -hex 32)" in generator
    example = (REPO / ".env.example").read_text()
    for name in (
        "LITELLM_DB_PASSWORD",
        "LITELLM_SALT_KEY",
        "RAG_API_GATEWAY_KEY",
        "INGESTION_GATEWAY_KEY",
        "EVAL_GATEWAY_KEY",
    ):
        assert re.search(rf"^{name}=<", example, re.MULTILINE) or re.search(
            rf"^{name}=sk-<", example, re.MULTILINE
        ), name


# --- shadow prices, retries, cooldown and fallbacks ------------------------------------------------


def _deployments() -> dict[str, dict[str, Any]]:
    return {m["model_name"]: m for m in _load(CONFIG)["model_list"]}


def test_local_models_carry_non_zero_shadow_prices() -> None:
    info = {name: d["model_info"] for name, d in _deployments().items()}
    for chat in ("qwen-quality", "qwen-fast"):
        assert info[chat]["input_cost_per_token"] > 0
        assert info[chat]["output_cost_per_token"] > info[chat]["input_cost_per_token"]
    # The slower 27B model costs more GPU time per token than the fast MoE.
    assert (
        info["qwen-quality"]["output_cost_per_token"] > info["qwen-fast"]["output_cost_per_token"]
    )
    assert info["embedder"]["input_cost_per_token"] > 0  # cheap, but heavy indexing shows up
    assert info["embedder"]["output_cost_per_token"] == 0


def _pricing_table() -> dict[str, list[str]]:
    rows = {}
    for line in PRICING.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and cells[0] in {
            "qwen-quality",
            "qwen-fast",
            "embedder",
            "reranker",
        }:
            rows[cells[0]] = cells[1:]
    return rows


def test_shadow_prices_follow_the_documented_formula_and_match_the_config() -> None:
    text = PRICING.read_text()
    assert "Notional GPU rate: $2.00 per hour" in text
    rate = 2.00
    rows = _pricing_table()
    info = {name: d["model_info"] for name, d in _deployments().items()}
    for chat in ("qwen-quality", "qwen-fast"):
        decode, prefill, out_price, in_price = rows[chat]
        assert float(out_price) == info[chat]["output_cost_per_token"]
        assert float(in_price) == info[chat]["input_cost_per_token"]
        # price = rate / (3600 x tok/s), rounded to 2 significant figures
        assert float(out_price) == pytest.approx(rate / (3600 * float(decode)), rel=0.02)
        assert float(in_price) == pytest.approx(rate / (3600 * float(prefill)), rel=0.02)
    assert float(rows["embedder"][3]) == info["embedder"]["input_cost_per_token"]


def test_retries_cooldown_and_chat_only_fallbacks() -> None:
    settings = _load(CONFIG)["litellm_settings"]
    assert settings["num_retries"] == 1
    assert settings["allowed_fails"] == 3
    assert settings["cooldown_time"] == 30
    assert settings["fallbacks"] == [
        {"qwen-fast": ["qwen-quality"]},
        {"qwen-quality": ["qwen-fast"]},
    ]
    # Never fall back between embedders (another vector space) or for the reranker
    # (the app skips reranking instead), whichever fallback setting would carry it.
    for key in ("fallbacks", "context_window_fallbacks", "content_policy_fallbacks"):
        for rule in settings.get(key, []):
            assert not {"embedder", "reranker"} & set(rule), key
            for targets in rule.values():
                assert not {"embedder", "reranker"} & set(targets), key
    assert "default_fallbacks" not in settings


def test_models_are_defined_only_in_git() -> None:
    general = _load(CONFIG)["general_settings"]
    assert general["store_model_in_db"] is False
    assert general["master_key"] == "os.environ/LITELLM_MASTER_KEY"
    assert "database_url" not in general  # comes from the DATABASE_URL secret, never the file


# --- access policy and recipes -----------------------------------------------------------------


def test_access_policy_lists_every_key_with_limits_expiry_and_owner() -> None:
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in POLICY.read_text().splitlines()
        if line.startswith("| rag-apps") or line.startswith("| evaluation")
    ]
    keys = {r[3]: r for r in rows}
    assert set(keys) == {"rag-api-dev", "ingestion-dev", "eval-harness"}
    assert keys["rag-api-dev"][1:3] == ["$50", "30d"]
    assert keys["eval-harness"][1:3] == ["$200", "30d"]
    assert keys["ingestion-dev"][4] == "embedder, qwen-fast"
    assert [keys[k][5:7] for k in ("rag-api-dev", "ingestion-dev", "eval-harness")] == [
        ["60", "4"],
        ["600", "8"],
        ["120", "4"],
    ]
    assert all(r[7] == "90d" and r[8] for r in rows)
    assert "Master key: admin tasks only" in POLICY.read_text()


def test_justfile_runs_the_admin_tools_with_secrets_in_memory() -> None:
    text = JUSTFILE.read_text()
    assert (
        "gateway-admin *args:\n    sops exec-env secrets/dev.enc.env 'uv run scripts/gateway_admin.py {{args}}'"
        in text
    )
    assert (
        "gateway-test:\n    sops exec-env secrets/dev.enc.env 'uv run scripts/gateway_limits_test.py'"
        in text
    )


# --- the scripts against a fake LiteLLM management API -----------------------------------------


PRICES = {"qwen-fast": (0.0000007, 0.0000069), "qwen-quality": (0.0000028, 0.0000278)}


class FakeLiteLLM(BaseHTTPRequestHandler):
    """Teams, virtual keys, allow-lists, RPM limits, budgets and blocking, like LiteLLM."""

    teams: ClassVar[dict[str, dict[str, Any]]] = {}
    keys: ClassVar[dict[str, dict[str, Any]]] = {}
    calls: ClassVar[list[tuple[str, str, dict[str, Any]]]] = []

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if not self._is_master():
            return
        if url.path == "/key/info":
            key = parse_qs(url.query)["key"][0]
            self._reply(200, {"key": key, "info": self.keys[key]})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLiteLLM.calls.append(("POST", self.path, body))
        if self.path == "/v1/chat/completions":
            self._chat(body)
        elif not self._is_master():
            return
        elif self.path == "/team/new":
            team_id = f"team-{len(self.teams) + 1}"
            self.teams[team_id] = {**body, "team_id": team_id, "spend": 0.0}
            self._reply(200, self.teams[team_id])
        elif self.path == "/key/generate":
            if body["team_id"] not in self.teams:
                self._reply(400, {"error": "team not found"})
                return
            key = "sk-" + secrets.token_hex(8)
            self.keys[key] = {**body, "spend": 0.0, "blocked": None, "expires": "later", "used": []}
            self._reply(200, {"key": key, **body})
        elif self.path == "/key/block":
            self.keys[body["key"]]["blocked"] = True
            self._reply(200, {"blocked": True})
        else:
            self._reply(404, {"error": "not found"})

    def _chat(self, body: dict[str, Any]) -> None:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        key = self.keys.get(token)
        if key is None or key["blocked"]:
            self._reply(401, {"error": {"message": "Authentication Error, invalid key"}})
            return
        model = body["model"]
        if model not in key["models"]:
            message = (
                f"key not allowed to access model. This key can only access models={key['models']}"
            )
            self._reply(401, {"error": {"message": message, "code": "401"}})
            return
        now = time.monotonic()
        key["used"] = [t for t in key["used"] if now - t < 60]
        if key.get("rpm_limit") is not None and len(key["used"]) >= key["rpm_limit"]:
            self._reply(429, {"error": {"message": "Max rpm limit reached", "code": "429"}})
            return
        team = self.teams[key["team_id"]]
        if team["spend"] >= team["max_budget"]:
            message = f"Budget has been exceeded! Current cost: {team['spend']}"
            self._reply(400, {"error": {"message": message, "type": "budget_exceeded"}})
            return
        key["used"].append(now)
        prompt, completion = 12, body.get("max_tokens", 20)
        in_price, out_price = PRICES[model]
        self._reply(
            200,
            {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Find me."}}],
                "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
            },
        )
        cost = prompt * in_price + completion * out_price  # spend is written just after the call
        key["spend"] += cost
        team["spend"] += cost

    def _is_master(self) -> bool:
        if self.headers.get("Authorization") != f"Bearer {MASTER}":
            self._reply(401, {"error": "Authentication Error, only the master key can do this"})
            return False
        return True

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
def gateway_url() -> Iterator[str]:
    FakeLiteLLM.teams, FakeLiteLLM.keys, FakeLiteLLM.calls = {}, {}, []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLiteLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _run(script: Path, url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    env.update(LITELLM_MASTER_KEY=MASTER, LLM_GATEWAY_URL=url, NO_PROXY="127.0.0.1")
    result = subprocess.run(  # noqa: S603 - fixed script path from this repo
        [sys.executable, str(script), *args], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result


def test_admin_tool_creates_teams_and_scoped_expiring_keys(gateway_url: str) -> None:
    out = _run(ADMIN, gateway_url, "team", "rag-apps", "--budget", "50", "--models", "qwen-fast")
    assert out.stdout.strip() == "team_id: team-1"
    assert FakeLiteLLM.calls[-1][2] == {
        "team_alias": "rag-apps",
        "max_budget": 50.0,
        "budget_duration": "30d",
        "models": ["qwen-fast"],
    }

    out = _run(
        ADMIN, gateway_url, "key", "ingestion-dev", "--team-id", "team-1",
        "--models", "embedder", "qwen-fast", "--rpm", "600", "--parallel", "8",
    )  # fmt: skip
    assert out.stdout.startswith("key (shown ONCE - store it now with `just secrets-edit`): sk-")
    # Unset limits are left out, so LiteLLM's defaults (none) apply; expiry defaults to 90 days.
    assert FakeLiteLLM.calls[-1][2] == {
        "key_alias": "ingestion-dev",
        "team_id": "team-1",
        "models": ["embedder", "qwen-fast"],
        "duration": "90d",
        "rpm_limit": 600,
        "max_parallel_requests": 8,
        "metadata": {"created_by": "gateway_admin.py"},
    }


def test_admin_tool_shows_and_blocks_a_key(gateway_url: str) -> None:
    _run(ADMIN, gateway_url, "team", "evaluation", "--budget", "200", "--models", "qwen-fast")
    out = _run(
        ADMIN,
        gateway_url,
        "key",
        "eval-harness",
        "--team-id",
        "team-1",
        "--models",
        "qwen-fast",
        "--rpm",
        "120",
    )
    key = out.stdout.split(": ", 1)[1].strip()

    info = json.loads(_run(ADMIN, gateway_url, "info", key).stdout)
    assert list(info) == [
        "key_alias", "team_id", "models", "spend", "max_budget", "rpm_limit",
        "tpm_limit", "max_parallel_requests", "expires", "blocked",
    ]  # fmt: skip
    assert info["key_alias"] == "eval-harness"
    assert info["rpm_limit"] == 120
    assert info["blocked"] is None

    assert _run(ADMIN, gateway_url, "block", key).stdout.strip() == "{'blocked': True}"
    assert json.loads(_run(ADMIN, gateway_url, "info", key).stdout)["blocked"] is True


def test_limits_test_proves_allow_list_rate_limit_and_budget(gateway_url: str) -> None:
    lines = _run(LIMITS, gateway_url).stdout.splitlines()
    assert lines == [
        "1. allow-list : qwen-quality with a qwen-fast-only key -> 401 (expect 401/403)",
        "2. rate limit : [200, 200, 429] (expect 200, 200, 429)",
        "3. budget     : [200, 400] (expect some 200s, then a budget rejection)",
        "test keys blocked. Delete the test-* teams in the admin UI when you like.",
    ]
    # Throwaway keys expire in an hour and are blocked at the end.
    assert all(k["duration"] == "1h" and k["blocked"] for k in FakeLiteLLM.keys.values())
    assert {t["team_alias"] for t in FakeLiteLLM.teams.values()} == {"test-limits", "test-budget"}
