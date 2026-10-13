"""The real policy, in a real OPA, through the real client. Skipped if `opa` isn't installed."""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from rag_api.policy import DocumentRef, OpaClient, PolicyUnavailable
from rag_common.auth import Principal

POLICIES = Path(__file__).resolve().parents[3] / "policies"
TOKEN = secrets.token_urlsafe(16)  # a fresh throwaway token for this test server
pytestmark = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")


def person(name: str, *groups: str, roles: tuple[str, ...] = ("rag-user",)) -> Principal:
    return Principal(f"sub-{name}", name, "rag-cli", frozenset(groups), frozenset(roles))


DOCS = [
    DocumentRef(1, "internal", ("all-staff",)),
    DocumentRef(3, "confidential", ("hr",)),
    DocumentRef(4, "restricted", ("executives",)),
]


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str]:
    with socket.socket() as s:  # find a free port
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cmd = ["opa", "run", "--server", f"--addr=127.0.0.1:{port}", "--authentication=token",
           "--authorization=basic", "--ignore=*_test.rego", "--bundle", str(POLICIES)]  # fmt: skip
    proc = subprocess.Popen(  # noqa: S603 - fixed command, test only
        cmd, env={**os.environ, "OPA_API_TOKEN": TOKEN}, stdout=subprocess.DEVNULL
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if httpx.get(f"{url}/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait()


def test_alice_may_search_with_a_narrow_filter(opa_url: str) -> None:
    d = OpaClient(opa_url, TOKEN).decide(person("alice", "all-staff", "engineering"), "search")
    assert d.allow
    assert d.filter.classifications == {"public", "internal"}


def test_admin_action_denied_with_reason(opa_url: str) -> None:
    d = OpaClient(opa_url, TOKEN).decide(person("alice", "all-staff"), "admin:ping")
    assert not d.allow
    assert d.reasons == ("action admin:ping requires role rag-admin",)


def test_who_reads_what(opa_url: str) -> None:
    opa = OpaClient(opa_url, TOKEN)
    assert opa.readable(person("alice", "all-staff", "engineering"), DOCS) == {1}
    assert opa.readable(person("bob", "all-staff", "hr"), DOCS) == {1, 3}
    assert opa.readable(person("carol", "all-staff", "executives"), DOCS) == {1, 4}
    assert opa.readable(person("zoe", "all-staff", "executives", "contractors"), DOCS) == {1}


def test_wrong_token_is_an_error_not_a_yes(opa_url: str) -> None:
    with pytest.raises(PolicyUnavailable):
        OpaClient(opa_url, "wrong").decide(person("alice", "all-staff"), "search")
