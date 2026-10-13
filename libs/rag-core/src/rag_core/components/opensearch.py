"""OpenSearch as keyword index (BM25 with Step 13's analyzers and synonyms) and as vector store
(k-NN), on Step 13's index design: alias rag-chunks, fields text/title/embedding/tenant_id/
acl_groups/classification/source_uri (Step 31). Plain REST through httpx.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core import filters as _filters
from rag_core.registry import Container, register
from rag_core.similarity import VectorIndexParams, check_contract, from_distance
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
    # Step 13's index maps metadata dynamically: strings become text with a ".keyword" sub-field.
    # Set ".keyword" there so exact filters (eq/in) match whole values; "" when metadata strings
    # are mapped as keyword (what create_if_missing does)
    keyword_suffix: str = ""


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

    def access_filter(
        self, principal: Principal, filters: Mapping[str, object] | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [
            {"term": {"tenant_id": principal.tenant}},
            {"terms": {"classification": list(principal.classifications)}},
            {"bool": {"should": [{"term": {"classification": "public"}},
                            {"terms": {"acl_groups": list(principal.groups)}}], "minimum_should_match": 1}},
        ]  # fmt: skip
        # the metadata filter (extension 01) is one more clause: it can only narrow the result
        if (
            extra := _filters.to_opensearch(filters, keyword_suffix=self.p.keyword_suffix)
        ) is not None:
            out.append(extra)
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
                filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        body = {"size": k, "_source": {"excludes": [self.p.vector_field]}, "query": {"bool": {
            "must": [{"multi_match": {"query": text, "fields": ["text", "embed_text", "title^2"]}}],
            "filter": self.access_filter(principal, filters)}}}  # fmt: skip
        return self._hits(self._req("POST", f"/{self.p.index}/_search", body), "sparse")


@register("keyword_index", "opensearch", params=OpenSearchParams, status="live",
            summary="OpenSearch BM25 with Step 13's analyzers and synonyms; permission-filtered")  # fmt: skip
def _os_kw(p: OpenSearchParams, c: Container) -> OpenSearchKeywordIndex:
    return OpenSearchKeywordIndex(p)


# metric -> OpenSearch's space_type
SPACE = {"cosine": "cosinesimil", "dot": "innerproduct", "l2": "l2", "l1": "l1"}


class OpenSearchKnnParams(OpenSearchParams, VectorIndexParams):
    """OpenSearchParams plus the k-NN index settings (extension 01)."""

    model_config = ConfigDict(extra="forbid")
    ef_construction: int = Field(100, ge=4, le=4096)  # Step 13's index uses 100
    ef_search: int = Field(100, ge=1, le=4096)  # sent per query as method_parameters (2.16+)
    # lucene (Step 13: filters DURING the graph search), faiss (big indexes), nmslib (2.x only;
    # the only engine with l1). OpenSearch 3 refuses to create new nmslib indexes.
    engine: Literal["lucene", "faiss", "nmslib"] = "lucene"
    create_if_missing: bool = False  # dev/tests; in production os_setup.py (Step 13) creates it

    @model_validator(mode="after")
    def _supported(self) -> OpenSearchKnnParams:
        if self.index_type == "ivfflat":
            raise ValueError("use index_type hnsw or flat (exact script scoring) with OpenSearch")
        if self.metric == "l1" and self.engine != "nmslib" and self.index_type == "hnsw":
            raise ValueError(
                "OpenSearch supports l1 only with engine nmslib (2.x) or index_type flat"
            )
        return self


def os_to_similarity(metric: str, score: float) -> float:
    """OpenSearch turns every distance into a positive _score with its own formula per space (the
    same for the k-NN query and the exact knn_score script); this undoes it, so the result follows
    rag-core's convention (similarity.py)."""
    if metric == "cosine":  # (1 + cos) / 2
        return 2.0 * score - 1.0
    if metric == "dot":  # ip >= 0: ip + 1; ip < 0: 1 / (1 - ip)
        return score - 1.0 if score >= 1.0 else 1.0 - 1.0 / score if score > 0 else float("-inf")
    if metric == "l2":  # 1 / (1 + d^2)
        return from_distance((max(0.0, 1.0 / score - 1.0)) ** 0.5) if score > 0 else 0.0
    return score  # l1: 1 / (1 + d), already our convention


class OpenSearchVectorStore(_OpenSearch):
    """k-NN (Lucene HNSW) with the permission filter applied DURING the graph search (efficient
    filtering), so a restricted user still gets k results, not k minus the filtered ones. The
    metric is the index's space_type: checked against the profile (the embedding contract)."""

    def __init__(self, p: OpenSearchParams, client: httpx.Client | None = None) -> None:
        knn = (
            p
            if isinstance(p, OpenSearchKnnParams)
            else OpenSearchKnnParams.model_validate(p.model_dump())
        )
        super().__init__(knn, client)
        self.k: OpenSearchKnnParams = knn
        self._ready = False

    def mapping(self) -> dict[str, Any]:
        """The index these settings describe (what create_if_missing creates)."""
        flat = self.k.index_type == "flat"
        vector: dict[str, Any] = {"type": "knn_vector", "dimension": self.k.dimensions}
        if flat:  # no graph at all: every search is an exact script score (any space, l1 too)
            vector["space_type"] = SPACE[self.k.metric]
        else:
            vector["method"] = {"name": "hnsw", "engine": self.k.engine, "space_type": SPACE[self.k.metric],
                                "parameters": {"m": self.k.hnsw_m, "ef_construction": self.k.ef_construction}}  # fmt: skip
        return {
            "settings": {"index": {"knn": not flat, "number_of_shards": 1, "number_of_replicas": 0}},
            "mappings": {
                # metadata strings as keyword: exact filters match whole values
                # metadata numbers as double: the first document's 3 must not make 2.5 a long
                "dynamic_templates": [{"metadata_strings": {"path_match": "metadata.*", "match_mapping_type": "string",
                                                            "mapping": {"type": "keyword"}}},
                                      {"metadata_numbers": {"path_match": "metadata.*", "match_mapping_type": "long",
                                                            "mapping": {"type": "double"}}}],
                "properties": {
                    "text": {"type": "text"}, "embed_text": {"type": "text"}, "title": {"type": "text"},
                    self.k.vector_field: vector,
                    "tenant_id": {"type": "keyword"}, "acl_groups": {"type": "keyword"},
                    "classification": {"type": "keyword"}, "source_uri": {"type": "keyword"},
                    "chunk_key": {"type": "keyword"},
                },
            },
        }  # fmt: skip

    def _ensure(self) -> None:
        if self._ready:
            return
        r = self._http.request("HEAD", f"/{self.k.index}")
        if r.status_code == 404:
            if not self.k.create_if_missing:
                raise RuntimeError(
                    f"opensearch index {self.k.index!r} doesn't exist (run os_setup.py, Step 13)"
                )
            self._req("PUT", f"/{self.k.index}", self.mapping())
        self._check_contract()
        self._ready = True

    def _check_contract(self) -> None:
        """The vector field's space_type and dimension must be the profile's."""
        res = self._req("GET", f"/{self.k.index}/_mapping")
        for body in (res or {}).values():
            field = (((body or {}).get("mappings") or {}).get("properties") or {}).get(
                self.k.vector_field
            )
            if not isinstance(field, dict):
                continue
            method = field.get("method") or {}
            space = method.get("space_type") or field.get("space_type")
            # an index created without a space_type uses l2 (OpenSearch's default)
            check_contract(f"opensearch index {self.k.index!r}",
                           {"space_type": SPACE[self.k.metric], "dimension": self.k.dimensions},
                           {"space_type": space or "l2", "dimension": field.get("dimension")})  # fmt: skip
            return
        raise RuntimeError(
            f"opensearch index {self.k.index!r} has no knn_vector field {self.k.vector_field!r}"
        )

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self._ensure()
        self._bulk(chunks, vectors)

    def query(self, vector: Sequence[float], k: int, flt: list[dict[str, Any]]) -> dict[str, Any]:
        """The search body: approximate k-NN with the filter inside, or an exact script score."""
        if self.k.index_type == "flat":
            script = {"source": "knn_score", "lang": "knn", "params": {
                "field": self.k.vector_field, "query_value": list(vector), "space_type": SPACE[self.k.metric]}}  # fmt: skip
            return {"size": k, "_source": {"excludes": [self.k.vector_field]},
                    "query": {"script_score": {"query": {"bool": {"filter": flt}}, "script": script}}}  # fmt: skip
        knn: dict[str, Any] = {"vector": list(vector), "k": k, "filter": {"bool": {"filter": flt}}}
        if self.k.engine != "nmslib":
            knn["method_parameters"] = {"ef_search": self.k.ef_search}
        return {"size": k, "_source": {"excludes": [self.k.vector_field]},
                "query": {"knn": {self.k.vector_field: knn}}}  # fmt: skip

    def search(self, vector: Sequence[float], principal: Principal, k: int,
                filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        flt = self.access_filter(principal, filters)  # an invalid filter fails before any request
        self._ensure()
        hits = self._hits(
            self._req("POST", f"/{self.k.index}/_search", self.query(vector, k, flt)), "dense"
        )
        out = [h.with_score(os_to_similarity(self.k.metric, h.score), "dense") for h in hits]
        return sorted(out, key=lambda h: -h.score)

    def count(self) -> int:
        self._ensure()
        return int(self._req("GET", f"/{self.k.index}/_count")["count"])


@register("vector_store", "opensearch-knn", params=OpenSearchKnnParams, status="live",
            summary="OpenSearch k-NN with filtering during the search; metric cosine/dot/l2/l1, engine lucene/faiss/nmslib, hnsw/flat")  # fmt: skip
def _os_knn(p: OpenSearchKnnParams, c: Container) -> OpenSearchVectorStore:
    return OpenSearchVectorStore(p)
