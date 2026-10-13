"""Step 20: Prometheus, Alertmanager and Grafana: dashboards, SLOs and alerts.

The static tests read the committed files and check the rules the chapter sets: Prometheus receives
OTLP and scrapes every component (OPA with a metrics-only token, Qdrant with its read-only key,
Postgres through the exporter); the search SLO uses multi-window burn rates; every alert has a
severity, a summary and a runbook that exists; Alertmanager routes by severity with inhibition;
Grafana's data sources and dashboards are provisioned from Git and the generated dashboard JSON is up
to date; the new Compose services are pinned by tag + digest and published on 127.0.0.1 only; the
two new secrets are generated and documented; ADR-0020 is recorded.

When Docker and the pinned images are available, promtool and amtool validate everything and run the
alert unit tests (``just alerts-test``). The live test runs only when Prometheus answers on
127.0.0.1:9090 (``just up``).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "infra" / "config"
PROM = CONFIG / "prometheus"
RULES = PROM / "rules"
ALERTMANAGER = CONFIG / "alertmanager" / "alertmanager.yml"
GRAFANA = CONFIG / "grafana"
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
JUSTFILE = REPO / "justfile"
ADR = REPO / "docs" / "adr" / "0020-use-prometheus-alertmanager-and-grafana.md"
PROM_IMAGE = "prom/prometheus:v3.13.4"
AM_IMAGE = "prom/alertmanager:v0.34.1"


def _yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


def _compose() -> dict[str, Any]:
    return _yaml(COMPOSE)


def _service(name: str) -> dict[str, Any]:
    service = _compose()["services"][name]
    assert isinstance(service, dict)
    return service


def _rules() -> list[dict[str, Any]]:
    return [
        rule
        for path in sorted(RULES.glob("*.yml"))
        for group in _yaml(path)["groups"]
        for rule in group["rules"]
    ]


def _alerts() -> dict[str, dict[str, Any]]:
    return {r["alert"]: r for r in _rules() if "alert" in r}


# --- Prometheus -------------------------------------------------------------------------------


def test_prometheus_globals_otlp_and_alertmanager() -> None:
    cfg = _yaml(PROM / "prometheus.yml")
    assert cfg["global"] == {
        "scrape_interval": "15s",
        "evaluation_interval": "15s",
        "external_labels": {"environment": "dev"},
    }
    assert cfg["otlp"]["promote_resource_attributes"] == [
        "service.version",
        "deployment.environment.name",
    ]
    assert cfg["rule_files"] == ["/etc/prometheus/rules/*.yml"]
    targets = cfg["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert targets == ["alertmanager:9093"]


def test_every_component_is_scraped_with_least_privilege() -> None:
    jobs = {j["job_name"]: j for j in _yaml(PROM / "prometheus.yml")["scrape_configs"]}
    assert set(jobs) == {
        "prometheus", "alertmanager", "otel-collector", "keycloak", "opa", "qdrant",
        "postgres-rag", "tei", "tempo", "loki", "openbao",
    }  # fmt: skip

    def targets(job: str) -> list[str]:
        result: list[str] = jobs[job]["static_configs"][0]["targets"]
        return result

    assert targets("otel-collector") == ["otel-collector:8888"]
    assert targets("keycloak") == ["keycloak:9000"]  # the management port, never published
    assert targets("postgres-rag") == ["postgres-exporter:9187"]
    assert targets("tei") == ["host.docker.internal:9083", "host.docker.internal:9084"]
    # Step 28: OpenBao's metrics need no token (they hold counts, never secrets; tests/test_vault.py)
    assert targets("openbao") == ["openbao:8200"]
    assert jobs["openbao"]["metrics_path"] == "/v1/sys/metrics"
    assert jobs["openbao"]["params"] == {"format": ["prometheus"]}
    assert "authorization" not in jobs["openbao"]
    # bearer tokens come from secret FILES that Compose mounts into the Prometheus container
    assert jobs["opa"]["authorization"]["credentials_file"] == "/run/secrets/opa_metrics_token"
    qdrant = jobs["qdrant"]["authorization"]["credentials_file"]
    assert qdrant == "/run/secrets/qdrant_read_only_api_key"
    secrets = set(_service("prometheus")["secrets"])
    assert secrets == {"opa_metrics_token", "qdrant_read_only_api_key"}


def test_the_collector_pushes_metrics_to_prometheus_and_exposes_its_own() -> None:
    cfg = _yaml(CONFIG / "otel-collector" / "config.yaml")
    exporter = cfg["exporters"]["otlp_http/prometheus"]
    assert exporter["endpoint"] == "http://prometheus:9090/api/v1/otlp"
    assert cfg["service"]["pipelines"]["metrics"]["exporters"] == ["otlp_http/prometheus"]
    reader = cfg["service"]["telemetry"]["metrics"]["readers"][0]["pull"]["exporter"]
    assert reader == {"prometheus": {"host": "0.0.0.0", "port": 8888}}  # noqa: S104 - container-internal


# --- rules ------------------------------------------------------------------------------------


def test_search_slo_uses_multi_window_burn_rates() -> None:
    alerts = _alerts()
    fast, slow = alerts["RagSearchErrorBudgetFastBurn"], alerts["RagSearchErrorBudgetSlowBurn"]
    assert "rag:search_errors:ratio_rate1h > (14.4 * 0.01)" in fast["expr"]
    assert "rag:search_errors:ratio_rate5m > (14.4 * 0.01)" in fast["expr"]
    assert (fast["for"], fast["labels"]["severity"]) == ("2m", "critical")
    assert "rag:search_errors:ratio_rate6h > (6 * 0.01)" in slow["expr"]
    assert "rag:search_errors:ratio_rate30m > (6 * 0.01)" in slow["expr"]
    assert (slow["for"], slow["labels"]["severity"]) == ("15m", "warning")
    assert alerts["RagSearchSlow"]["expr"] == "rag:search_latency:p95_5m > 2"
    records = {r["record"] for r in _rules() if "record" in r}
    assert records == {
        "rag:search_errors:ratio_rate5m", "rag:search_errors:ratio_rate30m",
        "rag:search_errors:ratio_rate1h", "rag:search_errors:ratio_rate6h",
        "rag:search_latency:p95_5m",
        # Step 37: answer quality (rules/rag-answers.yml)
        "rag:answer_outcome:ratio_rate15m", "rag:answer_outcome:ratio_rate1d",
        "rag:answer_latency:p95_15m", "rag:feedback_down:ratio_rate1h",
    }  # fmt: skip


def test_every_alert_has_a_severity_a_summary_and_an_existing_runbook() -> None:
    alerts = _alerts()
    assert set(alerts) == {
        "RagSearchErrorBudgetFastBurn", "RagSearchErrorBudgetSlowBurn", "RagSearchSlow",
        "RagPolicyQueryMismatch", "KeycloakLoginFailuresHigh", "TargetDown",
        "OtelCollectorLosingData", "RagAuditWriteFailing",  # Step 23
        "OpenBaoSealed", "OpenBaoAuditFailing",  # Step 28
        "RagGuardBlocksSpike", "RagAbstentionSpike", "RagThumbsDownHigh",  # Step 37
        "RagAnswerLatencyHigh", "RagScheduledJobFailed", "RagCanaryAborted",
    }  # fmt: skip
    for name, rule in alerts.items():
        assert rule["labels"]["severity"] in {"critical", "warning"}, name
        assert rule["annotations"]["summary"], name
        runbook = REPO / rule["annotations"]["runbook"]
        assert runbook.is_file(), f"{name}: missing {runbook}"
        assert name in runbook.read_text(), f"{name}: runbook doesn't mention the alert"
    # pages are reserved for user harm and security-control misfires
    critical = {n for n, r in alerts.items() if r["labels"]["severity"] == "critical"}
    # Step 23: a failing audit write means searches are being refused right now
    assert critical == {
        "RagSearchErrorBudgetFastBurn",
        "RagPolicyQueryMismatch",
        "RagAuditWriteFailing",
        "OpenBaoSealed",  # Step 28: no new credentials until someone unseals
        "OpenBaoAuditFailing",  # Step 28: OpenBao is refusing every request
    }


def test_collector_counters_are_named_explicitly_without_total() -> None:
    expr = _alerts()["OtelCollectorLosingData"]["expr"]
    assert "_total" not in expr  # Collector 0.162's own counters have no _total suffix
    assert "=~" not in expr  # one name pattern over several metrics made Prometheus answer 422
    assert expr.count("or vector(0)") == 6


def test_unit_tests_cover_every_rule_file_with_eleven_cases() -> None:
    tests = _yaml(PROM / "tests" / "rules_test.yml")
    # Step 37: the answer-quality rules have their own test file (tests/rag_answers_test.yml)
    files = {(PROM / "tests" / f).resolve()
             for path in sorted((PROM / "tests").glob("*.yml")) for f in _yaml(path)["rule_files"]}  # fmt: skip
    assert files == {p.resolve() for p in RULES.glob("*.yml")}
    # Step 23 adds RagAuditWriteFailing, Step 24 a PromQL test, Step 28 the two OpenBao alerts
    assert len(tests["tests"]) == 11
    tested = {c["alertname"] for t in tests["tests"] for c in t.get("alert_rule_test", [])}
    assert tested >= {
        "RagSearchErrorBudgetFastBurn", "RagSearchErrorBudgetSlowBurn", "RagSearchSlow",
        "RagPolicyQueryMismatch", "TargetDown", "OtelCollectorLosingData", "RagAuditWriteFailing",
        "OpenBaoSealed", "OpenBaoAuditFailing",
    }  # fmt: skip


# --- Alertmanager -----------------------------------------------------------------------------


def test_alertmanager_groups_routes_by_severity_and_inhibits() -> None:
    cfg = _yaml(ALERTMANAGER)
    route = cfg["route"]
    assert route["receiver"] == "platform-team"
    assert route["group_by"] == ["alertname", "service"]
    assert (route["group_wait"], route["group_interval"], route["repeat_interval"]) == (
        "30s",
        "5m",
        "4h",
    )
    assert route["routes"] == [
        {
            "matchers": ['severity="critical"'],
            "receiver": "platform-team-urgent",
            "repeat_interval": "1h",
        }
    ]
    assert cfg["inhibit_rules"] == [
        {
            "source_matchers": ['severity="critical"'],
            "target_matchers": ['severity="warning"'],
            "equal": ["alertname", "service"],
        }
    ]
    assert [r["name"] for r in cfg["receivers"]] == ["platform-team", "platform-team-urgent"]


# --- Grafana ----------------------------------------------------------------------------------


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_dashboards", REPO / "scripts" / "build_dashboards.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grafana_data_sources_are_provisioned_with_fixed_uids() -> None:
    sources = {
        d["uid"]: d
        for d in _yaml(GRAFANA / "provisioning" / "datasources" / "datasources.yaml")["datasources"]
    }
    assert sources["prometheus"]["url"] == "http://prometheus:9090"
    assert sources["prometheus"]["isDefault"] is True
    assert sources["alertmanager"]["url"] == "http://alertmanager:9093"
    assert all(d["access"] == "proxy" and d["editable"] is False for d in sources.values())
    assert _builder().DS == {"type": "prometheus", "uid": "prometheus"}


def test_dashboards_are_owned_by_git() -> None:
    provider = _yaml(GRAFANA / "provisioning" / "dashboards" / "dashboards.yaml")["providers"][0]
    assert provider["disableDeletion"] is True
    assert provider["allowUiUpdates"] is False
    path = provider["options"]["path"]
    assert f"../config/grafana/dashboards:{path}:ro" in _service("grafana")["volumes"]


def test_committed_dashboard_json_is_up_to_date() -> None:
    builder = _builder()
    for name, build in builder.DASHBOARDS.items():
        committed = (GRAFANA / "dashboards" / name).read_text()
        assert committed == json.dumps(build(), indent=2) + "\n", f"run `just dashboards` ({name})"


def test_every_panel_queries_the_provisioned_prometheus() -> None:
    dashboard = json.loads((GRAFANA / "dashboards" / "rag-overview.json").read_text())
    assert dashboard["uid"] == "rag-overview"
    assert dashboard["editable"] is False
    queries = [p for p in dashboard["panels"] if p["type"] != "row"]
    assert len(queries) == 11  # Step 24 adds "Active prompt versions"
    for panel in queries:
        assert panel["datasource"]["uid"] == "prometheus"
        assert all(t["expr"] for t in panel["targets"])
    ids = [p["id"] for p in dashboard["panels"]]
    assert ids == list(range(1, len(ids) + 1))


def test_prompt_versions_are_shown_and_marked_on_the_graphs() -> None:
    """Step 24: a table of what runs where, and an annotation whenever a prompt version changes."""
    dashboard = json.loads((GRAFANA / "dashboards" / "rag-overview.json").read_text())
    [table] = [p for p in dashboard["panels"] if p["title"] == "Active prompt versions"]
    assert "rag_prompt_info" in table["targets"][0]["expr"]
    [marker] = dashboard["annotations"]["list"]
    assert marker["name"] == "Prompt version changes"
    assert "unless" in marker["expr"]
    assert "offset 5m" in marker["expr"]
    # promtool checks the annotation query itself (rules_test.yml, case 9)
    tests = _yaml(PROM / "tests" / "rules_test.yml")["tests"]
    exprs = [c["expr"] for t in tests for c in t.get("promql_expr_test", [])]
    assert any("rag_prompt_info offset 5m" in e for e in exprs)


# --- Compose ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("service", "image", "port"),
    [
        ("prometheus", PROM_IMAGE, "127.0.0.1:9090:9090"),
        ("alertmanager", AM_IMAGE, "127.0.0.1:9093:9093"),
        ("grafana", "grafana/grafana:13.2.3", "127.0.0.1:3000:3000"),
        ("postgres-exporter", "quay.io/prometheuscommunity/postgres-exporter:v0.20.1", None),
    ],
)
def test_monitoring_services_are_pinned_locked_down_and_private(
    service: str, image: str, port: str | None
) -> None:
    s = _service(service)
    tag, _, digest = s["image"].partition("@")
    assert tag == image
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    assert s.get("ports", [None]) == [port]  # localhost only; the exporter isn't published at all
    assert s["cap_drop"] == ["ALL"]
    assert s["security_opt"] == ["no-new-privileges:true"]
    assert s["restart"] == "unless-stopped"
    assert "limits" in s["deploy"]["resources"]


def test_prometheus_flags_retention_and_otlp() -> None:
    s = _service("prometheus")
    assert s["command"] == [
        "--config.file=/etc/prometheus/prometheus.yml",
        "--storage.tsdb.path=/prometheus",
        "--storage.tsdb.retention.time=15d",
        "--storage.tsdb.retention.size=5GB",
        "--web.enable-otlp-receiver",
        "--web.enable-remote-write-receiver",  # Step 21: Tempo's generated metrics
        "--enable-feature=exemplar-storage",  # Step 21: trace ids on metric points
    ]
    assert "host.docker.internal:host-gateway" in s["extra_hosts"]
    assert "--cluster.listen-address=" in _service("alertmanager")["command"]
    assert _service("alertmanager")["read_only"] is True


def test_grafana_login_only_from_a_secret_file() -> None:
    env = _service("grafana")["environment"]
    assert env["GF_SECURITY_ADMIN_PASSWORD__FILE"] == "/run/secrets/grafana_admin_password"  # noqa: S105 - a path
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert _service("grafana")["depends_on"] == {"prometheus": {"condition": "service_healthy"}}


def test_postgres_is_monitored_by_a_statistics_only_role() -> None:
    env = _service("postgres-exporter")["environment"]
    assert env["DATA_SOURCE_USER"] == "rag_metrics"
    assert env["DATA_SOURCE_PASS_FILE"] == "/run/secrets/rag_db_metrics_password"  # noqa: S105 - a path
    assert "rag_db_metrics_password" in _service("rag-db")["secrets"]
    init = (CONFIG / "rag-db" / "init" / "01-roles.sh").read_text()
    assert (
        "CREATE ROLE rag_metrics LOGIN PASSWORD :'metrics_pw' CONNECTION LIMIT 3 IN ROLE pg_monitor;"
        in init
    )
    assert 'metrics_pw="$(cat /run/secrets/rag_db_metrics_password)"' in init


def test_opa_and_keycloak_expose_what_the_scrapes_need() -> None:
    assert _service("opa")["environment"]["OPA_METRICS_TOKEN"] == "${OPA_METRICS_TOKEN}"  # noqa: S105
    rego = (REPO / "policies" / "system" / "authz" / "authz.rego").read_text()
    assert "opa.runtime().env.OPA_METRICS_TOKEN" in rego
    assert 'input.path == ["metrics"]' in rego
    env = _service("keycloak")["environment"]
    assert env["KC_METRICS_ENABLED"] == "true"
    assert env["KC_EVENT_METRICS_USER_ENABLED"] == "true"


def test_new_secrets_are_generated_documented_and_wired() -> None:
    secrets = _compose()["secrets"]
    for name, var in [
        ("opa_metrics_token", "OPA_METRICS_TOKEN"),
        ("grafana_admin_password", "GRAFANA_ADMIN_PASSWORD"),
        ("rag_db_metrics_password", "RAG_DB_METRICS_PASSWORD"),
    ]:
        assert secrets[name] == {"environment": var}
        assert re.search(
            rf"^{var}=\$\(rand\)$", (REPO / "scripts" / "new-dev-secrets.sh").read_text(), re.M
        )
        assert re.search(rf"^{var}=<", (REPO / ".env.example").read_text(), re.M)
    for volume in ("prometheus-data", "alertmanager-data", "grafana-data"):
        assert volume in _compose()["volumes"]


# --- tooling and decision record --------------------------------------------------------------


def test_just_check_runs_the_alert_tests_and_the_dashboard_drift_check() -> None:
    text = JUSTFILE.read_text()
    assert f'prom_image := "{PROM_IMAGE}"' in text
    assert f'am_image := "{AM_IMAGE}"' in text
    check = text.split("\ncheck:\n", 1)[1].split("\n\n", 1)[0]
    assert "just alerts-test" in check
    assert "just dashboards-check" in check
    recipe = text.split("\nalerts-test:\n", 1)[1].split("\n\n", 1)[0]
    assert "test rules tests/rules_test.yml" in recipe
    assert "check-config /a/alertmanager.yml" in recipe
    assert "kill -s HUP prometheus" in text


def test_adr_0020_is_recorded() -> None:
    text = ADR.read_text()
    assert text.startswith(
        "# ADR-0020: Use Prometheus, Alertmanager and Grafana with SLO-based alerting"
    )
    assert "**Status:** Accepted" in text
    for fact in ("14.4x", "promtool", "pg_monitor", "Revisit when"):
        assert fact in text
    assert ADR.name in (ADR.parent / "README.md").read_text()


# --- promtool and amtool (need Docker and the pinned images) ----------------------------------

DOCKER = shutil.which("docker")


def _image(image: str) -> None:
    if DOCKER is None:
        pytest.skip("docker not installed")
    have = subprocess.run(  # noqa: S603 - fixed arguments
        [DOCKER, "image", "inspect", image], capture_output=True, check=False
    )
    if have.returncode != 0:
        pytest.skip(f"{image} not pulled")


def _tool(image: str, tool: str, mount: str, *args: str) -> subprocess.CompletedProcess[str]:
    assert DOCKER is not None
    return subprocess.run(  # noqa: S603 - fixed arguments
        [DOCKER, "run", "--rm", "-v", mount, "-w", "/p", "--entrypoint", tool, image, *args],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_promtool_accepts_the_rules_and_every_alert_test_passes() -> None:
    _image(PROM_IMAGE)
    mount = f"{PROM}:/p:ro"
    rules = ["rules/slo-rag-search.yml", "rules/security.yml", "rules/platform.yml",
             "rules/rag-answers.yml"]  # fmt: skip
    checked = _tool(PROM_IMAGE, "promtool", mount, "check", "rules", *rules)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert checked.stdout.count("SUCCESS") == 4
    tested = _tool(PROM_IMAGE, "promtool", mount, "test", "rules", "tests/rules_test.yml",
                   "tests/rag_answers_test.yml")  # fmt: skip
    assert tested.returncode == 0, tested.stdout + tested.stderr


def test_amtool_accepts_the_alertmanager_config() -> None:
    _image(AM_IMAGE)
    result = _tool(
        AM_IMAGE, "amtool", f"{ALERTMANAGER.parent}:/p:ro", "check-config", "/p/alertmanager.yml"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 inhibit rules" in result.stdout
    assert "2 receivers" in result.stdout


# --- live -------------------------------------------------------------------------------------


def _prometheus_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9090), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _prometheus_up(), reason="Prometheus not running (just up)")
def test_live_prometheus_is_ready_with_every_scrape_job_and_the_rules_loaded() -> None:
    assert httpx.get("http://127.0.0.1:9090/-/ready", timeout=3).status_code == 200
    targets = httpx.get("http://127.0.0.1:9090/api/v1/targets", timeout=3).json()
    jobs = {t["labels"]["job"] for t in targets["data"]["activeTargets"]}
    assert {"prometheus", "opa", "postgres-rag", "otel-collector"} <= jobs
    rules = httpx.get("http://127.0.0.1:9090/api/v1/rules", timeout=3).json()
    names = {r["name"] for g in rules["data"]["groups"] for r in g["rules"]}
    assert {"RagSearchErrorBudgetFastBurn", "RagPolicyQueryMismatch", "TargetDown"} <= names
