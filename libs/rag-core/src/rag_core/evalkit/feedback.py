"""Feedback -> golden dataset (extension 04): real failures become tomorrow's test questions.

    rag eval-candidates --events audit.jsonl [--texts texts.jsonl] --out candidates.yaml
    rag eval-candidates --events audit.jsonl --append-to examples/eval/handbook.yaml

The audit log (Step 23) and /v1/feedback give, per answer: thumbs down (with a reason), the
groundedness guard's flag, the release, and the ids of the chunks shown and cited, but never the
question's text (it isn't stored there, by design). Each such answer becomes a candidate item
with `review: pending` and its trace id; a reviewer opens the trace (Langfuse/Tempo, where the
text lives under its own retention rule), writes or corrects the question, the documents that
answer it (or none: "should have said I don't know") and a reference answer, and approves it.
`--texts` takes a JSONL export of {"answer_id", "question", "answer"} (e.g. from Langfuse) to
pre-fill the question and show the answer that was rated down.

Candidates already in the dataset (same answer id) are skipped, so the command can run daily.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from rag_core.online import collect


def load_texts(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            out[str(row["answer_id"])] = row
    return out


def existing_answer_ids(doc: Mapping[str, Any]) -> set[str]:
    return {str(q["source"]["answer_id"]) for q in doc.get("questions") or []
            if isinstance(q.get("source"), dict) and q["source"].get("answer_id")}  # fmt: skip


def candidates(events: Iterable[Mapping[str, Any]], texts: Mapping[str, Mapping[str, Any]] | None = None,
               skip: set[str] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """Dataset items (review: pending) for every rated-down or flagged answer."""
    _, queue = collect(events, group_by="release")
    texts, skip = texts or {}, skip or set()
    out = []
    for item in queue:
        aid = str(item["answer_id"])
        if aid in skip:
            continue
        t = texts.get(aid, {})
        q = t.get("question") or f"TODO: copy the question from trace {item.get('trace_id') or aid}"
        cand: dict[str, Any] = {
            "id": f"fb-{aid[:12].lower()}",
            "question": q,
            "relevant": [],  # TODO: the documents that answer it; leave empty if none should
            "tags": ["from-feedback", *sorted({w.split(" ")[0] for w in item["why"]})],
            "review": "pending",
            "source": {"answer_id": aid, "trace_id": item.get("trace_id"), "release": item.get("group"),
                       "why": list(item["why"]), "context_ids": item.get("context_ids"),
                       "cited_ids": item.get("cited_ids")},
        }  # fmt: skip
        if t.get("answer"):
            cand["rated_answer"] = t[
                "answer"
            ]  # what went wrong, for the reviewer (not a reference)
        out.append(cand)
    return out


def append_to(dataset: Path, items: list[dict[str, Any]]) -> int:
    """Append items to the dataset's `questions:` list, keeping the file's comments and layout.
    Only when `questions:` is the last top-level key (as in the shipped datasets)."""
    text = dataset.read_text()
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict) or list(doc)[-1:] != ["questions"]:
        raise ValueError(f"{dataset}: `questions:` must be the last top-level key to append to it")
    known = existing_answer_ids(doc) | {str(q.get("id")) for q in doc.get("questions") or []}
    new = [i for i in items if i["id"] not in known and i["source"]["answer_id"] not in known]
    if not new:
        return 0
    block = yaml.safe_dump(new, sort_keys=False, allow_unicode=True, width=120)
    indented = "\n".join(("  " + line) if line else line for line in block.splitlines())
    sep = "" if text.endswith("\n") else "\n"
    dataset.write_text(
        text
        + sep
        + "  # proposed from feedback (rag eval-candidates): review before use\n"
        + indented
        + "\n"
    )
    return len(new)


__all__ = ["append_to", "candidates", "existing_answer_ids", "load_texts"]
