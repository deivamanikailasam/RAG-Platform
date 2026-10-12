#!/usr/bin/env python3
"""Delete Langfuse traces older than N days.

Self-hosted Langfuse under the MIT licence does not delete old data by itself (automatic data
retention is an Enterprise feature). Traces hold questions and retrieved context, so keeping them
forever breaks the "keep personal data only as long as needed" rule. This job closes the gap.

Run:      just langfuse-retention             (deletes)
Preview:  just langfuse-retention --dry-run   (counts only)

Langfuse v4 note (found while testing against the real 4.27 server, not in the guide): a fresh v4
deployment runs in "events_only" write mode, where the legacy GET /api/public/traces list answers
404. Deleting traces (DELETE /api/public/traces) still works. So each function first tries the
legacy list, and on that specific 404 finds old traces through the v2 observations API instead:
the ROOT observation of every trace, filtered by start time, paged with a cursor.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Iterator

from langfuse import Langfuse
from langfuse.api.core import ApiError


def _events_only(e: ApiError) -> bool:
    """True when the server rejected a legacy endpoint because it runs in v4 events_only mode."""
    return e.status_code == 404 and "events_only" in str(e.body)


def _old_trace_ids_v4(
    client: Langfuse, *, older_than: dt.datetime, batch: int
) -> Iterator[list[str]]:
    """Trace ids older than the cutoff, a page at a time, from v4's observations API."""
    cursor: str | None = None
    while True:
        page = client.api.observations.get_many(
            is_root_observation=True,  # one per trace: the observation the trace starts with
            to_start_time=older_than,
            limit=batch,
            cursor=cursor,
            fields="core",
        )
        ids = list(dict.fromkeys(o.trace_id for o in page.data if o.trace_id))
        if ids:
            yield ids
        cursor = page.meta.cursor
        if not cursor:
            return


def purge(client: Langfuse, *, older_than: dt.datetime, batch: int = 100) -> int:
    """Delete every trace with a timestamp before `older_than`, oldest first, in batches."""
    deleted: set[str] = set()
    try:
        return _purge_legacy(client, older_than=older_than, batch=batch, deleted=deleted)
    except ApiError as e:
        if not _events_only(e):
            raise
    # Langfuse v4: collect every old id FIRST, then delete. Deleting while paging would shift
    # the pages under the cursor and skip traces.
    old = list(
        dict.fromkeys(
            i for ids in _old_trace_ids_v4(client, older_than=older_than, batch=batch) for i in ids
        )
    )
    for start in range(0, len(old), batch):
        client.api.trace.delete_multiple(trace_ids=old[start : start + batch])
    return len(old)


def _purge_legacy(
    client: Langfuse, *, older_than: dt.datetime, batch: int, deleted: set[str]
) -> int:
    """The guide's loop, for servers that still offer GET /api/public/traces."""
    while True:
        # Always page 1: each round deletes what we just saw, so the "next page" moves up.
        page = client.api.trace.list(
            to_timestamp=older_than, limit=batch, page=1, order_by="timestamp.asc", fields="core"
        )
        ids = [t.id for t in page.data if t.id not in deleted]
        if not ids:
            # Nothing new. (Langfuse deletes asynchronously, so ids already sent for deletion can
            # still be listed for a moment; the next run picks up anything left over.)
            return len(deleted)
        client.api.trace.delete_multiple(trace_ids=ids)
        deleted.update(ids)


def count(client: Langfuse, *, older_than: dt.datetime) -> int:
    try:
        page = client.api.trace.list(to_timestamp=older_than, limit=1, fields="core")
        return int(page.meta.total_items)
    except ApiError as e:
        if not _events_only(e):
            raise
    seen: set[str] = set()  # Langfuse v4: no total count, so page through and count distinct ids
    for ids in _old_trace_ids_v4(client, older_than=older_than, batch=100):
        seen.update(ids)
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--days", type=int, default=int(os.getenv("LANGFUSE_RETENTION_DAYS", "30")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        sys.exit("refusing to delete everything: --days must be at least 1")
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=args.days)
    client = Langfuse(tracing_enabled=False)  # keys and URL from LANGFUSE_* environment variables
    if args.dry_run:
        print(
            f"would delete {count(client, older_than=cutoff)} traces older than {cutoff:%Y-%m-%d}"
        )
    else:
        print(f"deleted {purge(client, older_than=cutoff)} traces older than {cutoff:%Y-%m-%d}")


if __name__ == "__main__":
    main()
