"""Step 17: rag-api in the workspace, its container and Compose service, the demo and ADR-0017.

The token attacks themselves live next to the service (services/rag-api/tests/test_auth.py). These
tests check the wiring the chapter sets around it: the workspace includes services/*, the image is a
pinned two-stage uv build that runs as uid 10001 with root-owned code, the Compose service has no
capabilities, receives its two secrets as FILES, is published only on 127.0.0.1:8000 and keeps the
issuer (public name) apart from the JWKS address (internal name); the just recipes, the demo script
and ADR-0017.

The live tests run only when rag-api (127.0.0.1:8000) and Keycloak (127.0.0.1:8180) answer
(``just up``); the machine sign-in also needs ``KEYCLOAK_INGESTION_SECRET``
(``just with-secrets uv run pytest tests/test_rag_api.py``). They only read.
"""

import importlib.util
import os
import re
import socket
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import yaml

from rag_common.auth import OIDCSettings, TokenVerifier

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
DOCKERFILE = REPO / "services" / "rag-api" / "Dockerfile"
DOCKERIGNORE = REPO / ".dockerignore"
SERVICE_PYPROJECT = REPO / "services" / "rag-api" / "pyproject.toml"
JUSTFILE = REPO / "justfile"
DEMO = REPO / "scripts" / "api_demo.py"
ADR = REPO / "docs" / "adr" / "0017-validate-jwts-locally-in-every-service.md"
API = "http://127.0.0.1:8000"
KC = "http://127.0.0.1:8180"
ISSUER = "http://localhost:8180/realms/rag"


def _service() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    service = data["services"]["rag-api"]
    assert isinstance(service, dict)
    return service


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # safe: the demo only acts inside main()
    return module


# --- the workspace ----------------------------------------------------------------------------


def test_services_are_workspace_members_checked_by_mypy_and_pytest() -> None:
    root = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert "services/*" in root["tool"]["uv"]["workspace"]["members"]
    assert "services/rag-api/src" in root["tool"]["mypy"]["files"]
    assert "services" in root["tool"]["pytest"]["ini_options"]["testpaths"]
    assert "rag_api" in root["tool"]["ruff"]["lint"]["isort"]["known-first-party"]
    assert any(d.startswith("httpx") for d in root["dependency-groups"]["dev"])


def test_service_pyproject_depends_on_the_shared_library() -> None:
    project = tomllib.loads(SERVICE_PYPROJECT.read_text())
    assert project["project"]["name"] == "rag-api"
    assert project["project"]["requires-python"] == ">=3.12,<3.13"
    deps = project["project"]["dependencies"]
    assert "rag-common" in deps
    assert any(d.startswith("fastapi") for d in deps)
    assert project["tool"]["uv"]["sources"]["rag-common"] == {"workspace": True}
    common = tomllib.loads((REPO / "libs" / "rag-common" / "pyproject.toml").read_text())
    assert any(d.startswith("pyjwt[crypto]") for d in common["project"]["dependencies"])


# --- the container ----------------------------------------------------------------------------


def test_dockerfile_is_a_pinned_two_stage_locked_uv_build() -> None:
    text = DOCKERFILE.read_text()
    froms = re.findall(r"^FROM (\S+)", text, flags=re.M)
    assert len(froms) == 3  # uv binary, build stage, runtime stage
    assert all(re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", f) for f in froms)  # tag AND digest
    assert froms[0].startswith("ghcr.io/astral-sh/uv:0.11.32@")
    assert froms[1].startswith("python:3.12-slim-bookworm@")
    assert froms[2] == froms[1]
    assert (
        "--no-install-workspace" in text
    )  # dependencies layer first, cached until uv.lock changes
    assert text.count("uv sync --locked --no-dev --package rag-api") == 2
    assert "--no-editable" in text  # the runtime image needs no source tree
    runtime = text.split("FROM ", 3)[3]
    assert "COPY --from=build /app/.venv /app/.venv" in runtime
    assert "/uv" not in runtime  # no uv in the image you run


def test_container_runs_as_an_ordinary_user_with_a_healthcheck() -> None:
    text = DOCKERFILE.read_text()
    assert "useradd --system --uid 10001" in text
    assert re.search(r"^USER 10001$", text, flags=re.M)
    assert "HEALTHCHECK" in text
    assert "http://127.0.0.1:8000/healthz" in text
    assert '"--no-server-header"' in text


def test_dockerignore_sends_only_the_workspace() -> None:
    lines = DOCKERIGNORE.read_text().splitlines()
    assert lines[lines.index("*") :][:1] == ["*"]
    for keep in ("!pyproject.toml", "!uv.lock", "!libs/", "!services/"):
        assert keep in lines
    assert "!secrets/" not in lines


# --- the Compose service ----------------------------------------------------------------------


def test_compose_builds_from_the_repository_root() -> None:
    s = _service()
    assert s["build"] == {"context": "../..", "dockerfile": "services/rag-api/Dockerfile"}
    assert s["image"] == "rag-platform/rag-api:dev"


def test_issuer_is_the_public_name_and_jwks_the_internal_address() -> None:
    env = _service()["environment"]
    assert env["RAG_API_OIDC_ISSUER"] == ISSUER  # what Keycloak writes into "iss"
    assert env["RAG_API_OIDC_JWKS_URL"] == (
        "http://keycloak:8080/realms/rag/protocol/openid-connect/certs"
    )
    assert env["RAG_API_GATEWAY_URL"] == "http://litellm:4000/v1"
    assert env["RAG_API_DB_HOST"] == "rag-db"
    # Secrets only as files. The Langfuse PUBLIC key (Step 22) only identifies the project: not secret.
    public = {"RAG_API_LANGFUSE_PUBLIC_KEY"}
    assert not any("KEY" in k or "PASSWORD" in k for k in set(env) - public)


def test_secrets_arrive_as_files_from_the_step_10_and_11_values() -> None:
    # + the OPA token since Step 18 (checked in tests/test_policy_engine.py)
    assert _service()["secrets"] == [
        "rag_api_gateway_key",
        "rag_api_db_password",
        "rag_api_opa_token",
        "rag_api_langfuse_secret_key",  # Step 22: checked in tests/test_langfuse.py
        "rag_api_audit_db_password",  # Step 23: the append-only audit_writer role
    ]
    secrets = yaml.safe_load(COMPOSE.read_text())["secrets"]
    assert secrets["rag_api_gateway_key"] == {"environment": "RAG_API_GATEWAY_KEY"}
    assert secrets["rag_api_db_password"] == {"environment": "RAG_DB_APP_PASSWORD"}
    assert secrets["rag_api_audit_db_password"] == {"environment": "AUDIT_DB_WRITER_PASSWORD"}


def test_container_is_locked_down_and_localhost_only() -> None:
    s = _service()
    assert s["ports"] == ["127.0.0.1:8000:8000"]
    # Compose can't combine read_only with environment-sourced secrets, so the root filesystem is
    # writable in principle; the app process still can't change its own code (next test).
    assert "read_only" not in s
    assert s["tmpfs"] == ["/tmp"]  # noqa: S108 - a RAM-only scratch folder inside the container
    assert s["cap_drop"] == ["ALL"]
    assert s["security_opt"] == ["no-new-privileges:true"]
    assert s["restart"] == "unless-stopped"
    assert s["deploy"]["resources"]["limits"] == {"memory": "512m", "cpus": "1"}
    assert {k: v["condition"] for k, v in s["depends_on"].items()} == {
        "keycloak": "service_healthy",
        "rag-db": "service_healthy",
        "litellm": "service_healthy",
        "opa": "service_started",  # Step 18: the static OPA image has no healthcheck
        "otel-collector": "service_started",  # Step 19: the Collector image has no shell either
        "rag-api-agent": "service_healthy",  # Step 28: its OpenBao credentials files exist
    }


def test_app_files_belong_to_root_not_to_the_app_user() -> None:
    text = DOCKERFILE.read_text()
    assert "--chown" not in text  # COPY keeps /app/.venv owned by root
    assert "chown" not in text
    assert "chmod" not in text
    assert text.index("COPY --from=build /app/.venv") < text.index("USER 10001")


# --- recipes, demo, ADR -----------------------------------------------------------------------


def test_just_recipes() -> None:
    text = JUSTFILE.read_text()
    assert "api-up:" in text
    assert "up -d --build rag-api" in text
    assert "api-demo:\n    just with-secrets uv run --with httpx scripts/api_demo.py" in text


def test_demo_uses_device_flow_and_client_credentials_and_forges_a_signature() -> None:
    demo = _load(DEMO)
    assert (API, f"{KC}/realms/rag/protocol/openid-connect") == (demo.API, demo.OIDC)
    text = DEMO.read_text()
    assert "urn:ietf:params:oauth:grant-type:device_code" in text
    assert '"client_credentials"' in text
    assert 'os.environ["KEYCLOAK_INGESTION_SECRET"]' in text
    assert "password" not in text.replace("never sees your password", "")  # no password grant
    forged = demo.forge("aaa.bbb.cccccccccc")
    assert forged == "aaa.bbb.ccccAAAAAA"


def test_adr() -> None:
    adr = ADR.read_text()
    assert adr.startswith("# ADR-0017: Validate JWTs locally in every service")
    assert "- **Status:** Accepted" in adr
    for fact in ("RS256 only", "503", "403", "user=sub", "Introspection (RFC 7662)"):
        assert fact in adr
    assert (
        "0017-validate-jwts-locally-in-every-service.md" in (ADR.parent / "README.md").read_text()
    )


# --- live rag-api + Keycloak (opt-in) ---------------------------------------------------------


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(
    not (_port_open(8000) and _port_open(8180)),
    reason="needs rag-api on 127.0.0.1:8000 and Keycloak on 127.0.0.1:8180",
)


def _machine_token() -> str:
    secret = os.environ.get("KEYCLOAK_INGESTION_SECRET")
    if not secret:
        pytest.skip("needs KEYCLOAK_INGESTION_SECRET (run through `just with-secrets`)")
    r = httpx.post(
        f"{KC}/realms/rag/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "ingestion-worker",
            "client_secret": secret,
        },
        timeout=10,
    )
    return str(r.raise_for_status().json()["access_token"])


@live
def test_live_health_is_public_and_me_needs_a_token() -> None:
    assert httpx.get(f"{API}/healthz", timeout=5).json() == {"status": "ok"}
    r = httpx.get(f"{API}/v1/me", timeout=5)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == 'Bearer realm="rag-api"'
    assert "server" not in r.headers  # --no-server-header


@live
def test_live_machine_is_known_but_may_not_search() -> None:
    token = _machine_token()
    auth = {"Authorization": f"Bearer {token}"}
    me = httpx.get(f"{API}/v1/me", headers=auth, timeout=10)
    assert me.status_code == 200
    assert me.json()["username"] == "service-account-ingestion-worker"
    assert me.json()["service_account"] is True
    assert me.json()["groups"] == []
    assert "rag-ingest" in me.json()["roles"]
    r = httpx.post(f"{API}/v1/search", json={"query": "x"}, headers=auth, timeout=10)
    assert r.status_code == 403


@live
def test_live_forged_signature_is_401() -> None:
    head, payload, sig = _machine_token().split(".")
    forged = f"{head}.{payload}.{sig[:-6]}AAAAAA"
    r = httpx.get(f"{API}/v1/me", headers={"Authorization": f"Bearer {forged}"}, timeout=10)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith('Bearer realm="rag-api", error="invalid_token"')


@live
def test_live_shared_verifier_accepts_a_real_keycloak_token() -> None:
    # Fetch keys through 127.0.0.1 while the token says localhost: the issuer is text, not an address.
    verifier = TokenVerifier(
        OIDCSettings(ISSUER, "rag-api", f"{KC}/realms/rag/protocol/openid-connect/certs")
    )
    principal = verifier.verify(_machine_token())
    assert principal.client_id == "ingestion-worker"
    assert principal.is_service_account
