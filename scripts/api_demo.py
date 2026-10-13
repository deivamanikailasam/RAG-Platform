#!/usr/bin/env python3
"""Call rag-api as a person, as a machine, with no token and with a forged token.

Run: just api-demo
"""

import os
import time

import httpx

OIDC = "http://127.0.0.1:8180/realms/rag/protocol/openid-connect"
API = "http://127.0.0.1:8000"


def person_token() -> str:
    """Device flow (Step 16): you approve in the browser; the script never sees your password."""
    resp = httpx.post(f"{OIDC}/auth/device", data={"client_id": "rag-cli", "scope": "openid"})
    d = resp.raise_for_status().json()
    print(f"Open {d['verification_uri_complete']} and sign in (try alice, then carol).")
    while True:
        time.sleep(d.get("interval", 5))
        r = httpx.post(f"{OIDC}/token", data={"client_id": "rag-cli", "device_code": d["device_code"],
                                              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})  # fmt: skip
        if r.status_code == 200:
            return str(r.json()["access_token"])
        if r.json().get("error") not in ("authorization_pending", "slow_down"):
            r.raise_for_status()


def machine_token() -> str:
    r = httpx.post(f"{OIDC}/token", data={"grant_type": "client_credentials", "client_id": "ingestion-worker",
                                          "client_secret": os.environ["KEYCLOAK_INGESTION_SECRET"]})  # fmt: skip
    return str(r.raise_for_status().json()["access_token"])


def call(label: str, method: str, path: str, token: str | None, **kw: object) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = httpx.request(method, API + path, headers=headers, timeout=30, **kw)  # type: ignore[arg-type]
    print(f"{label:34} {method:4} {path:16} -> {r.status_code}  {r.text[:110]}")


def forge(token: str) -> str:
    """Change the last characters of the signature: the token still LOOKS valid."""
    head, payload, sig = token.split(".")
    return f"{head}.{payload}.{sig[:-6]}AAAAAA"


def main() -> None:
    question = {"query": "What is the plan for hybrid work?", "k": 3}
    person = person_token()
    call("person", "GET", "/v1/me", person)
    call("person", "POST", "/v1/search", person, json=question)
    call("person (not an admin)", "GET", "/v1/admin/ping", person)

    # Step 33: an answer, a follow-up in the same session, a streamed answer, feedback
    ask = {"question": "How many days a week can I work from home?", "session_id": "demo-1"}
    r = httpx.post(
        API + "/v1/answer", json=ask, headers={"Authorization": f"Bearer {person}"}, timeout=120
    )
    print(f"{'person':34} POST /v1/answer        -> {r.status_code}  {r.text[:300]}")
    call("person (follow-up)", "POST", "/v1/answer", person,
         json={"question": "Is there an allowance for it?", "session_id": "demo-1"})  # fmt: skip
    with httpx.stream("POST", API + "/v1/answer", headers={"Authorization": f"Bearer {person}"}, timeout=120,
                      json={"question": "What does VPN error E-1107 mean?", "stream": True}) as s:  # fmt: skip
        print(f"{'person (stream)':34} POST /v1/answer        -> {s.status_code}")
        for line in s.iter_lines():
            if line:
                print("        " + line[:120])
    if r.status_code == 200:
        call("person (feedback)", "POST", "/v1/feedback", person,
             json={"answer_id": r.json()["answer_id"], "rating": "up"})  # fmt: skip

    machine = machine_token()
    call("machine", "GET", "/v1/me", machine)
    call("machine (no rag-user role)", "POST", "/v1/search", machine, json=question)

    call("no token", "GET", "/v1/me", None)
    call("forged token (last chars changed)", "GET", "/v1/me", forge(person))


if __name__ == "__main__":
    main()
