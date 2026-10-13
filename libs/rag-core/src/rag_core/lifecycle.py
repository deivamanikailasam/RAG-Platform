"""The data lifecycle (Step 36): retention, erasure, access changes and re-indexing.

    rag retention --rules retention.yaml [--apply]        delete what has outlived its rule
    rag erase-source s3://bucket/key [--apply]            a document gone from everywhere, all versions
                     [--rules retention.yaml --override-hold "reason"]   (Step 37: legal holds)
    rag erase-subject --email jane@… [--apply]            a person's conversations, cached answers, and
                                                          which documents mention them
    rag reacl <uri> --group hr --classification …         new permissions, everywhere, now
    rag reindex --from local --to local-v2                rebuild into a new collection, then compare

Everything defaults to a DRY RUN that reports what would happen. `--apply` does it. Every action
returns a report that the caller records (rag-api's audit log, or the job's output).
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from rag_core.ingest import IngestionPipeline, load_source
from rag_core.registry import ComponentError, Container
from rag_core.types import Access, Principal

DAY = 86_400.0


# ================================================================ retention


class RetentionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match: str  # a glob on the source URI: "s3://rag-raw-docs/tickets/*"
    keep_days: int = Field(ge=1)
    reason: str = ""  # the record or policy that sets it, e.g. "Records Authority class 12.3"


class LegalHold(BaseModel):
    """Step 37: while a dispute, investigation or audit is open, matching sources must not be
    deleted by retention, and erasure needs an explicit, recorded override."""

    model_config = ConfigDict(extra="forbid")
    match: str  # glob on the source URI
    matter: str  # the case or request it belongs to, e.g. "LIT-2026-014"
    until: dt.date | None = None  # None: until someone removes it (the usual case)

    def active(self, today: dt.date) -> bool:
        return self.until is None or today <= self.until


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    rules: list[RetentionRule]
    default_keep_days: int | None = None  # None: sources no rule matches are kept
    legal_holds: list[LegalHold] = []

    def hold_for(self, uri: str, today: dt.date | None = None) -> LegalHold | None:
        today = today or dt.datetime.now(dt.UTC).date()
        return next(
            (h for h in self.legal_holds if h.active(today) and fnmatch.fnmatch(uri, h.match)), None
        )


def load_retention(path: Path) -> RetentionPolicy:
    try:
        return RetentionPolicy.model_validate(yaml.safe_load(path.read_text()))
    except Exception as e:
        raise ComponentError(f"{path}: {e}") from None


@dataclass
class LifecycleReport:
    action: str
    applied: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    held: list[dict[str, Any]] = field(default_factory=list)  # Step 37: kept by a legal hold

    def summary(self) -> str:
        verb = "done" if self.applied else "would be done (dry run; add --apply)"
        kept = f", {len(self.held)} kept by a legal hold" if self.held else ""
        return f"{self.action}: {len(self.items)} item(s) {verb}{kept}"


def apply_retention(pipeline: IngestionPipeline, policy: RetentionPolicy, *, apply: bool = False,
                    now: float | None = None) -> LifecycleReport:  # fmt: skip
    """The first matching rule decides. Age is measured from the last time the source was indexed
    (the manifest's updated_at): a document that keeps changing at the source is kept."""
    if pipeline.manifest is None:
        raise ComponentError("retention needs a manifest (it lists what was ingested and when)")
    now = now or time.time()
    report = LifecycleReport("retention", apply)
    for entry in pipeline.manifest.all():
        rule = next((r for r in policy.rules if fnmatch.fnmatch(entry.source_uri, r.match)), None)
        keep = rule.keep_days if rule else policy.default_keep_days
        if keep is None:
            continue
        age_days = (now - entry.updated_at) / DAY
        if age_days > keep:
            hold = policy.hold_for(entry.source_uri, dt.datetime.fromtimestamp(now, dt.UTC).date())
            if hold is not None:  # a legal hold wins over every retention rule
                report.held.append(
                    {"uri": entry.source_uri, "matter": hold.matter, "age_days": round(age_days, 1)}
                )
                continue
            item = {"uri": entry.source_uri, "age_days": round(age_days, 1), "keep_days": keep,
                    "rule": rule.match if rule else "default", "reason": rule.reason if rule else ""}  # fmt: skip
            if apply:
                item["chunks_deleted"] = pipeline.delete(entry.source_uri).chunks
            report.items.append(item)
    return report


# ================================================================ erasure


def erase_source(
    pipeline: IngestionPipeline,
    uri: str,
    *,
    apply: bool = False,
    s3_client: Any = None,
    policy: RetentionPolicy | None = None,
    override_hold: str = "",
) -> LifecycleReport:
    """A document must be forgotten: every store, the graph, the manifest, the cache, and for an
    s3:// original EVERY object version (Step 14 keeps versions, so deleting the latest isn't enough).
    Under a legal hold (Step 37) it refuses unless `override_hold` gives the reason (legal decides
    between an erasure request and a hold; the reason goes into the report and the audit trail)."""
    report = LifecycleReport("erase-source", apply)
    item: dict[str, Any] = {"uri": uri}
    hold = policy.hold_for(uri) if policy else None
    if hold is not None:
        if not override_hold:
            raise ComponentError(
                f'{uri} is under legal hold {hold.matter}: erasing needs --override-hold "reason"'
            )
        item["legal_hold_overridden"] = {"matter": hold.matter, "reason": override_hold}
    if uri.startswith("s3://"):
        bucket, _, key = uri[len("s3://") :].partition("/")
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        versions = []
        for page in s3_client.get_paginator("list_object_versions").paginate(
            Bucket=bucket, Prefix=key
        ):
            versions += [(v["Key"], v["VersionId"]) for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
                         if v["Key"] == key]  # fmt: skip
        item["object_versions"] = len(versions)
        if apply:
            for k, vid in versions:
                s3_client.delete_object(Bucket=bucket, Key=k, VersionId=vid)
    if apply:
        item["chunks_deleted"] = pipeline.delete(uri).chunks
    report.items.append(item)
    return report


def erase_subject(container: Container, subject: Principal | None, identifiers: list[str], *,
                  apply: bool = False) -> LifecycleReport:  # fmt: skip
    """A person asks to be forgotten. What the platform can do by itself:
       - their conversations (memory) are deleted, if `subject` is given
       - every cached answer is invalidated (an answer may quote them)
       - documents that mention them (by the exact text, or by the pseudonym Step 31 gave it) are
         LISTED: deleting or correcting a source document is the document owner's decision.
    The audit log keeps pseudonymous ids by design (Step 23); that is a documented exception."""
    report = LifecycleReport("erase-subject", apply)
    if subject is not None and container.has("memory"):
        memory = container.get("memory")
        n = memory.forget_subject(subject) if apply else memory.count_subject(subject)
        report.items.append({"what": "conversations", "subject": subject.subject, "sessions": n})
    if container.has("cache"):
        if apply:
            container.get("cache").invalidate()
        report.items.append({"what": "cached answers", "action": "all invalidated (new epoch)"})
    needles = [i for i in identifiers if i.strip()]
    if container.has("pii"):  # the pseudonyms ingestion would have written for these identifiers
        pii = container.get("pii")
        # Only a PSEUDONYM identifies someone: a mask ("[EMAIL]") or a removal is the same for
        # everyone, and searching for it would list every document that had any email in it
        if getattr(pii, "strategy", "pseudonymise") == "pseudonymise":
            for ident in identifiers:
                redacted, found = pii.redact(ident)
                if found and redacted != ident and redacted.strip():
                    needles.append(redacted.strip())
    if container.has("keyword_index"):
        index = container.get("keyword_index")
        everyone = Principal(
            "erasure-job", ("*",), ("public", "internal", "confidential", "restricted"), "*"
        )
        docs: set[str] = set()
        for n in needles:
            for h in _search_all(index, n, everyone):
                if n.lower() in h.chunk.text.lower():
                    docs.add(h.chunk.document_uri)
        report.items.append({"what": "documents mentioning the person", "documents": sorted(docs),
                             "action": "listed for their owners (not deleted automatically)"})  # fmt: skip
    return report


def _search_all(index: Any, text: str, who: Principal) -> list[Any]:
    """The erasure job must see every tenant and group: stores that support it accept '*'."""
    search_all = getattr(index, "search_all", None)
    return list(search_all(text, 200)) if search_all else list(index.search(text, who, 200))


# ================================================================ access changes


def change_access(pipeline: IngestionPipeline, uri: str, access: Access) -> LifecycleReport:
    n = pipeline.update_access(uri, access)
    return LifecycleReport("change-access", True, [{"uri": uri, "chunks": n, "access": {
        "classification": access.classification, "groups": list(access.groups), "tenant": access.tenant}}])  # fmt: skip


# ================================================================ re-indexing (blue/green)


def reindex(
    source: Container, target: Container, *, apply: bool = False, s3_client: Any = None
) -> LifecycleReport:
    """Rebuild everything the source collection holds into the target (new embedder, new
    chunker, new collection), from the ORIGINALS, with the access each source had. Then compare:
    `rag eval-search … --no-ingest` on both, and switch the profile's collection in a pull request."""
    src = IngestionPipeline(source)
    if src.manifest is None:
        raise ComponentError(
            "the source profile needs a manifest: it is the list of what to rebuild"
        )
    dst = IngestionPipeline(target) if apply else None
    report = LifecycleReport("reindex", apply)
    for entry in src.manifest.all():
        if entry.status != "indexed":
            continue
        item: dict[str, Any] = {"uri": entry.source_uri, "old_chunks": entry.chunk_count}
        if dst is not None:
            a = entry.access or {}
            access = Access(
                a.get("classification", "internal"),
                tuple(a.get("groups", ())),
                a.get("tenant", "default"),
            )
            try:
                r = dst.ingest(
                    load_source(entry.source_uri, access, entry.metadata, s3_client=s3_client),
                    force=True,
                )
                item |= {"new_chunks": r.chunks, "status": r.status}
            except (OSError, ValueError) as e:
                item |= {"status": "failed", "detail": f"{type(e).__name__}: {e}"}
        report.items.append(item)
    return report
