"""Embedding options (extension 02): how text becomes vectors, beyond "one model, one vector".

    instructed      query vs passage prefixes for e5 / bge / nomic / Qwen3 style models
    matryoshka      keep the first N dimensions of a Matryoshka-trained model (smaller, faster index)
    late-chunking   embed the whole document, then pool the token vectors of each chunk
    sparse vectors  a weight per word (BM25 offline, SPLADE via TEI), searched as a keyword index
                    in memory or in Qdrant's sparse vectors
    multi-vector    one vector per TOKEN, scored by MaxSim (ColBERT), as a reranker

Each has an offline implementation (hashing-based) that runs in CI; the model-backed ones are
"mocked" (tested against a stand-in HTTP service) or "reference" (needs an optional package).
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core import filters as _filters
from rag_core.components.basics import WORD, words
from rag_core.components.qdrant import QdrantParams, QdrantStore
from rag_core.components.retrieval import RerankParams, _Reranker
from rag_core.registry import Container, register, spec
from rag_core.types import Access, Chunk, Document, Principal, ScoredChunk

SparseVector = dict[int, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _inner(raw: Mapping[str, Any], c: Container, kind: str = "embedder") -> Any:
    """Build a wrapped component from its {use: …, …} mapping."""
    d = dict(raw)
    s = spec(kind, str(d.pop("use")))
    return s.factory(s.params.model_validate(d), c)


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _hid(feature: str, bits: int = 31) -> int:
    """A stable integer id for a word (the same on every machine and run)."""
    return int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big") & (
        (1 << bits) - 1
    )


# ================================================================ instructions / prefixes

PRESETS: dict[str, tuple[str, str]] = {  # (query prefix, passage prefix)
    "none": ("", ""),
    "e5": ("query: ", "passage: "),  # intfloat/e5-*, multilingual-e5-*
    "bge": ("Represent this sentence for searching relevant passages: ", ""),  # BAAI/bge-*-en-v1.5
    "nomic": ("search_query: ", "search_document: "),  # nomic-embed-text-v1/v1.5/v2
    "qwen3": ("Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ", ""),
    "gte": ("", ""),  # gte-base/large: no prefixes; gte-Qwen2-instruct: use qwen3
    "mxbai": ("Represent this sentence for searching relevant passages: ", ""),
    "snowflake": ("Represent this sentence for searching relevant passages: ", ""),  # arctic-embed
}  # fmt: skip


class InstructedParams(_Strict):
    inner: dict[
        str, Any
    ]  # the model: {use: gateway, model: e5-large, query_instruction: "{query}"}
    preset: Literal["none", "e5", "bge", "nomic", "qwen3", "gte", "mxbai", "snowflake"] = "none"
    query_prefix: str | None = None  # overrides the preset's
    passage_prefix: str | None = None


class InstructedEmbedder:
    """Asymmetric models are trained with a prefix that says what the text is: "query: …" for a
    question, "passage: …" for a document (e5); "search_query:"/"search_document:" (nomic); an
    instruction before the question only (bge, Qwen3). Without the right prefix they lose several
    points of retrieval quality, silently. The prefix is part of the embedding contract: change
    it and the index must be rebuilt (it changes the model name recorded with every vector)."""

    def __init__(self, inner: Any, query_prefix: str, passage_prefix: str) -> None:
        self.inner, self.dimensions = inner, inner.dimensions
        self.query_prefix, self.passage_prefix = query_prefix, passage_prefix
        tag = hashlib.sha256(f"{query_prefix}\x00{passage_prefix}".encode()).hexdigest()[:6]
        self.model = (
            f"{inner.model}+prefix-{tag}" if query_prefix or passage_prefix else inner.model
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return list(self.inner.embed_documents([self.passage_prefix + t for t in texts]))

    def embed_query(self, text: str) -> list[float]:
        # through embed_documents: the inner model's own query instruction must not be added twice
        return list(self.inner.embed_documents([self.query_prefix + text])[0])


@register("embedder", "instructed", params=InstructedParams,
          summary="query vs passage prefixes for e5/bge/nomic/Qwen3-style models (presets or your own)")  # fmt: skip
def _instructed(p: InstructedParams, c: Container) -> InstructedEmbedder:
    q, d = PRESETS[p.preset]
    return InstructedEmbedder(_inner(p.inner, c), p.query_prefix if p.query_prefix is not None else q,
                              p.passage_prefix if p.passage_prefix is not None else d)  # fmt: skip


# ================================================================ Matryoshka truncation


class MatryoshkaParams(_Strict):
    inner: dict[
        str, Any
    ]  # a Matryoshka-trained model (OpenAI text-embedding-3, nomic v1.5, Qwen3, …)
    dimensions: int = Field(256, ge=8)
    normalise: bool = True  # re-normalise after cutting (needed for cosine/dot to stay comparable)


class MatryoshkaEmbedder:
    """Matryoshka Representation Learning (Kusupati et al., 2022): models trained so the FIRST N
    numbers of a vector are already a good, smaller vector. Keeping 256 of 1024 dimensions makes
    the index 4x smaller and search faster for a few points of quality. Only for models trained
    this way: cutting any other model's vector ruins it. Many APIs can do the cut server-side
    (the gateway embedder's `request_dimensions`)."""

    def __init__(self, inner: Any, dimensions: int, normalise: bool = True) -> None:
        if dimensions > inner.dimensions:
            raise ValueError(f"can't keep {dimensions} of {inner.dimensions} dimensions")
        self.inner, self.dimensions, self.norm = inner, dimensions, normalise
        self.model = f"{inner.model}@{dimensions}"

    def _cut(self, v: Sequence[float]) -> list[float]:
        head = list(v[: self.dimensions])
        return _normalise(head) if self.norm else head

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._cut(v) for v in self.inner.embed_documents(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self._cut(self.inner.embed_query(text))


@register("embedder", "matryoshka", params=MatryoshkaParams,
          summary="keep the first N dimensions of a Matryoshka-trained model's vectors (smaller, faster index)")  # fmt: skip
def _matryoshka(p: MatryoshkaParams, c: Container) -> MatryoshkaEmbedder:
    return MatryoshkaEmbedder(_inner(p.inner, c), p.dimensions, p.normalise)


# ================================================================ token vectors (late chunking, MaxSim)

TokenVectors = tuple[
    list[tuple[int, int]], list[list[float]]
]  # (char offsets, one vector per token)


class HashTokenEncoder:
    """Offline stand-in for a long-context model's token embeddings: each token's vector is its own
    hashed word plus its neighbours' (weight decay^distance, within `window`), plus a share of
    the whole text's average (`global_weight`): every token "sees" its context, as in a
    transformer, which is what late chunking relies on."""

    model = "hash-tokens-v1"

    def __init__(self, dimensions: int = 256, window: int = 8, decay: float = 0.7,
                 global_weight: float = 0.15) -> None:  # fmt: skip
        self.dimensions, self.window, self.decay, self.global_weight = (
            dimensions,
            window,
            decay,
            global_weight,
        )

    def _base(self, word: str) -> tuple[int, float]:
        h = _hid(word, 63)
        return h % self.dimensions, 1.0 if (h >> 32) & 1 else -1.0

    def encode(self, text: str) -> TokenVectors:
        toks = [(m.start(), m.end(), m.group(0).lower()) for m in WORD.finditer(text)]
        base = [self._base(w) for _, _, w in toks]
        glob = [0.0] * self.dimensions
        for i, s in base:
            glob[i] += s
        glob = [x * self.global_weight for x in _normalise(glob)]
        vectors = []
        for t in range(len(toks)):
            v = list(glob)
            for j in range(max(0, t - self.window), min(len(toks), t + self.window + 1)):
                i, s = base[j]
                v[i] += s * self.decay ** abs(t - j)
            vectors.append(v)
        return [(a, b) for a, b, _ in toks], vectors


class TeiTokenEncoder:
    """Token embeddings from Text Embeddings Inference: /tokenize (with character offsets) and
    /embed_all (one vector per token), aligned by position, special tokens dropped."""

    def __init__(self, url: str, dimensions: int, timeout: float = 120.0,
                 client: httpx.Client | None = None) -> None:  # fmt: skip
        self.dimensions, self.model = dimensions, f"tei-tokens@{url}"
        self._http = client or httpx.Client(base_url=url.rstrip("/") + "/", timeout=timeout)

    def encode(self, text: str) -> TokenVectors:
        r = self._http.post("tokenize", json={"inputs": text, "add_special_tokens": True})
        r.raise_for_status()
        tokens = r.json()[0]
        e = self._http.post("embed_all", json={"inputs": text, "truncate": True})
        e.raise_for_status()
        vectors = e.json()[0]
        offsets, out = [], []
        for tok, vec in zip(tokens, vectors, strict=False):  # truncation: fewer vectors than tokens
            if tok.get("special"):
                continue
            offsets.append((int(tok["start"]), int(tok["stop"])))
            out.append([float(x) for x in vec])
        return offsets, out


def _pool(vectors: Sequence[Sequence[float]], dims: int) -> list[float]:
    acc = [0.0] * dims
    for v in vectors:
        for i, x in enumerate(v):
            acc[i] += x
    return _normalise(acc)


class LateChunkingParams(_Strict):
    backend: Literal["hashing", "tei"] = "hashing"
    dimensions: int = Field(256, ge=16, le=8192)  # hashing: the vector size; tei: the model's
    url: str = "http://host.docker.internal:8085"  # tei: a long-context model (jina-embeddings-v3, bge-m3, …)
    max_tokens: int = Field(
        8192, ge=64
    )  # the model's context; longer documents in overlapping windows
    window_overlap: float = Field(0.25, ge=0, lt=1)
    window: int = Field(8, ge=0, le=64)  # hashing: neighbours each token sees
    timeout: float = 120.0


class LateChunkingEmbedder:
    """Late chunking (Günther et al., Jina AI, 2024): embed the WHOLE document once with a
    long-context model, then average the token vectors that fall inside each chunk. A chunk
    saying "It is 18 weeks." keeps what "it" refers to, because its tokens were encoded with
    the rest of the section in view. Ingestion calls `embed_chunks(document, chunks)`; questions
    are embedded alone (`embed_query`). Documents longer than the model's context are encoded in
    overlapping windows ("long late chunking"); a chunk not found in the text (a generated
    summary) is embedded on its own."""

    def __init__(self, p: LateChunkingParams, encoder: Any = None) -> None:
        self.p = p
        self.encoder = encoder or (HashTokenEncoder(p.dimensions, p.window) if p.backend == "hashing"
                                   else TeiTokenEncoder(p.url, p.dimensions, p.timeout))  # fmt: skip
        self.dimensions = p.dimensions
        self.model = f"late-chunking/{self.encoder.model}"

    def _alone(self, text: str) -> list[float]:
        _, vecs = self.encoder.encode(text)
        return _pool(vecs, self.dimensions) if vecs else [0.0] * self.dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._alone(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._alone(text)

    def _windows(self, text: str) -> list[tuple[int, int]]:
        size = self.p.max_tokens * 4  # characters, ~4 per token
        if len(text) <= size:
            return [(0, len(text))]
        step = max(1, int(size * (1 - self.p.window_overlap)))
        return [
            (s, min(len(text), s + size)) for s in range(0, max(1, len(text) - size + step), step)
        ]

    def embed_chunks(self, document: Document, chunks: Sequence[Chunk]) -> list[list[float]]:
        text = document.text
        spans: list[tuple[int, int] | None] = []
        cursor = 0
        for c in chunks:
            at = text.find(c.text, cursor)
            if at < 0:
                at = text.find(c.text)
            spans.append((at, at + len(c.text)) if at >= 0 else None)
            if at >= 0:
                cursor = at + 1
        windows = self._windows(text)
        encoded: dict[int, TokenVectors] = {}
        out: list[list[float]] = []
        for c, span in zip(chunks, spans, strict=True):
            w = next(
                (i for i, (a, b) in enumerate(windows) if span and a <= span[0] and span[1] <= b),
                None,
            )
            if span is None or w is None:
                out.append(self._alone(c.indexed_text))
                continue
            if w not in encoded:
                a, b = windows[w]
                offs, vecs = self.encoder.encode(text[a:b])
                encoded[w] = ([(s + a, e + a) for s, e in offs], vecs)
            offs, vecs = encoded[w]
            inside = [
                v for (s, e), v in zip(offs, vecs, strict=True) if s >= span[0] and e <= span[1]
            ]
            out.append(_pool(inside, self.dimensions) if inside else self._alone(c.indexed_text))
        return out


@register("embedder", "late-chunking", params=LateChunkingParams,
          summary="embed the whole document, pool token vectors per chunk (offline hashing; TEI token embeddings as reference)")  # fmt: skip
def _late(p: LateChunkingParams, c: Container) -> LateChunkingEmbedder:
    return LateChunkingEmbedder(p)


# ================================================================ sparse vectors


class Bm25SparseParams(_Strict):
    k1: float = Field(1.2, gt=0)
    b: float = Field(0.75, ge=0, le=1)
    avg_length: float = Field(150, gt=0)  # typical chunk length in words (for length normalisation)


class Bm25Sparse:
    """BM25 as a sparse vector (Qdrant's recipe): a document's weight per word is the BM25 term
    frequency part; the IDF part is applied at search time by the index (`idf = True`), so it
    stays right as the collection grows. Offline, exact, no model."""

    idf = True

    def __init__(self, p: Bm25SparseParams) -> None:
        self.p = p
        self.model = f"bm25-hash-v1(k1={p.k1},b={p.b})"

    def embed_sparse_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        out = []
        for t in texts:
            tf = Counter(words(t))
            n = sum(tf.values())
            norm = self.p.k1 * (1 - self.p.b + self.p.b * n / self.p.avg_length)
            out.append({_hid(w): round(f * (self.p.k1 + 1) / (f + norm), 6) for w, f in tf.items()})
        return out

    def embed_sparse_query(self, text: str) -> SparseVector:
        return {_hid(w): 1.0 for w in set(words(text))}


@register("sparse_embedder", "bm25", params=Bm25SparseParams,
          summary="BM25 term weights as sparse vectors (IDF applied by the index); offline")  # fmt: skip
def _bm25_sparse(p: Bm25SparseParams, c: Container) -> Bm25Sparse:
    return Bm25Sparse(p)


class TeiSparseParams(_Strict):
    url: str = "http://host.docker.internal:8086"  # TEI serving a SPLADE model (naver/splade-v3, …)
    query_url: str | None = None  # a separate query encoder (SPLADE doc/query pairs), else the same
    model: str = "naver/splade-v3"  # recorded with every vector
    batch_size: int = Field(32, ge=1, le=512)
    timeout: float = 60.0


class TeiSparse:
    """SPLADE (Formal et al., 2021) through Text Embeddings Inference's /embed_sparse: a model
    writes a weight for each vocabulary word, INCLUDING related words the text doesn't contain
    ("car" also lights up "vehicle"), so sparse search gains some meaning while staying exact
    on names and codes. The model's weights already include importance: no IDF at search time."""

    idf = False

    def __init__(self, p: TeiSparseParams, client: httpx.Client | None = None,
                 query_client: httpx.Client | None = None) -> None:  # fmt: skip
        self.p, self.model = p, p.model
        self._http = client or httpx.Client(base_url=p.url.rstrip("/") + "/", timeout=p.timeout)
        self._q = query_client or (httpx.Client(base_url=p.query_url.rstrip("/") + "/", timeout=p.timeout)
                                   if p.query_url else self._http)  # fmt: skip

    @staticmethod
    def _call(http: httpx.Client, texts: list[str]) -> list[SparseVector]:
        r = http.post("embed_sparse", json={"inputs": texts, "truncate": True})
        r.raise_for_status()
        return [{int(x["index"]): float(x["value"]) for x in row} for row in r.json()]

    def embed_sparse_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        out: list[SparseVector] = []
        for i in range(0, len(texts), self.p.batch_size):
            out += self._call(self._http, list(texts[i : i + self.p.batch_size]))
        return out

    def embed_sparse_query(self, text: str) -> SparseVector:
        return self._call(self._q, [text])[0]


@register("sparse_embedder", "splade-tei", params=TeiSparseParams, status="mocked",
          summary="SPLADE learned sparse vectors from TEI's /embed_sparse (expands to related words)")  # fmt: skip
def _splade(p: TeiSparseParams, c: Container) -> TeiSparse:
    return TeiSparse(p)


def _sparse_encoder(c: Container) -> Any:
    return c.get("sparse_embedder") if c.has("sparse_embedder") else Bm25Sparse(Bm25SparseParams())


class SparseIndexParams(_Strict):
    idf: bool | None = None  # None: what the sparse embedder says (BM25 yes, SPLADE no)


class MemorySparseIndex:
    """Sparse-vector search in memory: score = sum over shared words of query weight x document
    weight (x IDF when the encoder needs it). A keyword_index, so `retriever: keyword` or
    `hybrid` uses it unchanged; scores are recorded as "sparse" for fusion."""

    def __init__(self, encoder: Any, idf: bool | None = None) -> None:
        self.encoder = encoder
        self.idf = bool(getattr(encoder, "idf", False)) if idf is None else idf
        self._docs: dict[str, tuple[Chunk, SparseVector]] = {}
        self._df: defaultdict[int, int] = defaultdict(int)
        self._lock = threading.Lock()

    def index(self, chunks: Sequence[Chunk]) -> None:
        vectors = self.encoder.embed_sparse_documents([c.indexed_text for c in chunks])
        with self._lock:
            for c, v in zip(chunks, vectors, strict=True):
                self._remove(c.id)
                self._docs[c.id] = (c, v)
                for t in v:
                    self._df[t] += 1

    def _remove(self, chunk_id: str) -> None:
        old = self._docs.pop(chunk_id, None)
        if old:
            for t in old[1]:
                self._df[t] -= 1

    def delete_document(self, document_uri: str) -> int:
        with self._lock:
            ids = [i for i, (c, _) in self._docs.items() if c.document_uri == document_uri]
            for i in ids:
                self._remove(i)
        return len(ids)

    def update_access(self, document_uri: str, access: Access) -> int:
        with self._lock:
            ids = [i for i, (c, _) in self._docs.items() if c.document_uri == document_uri]
            for i in ids:
                c, v = self._docs[i]
                self._docs[i] = (replace(c, access=access), v)
        return len(ids)

    def _rank(self, text: str, k: int, visible: Callable[[Chunk], bool]) -> list[ScoredChunk]:
        q = self.encoder.embed_sparse_query(text)
        n = len(self._docs) or 1
        hits = []
        for c, v in list(self._docs.values()):
            if not visible(c):
                continue
            score = 0.0
            for t, qw in q.items():
                if t in v:
                    idf = (
                        math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                        if self.idf
                        else 1.0
                    )
                    score += qw * v[t] * idf
            if score > 0:
                hits.append(ScoredChunk(c, score, {"sparse": score}))
        return sorted(hits, key=lambda h: -h.score)[:k]

    def search(self, text: str, principal: Principal, k: int,
               filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        wanted = _filters.matcher(filters)
        return self._rank(text, k, lambda c: c.access.allows(principal) and wanted(c))

    def search_all(self, text: str, k: int) -> list[ScoredChunk]:
        """Every tenant and group: for the erasure job only (Step 36), never for people."""
        return self._rank(text, k, lambda c: True)


@register("keyword_index", "sparse", params=SparseIndexParams,
          summary="sparse-vector search in memory with the sparse_embedder slot (BM25 offline by default, or SPLADE)")  # fmt: skip
def _sparse_index(p: SparseIndexParams, c: Container) -> MemorySparseIndex:
    return MemorySparseIndex(_sparse_encoder(c), p.idf)


class QdrantSparseParams(_Strict):
    url: str = "http://qdrant:6333"
    collection: str = "rag_chunks_sparse"
    api_key_env: str | None = "QDRANT_API_KEY"
    vector_name: str = "sparse"
    idf: bool | None = (
        None  # None: what the sparse embedder says; True sets Qdrant's modifier "idf"
    )
    create_if_missing: bool = False
    metadata_indexes: dict[str, Literal["keyword", "integer", "float", "bool", "datetime", "text"]] = Field(
        default_factory=dict)  # fmt: skip
    timeout: float = 30.0

    @model_validator(mode="after")
    def _name(self) -> QdrantSparseParams:
        if not self.vector_name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("vector_name: letters, digits, _ and - only")
        return self


class QdrantSparseIndex(QdrantStore):
    """Sparse vectors in Qdrant (named sparse vector, Qdrant applies the IDF itself with
    `modifier: idf`): BM25 or SPLADE search in the same engine and with the same tenant/ACL
    payload filter as the dense vectors. A keyword_index: `hybrid` fuses it with dense search."""

    def __init__(
        self, p: QdrantSparseParams, encoder: Any, client: httpx.Client | None = None
    ) -> None:
        super().__init__(QdrantParams(url=p.url, collection=p.collection, api_key_env=p.api_key_env,
                                      vector_name=p.vector_name, create_if_missing=p.create_if_missing,
                                      metadata_indexes=p.metadata_indexes, timeout=p.timeout), client)  # fmt: skip
        self.encoder = encoder
        self.idf = bool(getattr(encoder, "idf", False)) if p.idf is None else p.idf

    def collection_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {"modifier": "idf"} if self.idf else {}
        return {"vectors": {}, "sparse_vectors": {self.p.vector_name: cfg}}

    def _check_contract(self) -> None:
        info = self._call("GET", "")
        params = ((info or {}).get("config") or {}).get("params") or {}
        have = (params.get("sparse_vectors") or {}).get(self.p.vector_name)
        if have is None:
            raise RuntimeError(f"qdrant collection {self.p.collection!r} has no sparse vector "
                               f"named {self.p.vector_name!r}")  # fmt: skip
        if (have.get("modifier") == "idf") != self.idf:
            raise RuntimeError(f"qdrant collection {self.p.collection!r}: sparse vector modifier "
                               f"{have.get('modifier')!r} doesn't match idf={self.idf}")  # fmt: skip

    def index(self, chunks: Sequence[Chunk]) -> None:
        self._ensure()
        vectors = self.encoder.embed_sparse_documents([c.indexed_text for c in chunks])
        self._put([{"id": self.point_id(c.id), "payload": self.payload(c),
                    "vector": {self.p.vector_name: {"indices": list(v), "values": list(v.values())}}}
                   for c, v in zip(chunks, vectors, strict=True)])  # fmt: skip

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        raise TypeError(
            "qdrant-sparse is a keyword_index: it computes its own sparse vectors in index()"
        )

    def search(self, text: str, principal: Principal, k: int,  # type: ignore[override]
               filters: Mapping[str, object] | None = None) -> list[ScoredChunk]:  # fmt: skip
        flt = self.access_filter(principal, filters)
        q = self.encoder.embed_sparse_query(str(text))
        if not q:
            return []
        self._ensure()
        res = self._call("POST", "/points/query", {
            "query": {"indices": list(q), "values": list(q.values())}, "using": self.p.vector_name,
            "limit": k, "with_payload": True, "filter": flt})  # fmt: skip
        out = [ScoredChunk(self.chunk_of(pt["payload"]), float(pt["score"]), {"sparse": float(pt["score"])})
               for pt in res["points"] if float(pt["score"]) > 0]  # fmt: skip
        return sorted(out, key=lambda h: -h.score)


@register("keyword_index", "qdrant-sparse", params=QdrantSparseParams,
          summary="sparse vectors (BM25/SPLADE) in a Qdrant collection, IDF by Qdrant; payload-filtered by access and metadata")  # fmt: skip
def _qdrant_sparse(p: QdrantSparseParams, c: Container) -> QdrantSparseIndex:
    return QdrantSparseIndex(p, _sparse_encoder(c))


# ================================================================ multi-vector (ColBERT) reranking


def maxsim(query: Sequence[Sequence[float]], doc: Sequence[Sequence[float]]) -> float:
    """ColBERT's late interaction: for each query token, the similarity of the MOST similar
    document token; averaged over query tokens (vectors normalised: dot = cosine)."""
    if not query or not doc:
        return 0.0
    total = 0.0
    for q in query:
        total += max(sum(a * b for a, b in zip(q, d, strict=True)) for d in doc)
    return total / len(query)


class MaxSimParams(RerankParams):
    dimensions: int = Field(128, ge=16, le=1024)
    window: int = Field(2, ge=0, le=8)  # neighbours each token vector sees


class MaxSimReranker(_Reranker):
    """Multi-vector (ColBERT-style) reranking, offline: one vector PER TOKEN (hashed word plus its
    neighbours), scored by MaxSim. Finer than one vector per passage: every question word must
    find its match somewhere in the passage. The same scoring a real ColBERT model gives, with
    learned token vectors instead of hashed ones (`colbert`)."""

    def __init__(self, p: MaxSimParams) -> None:
        super().__init__(p)
        self.enc = HashTokenEncoder(p.dimensions, p.window, decay=0.5, global_weight=0.0)

    def _tokens(self, text: str) -> list[list[float]]:
        return [_normalise(v) for v in self.enc.encode(text)[1]]

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        q = self._tokens(query)
        return [maxsim(q, self._tokens(t)) for t in texts]


@register("reranker", "maxsim", params=MaxSimParams,
          summary="multi-vector late interaction (ColBERT MaxSim) over hashed token vectors; offline")  # fmt: skip
def _maxsim(p: MaxSimParams, c: Container) -> MaxSimReranker:
    return MaxSimReranker(p)


class ColbertParams(RerankParams):
    model: str = (
        "lightonai/GTE-ModernColBERT-v1"  # or colbert-ir/colbertv2.0, jinaai/jina-colbert-v2
    )
    device: str | None = None


class ColbertReranker(_Reranker):
    """A real ColBERT model in-process (PyLate): learned token vectors, MaxSim scoring. Reference:
    `pip install pylate` (pulls torch). At scale, store the token vectors in Qdrant's multivector
    field (comparator max_sim) and retrieve with them, instead of reranking."""

    def __init__(self, p: ColbertParams, model: Any = None) -> None:
        super().__init__(p)
        if model is None:
            from pylate import models  # optional: pip install pylate

            model = models.ColBERT(model_name_or_path=p.model, device=p.device)
        self._m = model

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        q = self._m.encode([query], is_query=True)[0]
        docs = self._m.encode(texts, is_query=False)
        return [maxsim(_rows(q), _rows(d)) for d in docs]


def _rows(m: Any) -> list[list[float]]:
    rows = m.tolist() if hasattr(m, "tolist") else m
    return [_normalise([float(x) for x in r]) for r in rows]


@register("reranker", "colbert", params=ColbertParams, status="reference", requires=("pylate",),
          summary="a ColBERT model in-process (PyLate): learned token vectors, MaxSim")  # fmt: skip
def _colbert(p: ColbertParams, c: Container) -> ColbertReranker:
    return ColbertReranker(p)
