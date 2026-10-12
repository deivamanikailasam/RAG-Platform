"""Step 19: the OpenTelemetry Collector and the services that send to it.

The static tests read the committed files and check the rules the chapter sets: the Collector config
receives OTLP on 4317/4318, has a health check, processes in the fixed order memory_limiter ->
attributes/scrub -> redaction -> resource -> batch for traces and logs (metrics skip scrubbing),
deletes the risky keys and masks JWT-, key- and email-shaped values; the Compose service is the
contrib 0.162.x image pinned by tag + digest, read-only, without capabilities, limited to 512 MB and
published on 127.0.0.1 only; rag-api, LiteLLM (message logging off), OPA and Keycloak send their
spans to it.

When Docker and the pinned image are available the config is validated by the Collector itself.
The live test runs only when the Collector answers on 127.0.0.1:13133 (``just up``).
"""

import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "infra" / "config" / "otel-collector" / "config.yaml"
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
LITELLM = REPO / "infra" / "config" / "litellm" / "config.yaml"
IMAGE = "otel/opentelemetry-collector-contrib:0.162.0"
ORDER = ["memory_limiter", "attributes/scrub", "redaction", "resource", "batch"]


def _yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


def _service(name: str) -> dict[str, Any]:
    service = _yaml(COMPOSE)["services"][name]
    assert isinstance(service, dict)
    return service


# --- the Collector config ---------------------------------------------------------------------


def test_receives_otlp_on_both_protocols_and_has_a_health_check() -> None:
    cfg = _yaml(CONFIG)
    protocols = cfg["receivers"]["otlp"]["protocols"]
    assert protocols["grpc"]["endpoint"] == "0.0.0.0:4317"
    assert protocols["http"]["endpoint"] == "0.0.0.0:4318"
    assert cfg["extensions"]["health_check"]["endpoint"] == "0.0.0.0:13133"
    assert cfg["service"]["extensions"] == ["health_check"]
    assert cfg["service"]["telemetry"]["logs"] == {"level": "info", "encoding": "json"}


def test_processor_order_protects_memory_first_and_batches_last() -> None:
    pipelines = _yaml(CONFIG)["service"]["pipelines"]
    assert pipelines["traces"]["processors"] == ORDER
    assert pipelines["logs"]["processors"] == ORDER
    # metrics carry numbers and short labels, never content: no scrubbing or redaction
    assert pipelines["metrics"]["processors"] == ["memory_limiter", "resource", "batch"]
    for signal in ("traces", "metrics", "logs"):
        assert pipelines[signal]["receivers"] == ["otlp"]
        assert pipelines[signal]["exporters"] == ["debug"]  # real backends arrive in Steps 20-21


def test_memory_limiter_and_batch_settings() -> None:
    p = _yaml(CONFIG)["processors"]
    assert p["memory_limiter"] == {
        "check_interval": "1s",
        "limit_percentage": 80,
        "spike_limit_percentage": 20,
    }
    assert p["batch"] == {"timeout": "2s", "send_batch_size": 1024}
    assert p["resource"]["attributes"] == [
        {"key": "deployment.environment.name", "value": "dev", "action": "upsert"}
    ]


def test_risky_keys_are_deleted() -> None:
    actions = _yaml(CONFIG)["processors"]["attributes/scrub"]["actions"]
    assert all(a["action"] == "delete" for a in actions)
    assert {a["key"] for a in actions} == {
        "http.request.header.authorization",
        "http.request.header.cookie",
        "db.query.parameters",
        "gen_ai.input.messages",
        "gen_ai.output.messages",
    }


@pytest.mark.parametrize(
    ("value", "masked"),
    [
        ("Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl", True),  # a JWT
        ("sk-1234567890abcdefXYZ", True),  # a LiteLLM virtual key
        ("carol.chen@example.com", True),  # an email address
        ("8f1c0000-alice", False),  # the pseudonymous sub stays readable
        ("POST /v1/search", False),
        ("sk-short", False),  # too short to be a key
    ],
)
def test_redaction_patterns_mask_secret_shaped_values(value: str, masked: bool) -> None:
    redaction = _yaml(CONFIG)["processors"]["redaction"]
    assert redaction["allow_all_keys"] is True
    assert redaction["summary"] == "info"
    patterns = [re.compile(p) for p in redaction["blocked_values"]]
    assert len(patterns) == 3
    assert any(p.search(value) for p in patterns) is masked


DOCKER = shutil.which("docker")


@pytest.mark.skipif(DOCKER is None, reason="docker not installed")
def test_the_collector_itself_accepts_the_config() -> None:
    assert DOCKER is not None
    have = subprocess.run(  # noqa: S603 - fixed arguments
        [DOCKER, "image", "inspect", IMAGE], capture_output=True, check=False
    )
    if have.returncode != 0:
        pytest.skip(f"{IMAGE} not pulled")
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [DOCKER, "run", "--rm", "-v", f"{CONFIG.parent}:/cfg:ro", IMAGE, "validate",
         "--config=/cfg/config.yaml"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr


# --- Compose ----------------------------------------------------------------------------------


def test_collector_service_is_pinned_locked_down_and_localhost_only() -> None:
    s = _service("otel-collector")
    image, _, digest = s["image"].partition("@")
    assert image == IMAGE
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    assert s["command"] == ["--config=/etc/otelcol/config.yaml"]
    assert s["volumes"] == ["../config/otel-collector/config.yaml:/etc/otelcol/config.yaml:ro"]
    assert (COMPOSE.parent / "../config/otel-collector/config.yaml").resolve() == CONFIG
    assert s["ports"] == ["127.0.0.1:4317:4317", "127.0.0.1:4318:4318", "127.0.0.1:13133:13133"]
    assert s["read_only"] is True
    assert s["cap_drop"] == ["ALL"]
    assert s["security_opt"] == ["no-new-privileges:true"]
    assert s["restart"] == "unless-stopped"
    assert s["deploy"]["resources"]["limits"] == {"memory": "512m", "cpus": "1"}
    assert "healthcheck" not in s  # the image has no shell


def test_rag_api_is_configured_only_through_standard_otel_variables() -> None:
    s = _service("rag-api")
    env = s["environment"]
    assert env["OTEL_SERVICE_NAME"] == "rag-api"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel-collector:4317"
    assert env["OTEL_RESOURCE_ATTRIBUTES"] == "service.version=0.1.0"
    assert env["OTEL_TRACES_SAMPLER"] == "parentbased_traceidratio"
    assert env["OTEL_TRACES_SAMPLER_ARG"] == "1.0"
    assert s["depends_on"]["otel-collector"]["condition"] == "service_started"


def test_litellm_sends_spans_without_message_content() -> None:
    env = _service("litellm")["environment"]
    assert env == {
        "OTEL_EXPORTER": "otlp_http",
        "OTEL_ENDPOINT": "http://otel-collector:4318",
        "OTEL_SERVICE_NAME": "litellm",
    }
    cfg = _yaml(LITELLM)
    assert "otel" in cfg["litellm_settings"]["callbacks"]
    assert cfg["callback_settings"]["otel"]["message_logging"] is False


def test_opa_and_keycloak_trace_into_the_collector() -> None:
    cmd = _service("opa")["command"]
    assert "--set=distributed_tracing.type=grpc" in cmd
    assert "--set=distributed_tracing.address=otel-collector:4317" in cmd
    assert "--set=distributed_tracing.service_name=opa" in cmd
    env = _service("keycloak")["environment"]
    assert env["KC_TRACING_ENABLED"] == "true"
    assert env["KC_TRACING_ENDPOINT"] == "http://otel-collector:4317"


# --- live -------------------------------------------------------------------------------------


def _collector_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 13133), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _collector_up(), reason="Collector not running (just up)")
def test_live_collector_reports_available() -> None:
    r = httpx.get("http://127.0.0.1:13133/", timeout=3)
    assert r.status_code == 200
    assert r.json()["status"] == "Server available"
