"""Qdrant as vector store (Step 31), on Step 12's collection design: named vector "dense",
tenant/ACL payload indexes, an alias. Plain REST through httpx: no client library to pin.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from rag_core.registry import Container, register
from rag_core.types import Access, Chunk, Principal, ScoredChunk

NAMESPACE = uuid.UUID("6f1c9e0a-2b51-4b8e-9b0e-6a3f1f3c9d11")  # chunk key -> stable Qdrant point id


class QdrantParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = "http://qdrant:6333"
    collection: str = "rag_chunks"  # the ALIAS (Step 12); re-indexing switches what it points to
    api_key_env: str | None = "QDRANT_API_KEY"
    vector_name: str = "dense"
    dimensions: int = Field(1024, ge=16)
    create_if_missing: bool = False  # dev/tests; in production qdrant_setup.py (Step 12) creates it
    hnsw_ef: int = Field(128, ge=8)
    timeout: float = 30.0


class QdrantStore:
    def __init__(self, p: QdrantParams, client: httpx.Client | None = None) -> None:
        self.p = p
        headers = {}
        if p.api_key_env and os.environ.get(p.api_key_env):
            headers["api-key"] = os.environ[p.api_key_env]
        self._http = client or httpx.Client(
            base_url=p.url, headers=headers, timeout=p.timeout, trust_env=False
        )
        self._ready = False

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        r = self._http.request(method, f"/collections/{self.p.collection}{path}", json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"qdrant {method} {path}: {r.status_code} {r.text[:300]}")
        return r.json().get("result")

    def _ensure(self) -> None:
        if self._ready:
            return
        r = self._http.get(f"/collections/{self.p.collection}/exists")
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"qdrant: {r.status_code} {r.text[:200]} (check {self.p.api_key_env})"
            )
        exists = r.status_code == 200 and r.json()["result"]["exists"]
        if not exists:
            if not self.p.create_if_missing:
                raise RuntimeError(
                    f"qdrant collection {self.p.collection!r} doesn't exist (run qdrant_setup.py, Step 12)"
                )
            self._call(
                "PUT",
                "",
                {
                    "vectors": {
                        self.p.vector_name: {"size": self.p.dimensions, "distance": "Cosine"}
                    }
                },
            )
            for field, schema in {"tenant_id": {"type": "keyword", "is_tenant": True}, "acl_groups": "keyword",
                            "classification": "keyword", "source_uri": "keyword"}.items():  # fmt: skip
                self._call("PUT", "/index?wait=true", {"field_name": field, "field_schema": schema})
        self._ready = True

    @staticmethod
    def point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(NAMESPACE, chunk_id))

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self._ensure()
        points = [{
            "id": self.point_id(c.id), "vector": {self.p.vector_name: list(v)},
            "payload": {"chunk_key": c.id, "source_uri": c.document_uri, "chunk_index": c.index, "text": c.text,
                        "embed_text": c.embed_text, "token_count": c.token_count, "parent_key": c.parent_id,
                        "tenant_id": c.access.tenant, "classification": c.access.classification,
                        "acl_groups": list(c.access.groups), "metadata": dict(c.metadata)},
        } for c, v in zip(chunks, vectors, strict=True)]  # fmt: skip
        for i in range(0, len(points), 256):
            self._call("PUT", "/points?wait=true", {"points": points[i : i + 256]})

    def delete_document(self, document_uri: str) -> int:
        self._ensure()
        flt = {"must": [{"key": "source_uri", "match": {"value": document_uri}}]}
        n = int(self._call("POST", "/points/count", {"filter": flt, "exact": True})["count"])
        self._call("POST", "/points/delete?wait=true", {"filter": flt})
        return n

    def update_access(self, document_uri: str, access: Access) -> int:
        """Overwrite the access fields in every point of this document's payload (no re-embedding)."""
        self._ensure()
        flt = {"must": [{"key": "source_uri", "match": {"value": document_uri}}]}
        n = int(self._call("POST", "/points/count", {"filter": flt, "exact": True})["count"])
        self._call("POST", "/points/payload?wait=true", {"filter": flt, "payload": {
            "tenant_id": access.tenant, "classification": access.classification, "acl_groups": list(access.groups)}})  # fmt: skip
        return n

    @staticmethod
    def access_filter(
        principal: Principal, filters: dict[str, object] | None = None
    ) -> dict[str, Any]:
        """The same rule as Step 18's policy and Step 11's SQL, as a Qdrant filter."""
        must: list[dict[str, Any]] = [
            {"key": "tenant_id", "match": {"value": principal.tenant}},
            {"key": "classification", "match": {"any": list(principal.classifications)}},
            # public, OR at least one shared group (a nested "should" = OR)
            {"should": [{"key": "classification", "match": {"value": "public"}},
                        {"key": "acl_groups", "match": {"any": list(principal.groups) or ["\x00none"]}}]},
        ]  # fmt: skip
        for key, want in (filters or {}).items():
            match = {"any": list(want)} if isinstance(want, list | tuple | set) else {"value": want}
            must.append({"key": f"metadata.{key}", "match": match})
        return {"must": must}

    def search(self, vector: Sequence[float], principal: Principal, k: int,
                filters: dict[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        self._ensure()
        res = self._call("POST", "/points/query", {
            "query": list(vector), "using": self.p.vector_name, "limit": k, "with_payload": True,
            "filter": self.access_filter(principal, filters), "params": {"hnsw_ef": self.p.hnsw_ef},
        })  # fmt: skip
        out = []
        for pt in res["points"]:
            pl = pt["payload"]
            chunk = Chunk(id=pl["chunk_key"], document_uri=pl["source_uri"], index=pl["chunk_index"], text=pl["text"],
                            token_count=pl["token_count"], access=Access(pl["classification"], tuple(pl["acl_groups"]),
                            pl["tenant_id"]), embed_text=pl.get("embed_text") or "", parent_id=pl.get("parent_key"),
                            metadata=pl.get("metadata") or {})  # fmt: skip
            out.append(ScoredChunk(chunk, float(pt["score"]), {"dense": float(pt["score"])}))
        return out

    def count(self) -> int:
        self._ensure()
        return int(self._call("POST", "/points/count", {"exact": True})["count"])


@register("vector_store", "qdrant", params=QdrantParams,
            summary="Qdrant over REST: Step 12's collection, payload-filtered by tenant, classification and groups")  # fmt: skip
def _qdrant(p: QdrantParams, c: Container) -> QdrantStore:
    return QdrantStore(p)
