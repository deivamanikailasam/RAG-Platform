"""Synthetic test sets (extension 04): question / answer / evidence triples from the corpus.

    rag eval-generate --from examples/eval/handbook.yaml --out examples/eval/generated.yaml
    rag eval-generate --source docs/policies/ --per-document 5 --mode llm --profile local --out gen.yaml

For each document: parse and chunk it with the profile's own components, pick the passages that
state something checkable (numbers, rules: "must", "can", "within"), and write a question that
passage answers, the reference answer, and the evidence (document, chunk, quote and its character
offsets). `template` mode needs no model (the questions are stilted but answerable, and good
regression tests for retrieval); `llm` mode asks a model for natural questions, and keeps a reply
only if its quote really is in the passage and its answer is made of the passage's words.

Every generated question is written with `review: pending`: the evaluation commands leave it out
until a person has read it and set `review: approved` (or `rejected`). `rag eval-review --check`
fails while any are pending, so an unreviewed set can't become a release gate by accident.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rag_core.components.formatting import spans
from rag_core.registry import Container
from rag_core.text import content_words, grounded, overlap, tfidf_keywords
from rag_core.types import Source

log = logging.getLogger("rag_core.synth")

_CHECKABLE = re.compile(r"\d|\b(must|must not|can|cannot|may|should|within|at least|at most|up to|"
                        r"only|never|always|required|requires|per|before|after)\b", re.I)  # fmt: skip

LLM_PROMPT = (
    "You write evaluation questions for a document assistant. Given one passage, write ONE "
    "question an employee might really ask that the passage answers, the short answer, and the "
    "exact sentence of the passage that supports it. Reply with JSON only: "
    '{"question": "...", "answer": "...", "quote": "..."}'
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24] or "doc"


def _doc_name(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


def candidates(chunks: Sequence[Any]) -> list[tuple[Any, int, int, str]]:
    """(chunk, start, end, sentence) for sentences worth asking about, best first."""
    found = []
    for ch in chunks:
        for start, end, s in spans(ch.text):
            cw = content_words(s)
            if len(cw) < 5 or len(s) > 400 or s.lstrip().startswith(("#", "|", "-", "*")):
                continue
            score = (
                2 * bool(re.search(r"\d", s)) + bool(_CHECKABLE.search(s)) + min(len(cw), 15) / 15
            )
            found.append((score, ch, start, end, s))
    found.sort(key=lambda t: -t[0])
    return [(ch, a, b, s) for _, ch, a, b, s in found]


_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")


def template_question(sentence: str, title: str, keywords: Sequence[str]) -> str:
    """A question this sentence answers, without a model. A sentence with a number becomes a
    gap to fill ("… staff get ___ days …": the number is the answer); any other sentence a
    "what does <document> say about <its two most specific words>" question. Stilted, and close
    to the passage's own words: good for regression tests of retrieval and citations, not for
    measuring robustness to paraphrase (use `--mode llm` and review the result for that)."""
    if _NUMBER.search(sentence):
        gap = _NUMBER.sub("___", sentence, count=1).rstrip(".")
        return f'In "{title}", what number fills the gap: "{gap}"?'
    title_words = set(content_words(title))
    kws = [k for k in dict.fromkeys(keywords) if k not in title_words and not k.isdigit()][:2]
    return f'What does "{title}" say about {" and ".join(kws) if kws else "this"}?'


def generate(container: Container, sources: Sequence[Source], *, per_document: int = 3,
             mode: str = "template", llm: Any = None) -> list[dict[str, Any]]:  # fmt: skip
    """Question/answer/evidence items for these sources (unreviewed)."""
    from rag_core.components.parsing import ParserRouter

    router = ParserRouter(container.get("parsers"))
    normalizers = container.get("normalizers") if container.has("normalizers") else []
    chunker = container.get("chunker")
    items: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for source in sources:
        doc = router.parse(source)
        for n in normalizers:
            doc = n.normalize(doc)
        chunks = chunker.chunk(doc)
        if not chunks:
            continue
        title = doc.title or _doc_name(source.uri)
        cands = candidates(chunks)
        keywords = {
            id(ch): kw
            for ch, kw in zip(chunks, tfidf_keywords([c.text for c in chunks], k=8), strict=True)
        }
        picked: list[tuple[Any, int, int, str]] = []
        for c in cands:  # different chunks first, so one paragraph doesn't supply every question
            if len(picked) < per_document and all(c[0] is not p[0] for p in picked):
                picked.append(c)
        for c in cands:
            if len(picked) < per_document and c not in picked:
                picked.append(c)
        asked: set[str] = set()
        for ch, start, end, sentence in picked:
            item = None
            if mode == "llm" and llm is not None:
                item = _by_llm(llm, ch)
            if item is None:
                sent_kw = list(dict.fromkeys(content_words(sentence)))
                kws = [k for k in keywords.get(id(ch), []) if k in sent_kw] + sent_kw
                item = {"question": template_question(sentence, title, kws), "reference": sentence,
                        "evidence": {"chunk_id": ch.id, "quote": sentence, "start": start, "end": end},
                        "generated_by": "template"}  # fmt: skip
            if item["question"] in asked:
                continue  # two sentences that read alike: one question is enough
            asked.add(item["question"])
            base = f"gen-{_slug(Path(_doc_name(source.uri)).stem)}-{len(asked)}"
            qid, k = base, 1
            while qid in used_ids:
                k += 1
                qid = f"{base}-{k}"
            used_ids.add(qid)
            items.append({"id": qid, "question": item["question"], "reference": item["reference"],
                          "relevant": [_doc_name(source.uri)],
                          "evidence": {"document": _doc_name(source.uri), **item["evidence"]},
                          "tags": ["synthetic", item["generated_by"].split(":")[0]],
                          "generated_by": item["generated_by"], "review": "pending"})  # fmt: skip
    return items


def _by_llm(llm: Any, chunk: Any) -> dict[str, Any] | None:
    try:
        reply = str(llm.complete(LLM_PROMPT, chunk.text, max_tokens=300))
        m = re.search(r"\{.*\}", reply, re.S)
        data = json.loads(m.group(0)) if m else None
    except Exception as e:  # a failed or invalid reply: the template takes over
        log.warning("eval-generate: model reply unusable, using the template: %s", e)
        return None
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k].strip()
                                             for k in ("question", "answer", "quote")):  # fmt: skip
        return None
    quote = data["quote"].strip()
    start = chunk.text.find(quote)
    if start < 0:  # not verbatim: accept the passage sentence it matches best, if it matches well
        best = max(spans(chunk.text), key=lambda s: overlap(quote, s[2]), default=None)
        if best is None or overlap(quote, best[2]) < 0.8:
            return None
        start, end, quote = best
    else:
        end = start + len(quote)
    if not grounded(data["answer"], chunk.text, 0.5):
        return None  # an answer the passage doesn't support would be a wrong reference
    return {"question": data["question"].strip(), "reference": data["answer"].strip(),
            "evidence": {"chunk_id": chunk.id, "quote": quote, "start": start, "end": end},
            "generated_by": f"llm:{getattr(llm, 'model', '?')}"}  # fmt: skip


def dataset(items: list[dict[str, Any]], *, corpus: list[dict[str, Any]], principal: dict[str, Any],
            k: int = 5, mode: str = "template") -> dict[str, Any]:  # fmt: skip
    return {"version": 1, "k": k, "principal": principal, "corpus": corpus,
            "generated": {"at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "mode": mode,
                          "note": "every question is review: pending until a person approves it"},
            "questions": items}  # fmt: skip


def review_status(doc: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for q in doc.get("questions") or []:
        s = str(q.get("review", "approved"))
        out[s] = out.get(s, 0) + 1
    return out


_REVIEW = re.compile(r"(\breview:\s*)(\w+)")


def set_review(path: Path, ids: Sequence[str], status: str) -> int:
    """Set `review: <status>` on these questions, editing the file's text in place (comments and
    layout kept): a flow item `- {id: x, …, review: pending}` or a block item's `review:` line."""
    lines = path.read_text().splitlines(keepends=True)
    changed = 0
    for qid in ids:
        start = re.compile(r"^(\s*)-\s+\{?\s*id:\s*['\"]?" + re.escape(qid) + r"['\"]?\s*[,}\n]")
        for i, line in enumerate(lines):
            m = start.match(line)
            if not m:
                continue
            if "{" in line.split("id:", 1)[0]:  # a one-line flow item
                lines[i], n = _REVIEW.subn(lambda r: r.group(1) + status, line, count=1)
                changed += n
                break
            indent = len(m.group(1))
            for j in range(i + 1, len(lines)):  # the item's own lines, up to the next item
                body = lines[j]
                lead = len(body) - len(body.lstrip())
                if body.strip() and lead <= indent:
                    break
                if lead == indent + 2 and _REVIEW.match(body.strip()):
                    lines[j], n = _REVIEW.subn(lambda r: r.group(1) + status, body, count=1)
                    changed += n
                    break
            break
    path.write_text("".join(lines))
    return changed


__all__ = ["candidates", "dataset", "generate", "review_status", "set_review", "template_question"]
