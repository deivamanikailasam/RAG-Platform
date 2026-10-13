"""OpenBao, for real (Step 28): a throwaway server from the REAL server.hcl, configured by the REAL
setup script against the throwaway Postgres, with the REAL agent configuration.

Needs `bao` on PATH (just tools) and AUDIT_TEST_ADMIN_DSN (just audit-test). Skips otherwise.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from rag_api.audit import AuditEvent, PgAuditLog
from rag_common.secrets import CredentialsFile

from .conftest import AuditDb

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "infra/config/openbao"
BOOTSTRAP_PW = "bootstrap-only"
ADMIN_LOGIN_PW = "admin-login-test"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vault_setup", ROOT / "scripts/vault_setup.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["vault_setup"] = module
    spec.loader.exec_module(module)
    return module


vs = _load()
NO_PROXY_ENV = {
    k: v
    for k, v in os.environ.items()
    if "proxy" not in k.lower() and not k.startswith(("BAO_", "VAULT_"))
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for(check: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    pytest.fail(f"timed out waiting for {what}")


def real_config(src: Path, replacements: dict[str, str]) -> str:
    text = src.read_text()
    for old, new in replacements.items():
        assert old in text, f"{src.name} no longer contains {old!r}"
        text = text.replace(old, new)
    return text


@dataclass
class Env:
    addr: str
    root_token: str
    pg_host: str
    pg_port: int
    admin_dsn: str
    tmp: Path
    unseal_keys: list[str]

    def bao(self, token: str | None = None) -> Any:
        return vs.Bao(self.addr, token or self.root_token)

    def http(self) -> httpx.Client:
        return httpx.Client(base_url=self.addr + "/v1/", trust_env=False, timeout=10)

    def pg(self, user: str, password: str, dbname: str) -> psycopg.Connection[Any]:
        return psycopg.connect(make_conninfo(host=self.pg_host, port=self.pg_port, dbname=dbname,
                                             user=user, password=password), autocommit=True)  # fmt: skip

    def admin(self, dbname: str = "postgres") -> psycopg.Connection[Any]:
        return psycopg.connect(make_conninfo(self.admin_dsn, dbname=dbname), autocommit=True)

    def setup(self, token: str | None = None, admin_password: str | None = None) -> list[str]:
        return list(vs.setup(self.bao(token), pg_host=self.pg_host, pg_port=self.pg_port,
                             admin_password=admin_password, admin_login_password=ADMIN_LOGIN_PW,
                             cidrs=("127.0.0.1/32",)))  # fmt: skip

    def approle_login(self, name: str = "rag-api") -> str:
        bao = self.bao()
        wrapped = vs.wrapped_secret_id(bao, name)
        with self.http() as c:
            c.headers["X-Vault-Token"] = wrapped
            secret_id = c.post("sys/wrapping/unwrap").json()["data"]["secret_id"]
            r = c.post("auth/approle/login", json={"role_id": vs.role_id(bao, name), "secret_id": secret_id},
                       headers={"X-Vault-Token": ""})  # fmt: skip
        return str(r.json()["auth"]["client_token"])


def _prepare_postgres(admin_dsn: str, tmp: Path) -> None:
    """The rag database as Step 11 makes it (cut down to one table), then the REAL 03-openbao.sh."""
    with psycopg.connect(make_conninfo(admin_dsn, dbname="postgres"), autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS rag WITH (FORCE)")
        for r in conn.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'v-%' OR "
                              "rolname IN ('vault_admin_rag', 'vault_admin_audit', 'rag_migrator',"
                              " 'rag_app', 'rag_readonly')").fetchall():  # fmt: skip
            conn.execute(f'DROP OWNED BY "{r[0]}"')
            conn.execute(f'DROP ROLE "{r[0]}"')
        conn.execute("CREATE DATABASE rag")
        for role in ("rag_migrator", "rag_app", "rag_readonly"):
            conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'static-{role}'")
        conn.execute("REVOKE ALL ON DATABASE rag FROM PUBLIC")
        conn.execute("GRANT CONNECT ON DATABASE rag TO rag_migrator, rag_app, rag_readonly")
    with psycopg.connect(make_conninfo(admin_dsn, dbname="rag"), autocommit=True) as conn:
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute("CREATE SCHEMA rag AUTHORIZATION rag_migrator")
        conn.execute("GRANT USAGE ON SCHEMA rag TO rag_app, rag_readonly")
        conn.execute("ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrator IN SCHEMA rag "
                     "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_app")  # fmt: skip
        conn.execute("ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrator IN SCHEMA rag "
                     "GRANT SELECT ON TABLES TO rag_readonly")  # fmt: skip
        conn.execute("SET ROLE rag_migrator")
        conn.execute("CREATE TABLE rag.documents (id int PRIMARY KEY, title text)")
        conn.execute("INSERT INTO rag.documents VALUES (1, 'Leave policy')")
    secrets = tmp / "pg-secrets"
    secrets.mkdir()
    (secrets / "vault_admin_pg_password").write_text(BOOTSTRAP_PW)
    p = conninfo_to_dict(admin_dsn)
    subprocess.run(  # noqa: S603 - the real bootstrap script, test-only
        [str(ROOT / "infra/config/rag-db/init/03-openbao.sh")], check=True, capture_output=True,
        env={**os.environ, "SECRETS_DIR": str(secrets), "POSTGRES_USER": str(p.get("user", "postgres")),
             "PGHOST": str(p.get("host", "127.0.0.1")), "PGPORT": str(p.get("port", 5432)),
             "PGPASSWORD": str(p.get("password", ""))},
    )  # fmt: skip


@pytest.fixture(scope="module")
def env(audit_db: AuditDb, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    if shutil.which("bao") is None:
        pytest.skip("bao not installed (just tools bao)")
    tmp = tmp_path_factory.mktemp("openbao")
    _prepare_postgres(audit_db.admin_dsn, tmp)
    port = free_port()
    (tmp / "data").mkdir()
    (tmp / "logs").mkdir()
    cfg = tmp / "server.hcl"
    cfg.write_text(real_config(CONFIG / "server.hcl", {
        '"/openbao/file"': f'"{tmp / "data"}"', '"0.0.0.0:8200"': f'"127.0.0.1:{port}"',
        '"http://openbao:8200"': f'"http://127.0.0.1:{port}"',
        '"http://openbao:8201"': f'"http://127.0.0.1:{free_port()}"',
        '"/openbao/logs/audit.log"': f'"{tmp / "logs/audit.log"}"',
    }))  # fmt: skip
    server = subprocess.Popen(  # noqa: S603
        ["bao", "server", f"-config={cfg}"], env=NO_PROXY_ENV,  # noqa: S607
        stdout=(tmp / "server.log").open("w"), stderr=subprocess.STDOUT,
    )  # fmt: skip
    addr = f"http://127.0.0.1:{port}"
    init: dict[str, Any] = {}
    try:
        http = httpx.Client(base_url=addr + "/v1/", trust_env=False, timeout=10)

        def up() -> bool:
            try:
                return http.get("sys/seal-status").status_code == 200
            except httpx.TransportError:
                return False

        wait_for(up, 20, "OpenBao to listen")
        init = http.put("sys/init", json={"secret_shares": 3, "secret_threshold": 2}).json()
        for key in init["keys_base64"][:2]:  # any 2 of the 3 shares
            http.put("sys/unseal", json={"key": key})
        wait_for(lambda: http.get("sys/health").status_code == 200, 30, "unsealed and active")
        p = conninfo_to_dict(audit_db.admin_dsn)
        yield Env(addr, init["root_token"], str(p.get("host", "127.0.0.1")), int(str(p.get("port", 5432))),
                  audit_db.admin_dsn, tmp, init["keys_base64"])  # fmt: skip
    finally:
        if init:  # revoke every lease, so no database user outlives the test server
            with contextlib.suppress(httpx.HTTPError):
                httpx.put(f"{addr}/v1/sys/leases/revoke-prefix/database", trust_env=False,
                          headers={"X-Vault-Token": init["root_token"]}, timeout=30)  # fmt: skip
        server.terminate()
        server.wait(10)


@pytest.fixture(scope="module")
def configured(env: Env) -> Env:
    done = env.setup(admin_password=BOOTSTRAP_PW)
    assert "connection rag-db (root password rotated)" in done
    assert "connection audit-db (root password rotated)" in done
    vs.put_secret(
        env.bao(), "rag-api", {"gateway_key": "gw-key-from-bao", "opa_token": "opa-token-from-bao"}
    )
    return env


def creds(env: Env, role: str, token: str | None = None) -> dict[str, Any]:
    data = env.bao(token).call("GET", f"database/creds/{role}")
    assert data is not None
    return dict(data)


# ---- the setup script ---------------------------------------------------------------------------


def test_setup_converges_and_never_needs_the_bootstrap_password_again(configured: Env) -> None:
    again = configured.setup()  # no admin_password: the connections exist, nothing is resent
    assert not any("connection" in item for item in again)
    for user in (
        "vault_admin_rag",
        "vault_admin_audit",
    ):  # rotate-root: the bootstrap value is dead
        with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
            configured.pg(user, BOOTSTRAP_PW, "postgres")


def test_setup_refuses_a_server_without_an_audit_device() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})  # GET sys/audit: no devices

    client = httpx.Client(base_url="http://bao/v1/", transport=httpx.MockTransport(handler))
    with pytest.raises(vs.BaoError, match="no 'file' audit device"):
        vs.setup(
            vs.Bao("http://bao", "t", client),
            pg_host="h",
            pg_port=1,
            cidrs=(),
            admin_password="x",  # noqa: S106 - never reaches a database
        )


def test_first_run_needs_the_bootstrap_password() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("sys/audit"):
            return httpx.Response(200, json={"data": {"file/": {}}})
        if request.url.path.endswith(("sys/mounts", "sys/auth")):
            return httpx.Response(
                200,
                json={"data": {"secret/": {}, "database/": {}, "approle/": {}, "userpass/": {}}},
            )
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(204)

    client = httpx.Client(base_url="http://bao/v1/", transport=httpx.MockTransport(handler))
    with pytest.raises(vs.BaoError, match="VAULT_ADMIN_PG_PASSWORD"):
        vs.setup(
            vs.Bao("http://bao", "t", client), pg_host="h", pg_port=1, admin_password=None, cidrs=()
        )
    assert "GET /v1/database/config/rag-db" in calls  # it looked first, and sent nothing without it


# ---- dynamic database credentials -----------------------------------------------------------------


def test_rag_api_credentials_work_with_the_right_settings(configured: Env) -> None:
    c = creds(configured, "rag-api")
    user, password = c["data"]["username"], c["data"]["password"]
    assert user.startswith("v-root-rag-api-")
    assert c["lease_duration"] == 3600
    with configured.pg(user, password, "rag") as conn:
        assert conn.execute("SELECT title FROM documents WHERE id = 1").fetchone() == (
            "Leave policy",
        )
        conn.execute("INSERT INTO documents VALUES (99, 'x')")
        conn.execute("DELETE FROM documents WHERE id = 99")
        assert conn.execute("SHOW statement_timeout").fetchone() == ("30s",)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE rag.mine (id int)")  # DML only, like rag_app
    with configured.admin() as conn:
        row = conn.execute("SELECT rolvaliduntil > now() + interval '50 minutes',"
                           " rolvaliduntil < now() + interval '70 minutes', rolsuper, rolcreaterole"
                           " FROM pg_roles WHERE rolname = %s", (user,)).fetchone()  # fmt: skip
    assert row == (True, True, False, False)  # Postgres itself refuses the login after ~1 hour


def test_renewing_a_lease_moves_valid_until(configured: Env) -> None:
    """Postgres' own expiry follows the lease: renewals push VALID UNTIL forward."""
    c = creds(configured, "rag-api")
    user = c["data"]["username"]

    def valid_until() -> Any:
        with configured.admin() as conn:
            row = conn.execute(
                "SELECT rolvaliduntil FROM pg_roles WHERE rolname = %s", (user,)
            ).fetchone()
        assert row is not None
        return row[0]

    before = valid_until()
    renewed = configured.bao().call(
        "PUT", "sys/leases/renew", {"lease_id": c["lease_id"], "increment": "2h"}
    )
    assert renewed is not None
    assert renewed["lease_duration"] == 7200
    assert (valid_until() - before).total_seconds() > 3000  # about one hour later than before


def test_readonly_credentials_cannot_write(configured: Env) -> None:
    c = creds(configured, "rag-readonly")["data"]
    with configured.pg(c["username"], c["password"], "rag") as conn:
        assert conn.execute("SELECT count(*) FROM documents").fetchone() == (1,)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("INSERT INTO documents VALUES (98, 'x')")


def test_audit_writer_credentials_can_append_but_not_read(configured: Env) -> None:
    c = creds(configured, "audit-writer")["data"]
    with configured.pg(c["username"], c["password"], "audit") as conn:
        seq = conn.execute(
            "SELECT audit.append('u', 'c', 'search', 'allowed', 'documents')"
        ).fetchone()
        assert seq is not None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM audit.events")
    with pytest.raises(psycopg.OperationalError):  # and only into the audit database
        configured.pg(c["username"], c["password"], "rag")


def test_revoking_a_lease_ends_sessions_and_drops_the_user(configured: Env) -> None:
    c = creds(configured, "rag-api")
    user, password = c["data"]["username"], c["data"]["password"]
    conn = configured.pg(user, password, "rag")
    configured.bao().call("PUT", "sys/leases/revoke", {"lease_id": c["lease_id"]})
    with pytest.raises(psycopg.OperationalError):
        conn.execute("SELECT 1")  # the open session was ended
    conn.close()
    with configured.admin() as admin:
        assert admin.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname = %s", (user,)
        ).fetchone() == (0,)


# ---- who may do what ----------------------------------------------------------------------------


def test_rag_api_token_gets_exactly_its_own_secrets(configured: Env) -> None:
    token = configured.approle_login("rag-api")
    bao = configured.bao(token)
    assert bao.call("GET", "database/creds/rag-api") is not None
    assert (
        bao.call("GET", "secret/data/rag-api")["data"]["data"]["gateway_key"] == "gw-key-from-bao"
    )
    for path in ("database/creds/rag-readonly", "secret/data/rag-evals", "sys/policies/acl/rag-api",
                 "database/config/rag-db"):  # fmt: skip
        with pytest.raises(vs.BaoError, match="403"):
            bao.call("GET", path)


def test_a_wrapped_secret_id_works_exactly_once(configured: Env) -> None:
    wrapped = vs.wrapped_secret_id(configured.bao(), "rag-api")
    with configured.http() as c:
        c.headers["X-Vault-Token"] = wrapped
        assert c.post("sys/wrapping/unwrap").status_code == 200
        second = c.post("sys/wrapping/unwrap")  # someone else got there first? You'd know.
    assert second.status_code in (400, 403)


def test_admin_login_writes_secrets_but_cannot_read_them(configured: Env) -> None:
    with configured.http() as c:
        r = c.post("auth/userpass/login/admin", json={"password": ADMIN_LOGIN_PW})
    token = r.json()["auth"]["client_token"]
    assert r.json()["auth"]["policies"] == ["default", "developer", "platform-admin"]
    bao = configured.bao(token)
    assert vs.put_secret(bao, "rag-evals", {"gateway_key": "k"}) >= 1
    with pytest.raises(vs.BaoError, match="403"):
        bao.call("GET", "secret/data/rag-api")
    with pytest.raises(vs.BaoError, match="403"):
        bao.call("GET", "database/creds/rag-api")
    assert bao.call("GET", "database/creds/rag-readonly") is not None  # the developer policy
    assert configured.setup(token)  # day-to-day re-runs need no root token


def test_audit_log_records_requests_without_secret_values(configured: Env) -> None:
    c = creds(configured, "rag-api")["data"]
    log = (configured.tmp / "logs/audit.log").read_text()
    assert c["password"] not in log
    assert "gw-key-from-bao" not in log
    last = [json.loads(line) for line in log.splitlines() if "database/creds/rag-api" in line][-1]
    assert last["type"] == "response"
    assert last["response"]["data"]["password"].startswith("hmac-sha256:")


def test_metrics_need_no_token_and_hold_no_secrets(configured: Env) -> None:
    secret = creds(configured, "rag-api")["data"]["password"]
    with configured.http() as c:  # no token at all, like Prometheus
        text = c.get("sys/metrics", params={"format": "prometheus"}).text
    assert 'vault_core_unsealed{cluster="vault-cluster-' in text
    assert secret not in text
    assert "gw-key-from-bao" not in text


def test_sealed_server_hands_out_nothing(configured: Env) -> None:
    with configured.http() as c:
        c.headers["X-Vault-Token"] = configured.root_token
        assert c.put("sys/seal").status_code == 204
        assert c.get("database/creds/rag-api").status_code == 503
        for key in configured.unseal_keys[:2]:
            c.put("sys/unseal", json={"key": key})
    wait_for(lambda: configured.http().get("sys/health").status_code == 200, 30, "unsealed again")


# ---- the agent, and rag-api picking up new credentials -------------------------------------------


def test_agent_renders_files_and_rotates_credentials(configured: Env) -> None:
    bao = configured.bao()
    # Short tokens so we see a full rotation in seconds (real life: 1 h, renewed up to 24 h)
    bao.call("POST", "auth/approle/role/rag-api", {"token_ttl": "6s", "token_max_ttl": "12s"})
    boot, out = configured.tmp / "bootstrap", configured.tmp / "out"
    boot.mkdir()
    out.mkdir()
    (boot / "role_id").write_text(vs.role_id(bao, "rag-api"))
    (boot / "secret_id").write_text(vs.wrapped_secret_id(bao, "rag-api"))
    cfg = configured.tmp / "agent.hcl"
    cfg.write_text(real_config(CONFIG / "agent-rag-api.hcl", {
        '"http://openbao:8200"': f'"{configured.addr}"', '"/openbao/bootstrap/': f'"{boot}/',
        '"/openbao/out/': f'"{out}/',
    }))  # fmt: skip
    agent = subprocess.Popen(  # noqa: S603
        ["bao", "agent", f"-config={cfg}"], env=NO_PROXY_ENV,  # noqa: S607
        stdout=(configured.tmp / "agent.log").open("w"), stderr=subprocess.STDOUT,
    )  # fmt: skip
    audit_file = out / "audit_db.json"
    try:
        wait_for(
            lambda: audit_file.exists() and (out / "rag_api_opa_token").exists(), 20, "agent files"
        )
        assert not (boot / "secret_id").exists()  # read once, then deleted
        assert stat.S_IMODE((out / "rag_db.json").stat().st_mode) == 0o400
        assert (out / "rag_api_gateway_key").read_text() == "gw-key-from-bao"

        audit_creds = CredentialsFile(audit_file)
        first_user = audit_creds()[0]
        assert first_user.startswith("v-approle-audit-wr")
        log = PgAuditLog(host=configured.pg_host, port=configured.pg_port, credentials=audit_creds)
        try:
            event = AuditEvent("u", "rag-cli", "search", "allowed", "documents")
            log.record(event)
            # the token expires -> the agent logs in again (secret ID kept in memory) -> new user
            wait_for(lambda: audit_creds()[0] != first_user, 40, "rotated credentials")
            wait_for(lambda: _role_gone(configured, first_user), 20, "old user dropped")
            log.record(event)  # the pool's old connection was ended; a new one uses the new user
            log.record(event)
        finally:
            log.close()
        assert audit_creds.changes >= 2
        assert agent.poll() is None  # still running
    finally:
        agent.terminate()
        agent.wait(10)
        bao.call("POST", "auth/approle/role/rag-api", {"token_ttl": "1h", "token_max_ttl": "24h"})


def _role_gone(env: Env, user: str) -> bool:
    with env.admin() as conn:
        return conn.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname = %s", (user,)
        ).fetchone() == (0,)


def test_agent_stops_when_its_secret_id_was_already_used(configured: Env) -> None:
    """A stolen-and-used wrapping token: the agent must fail loudly, not run without secrets."""
    bao = configured.bao()
    boot = configured.tmp / "bootstrap-used"
    out = configured.tmp / "out-used"
    boot.mkdir()
    out.mkdir()
    (boot / "role_id").write_text(vs.role_id(bao, "rag-api"))
    wrapped = vs.wrapped_secret_id(bao, "rag-api")
    with configured.http() as c:  # the "attacker" unwraps it first
        c.headers["X-Vault-Token"] = wrapped
        assert c.post("sys/wrapping/unwrap").status_code == 200
    (boot / "secret_id").write_text(wrapped)
    cfg = configured.tmp / "agent-used.hcl"
    cfg.write_text(real_config(CONFIG / "agent-rag-api.hcl", {
        '"http://openbao:8200"': f'"{configured.addr}"', '"/openbao/bootstrap/': f'"{boot}/',
        '"/openbao/out/': f'"{out}/',
    }))  # fmt: skip
    agent = subprocess.Popen(  # noqa: S603
        ["bao", "agent", f"-config={cfg}"], env=NO_PROXY_ENV,  # noqa: S607
        stdout=(configured.tmp / "agent-used.log").open("w"), stderr=subprocess.STDOUT,
    )  # fmt: skip
    try:
        time.sleep(5)
        assert not list(out.iterdir())  # nothing rendered: no secrets without a valid login
        assert (
            "wrapping token is not valid or does not exist"
            in (configured.tmp / "agent-used.log").read_text()
        )
    finally:
        agent.terminate()
        agent.wait(10)
