"""Ask OPA for authorisation decisions. Any doubt (OPA down, odd answer) means "no"."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from rag_common.auth import Principal


class PolicyUnavailable(Exception):  # noqa: N818 - reads better than ...Error here
    """OPA could not be reached or answered nonsense. Maps to HTTP 503: we never guess."""


@dataclass(frozen=True)
class SearchFilter:
    groups: frozenset[str]
    classifications: frozenset[str]


@dataclass(frozen=True)
class Decision:
    allow: bool
    reasons: tuple[str, ...]
    filter: SearchFilter


@dataclass(frozen=True)
class DocumentRef:
    id: int
    classification: str
    acl_groups: tuple[str, ...]


class PolicyEngine(Protocol):
    def decide(self, principal: Principal, action: str) -> Decision: ...

    def readable(self, principal: Principal, docs: list[DocumentRef]) -> set[int]: ...


def _principal_input(p: Principal) -> dict[str, Any]:
    # Only facts from the VERIFIED token go to the policy, never anything the caller sent.
    return {
        "sub": p.subject,
        "username": p.username,
        "client_id": p.client_id,
        "groups": sorted(p.groups),
        "roles": sorted(p.roles),
    }


class OpaClient:
    def __init__(self, url: str, token: str, timeout: float = 2.0) -> None:
        self._http = httpx.Client(
            base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout
        )

    def _query(self, rule: str, input_: dict[str, Any]) -> Any:
        try:
            r = self._http.post(f"/v1/data/rag/authz/{rule}", json={"input": input_})
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PolicyUnavailable(f"OPA query {rule} failed: {e}") from e
        if "result" not in body:  # an undefined result means the policy isn't loaded
            raise PolicyUnavailable(f"OPA returned no result for {rule}")
        return body["result"]

    def decide(self, principal: Principal, action: str) -> Decision:
        res = self._query("decision", {"principal": _principal_input(principal), "action": action})
        try:
            return Decision(
                allow=res["allow"] is True,  # only a literal true allows
                reasons=tuple(res["reasons"]),
                filter=SearchFilter(
                    groups=frozenset(res["filter"]["groups"]),
                    classifications=frozenset(res["filter"]["classifications"]),
                ),
            )
        except (KeyError, TypeError) as e:
            raise PolicyUnavailable(f"unexpected decision shape: {res!r}") from e

    def readable(self, principal: Principal, docs: list[DocumentRef]) -> set[int]:
        if not docs:
            return set()
        documents = [
            {"id": d.id, "classification": d.classification, "acl_groups": list(d.acl_groups)}
            for d in docs
        ]
        res = self._query(
            "readable_ids", {"principal": _principal_input(principal), "documents": documents}
        )
        if not isinstance(res, list):
            raise PolicyUnavailable(f"unexpected readable_ids shape: {res!r}")
        return {int(i) for i in res}
