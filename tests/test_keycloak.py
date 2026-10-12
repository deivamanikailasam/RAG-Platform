"""Step 16: Keycloak realm 'rag', users, groups, roles, clients and service accounts.

The static tests read the committed files and check the rules the chapter sets: Keycloak 26.8.x
pinned by tag + digest in production mode with its own private Postgres, only 127.0.0.1:8180
published (management port 9000 stays internal), passwords and client secrets only as secret FILES,
a realm file with no secrets (``${...}`` placeholders), password policy + temporary lockout + short
token lifetimes + login/admin events, groups that match the documents' ``acl_groups`` and carry the
roles, no password grant / implicit flow / wildcard redirect anywhere, least-privilege service
accounts, the generator and ``.env.example``, the two ``just`` recipes, both scripts and ADR-0016.

The live tests run only when Keycloak answers on 127.0.0.1:8180 (``just up``). The machine-login
tests also need the client secrets (``just with-secrets uv run pytest tests/test_keycloak.py``).
They only sign in and read; nothing is created or changed.
"""

import base64
import importlib.util
import json
import os
import re
import socket
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
REALM_FILE = REPO / "infra" / "config" / "keycloak" / "realm-rag.json"
JUSTFILE = REPO / "justfile"
USERS_SCRIPT = REPO / "scripts" / "kc_users.py"
WHOAMI_SCRIPT = REPO / "scripts" / "kc_whoami.py"
PG_DEMO = REPO / "scripts" / "pg_demo.py"
ADR = REPO / "docs" / "adr" / "0016-use-keycloak-for-identity.md"
NEW_SECRETS = ("KEYCLOAK_DB_PASSWORD", "KEYCLOAK_PROVISIONER_SECRET", "KEYCLOAK_INGESTION_SECRET")
SECRETS = {
    "keycloak_admin_password": "KEYCLOAK_ADMIN_PASSWORD",
    "keycloak_db_password": "KEYCLOAK_DB_PASSWORD",
    "keycloak_ingestion_secret": "KEYCLOAK_INGESTION_SECRET",
    "keycloak_provisioner_secret": "KEYCLOAK_PROVISIONER_SECRET",
}
KC = "http://127.0.0.1:8180"
ISSUER = "http://localhost:8180/realms/rag"


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def _service(name: str) -> dict[str, Any]:
    service = _compose()["services"][name]
    assert isinstance(service, dict)
    return service


def _realm() -> dict[str, Any]:
    data = json.loads(REALM_FILE.read_text())
    assert isinstance(data, dict)
    return data


def _clients() -> dict[str, dict[str, Any]]:
    return {c["clientId"]: c for c in _realm()["clients"]}


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # safe: both scripts only act inside main()
    return module


# --- Compose services -----------------------------------------------------------------------


def test_keycloak_is_26_8_pinned_by_tag_and_digest_in_production_mode() -> None:
    service = _service("keycloak")
    assert re.fullmatch(
        r"quay\.io/keycloak/keycloak:26\.8\.\d+@sha256:[0-9a-f]{64}", service["image"]
    )
    assert service["entrypoint"] == ["/bin/bash", "-c"]
    (command,) = service["command"]
    lines = command.strip().splitlines()
    # start (production mode), never start-dev; the realm is imported on first start only
    assert lines[-1] == "exec /opt/keycloak/bin/kc.sh start --import-realm"
    assert "start-dev" not in command


def test_passwords_and_client_secrets_arrive_only_as_secret_files() -> None:
    service = _service("keycloak")
    (command,) = service["command"]
    for var, name in (
        ("KC_BOOTSTRAP_ADMIN_PASSWORD", "keycloak_admin_password"),
        ("KC_DB_PASSWORD", "keycloak_db_password"),
        ("KEYCLOAK_INGESTION_SECRET", "keycloak_ingestion_secret"),
        ("KEYCLOAK_PROVISIONER_SECRET", "keycloak_provisioner_secret"),
    ):
        assert f'export {var}="$$(cat /run/secrets/{name})"' in command
    assert service["secrets"] == list(SECRETS)
    env = service["environment"]
    assert not any("PASSWORD" in k or "SECRET" in k for k in env)  # never in `docker inspect`
    top = _compose()["secrets"]
    for name, var in SECRETS.items():
        assert top[name] == {"environment": var}


def test_keycloak_settings_fix_the_issuer_and_expose_health_and_metrics_internally() -> None:
    env = _service("keycloak")["environment"]
    assert env == {
        "KC_DB": "postgres",
        "KC_DB_URL": "jdbc:postgresql://keycloak-db:5432/keycloak",  # gitleaks:allow (no password)
        "KC_DB_USERNAME": "keycloak",
        "KC_HOSTNAME": "http://localhost:8180",
        "KC_HOSTNAME_BACKCHANNEL_DYNAMIC": "true",
        "KC_HTTP_ENABLED": "true",
        "KC_HEALTH_ENABLED": "true",
        "KC_METRICS_ENABLED": "true",
        "KC_CACHE": "local",
        "KC_LOG_CONSOLE_OUTPUT": "json",
        "KC_BOOTSTRAP_ADMIN_USERNAME": "temp-admin",
        "KC_TRACING_ENABLED": "true",  # Step 19: sign-ins and token requests as spans
        "KC_TRACING_ENDPOINT": "http://otel-collector:4317",
    }


def test_only_8180_on_localhost_and_a_readiness_healthcheck() -> None:
    service = _service("keycloak")
    assert service["ports"] == ["127.0.0.1:8180:8080"]  # 9000 (health/metrics) NOT published
    assert service["volumes"] == [
        "../config/keycloak/realm-rag.json:/opt/keycloak/data/import/realm-rag.json:ro"
    ]
    assert service["depends_on"] == {"keycloak-db": {"condition": "service_healthy"}}
    check = service["healthcheck"]
    assert check["test"][:3] == ["CMD", "bash", "-c"]
    assert "HEAD /health/ready" in check["test"][3]
    assert "/dev/tcp/localhost/9000" in check["test"][3]
    assert check["start_period"] == "60s"
    assert service["restart"] == "unless-stopped"
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["deploy"]["resources"]["limits"] == {"memory": "1536m", "cpus": "2"}


def test_keycloak_db_is_private_and_pinned() -> None:
    db = _service("keycloak-db")
    assert re.fullmatch(r"postgres:17-alpine@sha256:[0-9a-f]{64}", db["image"])
    assert db["environment"] == {
        "POSTGRES_DB": "keycloak",
        "POSTGRES_USER": "keycloak",
        "POSTGRES_PASSWORD_FILE": "/run/secrets/keycloak_db_password",
    }
    assert db["secrets"] == ["keycloak_db_password"]
    assert "ports" not in db  # only Keycloak needs it
    assert db["volumes"] == ["keycloak-db-data:/var/lib/postgresql/data"]
    assert "keycloak-db-data" in _compose()["volumes"]
    assert db["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U keycloak -d keycloak"]
    assert db["deploy"]["resources"]["limits"] == {"memory": "512m", "cpus": "1"}


# --- the realm file -------------------------------------------------------------------------


def test_realm_file_holds_no_secrets_only_placeholders() -> None:
    text = REALM_FILE.read_text()
    secrets = [c["secret"] for c in _realm()["clients"] if "secret" in c]
    assert secrets == ["${KEYCLOAK_INGESTION_SECRET}", "${KEYCLOAK_PROVISIONER_SECRET}"]
    assert '"credentials"' not in text  # no user passwords in the file
    assert '"password"' not in text


def test_sign_in_rules_password_policy_and_lockout() -> None:
    realm = _realm()
    assert realm["realm"] == "rag"
    assert realm["sslRequired"] == "external"
    assert realm["registrationAllowed"] is False
    assert realm["resetPasswordAllowed"] is False
    assert realm["duplicateEmailsAllowed"] is False
    assert realm["passwordPolicy"] == (
        "length(12) and maxLength(128) and notUsername and notEmail and passwordHistory(5)"
    )
    assert realm["bruteForceProtected"] is True
    assert realm["failureFactor"] == 5
    assert realm["waitIncrementSeconds"] == 60
    assert realm["maxFailureWaitSeconds"] == 900
    assert realm["permanentLockout"] is False  # an attacker can't lock everyone out for good


def test_short_token_lifetimes_and_events() -> None:
    realm = _realm()
    assert realm["accessTokenLifespan"] == 300
    assert realm["ssoSessionIdleTimeout"] == 1800
    assert realm["ssoSessionMaxLifespan"] == 36000
    assert realm["revokeRefreshToken"] is True
    assert realm["refreshTokenMaxReuse"] == 0
    assert realm["eventsEnabled"] is True
    assert realm["eventsExpiration"] == 30 * 24 * 3600
    assert realm["adminEventsEnabled"] is True
    assert realm["adminEventsDetailsEnabled"] is True


def test_groups_carry_roles_and_match_document_acl_groups() -> None:
    realm = _realm()
    roles = {r["name"] for r in realm["roles"]["realm"]}
    assert roles == {"rag-user", "rag-admin", "rag-auditor", "rag-ingest"}
    groups = {g["name"]: g.get("realmRoles", []) for g in realm["groups"]}
    assert groups == {
        "all-staff": ["rag-user"],
        "engineering": [],
        "hr": [],
        "executives": [],
        "platform-admins": ["rag-admin"],
        "auditors": ["rag-auditor"],
    }
    assert realm["defaultGroups"] == ["/all-staff"]
    # every acl_group used by the Step 11 demo documents is a real group
    demo_groups = set(re.findall(r'\["([a-z-]+)"\]', PG_DEMO.read_text()))
    assert demo_groups
    assert demo_groups <= set(groups)


def test_no_person_gets_a_role_directly() -> None:
    for user in _realm()["users"]:
        assert user["username"].startswith("service-account-")
        assert "serviceAccountClientId" in user
        assert "groups" not in user


def test_clients_never_allow_password_grant_implicit_or_wildcard_redirects() -> None:
    clients = _clients()
    assert set(clients) == {"rag-api", "rag-web", "rag-cli", "ingestion-worker", "rag-provisioner"}
    for client in clients.values():
        assert client["directAccessGrantsEnabled"] is False
        assert client.get("implicitFlowEnabled", False) is False
        for uri in client.get("redirectUris", []):
            assert uri != "*"
            assert uri.startswith("http://localhost:3000/")
    assert clients["rag-api"]["bearerOnly"] is True
    web = clients["rag-web"]
    assert web["publicClient"] is True
    assert web["standardFlowEnabled"] is True
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"
    cli = clients["rag-cli"]
    assert cli["publicClient"] is True
    assert cli["standardFlowEnabled"] is False
    assert cli["attributes"] == {"oauth2.device.authorization.grant.enabled": "true"}
    for machine in ("ingestion-worker", "rag-provisioner"):
        assert clients[machine]["publicClient"] is False
        assert clients[machine]["serviceAccountsEnabled"] is True
        assert clients[machine]["standardFlowEnabled"] is False


def test_people_clients_put_rag_api_in_aud_and_plain_group_names_in_tokens() -> None:
    clients = _clients()
    for name in ("rag-web", "rag-cli", "ingestion-worker"):
        mappers = {m["name"]: m for m in clients[name]["protocolMappers"]}
        aud = mappers["audience-rag-api"]
        assert aud["protocolMapper"] == "oidc-audience-mapper"
        assert aud["config"]["included.client.audience"] == "rag-api"
        assert aud["config"]["access.token.claim"] == "true"
    for name in ("rag-web", "rag-cli"):
        mappers = {m["name"]: m for m in clients[name]["protocolMappers"]}
        groups = mappers["groups"]
        assert groups["protocolMapper"] == "oidc-group-membership-mapper"
        assert groups["config"]["claim.name"] == "groups"
        assert groups["config"]["full.path"] == "false"  # "hr", not "/hr"
    assert "protocolMappers" not in clients["rag-provisioner"]


def test_service_accounts_are_least_privilege() -> None:
    users = {u["serviceAccountClientId"]: u for u in _realm()["users"]}
    assert users["ingestion-worker"]["realmRoles"] == ["rag-ingest"]
    assert "clientRoles" not in users["ingestion-worker"]
    provisioner = users["rag-provisioner"]
    assert "realmRoles" not in provisioner
    # users only: not clients, not realm settings
    assert provisioner["clientRoles"] == {
        "realm-management": ["manage-users", "view-users", "query-users", "query-groups"]
    }


# --- secrets, recipes, scripts, docs --------------------------------------------------------


def test_new_secrets_are_generated_and_documented() -> None:
    generator = (REPO / "scripts" / "new-dev-secrets.sh").read_text()
    example = (REPO / ".env.example").read_text()
    for name in ("KEYCLOAK_ADMIN_PASSWORD", *NEW_SECRETS):
        assert f"{name}=$(rand)" in generator
        assert re.search(rf"^{name}=<generated", example, re.MULTILINE), name


def test_just_recipes_run_the_scripts_with_secrets() -> None:
    text = JUSTFILE.read_text()
    for recipe, script in (("kc-users", "kc_users.py"), ("kc-whoami", "kc_whoami.py")):
        body = text.split(f"\n{recipe}:\n", 1)[1].splitlines()[0]
        assert body.strip() == f"just with-secrets uv run --with httpx scripts/{script}"


def test_provisioning_script_creates_users_in_real_groups_with_safe_defaults() -> None:
    module = _load(USERS_SCRIPT)
    groups = {g["name"] for g in _realm()["groups"]}
    assert [u[0] for u in module.USERS] == ["alice", "bob", "carol", "dave", "erin"]
    for _username, _first, user_groups, _mfa in module.USERS:
        assert set(user_groups) <= groups
    mfa = {u[0] for u in module.USERS if u[3]}
    assert mfa == {"dave", "erin"}  # admins and auditors must set up MFA
    source = USERS_SCRIPT.read_text()
    assert '"grant_type": "client_credentials"' in source
    assert '"client_id": "rag-provisioner"' in source
    assert '"temporary": True' in source  # one-time password, changed at first sign-in
    assert "secrets.token_urlsafe(12)" in source
    assert 'api.get("/clients")' in source  # the least-privilege proof


def test_whoami_decodes_claims_without_trusting_them() -> None:
    module = _load(WHOAMI_SCRIPT)

    def b64(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    payload = {"iss": ISSUER, "groups": ["all-staff", "hr"], "exp": int(time.time()) + 300}
    token = f"{b64({'alg': 'RS256'})}.{b64(payload)}.c2ln"
    assert module.claims(token) == payload
    source = WHOAMI_SCRIPT.read_text()
    assert "urn:ietf:params:oauth:grant-type:device_code" in source
    assert '"client_id": "rag-cli"' in source
    assert '"client_id": "ingestion-worker"' in source
    assert "/logout" in source
    assert '"grant_type": "password"' not in source  # never the password grant


def test_adr() -> None:
    adr = ADR.read_text()
    assert adr.startswith("# ADR-0016: Use Keycloak for identity")
    assert "- **Status:** Accepted" in adr
    assert "0016-use-keycloak-for-identity.md" in (ADR.parent / "README.md").read_text()


# --- live Keycloak (opt-in) -----------------------------------------------------------------


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(not _port_open(8180), reason="needs Keycloak on 127.0.0.1:8180")


def _secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"needs {name} (run through `just with-secrets`)")
    return value


def _claims(jwt: str) -> dict[str, Any]:
    part = jwt.split(".")[1]
    data: dict[str, Any] = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return data


def _token(data: dict[str, str]) -> httpx.Response:
    return httpx.post(f"{KC}/realms/rag/protocol/openid-connect/token", data=data, timeout=10)


@live
def test_live_discovery_document_has_the_fixed_issuer() -> None:
    doc = httpx.get(f"{KC}/realms/rag/.well-known/openid-configuration", timeout=10).json()
    assert doc["issuer"] == ISSUER  # same whichever address we used to reach Keycloak
    # back-channel addresses follow the caller (KC_HOSTNAME_BACKCHANNEL_DYNAMIC): containers get
    # http://keycloak:8080/..., we (via 127.0.0.1) get http://127.0.0.1:8180/...; the issuer never moves
    assert doc["jwks_uri"] == f"{KC}/realms/rag/protocol/openid-connect/certs"
    assert "urn:ietf:params:oauth:grant-type:device_code" in doc["grant_types_supported"]


@live
def test_live_management_port_is_not_published() -> None:
    assert not _port_open(9000)


@live
@pytest.mark.parametrize("client", ["rag-cli", "rag-web"])
def test_live_password_grant_is_refused(client: str) -> None:
    r = _token(
        {"grant_type": "password", "client_id": client, "username": "alice", "password": "x"}
    )
    assert r.status_code in (400, 401)
    assert r.json()["error"] == "unauthorized_client"


@live
def test_live_machine_sign_in_gets_rag_ingest_and_no_refresh_token() -> None:
    r = _token(
        {
            "grant_type": "client_credentials",
            "client_id": "ingestion-worker",
            "client_secret": _secret("KEYCLOAK_INGESTION_SECRET"),
        }
    )
    r.raise_for_status()
    body = r.json()
    assert "refresh_token" not in body  # a machine simply asks again with its secret
    c = _claims(body["access_token"])
    assert c["iss"] == ISSUER
    assert c["azp"] == "ingestion-worker"
    assert c["preferred_username"] == "service-account-ingestion-worker"
    assert "rag-api" in ([c["aud"]] if isinstance(c["aud"], str) else c["aud"])
    assert "rag-ingest" in c["realm_access"]["roles"]
    assert "groups" not in c
    assert 290 <= c["exp"] - c["iat"] <= 300


@live
def test_live_wrong_client_secret_is_refused() -> None:
    r = _token(
        {"grant_type": "client_credentials", "client_id": "ingestion-worker", "client_secret": "x"}
    )
    assert r.status_code == 401


@live
def test_live_provisioner_may_read_users_but_not_clients() -> None:
    token = (
        _token(
            {
                "grant_type": "client_credentials",
                "client_id": "rag-provisioner",
                "client_secret": _secret("KEYCLOAK_PROVISIONER_SECRET"),
            }
        )
        .raise_for_status()
        .json()["access_token"]
    )
    headers = {"Authorization": f"Bearer {token}"}
    admin = f"{KC}/admin/realms/rag"
    assert httpx.get(f"{admin}/groups", headers=headers, timeout=10).status_code == 200
    assert httpx.get(f"{admin}/users", headers=headers, timeout=10).status_code == 200
    # not the realm's apps (and their secrets), not identity providers, not roles' setup
    assert httpx.get(f"{admin}/clients", headers=headers, timeout=10).status_code == 403
    assert (
        httpx.get(f"{admin}/identity-provider/instances", headers=headers, timeout=10).status_code
        == 403
    )
