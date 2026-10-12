"""Step 18: OPA as the policy decision point.

The static tests read the committed files and check the rules the chapter sets: policies/ holds the
rag.authz and system.authz policies with their tests and a data.json whose roles and groups exist in
the Keycloak realm; OPA 1.21.x runs in Compose pinned by tag + digest, non-root, read-only, with
token authentication, system.authz authorisation, tests ignored, decision logs on and the policies
mounted read-only; rag-api gets the OPA URL and token (as a FILE) and starts after OPA; the token is
generated and documented; ``just policy-check`` exists and ``just check`` calls it; Regal is told
about data.json; the Brewfile installs opa and regal; ADR-0018 is recorded.

When the ``opa`` binary is on PATH the policy suite itself runs (``opa check --strict`` and
``opa test`` with the 90% coverage threshold); otherwise those tests are skipped.

The live tests run only when OPA answers on 127.0.0.1:8181 (``just up``) and need the token
(``just with-secrets uv run pytest tests/test_policy_engine.py``). They only ask for decisions.
"""

import json
import os
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
POLICIES = REPO / "policies"
DATA = POLICIES / "rag" / "authz" / "data.json"
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
REALM_FILE = REPO / "infra" / "config" / "keycloak" / "realm-rag.json"
JUSTFILE = REPO / "justfile"
ADR = REPO / "docs" / "adr" / "0018-use-opa-as-the-policy-decision-point.md"
OPA = "http://127.0.0.1:8181"
LEVELS = {"public", "internal", "confidential", "restricted"}


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def _service(name: str) -> dict[str, Any]:
    service = _compose()["services"][name]
    assert isinstance(service, dict)
    return service


def _data() -> dict[str, Any]:
    data = json.loads(DATA.read_text())
    assert isinstance(data, dict)
    return data


# --- the policies -----------------------------------------------------------------------------


def test_policy_files_are_where_the_bundle_expects_them() -> None:
    for rel in (
        "rag/authz/authz.rego",
        "rag/authz/authz_test.rego",
        "rag/authz/data.json",
        "system/authz/authz.rego",
        "system/authz/authz_test.rego",
    ):
        assert (POLICIES / rel).is_file(), rel


def test_policy_is_deny_by_default_and_reads_input_safely() -> None:
    rego = (POLICIES / "rag" / "authz" / "authz.rego").read_text()
    assert "package rag.authz" in rego
    assert "default allow := false" in rego
    assert "default clearance := -1" in rego  # no known group: no clearance at all
    for line in (
        'principal := object.get(input, "principal", {})',
        'roles := object.get(principal, "roles", [])',
        'groups := object.get(principal, "groups", [])',
    ):
        assert line in rego  # missing fields are empty, never undefined (fail closed)
    assert rego.count("# entrypoint: true") == 2  # decision and readable_ids, nothing else


def test_data_json_matches_the_keycloak_realm() -> None:
    data, realm = _data(), json.loads(REALM_FILE.read_text())
    realm_roles = {r["name"] for r in realm["roles"]["realm"]}
    realm_groups = {g["name"] for g in realm["groups"]}
    assert set(data["action_roles"].values()) <= realm_roles  # every action needs a real role
    assert set(data["group_clearance"]) == realm_groups  # every Step 16 group has a clearance
    assert data["action_roles"]["search"] == "rag-user"
    assert data["action_roles"]["admin:ping"] == "rag-admin"
    assert data["group_clearance"]["hr"] == "confidential"
    assert data["group_clearance"]["executives"] == "restricted"
    assert data["capped_groups"] == {"contractors": "internal"}
    assert set(data["group_clearance"].values()) | set(data["capped_groups"].values()) <= LEVELS


def test_system_authz_protects_opas_own_api() -> None:
    rego = (POLICIES / "system" / "authz" / "authz.rego").read_text()
    assert "package system.authz" in rego
    assert "default allow := false" in rego
    assert "opa.runtime().env.OPA_API_TOKEN" in rego
    assert '["v1", "data", "rag", "authz"]' in rego
    assert '"PUT"' not in rego  # no rule ever allows policy or data uploads


def test_regal_knows_about_data_json() -> None:
    config = yaml.safe_load((REPO / ".regal" / "config.yaml").read_text())
    rule = config["rules"]["imports"]["unresolved-reference"]
    assert rule["level"] == "error"
    assert set(rule["except-paths"]) == {f"data.rag.authz.{k}" for k in _data()}


# --- the policy suite itself (needs the opa binary) -------------------------------------------

needs_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")


def _opa(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed command, test only
        ["opa", *args],  # noqa: S607 - opa from PATH, like `just policy-check`
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


@needs_opa
def test_policies_compile_strictly_and_are_formatted() -> None:
    assert _opa("check", "--strict", "policies").returncode == 0
    fmt = _opa("fmt", "--list", "--fail", "policies")
    assert fmt.returncode == 0, fmt.stdout


@needs_opa
def test_all_21_policy_tests_pass_with_coverage_over_90() -> None:
    run = _opa("test", "policies", "--coverage", "--threshold", "90")
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(run.stdout)
    assert report["coverage"] >= 90
    verbose = _opa("test", "policies")
    assert "PASS: 21/21" in verbose.stdout


# --- OPA in Compose ---------------------------------------------------------------------------


def test_opa_is_pinned_by_tag_and_digest() -> None:
    image = _service("opa")["image"]
    assert re.fullmatch(r"openpolicyagent/opa:1\.21\.\d+-static@sha256:[0-9a-f]{64}", image)


def test_opa_api_is_locked_down_and_decisions_are_logged() -> None:
    cmd = _service("opa")["command"]
    assert cmd[:2] == ["run", "--server"]
    for flag in (
        "--addr=0.0.0.0:8181",
        "--authentication=token",
        "--authorization=basic",
        "--ignore=*_test.rego",
        "--log-format=json",
        "--set=decision_logs.console=true",
    ):
        assert flag in cmd
    assert cmd[cmd.index("--bundle") + 1] == "/policies"


def test_opa_runs_unprivileged_with_read_only_policies() -> None:
    s = _service("opa")
    assert s["volumes"] == ["../../policies:/policies:ro"]
    assert s["ports"] == ["127.0.0.1:8181:8181"]
    assert s["user"] == "65532:65532"
    assert s["read_only"] is True
    assert s["cap_drop"] == ["ALL"]
    assert s["security_opt"] == ["no-new-privileges:true"]
    assert s["environment"] == {"OPA_API_TOKEN": "${OPA_API_TOKEN}"}
    assert s["deploy"]["resources"]["limits"] == {"memory": "256m", "cpus": "0.5"}
    assert "healthcheck" not in s  # the static image has no shell or curl


def test_rag_api_gets_the_opa_url_and_token_file_and_waits_for_opa() -> None:
    s = _service("rag-api")
    assert s["environment"]["RAG_API_OPA_URL"] == "http://opa:8181"
    assert "rag_api_opa_token" in s["secrets"]
    assert s["depends_on"]["opa"] == {"condition": "service_started"}
    assert _compose()["secrets"]["rag_api_opa_token"] == {"environment": "OPA_API_TOKEN"}


def test_token_is_generated_and_documented() -> None:
    generator = (REPO / "scripts" / "new-dev-secrets.sh").read_text()
    assert "OPA_API_TOKEN=$(openssl rand -base64 48 | tr -d '/+=\\n' | cut -c1-40)" in generator
    assert re.search(r"^OPA_API_TOKEN=<", (REPO / ".env.example").read_text(), re.M)


# --- tooling ----------------------------------------------------------------------------------


def test_just_policy_check_runs_everything_and_check_calls_it() -> None:
    text = JUSTFILE.read_text()
    recipe = text.split("\npolicy-check:\n", 1)[1].split("\n\n", 1)[0]
    assert [line.strip() for line in recipe.splitlines()] == [
        "opa fmt --list --fail policies",
        "opa check --strict policies",
        "regal lint policies",
        "opa test policies --coverage --threshold 90 > /dev/null",
        "opa test policies",
    ]
    check = text.split("\ncheck:\n", 1)[1].split("\n\n", 1)[0]
    assert "just policy-check" in check


def test_brewfile_installs_opa_and_regal() -> None:
    brewfile = (REPO / "bootstrap" / "Brewfile").read_text()
    assert re.search(r'^brew "opa"', brewfile, re.M)
    assert re.search(r'^brew "regal"', brewfile, re.M)


def test_adr() -> None:
    adr = ADR.read_text()
    assert adr.startswith("# ADR-0018: Use OPA as the policy decision point")
    assert "- **Status:** Accepted" in adr
    for fact in ("Deny by default", "system.authz", "503", "readable_ids", "OpenFGA"):
        assert fact in adr
    assert ADR.name in (ADR.parent / "README.md").read_text()


# --- live OPA (opt-in) ------------------------------------------------------------------------


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(not _port_open(8181), reason="needs OPA on 127.0.0.1:8181")


def _token() -> str:
    token = os.environ.get("OPA_API_TOKEN")
    if not token:
        pytest.skip("needs OPA_API_TOKEN (run through `just with-secrets`)")
    return token


@live
def test_live_bob_gets_confidential_clearance() -> None:
    bob = {"groups": ["all-staff", "hr"], "roles": ["rag-user"]}
    r = httpx.post(
        f"{OPA}/v1/data/rag/authz/decision",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"input": {"principal": bob, "action": "search"}},
        timeout=5,
    )
    result = r.raise_for_status().json()["result"]
    assert result["allow"] is True
    assert result["filter"]["classifications"] == ["confidential", "internal", "public"]
    assert "decision_id" in r.json()  # the same id appears in the decision log


@live
def test_live_no_token_and_uploads_are_refused() -> None:
    no_token = httpx.post(f"{OPA}/v1/data/rag/authz/decision", json={}, timeout=5)
    assert no_token.status_code == 401
    upload = httpx.put(
        f"{OPA}/v1/policies/x",
        headers={"Authorization": f"Bearer {_token()}"},
        content=b"package rag.authz\nallow := true\n",
        timeout=5,
    )
    assert upload.status_code == 401
    assert httpx.get(f"{OPA}/health", timeout=5).status_code == 200  # probes need no token
