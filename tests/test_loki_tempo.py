"""Step 21: Loki + Tempo, from a metric spike to the exact trace and log line.

The static tests read the committed files and check the rules the chapter sets: Tempo 3 runs as one
process with 7-day block retention and a metrics generator (span metrics + service graph) that remote
writes to Prometheus with exemplars; Loki uses the tsdb v13 schema with 7-day retention that the
compactor really enforces; the Collector receives container logs on fluent_forward, regroups them by
Compose service, masks JWT/key/email patterns in the log TEXT and exports traces to Tempo and logs to
Loki under the new exporter names; every Compose service except the Collector logs through the
shared ``to-collector`` fluentd block and nothing mounts the Docker socket; Prometheus accepts remote
write and stores exemplars; Grafana's data sources link exemplar -> trace -> logs -> trace, and the
derived-field regex matches a real rag-api log line; ADR-0021 is recorded.

When Docker and the pinned images are available, Tempo and Loki check their own configs. The live
tests run only when Tempo answers on 127.0.0.1:3200 and Loki on 127.0.0.1:3100 (``just up``).
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from opentelemetry.sdk.trace import TracerProvider

from rag_common.telemetry import JsonFormatter

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "infra" / "config"
TEMPO = CONFIG / "tempo" / "tempo.yaml"
LOKI = CONFIG / "loki" / "loki.yaml"
COLLECTOR = CONFIG / "otel-collector" / "config.yaml"
PROMETHEUS = CONFIG / "prometheus" / "prometheus.yml"
DATASOURCES = CONFIG / "grafana" / "provisioning" / "datasources" / "datasources.yaml"
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
ADR = REPO / "docs" / "adr" / "0021-use-tempo-and-loki-for-traces-and-logs.md"
TEMPO_IMAGE = "grafana/tempo:3.0.3"
LOKI_IMAGE = "grafana/loki:3.7.7"


def _yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


def _services() -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = _yaml(COMPOSE)["services"]
    return services


def _sources() -> dict[str, dict[str, Any]]:
    return {d["uid"]: d for d in _yaml(DATASOURCES)["datasources"]}


# --- Tempo ------------------------------------------------------------------------------------


def test_tempo_is_single_process_with_seven_day_retention() -> None:
    cfg = _yaml(TEMPO)
    assert cfg["stream_over_http_enabled"] is True
    assert cfg["server"]["http_listen_port"] == 3200
    otlp = cfg["distributor"]["receivers"]["otlp"]["protocols"]
    assert otlp == {"grpc": {"endpoint": "0.0.0.0:4317"}}  # gRPC only, from the Collector
    assert cfg["storage"]["trace"]["backend"] == "local"
    assert cfg["backend_worker"]["compaction"]["block_retention"] == "168h"
    assert cfg["usage_report"]["reporting_enabled"] is False
    # Tempo 2 blocks that Tempo 3 no longer has must not be copied in
    assert "ingester" not in cfg
    assert "compactor" not in cfg


def test_tempo_generates_span_metrics_and_a_service_graph_into_prometheus() -> None:
    cfg = _yaml(TEMPO)
    generator = cfg["metrics_generator"]
    assert generator["registry"]["external_labels"] == {"source": "tempo"}
    assert generator["storage"]["remote_write"] == [
        {"url": "http://prometheus:9090/api/v1/write", "send_exemplars": True}
    ]
    processors = cfg["overrides"]["defaults"]["metrics_generator"]["processors"]
    assert processors == ["span-metrics", "service-graphs"]


# --- Loki -------------------------------------------------------------------------------------


def test_loki_keeps_logs_seven_days_and_really_deletes_them() -> None:
    cfg = _yaml(LOKI)
    assert cfg["auth_enabled"] is False  # single tenant: internal network only
    assert cfg["server"]["http_listen_port"] == 3100
    schema = cfg["schema_config"]["configs"]
    assert schema == [
        {
            "from": "2026-01-01",
            "store": "tsdb",
            "object_store": "filesystem",
            "schema": "v13",
            "index": {"prefix": "index_", "period": "24h"},
        }
    ]
    limits = cfg["limits_config"]
    assert limits["retention_period"] == "168h"
    assert limits["max_query_lookback"] == "168h"
    assert limits["allow_structured_metadata"] is True
    # retention_period alone deletes nothing: the compactor must be told to enforce it
    assert cfg["compactor"]["retention_enabled"] is True
    assert cfg["compactor"]["delete_request_store"] == "filesystem"
    assert cfg["analytics"]["reporting_enabled"] is False


# --- the Collector ----------------------------------------------------------------------------


def test_collector_receives_container_logs_and_exports_to_tempo_and_loki() -> None:
    cfg = _yaml(COLLECTOR)
    assert cfg["receivers"]["fluent_forward"] == {"endpoint": "0.0.0.0:24224"}
    exporters = cfg["exporters"]
    assert exporters["otlp_grpc/tempo"] == {"endpoint": "tempo:4317", "tls": {"insecure": True}}
    assert exporters["otlp_http/loki"] == {
        "endpoint": "http://loki:3100/otlp",
        "tls": {"insecure": True},
    }
    assert "debug" not in exporters
    # the deprecated names (otlp, otlphttp) are gone everywhere
    for name in exporters:
        assert name.split("/")[0] in {"otlp_grpc", "otlp_http"}
    logs = cfg["service"]["pipelines"]["logs"]
    assert logs["receivers"] == ["otlp", "fluent_forward"]
    assert logs["processors"] == [
        "memory_limiter",
        "groupbyattrs/container",
        "transform/container-logs",
        "attributes/scrub",
        "redaction",
        "transform/redact-log-body",
        "resource",
        "batch",
    ]
    assert logs["exporters"] == ["otlp_http/loki"]
    assert cfg["service"]["pipelines"]["traces"]["exporters"] == ["otlp_grpc/tempo"]


def test_container_logs_are_grouped_then_named_by_compose_service() -> None:
    p = _yaml(COLLECTOR)["processors"]
    assert p["groupbyattrs/container"] == {"keys": ["com.docker.compose.service"]}
    resource, log = p["transform/container-logs"]["log_statements"]
    assert resource["context"] == "resource"
    assert resource["conditions"] == ['attributes["com.docker.compose.service"] != nil']
    assert resource["statements"] == [
        'set(attributes["service.name"], attributes["com.docker.compose.service"])',
        'delete_key(attributes, "com.docker.compose.service")',
    ]
    assert log == {"context": "log", "statements": ['delete_key(attributes, "fluent.tag")']}


def _body_patterns() -> list[re.Pattern[str]]:
    """The regexes inside the OTTL replace_pattern(...) statements, as OTTL reads them."""
    statements = _yaml(COLLECTOR)["processors"]["transform/redact-log-body"]["log_statements"]
    assert statements[0]["context"] == "log"
    patterns = []
    for statement in statements[0]["statements"]:
        match = re.fullmatch(r'replace_pattern\(body, "(.+)", "\*\*\*\*"\)', statement)
        assert match, statement
        patterns.append(re.compile(match.group(1).replace("\\\\", "\\")))  # OTTL string escapes
    return patterns


def test_log_body_masking_uses_the_same_patterns_as_attribute_redaction() -> None:
    blocked = _yaml(COLLECTOR)["processors"]["redaction"]["blocked_values"]
    assert [p.pattern for p in _body_patterns()] == blocked


def test_log_body_masking_turns_secrets_into_stars() -> None:
    line = (
        "login failed for carol@example.com, token "
        "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl key sk-1234567890abcdefXYZ"
    )
    for pattern in _body_patterns():
        line = pattern.sub("****", line)
    assert line == "login failed for ****, token **** key ****"
    # ids that join logs to traces survive untouched
    kept = '{"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "user": "8f1c0000-alice"}'
    for pattern in _body_patterns():
        assert pattern.sub("****", kept) == kept


# --- Compose ----------------------------------------------------------------------------------


def test_the_shared_logging_block_uses_the_engines_fluentd_driver() -> None:
    anchor = _yaml(COMPOSE)["x-logging"]
    assert anchor == {
        "driver": "fluentd",
        "options": {
            "fluentd-address": "127.0.0.1:24224",
            "fluentd-async": "true",
            "labels": "com.docker.compose.service",
            "tag": "docker",
        },
    }


def test_every_service_except_the_collector_ships_its_logs() -> None:
    anchor = _yaml(COMPOSE)["x-logging"]
    for name, service in _services().items():
        if name == "otel-collector":
            assert "logging" not in service  # it can't ship its own logs to itself
        else:
            assert service.get("logging") == anchor, name
    text = COMPOSE.read_text()
    assert text.count("logging: *to-collector") == len(_services()) - 1


def test_no_container_mounts_the_docker_socket() -> None:
    for name, service in _services().items():
        for volume in service.get("volumes", []):
            assert "docker.sock" not in str(volume), name


@pytest.mark.parametrize(
    ("name", "image", "port", "command"),
    [
        ("tempo", TEMPO_IMAGE, "127.0.0.1:3200:3200",
         ["-target=all", "-config.file=/etc/tempo.yaml"]),
        ("loki", LOKI_IMAGE, "127.0.0.1:3100:3100", ["-config.file=/etc/loki/loki.yaml"]),
    ],
)  # fmt: skip
def test_tempo_and_loki_are_pinned_locked_down_and_private(
    name: str, image: str, port: str, command: list[str]
) -> None:
    s = _services()[name]
    tag, _, digest = s["image"].partition("@")
    assert tag == image
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    assert s["command"] == command
    assert s["ports"] == [port]  # the query API only, on localhost; OTLP is never published
    assert s["cap_drop"] == ["ALL"]
    assert s["security_opt"] == ["no-new-privileges:true"]
    assert s["restart"] == "unless-stopped"
    assert s["deploy"]["resources"]["limits"] == {"memory": "1g", "cpus": "1"}
    assert f"{name}-data" in _yaml(COMPOSE)["volumes"]
    config_mount = s["volumes"][0].split(":")[0]
    assert (COMPOSE.parent / config_mount).resolve() == (TEMPO if name == "tempo" else LOKI)


def test_collector_publishes_the_log_port_on_localhost_only() -> None:
    assert "127.0.0.1:24224:24224" in _services()["otel-collector"]["ports"]


def test_prometheus_accepts_generated_metrics_and_keeps_exemplars() -> None:
    command = _services()["prometheus"]["command"]
    assert "--web.enable-remote-write-receiver" in command
    assert "--enable-feature=exemplar-storage" in command
    assert _services()["prometheus"]["ports"] == ["127.0.0.1:9090:9090"]
    jobs = {j["job_name"]: j for j in _yaml(PROMETHEUS)["scrape_configs"]}
    assert jobs["tempo"]["static_configs"] == [{"targets": ["tempo:3200"]}]
    assert jobs["loki"]["static_configs"] == [{"targets": ["loki:3100"]}]


# --- Grafana ----------------------------------------------------------------------------------


def test_grafana_links_every_signal_to_the_others() -> None:
    sources = _sources()
    assert set(sources) == {"prometheus", "tempo", "loki", "alertmanager"}
    assert all(d["access"] == "proxy" and d["editable"] is False for d in sources.values())
    # 1. metric point -> its example trace
    prom = sources["prometheus"]["jsonData"]
    assert prom["exemplarTraceIdDestinations"] == [{"name": "trace_id", "datasourceUid": "tempo"}]
    # 2. span -> that request's log lines, and 3. span -> that service's request rate
    tempo = sources["tempo"]
    assert tempo["url"] == "http://tempo:3200"
    jd = tempo["jsonData"]
    assert jd["serviceMap"] == {"datasourceUid": "prometheus"}
    assert jd["nodeGraph"] == {"enabled": True}
    logs = jd["tracesToLogsV2"]
    assert logs["datasourceUid"] == "loki"
    assert logs["filterByTraceID"] is True
    assert logs["tags"] == [{"key": "service.name", "value": "service_name"}]
    metrics = jd["tracesToMetrics"]
    assert metrics["datasourceUid"] == "prometheus"
    query = metrics["queries"][0]["query"]
    assert query == "sum(rate(traces_spanmetrics_calls_total{$$__tags}[5m]))"  # $$ = literal $
    # 4. log line -> its trace
    loki = sources["loki"]
    assert loki["url"] == "http://loki:3100"
    (field,) = loki["jsonData"]["derivedFields"]
    assert field["datasourceUid"] == "tempo"
    assert field["url"] == "$${__value.raw}"
    assert field["urlDisplayLabel"] == "View trace"


def test_derived_field_regex_finds_the_trace_id_in_a_real_rag_api_log_line() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.step21")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        tracer = TracerProvider().get_tracer("test")
        with tracer.start_as_current_span("search") as span:
            logger.error("query/policy mismatch: dropped [4]")
            trace_id = format(span.get_span_context().trace_id, "032x")
    finally:
        logger.removeHandler(handler)
    line = stream.getvalue().strip()
    assert json.loads(line)["trace_id"] == trace_id
    regex = _sources()["loki"]["jsonData"]["derivedFields"][0]["matcherRegex"]
    match = re.search(regex, line)
    assert match
    assert match.group(1) == trace_id


# --- decision record --------------------------------------------------------------------------


def test_adr_0021_is_recorded() -> None:
    text = ADR.read_text()
    assert text.startswith("# ADR-0021: Use Tempo and Loki for traces and logs")
    assert "**Status:** Accepted" in text
    for fact in ("-target=all", "fluent_forward", "groupbyattrs", "exemplar", "Revisit when"):
        assert fact in text
    assert ADR.name in (ADR.parent / "README.md").read_text()


# --- the real binaries check their own configs (need Docker and the pinned images) ------------

DOCKER = shutil.which("docker")


def _image(image: str) -> None:
    if DOCKER is None:
        pytest.skip("docker not installed")
    have = subprocess.run(  # noqa: S603 - fixed arguments
        [DOCKER, "image", "inspect", image], capture_output=True, check=False
    )
    if have.returncode != 0:
        pytest.skip(f"{image} not pulled")


def test_tempo_accepts_its_config() -> None:
    _image(TEMPO_IMAGE)
    assert DOCKER is not None
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [DOCKER, "run", "--rm", "-v", f"{TEMPO.parent}:/c:ro", TEMPO_IMAGE, "-target=all",
         "-config.file=/c/tempo.yaml", "-config.verify=true"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr


def test_loki_accepts_its_config() -> None:
    _image(LOKI_IMAGE)
    assert DOCKER is not None
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [DOCKER, "run", "--rm", "-v", f"{LOKI.parent}:/c:ro", LOKI_IMAGE,
         "-config.file=/c/loki.yaml", "-verify-config"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
    assert "config is valid" in result.stdout + result.stderr


# --- live -------------------------------------------------------------------------------------


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _listening(3200), reason="Tempo not running (just up)")
def test_live_tempo_is_ready() -> None:
    assert httpx.get("http://127.0.0.1:3200/ready", timeout=3).text.strip() == "ready"


@pytest.mark.skipif(not _listening(3100), reason="Loki not running (just up)")
def test_live_loki_is_ready_and_knows_our_services() -> None:
    assert httpx.get("http://127.0.0.1:3100/ready", timeout=3).text.strip() == "ready"
    r = httpx.get("http://127.0.0.1:3100/loki/api/v1/label/service_name/values", timeout=3)
    assert r.status_code == 200
    assert r.json()["status"] == "success"
