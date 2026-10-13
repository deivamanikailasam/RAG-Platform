"""Step 22: Langfuse, LLM traces with content, under control.

Static checks of the committed files against the rules the chapter sets: Langfuse 4.27 web + worker
with their own Postgres, ClickHouse and a separate, non-evicting Valkey; sign-up and vendor telemetry
off; headless initialisation of organisation, project, keys and admin; raw events in a "langfuse"
bucket on SeaweedFS through an identity scoped to that bucket; rag-api wired to Langfuse with its
secret key as a file; Grafana's Loki data source links a log line to the Langfuse trace; the
retention recipe, the secrets template and ADR-0022 exist.

The behaviour (masking, withheld titles, isolation, same trace id, the retention job) is tested in
services/rag-api/tests/test_llmtrace.py and tests/test_langfuse_retention.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
DATASOURCES = (
    REPO / "infra" / "config" / "grafana" / "provisioning" / "datasources" / "datasources.yaml"
)
LANGFUSE = [
    "langfuse-db",
    "langfuse-clickhouse",
    "langfuse-valkey",
    "langfuse-worker",
    "langfuse-web",
]


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def _services() -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = _compose()["services"]
    return services


def test_every_langfuse_service_is_pinned_and_hardened() -> None:
    services = _services()
    for name in LANGFUSE:
        svc = services[name]
        assert re.search(r"@sha256:[0-9a-f]{64}$", svc["image"]), f"{name} not pinned by digest"
        assert svc["logging"]["driver"] == "fluentd"  # Step 21: logs to the Collector
        assert "no-new-privileges:true" in svc["security_opt"]
        assert svc["deploy"]["resources"]["limits"]["memory"]
    assert ":4.27.0@" in services["langfuse-web"]["image"]
    assert ":4.27.0@" in services["langfuse-worker"]["image"]
    assert "clickhouse-server:25.12@" in services["langfuse-clickhouse"]["image"]


def test_only_the_web_ui_is_published_on_localhost_3002() -> None:
    services = _services()
    assert services["langfuse-web"]["ports"] == ["127.0.0.1:3002:3000"]  # 3000 is Grafana's
    for name in LANGFUSE[:-1]:
        assert "ports" not in services[name], f"{name} must stay inside the Compose network"


def test_shared_settings_keep_data_home_and_use_the_scoped_bucket() -> None:
    env = _compose()["x-langfuse-env"]
    assert env["TELEMETRY_ENABLED"] == "false"
    assert env["CLICKHOUSE_CLUSTER_ENABLED"] == "false"
    assert env["REDIS_HOST"] == "langfuse-valkey"  # NOT Step 15's cache
    assert env["LANGFUSE_S3_EVENT_UPLOAD_BUCKET"] == "langfuse"
    assert env["LANGFUSE_S3_EVENT_UPLOAD_PREFIX"] == "events/"  # the 30-day lifecycle rule's prefix
    assert env["LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE"] == "true"  # SeaweedFS
    assert env["LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT"] == "http://object-store:8333"
    assert env["LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT"] == "http://localhost:8333"  # the browser's view
    assert env["LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID"] == "${S3_LANGFUSE_ACCESS_KEY}"
    services = _services()
    assert services["langfuse-worker"]["environment"] == env


def test_web_has_signup_off_and_headless_init() -> None:
    env = _services()["langfuse-web"]["environment"]
    assert env["AUTH_DISABLE_SIGNUP"] == "true"
    assert env["LANGFUSE_INIT_ORG_ID"] == "rag-platform"
    assert env["LANGFUSE_INIT_PROJECT_ID"] == "rag-platform"  # used by the Grafana link
    assert env["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"] == "${LANGFUSE_PUBLIC_KEY}"
    assert env["LANGFUSE_INIT_PROJECT_SECRET_KEY"] == "${LANGFUSE_SECRET_KEY}"  # noqa: S105 - a variable reference, not a value
    assert env["LANGFUSE_INIT_USER_PASSWORD"] == "${LANGFUSE_ADMIN_PASSWORD}"  # noqa: S105 - a variable reference, not a value
    assert env["LANGFUSE_S3_MEDIA_UPLOAD_INTERNAL_ENDPOINT"] == "http://object-store:8333"
    assert env["TELEMETRY_ENABLED"] == "false"  # merged in from the shared block


def test_langfuse_valkey_never_evicts_and_keeps_its_password_in_ram() -> None:
    svc = _services()["langfuse-valkey"]
    script = svc["command"][0]
    assert "maxmemory-policy noeviction" in script
    assert "appendonly yes" in script
    assert "/run/secrets/langfuse_valkey_password" in script
    assert svc["tmpfs"] == ["/run/valkey:size=1m,mode=0700"]
    # Step 15's Valkey is a cache with an evicting policy: the two must stay separate instances
    assert _services()["valkey"] is not svc


def test_object_store_has_a_langfuse_identity_limited_to_its_bucket() -> None:
    svc = _services()["object-store"]
    script = svc["command"][0]
    assert '"name": "langfuse"' in script
    assert '"actions": ["Read:langfuse", "Write:langfuse", "List:langfuse"]' in script
    assert {"s3_langfuse_access_key", "s3_langfuse_secret_key"} <= set(svc["secrets"])


def test_rag_api_sends_to_langfuse_with_the_secret_key_as_a_file() -> None:
    svc = _services()["rag-api"]
    assert svc["environment"]["RAG_API_LANGFUSE_BASE_URL"] == "http://langfuse-web:3000"
    assert svc["environment"]["RAG_API_LANGFUSE_PUBLIC_KEY"] == "${LANGFUSE_PUBLIC_KEY}"
    assert "RAG_API_LANGFUSE_SECRET_KEY" not in svc["environment"]  # never an env var
    assert "rag_api_langfuse_secret_key" in svc["secrets"]
    secrets = _compose()["secrets"]
    assert secrets["rag_api_langfuse_secret_key"] == {"environment": "LANGFUSE_SECRET_KEY"}
    for name in ("langfuse_db_password", "langfuse_valkey_password"):
        assert name in secrets
    volumes = _compose()["volumes"]
    for name in ("langfuse-db-data", "langfuse-clickhouse-data", "langfuse-valkey-data"):
        assert name in volumes


def test_grafana_log_line_links_to_the_langfuse_trace() -> None:
    sources = {d["uid"]: d for d in yaml.safe_load(DATASOURCES.read_text())["datasources"]}
    fields = {f["name"]: f for f in sources["loki"]["jsonData"]["derivedFields"]}
    link = fields["Langfuse"]
    assert link["url"] == "http://localhost:3002/project/rag-platform/traces/$${__value.raw}"
    assert link["urlDisplayLabel"] == "Open in Langfuse"
    assert "datasourceUid" not in link  # an external URL, not another Grafana data source
    line = '{"level": "INFO", "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "msg": "search"}'
    match = re.search(link["matcherRegex"], line)
    assert match is not None
    assert match.group(1) == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_retention_recipe_secrets_template_and_adr() -> None:
    justfile = (REPO / "justfile").read_text()
    assert "langfuse-retention *args:" in justfile
    assert "scripts/langfuse_retention.py {{args}}" in justfile
    template = (REPO / ".env.example").read_text()
    generator = (REPO / "scripts" / "new-dev-secrets.sh").read_text()
    for key in (
        "LANGFUSE_DB_PASSWORD", "LANGFUSE_CLICKHOUSE_PASSWORD", "LANGFUSE_VALKEY_PASSWORD",
        "LANGFUSE_ADMIN_PASSWORD", "S3_LANGFUSE_ACCESS_KEY", "S3_LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_ENCRYPTION_KEY",
    ):  # fmt: skip
        assert f"{key}=" in template, key
        assert f"{key}=" in generator, key
    adr = REPO / "docs" / "adr" / "0022-use-self-hosted-langfuse-for-llm-traces.md"
    assert adr.exists()
    assert "noeviction" in adr.read_text()
