"""Extension 04, ingestion: the Valkey embedding cache, batching and rate limits, the
connectors and incremental `rag sync`. Offline: fakeredis and moto stand in for Valkey and S3."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import boto3
import fakeredis
import pytest
import yaml
from moto import mock_aws

from rag_core import config as cfg
from rag_core import evaluate as ev
from rag_core import sync
from rag_core.cli import main
from rag_core.components.basics import HashingEmbedder
from rag_core.components.connectors import (
    AccessRule,
    FilesystemConnector,
    FilesystemParams,
    S3Connector,
    S3Params,
)
from rag_core.components.enrichment import (
    BatchedEmbedder,
    BatchedParams,
    CachedEmbedder,
    ValkeyVectors,
)
from rag_core.registry import ComponentError, Container
from rag_core.types import Access, Answer, Chunk, Citation, Principal, Query, ScoredChunk

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "examples/eval/handbook.yaml"
STAFF = Principal("ann", ("all-staff",), ("public", "internal"))
EXEC = Principal("eve", ("executives",), ("public", "internal", "restricted"))


def offline(**slots: Any) -> dict[str, Any]:
    config = cfg.resolve(yaml.safe_load((ROOT / "rag.yaml").read_text()), "offline", env={})
    config.update(slots)
    return {k: v for k, v in config.items() if v != "none"}


def handbook(**slots: Any) -> Container:
    c = Container(offline(**slots), "test")
    ev.ingest_corpus(c, ev.load_dataset(DATASET), DATASET.parent)
    return c


def chunk(text: str, cid: str = "c1", uri: str = "doc://a", **md: Any) -> ScoredChunk:
    return ScoredChunk(
        Chunk(cid, uri, 0, text, len(text.split()), Access("public"), metadata=md), 1.0
    )


Q = Query("How many days of annual leave do staff get?", STAFF)
SOURCES = [
    chunk("Leave policy. Full-time staff get 25 days of annual leave per year. Book it in the portal.",
          "c1", "doc://leave", title="Leave policy", section="Annual leave"),
    chunk("Parental leave is 18 weeks at full pay for the primary carer.", "c2", "doc://parental",
          title="Parental leave"),
]  # fmt: skip
ANSWER = Answer("Full-time staff get 25 days of annual leave per year [doc 1].",
                (Citation(1, "c1", "doc://leave", "Leave policy"),))  # fmt: skip


# ================================================================ embeddings: shared cache, batching


def test_valkey_embedding_cache_is_shared_between_replicas() -> None:
    r = fakeredis.FakeRedis(decode_responses=True)
    inner = HashingEmbedder(64)
    calls: list[int] = []
    orig = inner.embed_documents

    def counting(texts: Sequence[str]) -> list[list[float]]:
        calls.append(len(texts))
        return orig(texts)

    inner.embed_documents = counting  # type: ignore[method-assign]
    a = CachedEmbedder(inner, 100, ValkeyVectors(r, "t", 60))
    v1 = a.embed_documents(["one", "two"])
    b = CachedEmbedder(inner, 100, ValkeyVectors(r, "t", 60))  # another pod, empty LRU
    v2 = b.embed_documents(["two", "one", "three"])
    assert calls == [2, 1]
    assert b.shared_hits == 2
    assert v2[0] == pytest.approx(v1[1], abs=1e-6)
    assert 0 < r.ttl(f"t:{a._key('d', 'one')}") <= 60
    q = b.embed_query("q")
    assert CachedEmbedder(inner, 100, ValkeyVectors(r, "t", 60)).embed_query("q") == pytest.approx(
        q, abs=1e-6
    )


def test_valkey_cache_down_never_fails_embedding() -> None:
    class Down:
        def mget(self, keys: Any) -> Any:
            raise ConnectionError("valkey down")

        def pipeline(self) -> Any:
            raise ConnectionError("valkey down")

    e = CachedEmbedder(HashingEmbedder(32), 10, ValkeyVectors(Down(), "t", 60))
    assert len(e.embed_documents(["a"])[0]) == 32


def test_cached_embedder_from_config_with_valkey(monkeypatch: pytest.MonkeyPatch) -> None:
    import rag_core.components.conversation as conv

    monkeypatch.setattr(conv, "_valkey", lambda env, f: fakeredis.FakeRedis(decode_responses=True))
    c = Container(
        {
            "embedder": {
                "use": "cached",
                "store": "valkey",
                "inner": {"use": "hashing", "dimensions": 32},
            }
        }
    )
    assert isinstance(c.get("embedder").shared, ValkeyVectors)


def test_batched_embedder_batches_paces_and_retries() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    inner = HashingEmbedder(16)
    sizes: list[int] = []
    fails = [1]

    def flaky(texts: Sequence[str]) -> list[list[float]]:
        if fails[0]:
            fails[0] -= 1
            raise TimeoutError("429")
        sizes.append(len(texts))
        return HashingEmbedder(16).embed_documents(texts)

    inner.embed_documents = flaky  # type: ignore[method-assign]
    b = BatchedEmbedder(inner, BatchedParams(inner={"use": "hashing"}, batch_size=2, requests_per_second=2,
                                             backoff_seconds=1.0), clock=lambda: now[0], sleep=sleep)  # fmt: skip
    out = b.embed_documents(["a", "b", "c", "d", "e"])
    assert len(out) == 5
    assert sizes == [2, 2, 1]
    assert b.retries == 1
    assert 1.0 in slept  # the backoff
    assert 0.5 in slept
    assert now[0] >= 1.5

    def invalid(texts: Sequence[str]) -> list[list[float]]:
        raise ValueError("bad input")

    inner.embed_documents = invalid  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="bad input"):
        BatchedEmbedder(
            inner, BatchedParams(inner={"use": "hashing"}), sleep=sleep
        ).embed_documents(["x"])
    built = Container(
        {"embedder": {"use": "batched", "inner": {"use": "hashing", "dimensions": 16}}}
    ).get("embedder")
    assert built.dimensions == 16
    assert len(built.embed_query("x")) == 16


# ================================================================ connectors and sync


def _folder(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    (root / "hr").mkdir(parents=True)
    (root / "it").mkdir()
    (root / "hr" / "leave.md").write_text(
        "# Leave\n\nStaff get 25 days of annual leave per year.\n"
    )
    (root / "it" / "vpn.md").write_text(
        "# VPN\n\nError E-4021 means your device certificate expired.\n"
    )
    (root / ".hidden.md").write_text("# Secret\n\nnot for indexing\n")
    (root / "notes.txt").write_text("plain notes about the canteen menu\n")
    return root


def _sync_profile(root: Path, **conn: Any) -> Container:
    return Container(offline(connector={"use": "filesystem", "root": str(root), "patterns": ["**/*.md"],
                                        "access": {"groups": ["all-staff"]},
                                        "rules": [{"prefix": "hr/", "classification": "confidential", "groups": ["hr"]}],
                                        **conn}), "sync")  # fmt: skip


def test_filesystem_connector_lists_with_patterns_and_access_rules(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    conn = FilesystemConnector(FilesystemParams(root=str(root), patterns=["**/*.md"],
                                                rules=[AccessRule(prefix="hr/", groups=["hr"])]))  # fmt: skip
    refs = {r.metadata["path"]: r for r in conn.list()}
    assert set(refs) == {"hr/leave.md", "it/vpn.md"}  # hidden file and .txt excluded
    assert refs["hr/leave.md"].access.groups == ("hr",)
    assert refs["it/vpn.md"].access.groups == ()
    src = conn.fetch(refs["it/vpn.md"])
    assert src.mime_type == "text/markdown"
    assert b"E-4021" in src.data
    with pytest.raises(ValueError, match="not a directory"):
        FilesystemConnector(FilesystemParams(root=str(root / "missing")))


def test_sync_is_incremental_and_deletes_what_disappeared(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    c = _sync_profile(root)
    from rag_core.ingest import IngestionPipeline

    pipe = IngestionPipeline(c)
    first = sync.sync_once(c, pipeline=pipe)
    assert len(first.ingested) == 2
    assert not first.failed
    assert first.unchanged == 0
    again = sync.sync_once(c, pipeline=pipe)
    assert again.unchanged == 2
    assert not again.ingested
    # an edit, a touch, a new file and a deleted file
    (root / "it" / "vpn.md").write_text(
        "# VPN\n\nError E-4021 means the certificate expired. Renew it.\n"
    )
    leave = root / "hr" / "leave.md"
    os.utime(leave, (time.time() + 5, time.time() + 5))  # touched, content unchanged
    (root / "it" / "laptop.md").write_text("# Laptop\n\nReport a lost laptop within 24 hours.\n")
    third = sync.sync_once(c, pipeline=pipe, dry_run=True)
    assert third.dry_run
    assert len(third.ingested) == 3
    third = sync.sync_once(c, pipeline=pipe)
    assert len(third.ingested) == 3
    assert not third.deleted
    assert sync.sync_once(c, pipeline=pipe).unchanged == 3  # the touched file's version remembered
    (root / "it" / "laptop.md").unlink()
    gone = sync.sync_once(c, pipeline=pipe)
    assert [u.rsplit("/", 1)[-1] for u in gone.deleted] == ["laptop.md"]
    assert pipe.manifest is not None
    assert len(pipe.manifest.all()) == 2
    # the access rules changed: permissions updated in place, nothing re-embedded
    c2 = _sync_profile(root, rules=[])
    c2._built.update(
        {k: c._built[k] for k in ("vector_store", "keyword_index", "manifest", "embedder")}
    )
    pipe2 = IngestionPipeline(c2)
    reacl = sync.sync_once(c2, pipeline=pipe2)
    assert [u.rsplit("/", 1)[-1] for u in reacl.reacl] == ["leave.md"]
    assert not reacl.ingested
    hits = c2.get("keyword_index").search("annual leave", STAFF, 5)
    assert hits
    assert hits[0].chunk.document_uri.endswith("leave.md")


def test_sync_enqueue_max_items_and_watch(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    c = _sync_profile(root)
    r = sync.sync_once(c, enqueue=True, max_items=1)
    assert r.enqueued == 1
    assert len(r.ingested) == 1
    assert c.get("queue").size() == 1
    reports: list[sync.SyncReport] = []
    sync.watch(_sync_profile(root), 0.01, rounds=2, on_report=reports.append, sleep=lambda s: None)
    assert len(reports) == 2
    assert len(reports[0].ingested) == 2
    assert reports[1].unchanged == 2


def test_sync_needs_a_manifest_and_a_failed_listing_deletes_nothing(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    c = Container({k: v for k, v in _sync_profile(root).config.items() if k != "manifest"}, "x")
    with pytest.raises(ValueError, match="manifest"):
        sync.sync_once(c)
    c = _sync_profile(root)
    sync.sync_once(c)

    class Broken:
        prefix = f"file://{root.resolve()}/"

        def list(self) -> Any:
            yield from []
            raise OSError("share unmounted")

    c._built["connector"] = Broken()
    with pytest.raises(OSError, match="unmounted"):
        sync.sync_once(c)
    assert len(c.get("manifest").all()) == 2  # nothing deleted


@mock_aws
def test_s3_connector_lists_by_etag_and_syncs() -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="rag-raw-docs")
    s3.put_object(
        Bucket="rag-raw-docs",
        Key="policies/leave.md",
        Body=b"# Leave\n\nStaff get 25 days of annual leave.\n",
    )
    s3.put_object(Bucket="rag-raw-docs", Key="policies/img.png", Body=b"\x89PNG")
    s3.put_object(Bucket="rag-raw-docs", Key="other/x.md", Body=b"# X\n\nnot in the prefix\n")
    conn = S3Connector(
        S3Params(bucket="rag-raw-docs", prefix="policies/", patterns=["**/*.md"]), client=s3
    )
    refs = list(conn.list())
    assert [r.uri for r in refs] == ["s3://rag-raw-docs/policies/leave.md"]
    assert refs[0].version
    assert conn.fetch(refs[0]).data.startswith(b"# Leave")
    c = Container(
        offline(
            connector={
                "use": "s3",
                "bucket": "rag-raw-docs",
                "prefix": "policies/",
                "patterns": ["**/*.md"],
            }
        ),
        "s3",
    )
    c._built["connector"] = conn
    assert len(sync.sync_once(c).ingested) == 1
    assert sync.sync_once(c).unchanged == 1


def test_reference_connectors_fail_clearly_but_validate() -> None:
    conf = {"connector": {"use": "confluence", "base_url": "https://wiki.example.com", "spaces": ["HR"],
                          "token_file": "/run/bao/confluence"}}  # fmt: skip
    assert Container(conf).validate() == []
    with pytest.raises(ComponentError, match="reference interface and is not configured"):
        Container(conf).get("connector")
    for name, extra in (("web", {"start_urls": ["https://intranet"]}), ("google-drive", {"folder_ids": ["f"], "service_account_file": "/x"}),
                        ("sharepoint", {"tenant_id": "t", "site_url": "https://s", "client_id": "c", "certificate_file": "/c"})):  # fmt: skip
        with pytest.raises(ComponentError, match="not configured"):
            Container({"connector": {"use": name, **extra}}).get("connector")


def test_rag_sync_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _folder(tmp_path)
    rag_yaml = tmp_path / "rag.yaml"
    rag_yaml.write_text(yaml.safe_dump({"version": 1, "include": {"platform": "rag-core:platform.yaml"},
                                        "profiles": {"mine": {"extends": "platform/offline",
                                                              "connector": {"use": "filesystem", "root": str(root),
                                                                            "patterns": ["**/*.md"]}}}}))  # fmt: skip
    assert main(["sync", "--file", str(rag_yaml), "--profile", "mine", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would ingest 2" in out
    assert "? file://" in out
    assert main(["sync", "--file", str(rag_yaml), "--profile", "mine", "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip())["listed"] == 2
