"""Connectors (extension 04): where sources come from, for incremental and continuous ingestion.

    connector: {use: filesystem, root: /data/handbook, patterns: ["**/*.md", "**/*.pdf"],
                access: {classification: internal, groups: [all-staff]}}
    connector: {use: s3, bucket: rag-raw-docs, prefix: policies/}

`rag sync` lists what the connector holds now, ingests what is new or changed (unchanged items
are skipped by version, then by content hash), and deletes from every store what disappeared.
`rag sync --watch` repeats that every `--interval` seconds; `--enqueue` hands the work to the
ingestion queue's workers instead (Step 31). Each run is incremental: a folder of 10,000 files
where three changed costs three ingestions.

`filesystem` and `s3` work today. `web`, `confluence`, `sharepoint` and `google-drive` are
reference interfaces: their settings are declared (so a profile validates and the catalogue
documents them) but building one fails with a clear "not configured" error until a project
implements it (docs/extensions/04-evaluation-loops-and-remaining-techniques.md shows how).
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core.registry import Container, register
from rag_core.types import Access, Source

MIME = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain",
        ".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf", ".csv": "text/csv",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}  # fmt: skip


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccessSpec(_Strict):
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    groups: list[str] = Field(default_factory=list)
    tenant: str = "default"

    def build(self) -> Access:
        return Access(self.classification, tuple(self.groups), self.tenant)


class AccessRule(AccessSpec):
    """Items under `prefix` (a path relative to the root, or a key prefix) get this access."""

    prefix: str


@dataclass(frozen=True)
class Ref:
    """One item a connector holds: its URI and a version that changes when its content does."""

    uri: str
    version: str
    access: Access = field(default_factory=Access)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ConnectorParams(_Strict):
    patterns: list[str] = Field(default_factory=lambda: ["**/*"])  # which items to ingest
    exclude: list[str] = Field(default_factory=lambda: ["**/.*", "**/~$*"])  # hidden, Office locks
    access: AccessSpec = Field(default_factory=AccessSpec)  # for every item ...
    rules: list[AccessRule] = Field(
        default_factory=list
    )  # ... unless the longest matching prefix says otherwise
    max_bytes: int = Field(50_000_000, ge=1)  # larger items are skipped (and reported)


def _match(rel: str, patterns: list[str]) -> bool:
    # "**/*.md" should also match "a.md" at the top level
    return any(fnmatch.fnmatch(rel, p) or (p.startswith("**/") and fnmatch.fnmatch(rel, p[3:]))
               for p in patterns)  # fmt: skip


def _access(rel: str, p: ConnectorParams) -> Access:
    rules = sorted((r for r in p.rules if rel.startswith(r.prefix)), key=lambda r: -len(r.prefix))
    return (rules[0] if rules else p.access).build()


# ================================================================ filesystem


class FilesystemParams(ConnectorParams):
    root: str
    follow_symlinks: bool = False  # a link out of the root could expose files nobody meant to share


class FilesystemConnector:
    """A folder (a mounted share, a synced drive, a git checkout). Version = mtime + size, so an
    unchanged file isn't even read."""

    def __init__(self, p: FilesystemParams) -> None:
        self.p, self.root = p, Path(p.root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"filesystem connector: {self.root} is not a directory")

    @property
    def prefix(self) -> str:
        return f"file://{self.root}/"

    def list(self) -> Iterator[Ref]:
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=self.p.follow_symlinks):
            dirnames.sort()
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.is_symlink() and not self.p.follow_symlinks:
                    continue
                rel = path.relative_to(self.root).as_posix()
                if not _match(rel, self.p.patterns) or _match(rel, self.p.exclude):
                    continue
                st = path.stat()
                yield Ref(f"file://{path}", f"{st.st_mtime_ns}-{st.st_size}", _access(rel, self.p),
                          {"path": rel, "bytes": st.st_size})  # fmt: skip

    def fetch(self, ref: Ref) -> Source:
        path = Path(ref.uri.removeprefix("file://"))
        if path.stat().st_size > self.p.max_bytes:
            raise ValueError(f"{ref.uri}: larger than max_bytes ({self.p.max_bytes})")
        return Source(ref.uri, path.read_bytes(), MIME.get(path.suffix.lower(), "application/octet-stream"),
                      ref.access, dict(ref.metadata))  # fmt: skip


@register("connector", "filesystem", params=FilesystemParams,
          summary="a folder: patterns, per-prefix access rules, mtime+size versions for incremental sync")  # fmt: skip
def _filesystem(p: FilesystemParams, c: Container) -> FilesystemConnector:
    return FilesystemConnector(p)


# ================================================================ S3


class S3Params(ConnectorParams):
    bucket: str
    prefix: str = ""
    endpoint_url: str | None = None  # MinIO / Ceph / LocalStack; None = AWS
    region: str | None = None


class S3Connector:
    """A bucket (or a prefix of one): Step 14's object store, or any S3-compatible service.
    Version = the object's ETag, so unchanged objects aren't downloaded. Credentials come from the
    usual AWS chain (workload identity, environment, profile), never from rag.yaml."""

    def __init__(self, p: S3Params, client: Any = None) -> None:
        self.p = p
        if client is None:
            import boto3

            client = boto3.client("s3", endpoint_url=p.endpoint_url, region_name=p.region)
        self.s3 = client

    @property
    def prefix(self) -> str:
        return f"s3://{self.p.bucket}/{self.p.prefix}"

    def list(self) -> Iterator[Ref]:
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.p.bucket, Prefix=self.p.prefix
        )
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                rel = key[len(self.p.prefix) :]
                if (
                    key.endswith("/")
                    or not _match(rel, self.p.patterns)
                    or _match(rel, self.p.exclude)
                ):
                    continue
                yield Ref(f"s3://{self.p.bucket}/{key}", str(obj.get("ETag", "")).strip('"'),
                          _access(rel, self.p), {"key": key, "bytes": obj.get("Size", 0)})  # fmt: skip

    def fetch(self, ref: Ref) -> Source:
        if int(ref.metadata.get("bytes", 0)) > self.p.max_bytes:
            raise ValueError(f"{ref.uri}: larger than max_bytes ({self.p.max_bytes})")
        key = ref.uri.removeprefix(f"s3://{self.p.bucket}/")
        data = self.s3.get_object(Bucket=self.p.bucket, Key=key)["Body"].read()
        return Source(ref.uri, data, MIME.get(Path(key).suffix.lower(), "application/octet-stream"),
                      ref.access, dict(ref.metadata))  # fmt: skip


@register("connector", "s3", params=S3Params, status="mocked", requires=("s3",),
          summary="an S3 bucket/prefix (AWS, MinIO, …): ETag versions for incremental sync")  # fmt: skip
def _s3(p: S3Params, c: Container) -> S3Connector:
    return S3Connector(p)


# ================================================================ reference interfaces


class NotConfiguredError(RuntimeError):
    """A reference connector: its interface is documented, its implementation is the project's."""


class WebParams(ConnectorParams):
    start_urls: list[str] = Field(min_length=1)
    allowed_domains: list[str] = Field(default_factory=list)
    max_pages: int = Field(1000, ge=1)
    max_depth: int = Field(3, ge=0)
    respect_robots_txt: bool = True
    requests_per_second: float = Field(1.0, gt=0)


class ConfluenceParams(ConnectorParams):
    base_url: str
    spaces: list[str] = Field(min_length=1)
    token_file: str  # a Confluence API token written by OpenBao Agent; never inline
    include_attachments: bool = False
    map_permissions: bool = True  # page restrictions -> groups (required before `internal`)


class SharePointParams(ConnectorParams):
    tenant_id: str
    site_url: str
    drives: list[str] = Field(default_factory=lambda: ["Documents"])
    client_id: str
    certificate_file: str  # app-only auth with a certificate (Microsoft Graph)
    map_permissions: bool = True


class GoogleDriveParams(ConnectorParams):
    folder_ids: list[str] = Field(min_length=1)
    service_account_file: str
    export_google_docs_as: Literal["text/markdown", "application/pdf", "text/html"] = (
        "text/markdown"
    )
    map_permissions: bool = True


_REFERENCE: dict[str, tuple[type[ConnectorParams], str]] = {
    "web": (WebParams, "a web crawler: start URLs, domain allow-list, robots.txt, depth/page limits, polite rate"),
    "confluence": (ConfluenceParams, "Confluence spaces: pages (and attachments), restrictions mapped to groups"),
    "sharepoint": (SharePointParams, "SharePoint / OneDrive via Microsoft Graph: drives, delta links, permissions"),
    "google-drive": (GoogleDriveParams, "Google Drive folders: Docs exported, changes API, sharing mapped to groups"),
}  # fmt: skip


def _reference(name: str) -> Any:
    def factory(p: ConnectorParams, c: Container) -> Any:
        raise NotConfiguredError(
            f"the {name!r} connector is a reference interface and is not configured in this platform: "
            "implement list()/fetch() in your project (register it under your own name), or export "
            "the content to a folder or bucket and use `filesystem` / `s3`. See "
            "docs/extensions/04-evaluation-loops-and-remaining-techniques.md#12-connectors-and-rag-sync"
        )

    return factory


for _name, (_params, _summary) in _REFERENCE.items():
    register("connector", _name, params=_params, status="reference", summary=_summary)(
        _reference(_name)
    )


__all__ = [
    "AccessRule",
    "AccessSpec",
    "FilesystemConnector",
    "NotConfiguredError",
    "Ref",
    "S3Connector",
]
