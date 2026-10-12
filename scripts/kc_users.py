#!/usr/bin/env python3
"""Create demo users in realm 'rag' (safe to re-run) using the rag-provisioner service account.

Run: just kc-users
"""

import os
import secrets

import httpx

KC, REALM = "http://127.0.0.1:8180", "rag"
USERS = [  # username, first name, groups, MFA required
    ("alice", "Alice", ["all-staff", "engineering"], False),
    ("bob", "Bob", ["all-staff", "hr"], False),
    ("carol", "Carol", ["all-staff", "executives"], False),
    ("dave", "Dave", ["all-staff", "platform-admins"], True),
    ("erin", "Erin", ["all-staff", "auditors"], True),
]


def main() -> None:
    # 1. The script signs in as a MACHINE (client credentials): no human password involved
    token = (
        httpx.post(
            f"{KC}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "rag-provisioner",
                "client_secret": os.environ["KEYCLOAK_PROVISIONER_SECRET"],
            },
        )
        .raise_for_status()
        .json()["access_token"]
    )
    api = httpx.Client(
        base_url=f"{KC}/admin/realms/{REALM}", headers={"Authorization": f"Bearer {token}"}
    )

    group_ids = {
        g["name"]: g["id"]
        for g in api.get("/groups", params={"max": 100}).raise_for_status().json()
    }

    for username, first, groups, mfa in USERS:
        found = (
            api.get("/users", params={"username": username, "exact": "true"})
            .raise_for_status()
            .json()
        )
        if found:
            uid, status = found[0]["id"], "already exists"
        else:
            password = secrets.token_urlsafe(12)  # 16 random characters, shown once
            r = api.post(
                "/users",
                json={
                    "username": username,
                    "firstName": first,
                    "lastName": "Demo",
                    "email": f"{username}@example.com",
                    "emailVerified": True,
                    "enabled": True,
                    "requiredActions": ["CONFIGURE_TOTP"] if mfa else [],
                    "credentials": [{"type": "password", "value": password, "temporary": True}],
                },
            )
            r.raise_for_status()
            uid = r.headers["Location"].rsplit("/", 1)[-1]
            status = f"created · one-time password: {password}"
        for g in groups:  # PUT is idempotent: safe to repeat
            api.put(f"/users/{uid}/groups/{group_ids[g]}").raise_for_status()
        print(f"{username:6} {', '.join(groups):30} {status}")

    # 2. Least-privilege proof: the provisioner can't read the realm's apps (and their secrets)
    print("provisioner -> list clients:", api.get("/clients").status_code, "(403 expected)")


if __name__ == "__main__":
    main()
