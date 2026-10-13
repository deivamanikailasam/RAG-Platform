"""OpenSearch as keyword index (BM25 with Step 13's analyzers and synonyms) and as vector store
(k-NN), on Step 13's index design: alias rag-chunks, fields text/title/embedding/tenant_id/
acl_groups/classification/source_uri (Step 31). Plain REST through httpx.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from rag_core.registry import Container, register
from rag_core.types import Access, Chunk, Principal, ScoredChunk


class OpenSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = "https://opensearch:9200"
    index: str = "rag-chunks"  # the alias (Step 13)
    user_env: str = "OPENSEARCH_USER"
    password_env: str = "OPENSEARCH_PASSWORD"  # noqa: S105 - the NAME of a variable
    verify: str | bool = (
        "/run/secrets/opensearch_ca.pem"  # its CA (Step 13); never just switch it off
    )
    vector_field: str = "embedding"
    dimensions: int = Field(1024, ge=16)
    timeout: float = 30.0


class _OpenSearch:
    def __init__(self, p: OpenSearchParams, client: httpx.Client | None = None) -> None:
        self.p = p
        auth = (os.environ.get(p.user_env, ""), os.environ.get(p.password_env, ""))
        self._http = client or httpx.Client(
            base_url=p.url, auth=auth, verify=p.verify, timeout=p.timeout, trust_env=False
        )

    def _req(
        self,
        method: str,
        path: str,
        body: Any = None,
        ndjson: str | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        if ndjson is not None:
            r = self._http.request(
                method,
                path,
                content=ndjson,
                params=params,
                headers={"Content-Type": "application/x-ndjson"},
            )
        else:
            r = self._http.request(method, path, json=body, params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"opensearch {method} {path}: {r.status_code} {r.text[:300]}")
        data = r.json()
        if isinstance(data, dict) and data.get("errors"):
            first = next(i for i in data["items"] if next(iter(i.values())).get("error"))
            raise RuntimeError(f"opensearch bulk error: {json.dumps(first)[:300]}")
        return data

    @staticmethod
    def access_filter(
        principal: Principal, filters: dict[str, object] | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [
            {"term": {"tenant_id": principal.tenant}},
            {"terms": {"classification": list(principal.classifications)}},
            {"bool": {"should": [{"term": {"classification": "public"}},
                            {"terms": {"acl_groups": list(principal.groups)}}], "minimum_should_match": 1}},
        ]  # fmt: skip
        for key, want in (filters or {}).items():
            out.append({"terms": {f"metadata.{key}": list(want)}} if isinstance(want, list | tuple | set)
                        else {"term": {f"metadata.{key}": want}})  # fmt: skip
        return out

    def _doc(self, c: Chunk, vector: Sequence[float] | None) -> dict[str, Any]:
        d = {"chunk_key": c.id, "source_uri": c.document_uri, "chunk_index": c.index, "text": c.text,
            "embed_text": c.embed_text, "title": str(c.metadata.get("title", "")), "token_count": c.token_count,
            "parent_key": c.parent_id, "tenant_id": c.access.tenant, "classification": c.access.classification,
            "acl_groups": list(c.access.groups), "metadata": dict(c.metadata)}  # fmt: skip
        if vector is not None:
            d[self.p.vector_field] = list(vector)
        return d

    def _bulk(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]] | None) -> None:
        lines = []
        for i, c in enumerate(chunks):
            lines.append(json.dumps({"index": {"_index": self.p.index, "_id": c.id}}))
            lines.append(
                json.dumps(self._doc(c, vectors[i] if vectors is not None else None), default=str)
            )
        for i in range(0, len(lines), 1000):
            self._req(
                "POST",
                "/_bulk",
                ndjson="\n".join(lines[i : i + 1000]) + "\n",
                params={"refresh": "wait_for"},
            )

    def delete_document(self, document_uri: str) -> int:
        res = self._req("POST", f"/{self.p.index}/_delete_by_query", {"query": {"term": {"source_uri": document_uri}}},
                        params={"refresh": "true"})  # fmt: skip
        return int(res.get("deleted", 0))

    def update_access(self, document_uri: str, access: Access) -> int:
        """Rewrite the access fields of this document's chunks in place (painless script, parameters)."""
        script = {"lang": "painless", "params": {"t": access.tenant, "c": access.classification, "g": list(access.groups)},
                  "source": "ctx._source.tenant_id = params.t; ctx._source.classification = params.c; "
                            "ctx._source.acl_groups = params.g"}  # fmt: skip
        res = self._req("POST", f"/{self.p.index}/_update_by_query", {"query": {"term": {"source_uri": document_uri}},
                        "script": script}, params={"refresh": "true", "conflicts": "proceed"})  # fmt: skip
        return int(res.get("updated", 0))

    def search_all(self, text: str, k: int) -> list[ScoredChunk]:
        """Every tenant and group: for the erasure job only (Step 36), never for people."""
        body = {"size": k, "_source": {"excludes": [self.p.vector_field]},
                "query": {"multi_match": {"query": text, "fields": ["text", "embed_text", "title"]}}}  # fmt: skip
        return self._hits(self._req("POST", f"/{self.p.index}/_search", body), "sparse")

    @staticmethod
    def _hits(res: dict[str, Any], stage: str) -> list[ScoredChunk]:
        out = []
        for h in res["hits"]["hits"]:
            s = h["_source"]
            chunk = Chunk(id=s["chunk_key"], document_uri=s["source_uri"], index=s["chunk_index"], text=s["text"],
                            token_count=s["token_count"], access=Access(s["classification"], tuple(s["acl_groups"]),
                            s["tenant_id"]), embed_text=s.get("embed_text") or "", parent_id=s.get("parent_key"),
                            metadata=s.get("metadata") or {})  # fmt: skip
            out.append(ScoredChunk(chunk, float(h["_score"]), {stage: float(h["_score"])}))
        return out


class OpenSearchKeywordIndex(_OpenSearch):
    """BM25 over text and title, with Step 13's index-time stemming and query-time synonyms."""

    def index(self, chunks: Sequence[Chunk]) -> None:
        self._bulk(chunks, None)

    def search(self, text: str, principal: Principal, k: int,
                filters: dict[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        body = {"size": k, "_source": {"excludes": [self.p.vector_field]}, "query": {"bool": {
            "must": [{"multi_match": {"query": text, "fields": ["text", "embed_text", "title^2"]}}],
            "filter": self.access_filter(principal, filters)}}}  # fmt: skip
        return self._hits(self._req("POST", f"/{self.p.index}/_search", body), "sparse")


@register("keyword_index", "opensearch", params=OpenSearchParams, status="mocked",
            summary="OpenSearch BM25 with Step 13's analyzers and synonyms; permission-filtered")  # fmt: skip
def _os_kw(p: OpenSearchParams, c: Container) -> OpenSearchKeywordIndex:
    return OpenSearchKeywordIndex(p)


class OpenSearchVectorStore(_OpenSearch):
    """k-NN (Lucene HNSW) with the permission filter applied DURING the graph search (efficient
    filtering), so a restricted user still gets k results, not k minus the filtered ones."""

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self._bulk(chunks, vectors)

    def search(self, vector: Sequence[float], principal: Principal, k: int,
                filters: dict[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        body = {"size": k, "_source": {"excludes": [self.p.vector_field]}, "query": {"knn": {self.p.vector_field: {
            "vector": list(vector), "k": k, "filter": {"bool": {"filter": self.access_filter(principal, filters)}}}}}}  # fmt: skip
        return self._hits(self._req("POST", f"/{self.p.index}/_search", body), "dense")

    def count(self) -> int:
        return int(self._req("GET", f"/{self.p.index}/_count")["count"])


@register("vector_store", "opensearch-knn", params=OpenSearchParams, status="mocked",
            summary="OpenSearch k-NN (Lucene HNSW) with filtering during the search")  # fmt: skip
def _os_knn(p: OpenSearchParams, c: Container) -> OpenSearchVectorStore:
    return OpenSearchVectorStore(p)
