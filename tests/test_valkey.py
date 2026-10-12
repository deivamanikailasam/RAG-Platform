"""Step 15: Valkey (Redis-compatible) for the LLM response cache, job queues and locks.

The static tests read the committed files and check the rules the guide sets (Valkey 9.1.x pinned by
tag + digest, an ACL file built from secret FILES into a RAM-only tmpfs, the default user off, the
litellm and rag_app users boxed in by command categories and key patterns, only 127.0.0.1:6379
published, a password-free healthcheck, memory cap + volatile-lru + AOF/RDB in valkey.conf, the
gateway's REDIS_URL and response cache, REDIS_PASSWORD replaced by three VALKEY_* passwords, the
`just kv-cli` recipe, the queue demo script and ADR-0015).

The live tests run only when Valkey answers on 127.0.0.1:6379 AND the three `VALKEY_*` passwords
are set (e.g. `just up`, then `just with-secrets uv run pytest tests/test_valkey.py`). They prove
anonymous access is refused, the server settings are live, each user's limits hold, and the queue
(crash recovery, dead-letter) and lock behave as the chapter describes. They only write keys under
`rag:test:*` / `test:*` with short TTLs, or delete what they create.
"""

import os
import re
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import redis
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "compose" / "compose.yaml"
CONF = REPO / "infra" / "config" / "valkey" / "valkey.conf"
LITELLM_CONFIG = REPO / "infra" / "config" / "litellm" / "config.yaml"
JUSTFILE = REPO / "justfile"
DEMO = REPO / "scripts" / "kv_queue_demo.py"
ADR = REPO / "docs" / "adr" / "0015-use-valkey-for-cache-queues-and-locks.md"
PASSWORDS = ("VALKEY_ADMIN_PASSWORD", "VALKEY_LITELLM_PASSWORD", "VALKEY_APP_PASSWORD")
SECRETS = ["valkey_admin_password", "valkey_litellm_password", "valkey_app_password"]


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    return data


def _service() -> dict[str, Any]:
    service = _compose()["services"]["valkey"]
    assert isinstance(service, dict)
    return service


def _acl_lines() -> dict[str, str]:
    """The ACL file the start-up script writes, one line per user, with secret reads stubbed out."""
    (command,) = _service()["command"]
    body = command.split("<<EOF\n", 1)[1].split("\nEOF\n", 1)[0]
    body = re.sub(r"\$\$\(cat /run/secrets/(\w+)\)", r"<\1>", body)
    return {line.split()[1]: line for line in body.splitlines()}


def _conf() -> dict[str, str]:
    """valkey.conf as {directive: arguments}, ignoring comments and blank lines."""
    out: dict[str, str] = {}
    for raw in CONF.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition(" ")
            out[key] = value.strip()
    return out


# --- Compose service ------------------------------------------------------------------------


def test_image_is_valkey_9_1_pinned_by_tag_and_digest() -> None:
    assert re.fullmatch(r"valkey/valkey:9\.1\.\d+-alpine@sha256:[0-9a-f]{64}", _service()["image"])


def test_acl_file_is_built_in_ram_from_secret_files() -> None:
    service = _service()
    assert service["entrypoint"] == ["/bin/sh", "-c"]
    (command,) = service["command"]
    lines = command.strip().splitlines()
    assert lines[0] == "umask 077"  # the ACL file is readable by its owner only
    assert lines[1] == "cat > /run/valkey/users.acl <<EOF"
    # Valkey runs from the image's entrypoint, which drops root for the "valkey" user.
    assert lines[-2] == "chown -R valkey:valkey /run/valkey"
    assert lines[-1] == (
        "exec docker-entrypoint.sh valkey-server /etc/valkey/valkey.conf"
        " --aclfile /run/valkey/users.acl"
    )
    assert service["tmpfs"] == ["/run/valkey:size=1m,mode=0700"]
    assert service["secrets"] == SECRETS
    assert "environment" not in service  # passwords arrive only as secret FILES
    top = _compose()["secrets"]
    for name, env in zip(SECRETS, PASSWORDS, strict=True):
        assert f"$$(cat /run/secrets/{name})" in command
        assert top[name] == {"environment": env}


def test_acl_users_are_least_privilege() -> None:
    acl = _acl_lines()
    assert list(acl) == ["default", "admin", "litellm", "rag_app"]
    assert acl["default"] == "user default off"  # no anonymous access at all
    assert acl["admin"] == "user admin on ><valkey_admin_password> ~* &* +@all"
    assert acl["litellm"] == ("user litellm on ><valkey_litellm_password> ~* &* +@all -@dangerous")
    assert acl["rag_app"] == (
        "user rag_app on ><valkey_app_password> ~rag:* &rag:* +@all -@dangerous -@admin"
    )


def test_only_localhost_port_and_password_free_healthcheck() -> None:
    service = _service()
    assert service["ports"] == ["127.0.0.1:6379:6379"]
    assert service["healthcheck"]["test"] == [
        "CMD-SHELL",
        "valkey-cli ping 2>&1 | grep -qE 'PONG|NOAUTH'",
    ]
    assert service["volumes"] == [
        "../config/valkey/valkey.conf:/etc/valkey/valkey.conf:ro",
        "valkey-data:/data",
    ]
    assert "valkey-data" in _compose()["volumes"]
    assert service["restart"] == "unless-stopped"
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["deploy"]["resources"]["limits"] == {"memory": "768m", "cpus": "1"}


def test_config_caps_memory_evicts_only_ttl_keys_and_persists() -> None:
    conf = _conf()
    assert conf["bind"] == "0.0.0.0"  # noqa: S104 - inside the Compose network; host port is 127.0.0.1 only
    assert conf["port"] == "6379"
    assert conf["protected-mode"] == "yes"
    assert conf["maxmemory"] == "512mb"
    assert conf["maxmemory-policy"] == "volatile-lru"  # never allkeys-lru: queues and locks survive
    assert conf["dir"] == "/data"
    assert conf["save"] == "900 1 300 10 60 10000"
    assert conf["appendonly"] == "yes"
    assert conf["appendfsync"] == "everysec"
    assert conf["slowlog-log-slower-than"] == "10000"
    assert conf["latency-monitor-threshold"] == "100"
    # Valkey rejects comments after a value, so every comment must be on a line of its own.
    for line in CONF.read_text().splitlines():
        assert "#" not in line or line.lstrip().startswith("#"), line
    # No password or user in the config file: those live only in the in-memory ACL file.
    assert not {"requirepass", "user", "aclfile", "masterauth"} & set(conf)


# --- gateway cache --------------------------------------------------------------------------


def test_gateway_connects_with_its_own_user_from_a_secret_file() -> None:
    litellm = _compose()["services"]["litellm"]
    (command,) = litellm["command"]
    assert (
        'REDIS_URL="redis://litellm:$$(cat /run/secrets/valkey_litellm_password)@valkey:6379/0" &&'
        in command
    )
    assert "valkey_litellm_password" in litellm["secrets"]
    assert litellm["depends_on"]["valkey"] == {"condition": "service_healthy"}


def test_gateway_response_cache_settings() -> None:
    config = yaml.safe_load(LITELLM_CONFIG.read_text())
    settings = config["litellm_settings"]
    assert settings["cache"] is True
    assert settings["cache_params"] == {"type": "redis", "ttl": 600, "namespace": "litellm.cache"}
    # The connection (with its password) comes only from REDIS_URL, never from this file.
    assert not {"host", "password", "url", "username"} & set(settings["cache_params"])


# --- secrets, recipes, scripts, docs --------------------------------------------------------


def test_redis_password_is_replaced_by_three_valkey_passwords() -> None:
    generator = (REPO / "scripts" / "new-dev-secrets.sh").read_text()
    example = (REPO / ".env.example").read_text()
    for text in (generator, example):
        assert "REDIS_PASSWORD" not in text
        for name in PASSWORDS:
            assert re.search(rf"^{name}=", text, re.MULTILINE), name
    for name in PASSWORDS:
        assert f"{name}=$(rand)" in generator  # letters/digits only: safe inside a redis:// URL


def test_kv_cli_recipe_passes_the_password_by_environment() -> None:
    text = JUSTFILE.read_text()
    recipe = text.split("\nkv-cli *args:\n", 1)[1].splitlines()[0]
    assert recipe.strip() == (
        "sops exec-env secrets/dev.enc.env 'docker compose -f infra/compose/compose.yaml exec"
        ' -e REDISCLI_AUTH="$VALKEY_ADMIN_PASSWORD" valkey valkey-cli --user admin {{args}}\''
    )
    assert " -a " not in recipe  # never a password on the command line


def test_demo_script_uses_the_app_user_and_safe_patterns() -> None:
    source = DEMO.read_text()
    compile(source, str(DEMO), "exec")
    assert 'username="rag_app"' in source
    assert 'password=os.environ["VALKEY_APP_PASSWORD"]' in source
    assert '"rag:ingest:jobs", "rag:ingest:workers", "rag:ingest:dead", 3' in source
    assert "xautoclaim(" in source
    assert "nx=True, px=30_000" in source  # lock: only if free, auto-expires
    assert "redis.call('get', KEYS[1]) == ARGV[1]" in source  # release only with the owner's token
    assert ".keys(" not in source  # KEYS blocks the server: never in application code


def test_adr() -> None:
    adr = ADR.read_text()
    assert adr.startswith("# ADR-0015: Use Valkey for cache, queues and locks")
    assert "- **Status:** Accepted" in adr
    assert "0015-use-valkey-for-cache-queues-and-locks.md" in (ADR.parent / "README.md").read_text()


# --- live Valkey (opt-in) -------------------------------------------------------------------


def _port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return False
    return True


live = pytest.mark.skipif(
    not (all(os.environ.get(k) for k in PASSWORDS) and _port_open(6379)),
    reason="needs Valkey on 127.0.0.1:6379 and the three VALKEY_* passwords",
)


def _client(user: str, env: str) -> "redis.Redis":
    return redis.Redis(
        host="127.0.0.1",
        port=6379,
        username=user,
        password=os.environ[env],
        decode_responses=True,
    )


@pytest.fixture
def admin() -> Iterator["redis.Redis"]:
    client = _client("admin", "VALKEY_ADMIN_PASSWORD")
    yield client
    client.close()


@pytest.fixture
def app() -> Iterator["redis.Redis"]:
    client = _client("rag_app", "VALKEY_APP_PASSWORD")
    yield client
    client.close()


@pytest.fixture
def gateway() -> Iterator["redis.Redis"]:
    client = _client("litellm", "VALKEY_LITELLM_PASSWORD")
    yield client
    client.close()


def _denied(call: Any) -> None:
    with pytest.raises(redis.exceptions.NoPermissionError):
        call()


@live
def test_anonymous_access_is_refused() -> None:
    with socket.create_connection(("127.0.0.1", 6379), timeout=3) as sock:
        sock.sendall(b"PING\r\n")
        assert sock.recv(256).startswith(b"-NOAUTH")
    with pytest.raises(redis.exceptions.AuthenticationError):
        redis.Redis(host="127.0.0.1", port=6379, username="rag_app", password="wrong").ping()  # noqa: S106 - deliberately wrong


@live
def test_server_runs_the_committed_settings(admin: "redis.Redis") -> None:
    assert admin.ping() is True
    info: Any = admin.info()
    assert str(info.get("valkey_version", "")).startswith("9.1.")
    config: Any = admin.config_get("*")
    assert config["maxmemory"] == str(512 * 1024 * 1024)
    assert config["maxmemory-policy"] == "volatile-lru"
    assert config["appendonly"] == "yes"
    assert config["appendfsync"] == "everysec"
    assert config["save"] == "900 1 300 10 60 10000"
    assert admin.info("persistence")["aof_enabled"] == 1
    users: Any = admin.acl_users()
    assert sorted(users) == ["admin", "default", "litellm", "rag_app"]
    default: Any = admin.acl_getuser("default")
    assert default["enabled"] is False


@live
def test_app_user_is_boxed_in(app: "redis.Redis", admin: "redis.Redis") -> None:
    other = f"test:{uuid.uuid4().hex}"
    admin.set(other, "gateway-owned", ex=60)
    mine = f"rag:test:{uuid.uuid4().hex}"
    try:
        assert app.set(mine, "ok", ex=60) is True
        assert app.get(mine) == "ok"
        _denied(lambda: app.get(other))  # can't read keys outside rag:*
        _denied(lambda: app.get("litellm.cache:anything"))
        _denied(app.flushall)  # @dangerous
        _denied(lambda: app.keys("rag:*"))  # @dangerous: blocks the server
        _denied(lambda: app.config_get("maxmemory"))  # @admin / @dangerous
        _denied(lambda: app.publish("litellm-events", "x"))  # channels outside rag:*
        assert app.publish("rag:events", "x") == 0  # own channels are fine
        found = list(app.scan_iter(match="rag:test:*", count=1000))  # SCAN, not KEYS
        assert mine in found
    finally:
        admin.delete(other, mine)


@live
def test_gateway_user_reads_any_key_but_nothing_dangerous(
    gateway: "redis.Redis", admin: "redis.Redis"
) -> None:
    key = f"litellm.cache:test-{uuid.uuid4().hex}"
    try:
        assert gateway.set(key, "cached answer", ex=60) is True
        assert gateway.get(key) == "cached answer"
        assert 0 < gateway.ttl(key) <= 60  # cache entries always carry a TTL
        _denied(gateway.flushall)
        _denied(lambda: gateway.keys("*"))
        _denied(lambda: gateway.config_set("maxmemory-policy", "allkeys-lru"))
    finally:
        admin.delete(key)


@live
def test_crashed_job_is_reclaimed_and_poison_job_dead_lettered(app: "redis.Redis") -> None:
    run = uuid.uuid4().hex
    stream, group, dlq = f"rag:test:{run}:jobs", f"rag:test:{run}:workers", f"rag:test:{run}:dead"
    try:
        app.xgroup_create(stream, group, id="0", mkstream=True)
        app.xadd(stream, {"document_id": "doc-poison", "action": "ingest"})
        reply: Any = app.xreadgroup(group, "worker-b", {stream: ">"}, count=1)
        ((_, [(mid, _job)]),) = reply  # taken, never acknowledged: worker-b "crashed"
        assert app.xpending(stream, group)["pending"] == 1
        # Each reclaim is another delivery. After MAX_TRIES (3) the job goes to the dead-letter stream.
        for _ in range(2):
            time.sleep(0.15)
            claimed: Any = app.xautoclaim(stream, group, "worker-a", min_idle_time=100)
            assert [m for m, _ in claimed[1]] == [mid]
        entry: Any = app.xpending_range(stream, group, min=mid, max=mid, count=1)
        assert entry[0]["times_delivered"] == 3
        app.xadd(dlq, {"document_id": "doc-poison", "action": "ingest"})
        app.xack(stream, group, mid)
        assert app.xpending(stream, group)["pending"] == 0
        assert app.xlen(dlq) == 1
    finally:
        app.delete(stream, dlq)


@live
def test_lock_is_exclusive_expiring_and_released_only_by_its_owner(app: "redis.Redis") -> None:
    key, token = f"rag:test:lock:{uuid.uuid4().hex}", uuid.uuid4().hex
    release = app.register_script(
        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1])"
        " else return 0 end"
    )
    try:
        assert app.set(key, token, nx=True, px=30_000) is True
        assert app.set(key, "other", nx=True, px=30_000) is None  # second worker is refused
        assert 0 < app.pttl(key) <= 30_000  # a crashed holder can't block the document forever
        assert release(keys=[key], args=["not-the-owner"]) == 0
        assert app.get(key) == token
        assert release(keys=[key], args=[token]) == 1
        assert app.exists(key) == 0
    finally:
        app.delete(key)


@live
def test_queue_demo_runs() -> None:
    out = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, str(DEMO)], capture_output=True, text=True, check=True
    ).stdout
    assert "ACL   : read gateway cache key rejected -> NoPermissionError" in out
    assert "ACL   : FLUSHALL rejected -> NoPermissionError" in out
    assert re.search(r"worker-b took doc-\d and crashed; pending = [1-9]", out)
    assert re.search(r"worker-a reclaimed doc-\d \(delivery [2-9]\)", out)
    assert "| second attempt: None" in out
    assert "lock  : released safely" in out
