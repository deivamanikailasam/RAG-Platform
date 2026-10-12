"""The evaluation harness must measure what /v1/search actually does (Step 26).

If someone changes the endpoint's retrieval steps and not the harness (or the other way round),
evaluation results stop describing production. This test runs both on the same inputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_api.policy import DocumentRef
from rag_api.search import Candidate, Hit
from rag_evals.datasets import Persona, RetrievalCase
from rag_evals.targets import PolicySearchTarget

if TYPE_CHECKING:  # type hints only: the objects themselves arrive as fixtures
    from conftest import FakeIdP, FakePolicy, FakeSearch
    from fastapi.testclient import TestClient


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_harness_and_endpoint_return_the_same_documents(
    client: TestClient, idp: FakeIdP, search: FakeSearch, policy: FakePolicy
) -> None:
    search.candidates = [
        Candidate(DocumentRef(1, "internal", ("all-staff",)), Hit(id=1, title="Remote", classification="internal", score=0.9)),
        Candidate(DocumentRef(4, "restricted", ("executives",)), Hit(id=4, title="Exec", classification="restricted", score=0.8)),
        Candidate(DocumentRef(2, "internal", ("all-staff",)), Hit(id=2, title="Parking", classification="internal", score=0.7)),
    ]  # fmt: skip
    policy.readable_ids = {1, 2}  # the post-check refuses document 4

    api = client.post("/v1/search", json={"query": "remote work", "k": 3},
                      headers=bearer(idp.mint(groups=["all-staff", "engineering"])))  # fmt: skip
    case = RetrievalCase(kind="retrieval", id="same", question="remote work", relevant=(1,),
                         persona=Persona(name="alice", groups=("all-staff", "engineering")))  # fmt: skip
    out = PolicySearchTarget(search, policy, {}).retrieve(case, k=3)
    assert [h["id"] for h in api.json()] == out.ranked == [1, 2]
    assert out.dropped == [4]
    # …and both asked the search backend with the same filter
    assert search.calls[0]["groups"] == search.calls[1]["groups"]
    assert search.calls[0]["classifications"] == search.calls[1]["classifications"]
