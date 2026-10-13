"""The data lifecycle on the sample handbook, in one process (Step 36).

    uv run python examples/lifecycle_demo.py

Uses the offline profile (in-memory stores), so nothing outside this process is touched.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from rag_core import config
from rag_core import evaluate as ev
from rag_core import lifecycle as lc
from rag_core.answer import AnswerPipeline
from rag_core.ingest import IngestionPipeline
from rag_core.types import Access, Principal

ROOT = Path(__file__).resolve().parents[1]
staff = Principal("ann", ("all-staff",), ("public", "internal"))
c = config.load(ROOT / "rag.yaml", "offline", env={})
ev.ingest_corpus(c, ev.load_dataset(ROOT / "examples/eval/handbook.yaml"), ROOT / "examples/eval")
pipe, answers, manifest = IngestionPipeline(c), AnswerPipeline(c), c.get("manifest")


def show(title: str, report: lc.LifecycleReport) -> None:
    print(f"\n== {title}")
    for item in report.items:
        print(
            "   "
            + "   ".join(
                f"{k}={str(v).rsplit('/', 1)[-1] if k == 'uri' else v}" for k, v in item.items()
            )
        )
    print("   " + report.summary())


# 1. Retention: pretend the superseded 2021 policy was last ingested 40 days ago
old = next(e for e in manifest.all() if e.source_uri.endswith("annual-leave-2021.md"))
manifest.put(replace(old, updated_at=time.time() - 40 * lc.DAY))
policy = lc.load_retention(ROOT / "examples/retention.yaml")
show("retention (dry run)", lc.apply_retention(pipe, policy))
show("retention (apply)", lc.apply_retention(pipe, policy, apply=True))

# 2. Revocation: the remote-work policy becomes HR-only; the next answer must not use it
q = "How many days a week can I work from home?"
print(f"\n== before: {answers.answer(q, staff).text[:70]}")
uri = next(e.source_uri for e in manifest.all() if e.source_uri.endswith("remote-work.md"))
show("change access", lc.change_access(pipe, uri, Access("confidential", ("hr",))))
print(f"== after:  {answers.answer(q, staff).text[:70]}")

# 3. Erasure request for a person: conversations, cached answers, where they're mentioned
answers.answer("How do I report phishing?", staff, session_id="s-1")
show("erase subject (dry run)", lc.erase_subject(c, staff, ["security@example.com"]))
show("erase subject (apply)", lc.erase_subject(c, staff, ["security@example.com"], apply=True))
