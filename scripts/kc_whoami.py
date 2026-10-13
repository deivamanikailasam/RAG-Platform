#!/usr/bin/env python3
"""Sign in from the terminal (device flow), sign in as a machine (client credentials),
look inside both tokens, then sign out.

Run: just kc-whoami
"""

import base64
import json
import os
import time
from typing import Any

import httpx

OIDC = "http://127.0.0.1:8180/realms/rag/protocol/openid-connect"


def claims(jwt: str) -> dict[str, Any]:
    """Decode the payload WITHOUT checking the signature. Fine for looking; never for trusting (Step 17)."""
    part = jwt.split(".")[1]
    payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return payload


def show(title: str, c: dict[str, Any]) -> None:
    print(f"\n{title}")
    for k in ("iss", "aud", "azp", "sub", "preferred_username", "groups", "realm_access", "scope"):
        if k in c:
            print(f"  {k:19} {c[k]}")
    print(f"  {'expires in':19} {c['exp'] - int(time.time())} s")


def main() -> None:
    # --- 1. a PERSON, via the device flow ---
    d = (
        httpx.post(f"{OIDC}/auth/device", data={"client_id": "rag-cli", "scope": "openid"})
        .raise_for_status()
        .json()
    )
    print(
        f"Open {d['verification_uri_complete']}\n  (or {d['verification_uri']} and enter {d['user_code']})"
    )
    while True:
        time.sleep(d.get("interval", 5))
        r = httpx.post(
            f"{OIDC}/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": "rag-cli",
                "device_code": d["device_code"],
            },
        )
        if r.status_code == 200:
            break
        if r.json().get("error") not in ("authorization_pending", "slow_down"):
            r.raise_for_status()
    person = r.json()
    show("PERSON · access token", claims(person["access_token"]))

    # --- 2. a MACHINE, via client credentials ---
    m = (
        httpx.post(
            f"{OIDC}/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "ingestion-worker",
                "client_secret": os.environ["KEYCLOAK_INGESTION_SECRET"],
            },
        )
        .raise_for_status()
        .json()
    )
    show("MACHINE · access token", claims(m["access_token"]))
    print("  machine got a refresh token?", "refresh_token" in m)

    # --- 3. sign the person out: ends the Keycloak session and kills the refresh token ---
    httpx.post(
        f"{OIDC}/logout", data={"client_id": "rag-cli", "refresh_token": person["refresh_token"]}
    ).raise_for_status()
    r = httpx.post(
        f"{OIDC}/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "rag-cli",
            "refresh_token": person["refresh_token"],
        },
    )
    print("\nrefresh after logout ->", r.status_code, r.json().get("error"))


if __name__ == "__main__":
    main()
