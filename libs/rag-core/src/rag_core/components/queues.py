"""Work queues and ingest manifests (Step 31).

Ingestion is slow and fails sometimes (a corrupt PDF, the embedder restarting), so it runs as a
queue of jobs: the API or a scheduler adds jobs, workers take them, failed jobs are retried and
finally parked for a person to look at. The manifest remembers what was ingested, with which
pipeline, so unchanged sources are skipped.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core.registry import Container, register


@dataclass(frozen=True)
class Job:
    op: Literal["upsert", "delete"]
    uri: str  # file://… or s3://bucket/key (the original, Step 14)
    access: dict[str, Any] = field(default_factory=dict)  # classification, groups, tenant
    metadata: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    id: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(raw: str | bytes) -> Job:
        return Job(**json.loads(raw))


class MemoryQueue:
    """In-process queue for dev and tests. Same semantics as the Valkey one: get → ack or fail."""

    def __init__(self, max_attempts: int = 3) -> None:
        self._q: deque[Job] = deque()
        self._pending: dict[str, Job] = {}
        self.dead: list[tuple[Job, str]] = []
        self.max_attempts = max_attempts
        self._n = 0
        self._lock = threading.Lock()

    def put(self, job: Job) -> str:
        with self._lock:
            self._n += 1
            job = Job(**{**asdict(job), "id": job.id or str(self._n)})
            self._q.append(job)
            return job.id

    def get(self, block_ms: int = 0) -> Job | None:
        with self._lock:
            if not self._q:
                return None
            job = self._q.popleft()
            self._pending[job.id] = job
            return job

    def ack(self, job: Job) -> None:
        with self._lock:
            self._pending.pop(job.id, None)

    def fail(self, job: Job, error: str) -> None:
        with self._lock:
            self._pending.pop(job.id, None)
            retry = Job(**{**asdict(job), "attempts": job.attempts + 1})
            if retry.attempts >= self.max_attempts:
                self.dead.append((retry, error))
            else:
                self._q.append(retry)

    def size(self) -> int:
        return len(self._q)


class QueueParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = Field(3, ge=1)


@register(
    "queue",
    "memory",
    params=QueueParams,
    summary="in-process job queue with retries and a dead-letter list",
)
def _memq(p: QueueParams, c: Container) -> MemoryQueue:
    return MemoryQueue(p.max_attempts)


class ValkeyParams(QueueParams):
    url_env: str = "VALKEY_URL"  # redis://rag_app:…@valkey:6379/0 (Step 15's ACL user)
    url_file: str | None = (
        None  # or read it from a file the OpenBao agent writes: /run/bao/valkey_url
    )
    stream: str = "rag:ingest"
    group: str = "ingest-workers"
    consumer: str = Field(default_factory=lambda: os.environ.get("HOSTNAME", "worker"))
    claim_idle_ms: int = Field(
        300_000, ge=1000
    )  # a job a crashed worker held this long goes to another


class ValkeyStreamQueue:
    """Valkey Streams with a consumer group (Step 15): durable, several workers share the work,
    every job is acknowledged, and jobs held by a crashed worker are claimed by another."""

    def __init__(self, p: ValkeyParams, client: Any = None) -> None:
        if client is None:
            import redis

            url = Path(p.url_file).read_text().strip() if p.url_file else os.environ[p.url_env]
            client = redis.Redis.from_url(url, decode_responses=True)
        self.r, self.p = client, p
        self.dead_stream = p.stream + ":dead"
        try:
            self.r.xgroup_create(p.stream, p.group, id="0", mkstream=True)
        except Exception as e:  # BUSYGROUP etc.
            if "BUSYGROUP" not in str(e):
                raise

    def put(self, job: Job) -> str:
        return str(self.r.xadd(self.p.stream, {"job": job.to_json()}))

    def get(self, block_ms: int = 1000) -> Job | None:
        # first: jobs another worker took but never finished
        claimed = self.r.xautoclaim(
            self.p.stream, self.p.group, self.p.consumer, self.p.claim_idle_ms, "0-0", count=1
        )
        entries = claimed[1] if claimed and len(claimed) > 1 else []
        if not entries:
            got = self.r.xreadgroup(
                self.p.group, self.p.consumer, {self.p.stream: ">"}, count=1, block=block_ms or None
            )
            entries = got[0][1] if got else []
        if not entries:
            return None
        msg_id, fields = entries[0]
        job = Job.from_json(fields["job"])
        return Job(**{**asdict(job), "id": msg_id})

    def ack(self, job: Job) -> None:
        self.r.xack(self.p.stream, self.p.group, job.id)
        self.r.xdel(self.p.stream, job.id)

    def fail(self, job: Job, error: str) -> None:
        retry = Job(**{**asdict(job), "attempts": job.attempts + 1, "id": ""})
        if retry.attempts >= self.p.max_attempts:
            self.r.xadd(self.dead_stream, {"job": retry.to_json(), "error": error[:2000]})
        else:
            self.r.xadd(self.p.stream, {"job": retry.to_json()})
        self.ack(job)

    def size(self) -> int:
        return int(self.r.xlen(self.p.stream))


@register(
    "queue",
    "valkey-streams",
    params=ValkeyParams,
    status="mocked",
    requires=("valkey",),
    summary="Valkey Streams consumer group: durable, shared by workers, crash-safe (Step 15)",
)
def _valkeyq(p: ValkeyParams, c: Container) -> ValkeyStreamQueue:
    return ValkeyStreamQueue(p)


# ---------------------------------------------------------------- manifests


@dataclass(frozen=True)
class ManifestEntry:
    source_uri: str
    content_sha256: str
    pipeline_hash: str
    chunk_count: int
    status: str
    detail: str = ""
    updated_at: float = field(default_factory=time.time)
    # Step 36: what the source was ingested WITH, so retention, erasure and a re-index can rebuild
    # it from the original without asking the source system again
    access: dict[str, Any] = field(default_factory=dict)  # classification, groups, tenant
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryManifest:
    def __init__(self) -> None:
        self.rows: dict[str, ManifestEntry] = {}

    def get(self, uri: str) -> ManifestEntry | None:
        return self.rows.get(uri)

    def put(self, entry: ManifestEntry) -> None:
        self.rows[entry.source_uri] = entry

    def delete(self, uri: str) -> None:
        self.rows.pop(uri, None)

    def all(self) -> list[ManifestEntry]:
        return list(self.rows.values())


@register("manifest", "memory", summary="what was ingested, in memory (dev, tests)")
def _memman(p: BaseModel, c: Container) -> MemoryManifest:
    return MemoryManifest()
