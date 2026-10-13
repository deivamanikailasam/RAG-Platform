#!/usr/bin/env python3
"""OpenBao configuration as code (Step 28). Safe to re-run: it converges to what's written here.

    just vault-setup                            audit device, engines, policies, DB connections, roles, AppRoles
    just vault-put rag-api gateway_key=… opa_token=…          write a secret (values from your SOPS env)
    just vault-secret-id rag-api                a single-use, wrapped secret ID for the agent
    just vault-creds rag-readonly               short-lived database login for a person or a job
    just vault-unseal                           after every OpenBao restart (keys from the SOPS file)
    just vault-k8s-trust                        let rag-api pods log in with their service account (Step 29)
                                                and the ingestion worker with its own (rag-ingest, Step 37)

Talks to the HTTP API directly (BAO_ADDR, BAO_TOKEN), so every call is visible and testable.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "infra/config/openbao/policies"


class BaoError(Exception):
    pass


class Bao:
    def __init__(self, addr: str, token: str, client: httpx.Client | None = None) -> None:
        self._http = client or httpx.Client(
            base_url=addr.rstrip("/") + "/v1/", timeout=15, trust_env=False
        )
        self._http.headers["X-Vault-Token"] = token

    def call(self, method: str, path: str, body: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> dict[str, Any] | None:  # fmt: skip
        r = self._http.request(method, path, json=body, headers=headers)
        if r.status_code == 404 and method == "GET":
            return None
        if r.status_code >= 400:
            errors = r.json().get("errors", []) if r.content else []
            raise BaoError(f"{method} {path}: {r.status_code} {'; '.join(errors)}")
        return r.json() if r.content else None


# ---------------------------------------------------------------------- the desired state


@dataclass(frozen=True)
class DbConnection:
    name: str
    database: str
    admin: str  # its own login: each connection's password is rotated on its own
    roles: tuple[str, ...]


@dataclass(frozen=True)
class DbRole:
    name: str
    connection: str
    member_of: str  # an existing NOLOGIN group role holding the actual privileges
    default_ttl: str
    max_ttl: str
    settings: tuple[
        str, ...
    ] = ()  # ALTER ROLE … SET lines: role settings are NOT inherited from groups


@dataclass(frozen=True)
class AppRole:
    name: str
    policies: tuple[str, ...]
    token_ttl: str = "1h"  # noqa: S105 - durations, not passwords
    token_max_ttl: str = "24h"  # noqa: S105
    secret_id_ttl: str = "720h"  # noqa: S105 - 30 days: issue a fresh one with every deployment
    cidrs: tuple[str, ...] = field(default_factory=tuple)


CONNECTIONS = (
    DbConnection("rag-db", "rag", "vault_admin_rag", ("rag-api", "rag-readonly", "rag-ingest")),
    DbConnection("audit-db", "audit", "vault_admin_audit", ("audit-writer", "audit-reader")),
)
ROLES = (
    DbRole("rag-api", "rag-db", "rag_app", "1h", "24h",
           ("SET search_path = rag, public", "SET statement_timeout = '30s'")),
    DbRole("rag-readonly", "rag-db", "rag_readonly", "1h", "8h",
           ("SET search_path = rag, public", "SET statement_timeout = '120s'",
            "SET default_transaction_read_only = on")),
    DbRole("audit-writer", "audit-db", "audit_writer", "1h", "24h",
           ("SET search_path = audit", "SET statement_timeout = '5s'")),
    # Step 37: the ingestion worker's own leases (same privileges as rag-api today; its own name in
    # pg_stat_activity and the audit trail, and revocable on its own), and read-only audit access
    # for online evaluation
    DbRole("rag-ingest", "rag-db", "rag_app", "1h", "24h",
           ("SET search_path = rag, public", "SET statement_timeout = '300s'")),
    DbRole("audit-reader", "audit-db", "audit_reader", "1h", "4h",
           ("SET search_path = audit", "SET statement_timeout = '60s'",
            "SET default_transaction_read_only = on")),
)  # fmt: skip
APPROLES = (
    AppRole("rag-api", ("rag-api",)),
    AppRole("rag-evals", ("rag-evals",), token_max_ttl="4h"),  # noqa: S106
)


@dataclass(frozen=True)
class K8sRole:
    name: str
    namespace: str
    service_account: str
    policies: tuple[str, ...]


# Step 29: pods in Kubernetes log in with their own service account token (no secret ID)
K8S_ROLES = (
    K8sRole("rag-api", "rag", "rag-api", ("rag-api",)),
    K8sRole("rag-ingest", "rag", "rag-ingest", ("rag-ingest",)),  # Step 37: its own identity
)
K8S_MOUNT = "kubernetes-jwt"
K8S_AUDIENCE = "openbao"


def creation_statements(role: DbRole) -> list[str]:
    stmts = [
        # {{name}}, {{password}} and {{expiration}} are filled in by OpenBao for each lease
        f"CREATE ROLE \"{{{{name}}}}\" WITH LOGIN PASSWORD '{{{{password}}}}' "
        f"VALID UNTIL '{{{{expiration}}}}' IN ROLE {role.member_of};"
    ]
    return stmts + [f'ALTER ROLE "{{{{name}}}}" {s};' for s in role.settings]


REVOCATION = [
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '{{name}}';",
    'DROP ROLE IF EXISTS "{{name}}";',
]


def setup(bao: Bao, *, pg_host: str, pg_port: int, admin_password: str | None,
          admin_login_password: str | None = None,
          cidrs: tuple[str, ...]) -> list[str]:  # fmt: skip
    done: list[str] = []
    # 1. Audit first. The device is declared in server.hcl (the API can't create one); refuse to
    #    configure a server that would hand out secrets without recording it.
    if "file/" not in (bao.call("GET", "sys/audit") or {}).get("data", {}):
        raise BaoError("no 'file' audit device: add the audit stanza to server.hcl and reload")
    done.append("audit device present")
    # 2. Engines and auth methods
    mounts = (bao.call("GET", "sys/mounts") or {}).get("data", {})
    if "secret/" not in mounts:
        bao.call("POST", "sys/mounts/secret", {"type": "kv", "options": {"version": "2"}})
        done.append("kv-v2 at secret/")
    if "database/" not in mounts:
        bao.call("POST", "sys/mounts/database", {"type": "database"})
        done.append("database engine")
    auths = (bao.call("GET", "sys/auth") or {}).get("data", {})
    if "approle/" not in auths:  # for machines
        bao.call("POST", "sys/auth/approle", {"type": "approle"})
        done.append("approle auth")
    if "userpass/" not in auths:  # for the person administering it (OIDC/Keycloak in a team)
        bao.call("POST", "sys/auth/userpass", {"type": "userpass"})
        done.append("userpass auth")
    # 3. Policies from files: the files in git are the truth
    for f in sorted(POLICIES.glob("*.hcl")):
        bao.call("PUT", f"sys/policies/acl/{f.stem}", {"policy": f.read_text()})
    done.append(f"{len(list(POLICIES.glob('*.hcl')))} policies")
    # 4. Database connections. Created once with the bootstrap password, which is then ROTATED:
    #    afterwards only OpenBao knows the admin passwords, and re-runs never resend it.
    for c in CONNECTIONS:
        body: dict[str, Any] = {
            "plugin_name": "postgresql-database-plugin",
            "connection_url": (
                f"postgresql://{{{{username}}}}:{{{{password}}}}@{pg_host}:{pg_port}/"
                f"{c.database}?sslmode=disable"
            ),
            "allowed_roles": list(c.roles),
            "password_authentication": "scram-sha-256",
            "verify_connection": True,
        }
        if bao.call("GET", f"database/config/{c.name}") is None:
            if not admin_password:
                raise BaoError("first run: set VAULT_ADMIN_PG_PASSWORD (the bootstrap password)")
            bao.call(
                "POST",
                f"database/config/{c.name}",
                body | {"username": c.admin, "password": admin_password},
            )
            bao.call("POST", f"database/rotate-root/{c.name}")
            done.append(f"connection {c.name} (root password rotated)")
        else:
            bao.call("POST", f"database/config/{c.name}", body)
    # 5. Roles: what a lease creates, how long it lives, how it's removed
    for r in ROLES:
        bao.call("POST", f"database/roles/{r.name}", {
            "db_name": r.connection, "creation_statements": creation_statements(r),
            "revocation_statements": REVOCATION, "default_ttl": r.default_ttl, "max_ttl": r.max_ttl,
        })  # fmt: skip
    done.append(f"{len(ROLES)} database roles")
    # 6. AppRoles for machines
    for a in APPROLES:
        bao.call("POST", f"auth/approle/role/{a.name}", {
            "token_policies": list(a.policies), "token_ttl": a.token_ttl,
            "token_max_ttl": a.token_max_ttl, "secret_id_ttl": a.secret_id_ttl,
            "secret_id_num_uses": 0, "secret_id_bound_cidrs": list(a.cidrs or cidrs),
            "token_bound_cidrs": list(a.cidrs or cidrs), "token_type": "service",
        })  # fmt: skip
    done.append(f"{len(APPROLES)} approles")
    # 7. The administrator's login: short sessions, admin + developer policies, never root
    if admin_login_password:
        bao.call("POST", "auth/userpass/users/admin", {
            "password": admin_login_password, "token_policies": ["platform-admin", "developer"],
            "token_ttl": "1h", "token_max_ttl": "8h",
        })  # fmt: skip
        done.append("admin login")
    return done


def jwks_to_pem(jwks: dict[str, Any]) -> list[str]:
    """The cluster's token-signing public keys (from /openid/v1/jwks) as PEM, for OpenBao."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
    from jwt.algorithms import RSAAlgorithm

    pems = []
    for key in jwks.get("keys", []):
        if key.get("kty") != "RSA":
            continue
        public = RSAAlgorithm.from_jwk(key)
        if isinstance(public, RSAPrivateKey):  # a JWKS should never hold one; take its public half
            public = public.public_key()
        pems.append(public.public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode())  # fmt: skip
    if not pems:
        raise BaoError("no RSA keys in the JWKS")
    return pems


def k8s_trust(bao: Bao, jwks: dict[str, Any], issuer: str) -> list[str]:
    """Let pods log in with their service account token. OpenBao checks the token's signature
    against the cluster's public keys OFFLINE: it never needs to reach the Kubernetes API."""
    done = []
    if f"{K8S_MOUNT}/" not in (bao.call("GET", "sys/auth") or {}).get("data", {}):
        bao.call("POST", f"sys/auth/{K8S_MOUNT}", {"type": "jwt"})
        done.append(f"jwt auth at {K8S_MOUNT}/")
    bao.call("POST", f"auth/{K8S_MOUNT}/config", {
        "jwt_validation_pubkeys": jwks_to_pem(jwks), "bound_issuer": issuer,
    })  # fmt: skip
    done.append(f"trusts {len(jwks['keys'])} cluster signing key(s), issuer {issuer}")
    for r in K8S_ROLES:
        bao.call("POST", f"auth/{K8S_MOUNT}/role/{r.name}", {
            "role_type": "jwt", "user_claim": "sub",
            # exactly this service account in exactly this namespace, and tokens made for us only
            "bound_subject": f"system:serviceaccount:{r.namespace}:{r.service_account}",
            "bound_audiences": [K8S_AUDIENCE],
            "token_policies": list(r.policies), "token_ttl": "1h", "token_max_ttl": "4h",
            "token_type": "service",
        })  # fmt: skip
    done.append(f"{len(K8S_ROLES)} kubernetes role(s)")
    return done


def role_id(bao: Bao, name: str) -> str:
    data = bao.call("GET", f"auth/approle/role/{name}/role-id")
    if data is None:
        raise BaoError(f"no approle {name}")
    return str(data["data"]["role_id"])


def wrapped_secret_id(bao: Bao, name: str, ttl: str = "10m") -> str:
    """A secret ID inside a single-use wrapping token: if anyone else unwraps it first, the agent
    fails loudly."""
    data = bao.call(
        "POST", f"auth/approle/role/{name}/secret-id", {}, headers={"X-Vault-Wrap-TTL": ttl}
    )
    if data is None or "wrap_info" not in data:
        raise BaoError("no wrap_info in response")
    return str(data["wrap_info"]["token"])


def issue_credentials(bao: Bao, role: str, out: Path) -> tuple[str, int]:
    """New database credentials for a person or a job, written to a 0600 file (never printed)."""
    data = bao.call("GET", f"database/creds/{role}")
    if data is None:
        raise BaoError(f"no database role {role}")
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({k: data["data"][k] for k in ("username", "password")}, f)
    return str(data["lease_id"]), int(data["lease_duration"])


def put_secret(bao: Bao, path: str, values: dict[str, str]) -> int:
    data = bao.call("POST", f"secret/data/{path}", {"data": values})
    return int((data or {}).get("data", {}).get("version", 0))


def unseal(addr: str, init: dict[str, Any]) -> bool:
    """Feed key shares until the threshold is reached. Keys arrive on stdin, never as arguments."""
    with httpx.Client(base_url=addr.rstrip("/") + "/v1/", timeout=15, trust_env=False) as http:
        status = http.get("sys/seal-status").json()
        for key in init["unseal_keys_b64"][: status["t"]]:
            if not status["sealed"]:
                break
            status = http.put("sys/unseal", json={"key": key}).json()
    return not status["sealed"]


def current_token() -> str:
    """BAO_TOKEN, or the token from your last `bao login` (the CLI's token helper)."""
    if token := os.environ.get("BAO_TOKEN"):
        return token
    r = subprocess.run(["bao", "print", "token"], capture_output=True, text=True, check=False)  # noqa: S607
    if r.returncode != 0 or not r.stdout.strip():
        raise BaoError("no token: run `just vault-login` first (or set BAO_TOKEN)")
    return r.stdout.strip()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="vault_setup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    p = sub.add_parser("put")
    p.add_argument("path")
    p.add_argument("pairs", nargs="+", metavar="KEY=ENV_VAR")
    p = sub.add_parser("role-id")
    p.add_argument("name")
    p = sub.add_parser("secret-id")
    p.add_argument("name")
    p = sub.add_parser("creds")
    p.add_argument("role")
    p.add_argument("--out", type=Path, required=True)
    sub.add_parser("unseal", help="reads the init JSON (from sops decrypt) on stdin")
    p = sub.add_parser("k8s-trust", help="trust a cluster's service account tokens (Step 29)")
    p.add_argument("--jwks", type=Path, required=True, help="the cluster's /openid/v1/jwks")
    p.add_argument("--issuer", required=True, help="the cluster's service account issuer")
    a = ap.parse_args(argv)
    addr = os.environ.get("BAO_ADDR", "http://127.0.0.1:8200")
    try:
        if a.cmd == "unseal":
            print("unsealed" if unseal(addr, json.load(sys.stdin)) else "STILL SEALED")
            return 0
        bao = Bao(addr, current_token())
        if a.cmd == "setup":
            cidrs = tuple(
                os.environ.get("BAO_APPROLE_CIDRS", "172.16.0.0/12,127.0.0.1/32").split(",")
            )
            for item in setup(bao, pg_host=os.environ.get("BAO_PG_HOST", "rag-db"),
                              pg_port=int(os.environ.get("BAO_PG_PORT", "5432")),
                              admin_password=os.environ.get("VAULT_ADMIN_PG_PASSWORD"),
                              admin_login_password=os.environ.get("BAO_ADMIN_PASSWORD"),
                              cidrs=cidrs):  # fmt: skip
                print("ok:", item)
        elif a.cmd == "put":
            # values come from environment variables (your SOPS env), never from the command line
            values = {k: os.environ[v] for k, v in (pair.split("=", 1) for pair in a.pairs)}
            print(
                f"secret/{a.path}: version {put_secret(bao, a.path, values)} "
                f"({', '.join(sorted(values))})"
            )
        elif a.cmd == "k8s-trust":
            for item in k8s_trust(bao, json.loads(a.jwks.read_text()), a.issuer):
                print("ok:", item)
        elif a.cmd == "role-id":
            print(role_id(bao, a.name))
        elif a.cmd == "creds":
            lease, ttl = issue_credentials(bao, a.role, a.out)
            print(f"{a.out}: valid for {ttl // 60} min (revoke early: bao lease revoke {lease})")
        else:
            print(wrapped_secret_id(bao, a.name))
    except (BaoError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
