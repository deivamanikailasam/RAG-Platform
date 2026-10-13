"""Incremental sync from a connector (extension 04): `rag sync [--watch] [--enqueue] [--dry-run]`.

One run: list what the connector holds now, and for each item

    new, or its version changed       -> ingest it (the pipeline still skips identical content)
    same version, other access rules  -> update its access in every store (no re-embedding)
    same version, same access         -> nothing (not even downloaded)
    gone since the last run           -> delete it from every store

Only items under the connector's own prefix are ever deleted, and only after a complete listing
(a listing that fails half way deletes nothing). `--watch` repeats the run every interval: a
polling watcher that works the same for a folder and a bucket. Event-driven ingestion (S3 event
notifications, a webhook) can call `rag enqueue` instead; both end in the same pipeline.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from rag_core.ingest import IngestionPipeline, IngestResult, _access_dict
from rag_core.registry import Container

log = logging.getLogger("rag_core.sync")


@dataclass
class SyncReport:
    listed: int = 0
    ingested: list[str] = field(default_factory=list)
    unchanged: int = 0
    reacl: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    enqueued: int = 0
    dry_run: bool = False

    def line(self) -> str:
        verb = "would " if self.dry_run else ""
        return (f"{self.listed} listed: {verb}ingest {len(self.ingested)}, {self.unchanged} unchanged, "
                f"{verb}re-permission {len(self.reacl)}, {verb}delete {len(self.deleted)}, "
                f"{len(self.failed)} failed" + (f", {self.enqueued} enqueued" if self.enqueued else ""))  # fmt: skip


def sync_once(container: Container, *, dry_run: bool = False, enqueue: bool = False,
              delete_missing: bool = True, max_items: int | None = None,
              pipeline: IngestionPipeline | None = None) -> SyncReport:  # fmt: skip
    """One incremental pass over the profile's `connector`."""
    from rag_core.components.queues import Job

    conn = container.get("connector")
    pipe = pipeline or IngestionPipeline(container)
    manifest = pipe.manifest
    if manifest is None:
        raise ValueError("rag sync needs a manifest (it remembers what each item's version was)")
    queue = container.get("queue") if enqueue else None
    report = SyncReport(dry_run=dry_run)
    seen: set[str] = set()
    done = 0
    for ref in conn.list():  # an exception here propagates: nothing is deleted on a partial list
        report.listed += 1
        seen.add(ref.uri)
        entry = manifest.get(ref.uri)
        access = _access_dict(ref.access)
        same_version = (entry is not None and entry.status == "indexed" and entry.pipeline_hash == pipe.hash
                        and entry.metadata.get("source_version") == ref.version)  # fmt: skip
        if same_version and entry is not None and entry.access == access:
            report.unchanged += 1
            continue
        if max_items is not None and done >= max_items:
            continue  # the next run picks it up: a rate limit for big first syncs
        done += 1
        if same_version:
            report.reacl.append(ref.uri)
            if not dry_run:
                pipe.update_access(ref.uri, ref.access)
            continue
        report.ingested.append(ref.uri)
        if dry_run:
            continue
        meta = {k: v for k, v in ref.metadata.items() if k != "bytes"} | {
            "source_version": ref.version
        }
        if queue is not None:
            queue.put(Job("upsert", ref.uri, access=access, metadata=meta))
            report.enqueued += 1
            continue
        try:
            source = conn.fetch(ref)
            r: IngestResult = pipe.ingest(replace(source, metadata=meta))
        except Exception as e:  # one bad item must not stop the sync
            report.failed.append((ref.uri, f"{type(e).__name__}: {e}"))
            continue
        if r.status == "failed":
            report.failed.append((ref.uri, r.detail))
        elif r.status == "unchanged" and (old := manifest.get(ref.uri)) is not None:
            # touched, not changed: remember the new version so the next run doesn't read it again
            manifest.put(replace(old, metadata={**old.metadata, "source_version": ref.version}))
    if delete_missing:
        prefix = getattr(conn, "prefix", None)
        for entry in manifest.all():
            uri = entry.source_uri
            if prefix and uri.startswith(prefix) and uri not in seen:
                report.deleted.append(uri)
                if dry_run:
                    continue
                if queue is not None:
                    queue.put(Job("delete", uri))
                    report.enqueued += 1
                else:
                    pipe.delete(uri)
    return report


def watch(container: Container, interval: float, *, rounds: int | None = None,
          on_report: Callable[[SyncReport], None] = lambda r: None,
          sleep: Callable[[float], None] = time.sleep, **kwargs: Any) -> None:  # fmt: skip
    """Sync, wait, sync again: forever (or `rounds` times, for tests). A failing round is logged
    and retried next interval; the pipeline (and its in-memory stores) is kept between rounds."""
    pipe = IngestionPipeline(container)
    n = 0
    while rounds is None or n < rounds:
        n += 1
        try:
            on_report(sync_once(container, pipeline=pipe, **kwargs))
        except Exception as e:
            log.error("sync round failed, retrying in %ss: %s", interval, e)
        if rounds is None or n < rounds:
            sleep(interval)


__all__ = ["SyncReport", "sync_once", "watch"]
