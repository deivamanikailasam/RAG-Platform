"""The retrieval target with the REAL policy in a real OPA: personas see what the policy allows."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator

import httpx
import pytest

from rag_api.policy import DocumentRef, OpaClient
from rag_api.search import Candidate, Hit
from rag_evals.datasets import Dataset
from rag_evals.runner import run_retrieval
from rag_evals.targets import PolicySearchTarget

from .conftest import REPO

pytestmark = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
TOKEN = "eval-test-token"  # noqa: S105 - throwaway token for a local test OPA
CORPUS = {  # Step 11's four documents
    1: ("Remote work policy", "internal", ("all-staff",)),
    2: ("Parking", "internal", ("all-staff",)),
    3: ("Salary bands 2026", "confidential", ("hr",)),
    4: ("Exec offsite", "restricted", ("executives",)),
}


class AllDocumentsSearch:
    """A deliberately BROKEN search: ignores the filter and returns everything. The post-check must hold."""

    def search(self, query: str, *, groups: frozenset[str], classifications: frozenset[str],
               k: int, user: str) -> list[Candidate]:  # fmt: skip
        return [Candidate(DocumentRef(i, c, acl), Hit(id=i, title=t, classification=c, score=0.5))
                for i, (t, c, acl) in CORPUS.items()][:k]  # fmt: skip


@pytest.fixture(scope="module")
def opa() -> Iterator[OpaClient]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(  # noqa: S603
        ["opa", "run", "--server", f"--addr=127.0.0.1:{port}", "--authentication=token",  # noqa: S607
         "--authorization=basic", "--ignore=*_test.rego", "--bundle", str(REPO / "policies")],
        env={**os.environ, "OPA_API_TOKEN": TOKEN}, stdout=subprocess.DEVNULL,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if httpx.get(f"{url}/health").status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.1)
    yield OpaClient(url, TOKEN)
    proc.terminate()


def test_no_persona_receives_a_forbidden_document(opa: OpaClient, retrieval_set: Dataset) -> None:
    r = run_retrieval(retrieval_set, PolicySearchTarget(AllDocumentsSearch(), opa, {}), k=5)
    assert r.summary["leaked_docs"] == 0  # the real policy's post-check removed every one
    by_id = {rec["id"]: rec for rec in r.records}
    assert by_id["offsite-denied"]["ranked"] == [1, 2]  # alice: internal documents only
    assert by_id["salary-hr"]["ranked"] == [1, 2, 3]  # bob: plus salary bands
    assert by_id["offsite-exec"]["ranked"] == [1, 2, 4]  # carol: plus the offsite
    assert by_id["contractor-cap"]["ranked"] == [1, 2]  # zoe: executive group, capped at internal
    # The broken search shows up as mismatches, exactly what the Step 18 alert watches for
    assert r.summary["policy_mismatches"] > 0
