"""Answer formatters (extension 04): shape a checked answer for whoever reads it.

They run in the answer pipeline AFTER citations are checked and the output guards have passed, in
the order listed, and never add a claim: they re-mark citations, attach the quoted evidence with
its character offsets, wrap the answer in a JSON object checked against a schema, score how much
to trust it, and suggest follow-up questions the documents can answer. What they add lands in
`Answer.extras` (and in rag-api's `extras` field):

    answer_formatters:
      - {use: confidence, abstain_below: 0.3}      # extras.confidence = {score, label, signals}
      - {use: follow-ups, n: 3}                    # extras.follow_ups = ["…?", …]
      - {use: citations, style: footnotes}         # [^1] markers + footnotes; extras.citations = quotes with spans
      - {use: json}                                # extras.json = {answer, citations, …}, schema-checked

A formatter that fails is skipped (and the trace says so): formatting must never take an answer
down. Blocked answers are not formatted (they are a fixed message).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core.components.generation import ABSTAIN
from rag_core.components.guards import GroundednessParams, LexicalGroundedness
from rag_core.registry import Container, register
from rag_core.text import SENTENCE, content_words, overlap, sentences, tfidf_keywords
from rag_core.types import Answer, Query, ScoredChunk

log = logging.getLogger("rag_core.formatting")

_MARK = re.compile(r"\[doc\s*(\d+(?:\s*,\s*\d+)*)\]", re.I)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _with(answer: Answer, **extras: Any) -> Answer:
    return replace(answer, extras={**answer.extras, **extras})


def spans(text: str) -> list[tuple[int, int, str]]:
    """Sentences of `text` with their character offsets: (start, end, sentence)."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    for m in [*SENTENCE.finditer(text), None]:
        end = m.start() if m is not None else len(text)
        seg = text[pos:end]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            start = pos + lead
            out.append((start, start + len(seg.strip()), seg.strip()))
        if m is not None:
            pos = m.end()
    return out


def _cited_by(text: str) -> dict[int, list[str]]:
    """Marker number -> the answer sentences that cite it."""
    found: dict[int, list[str]] = {}
    for s in sentences(text):
        for m in _MARK.finditer(s):
            for n in re.findall(r"\d+", m.group(1)):
                found.setdefault(int(n), []).append(_MARK.sub("", s).strip())
    return found


# ================================================================ citation styles and quotes


class CitationParams(_Strict):
    style: Literal["numeric", "footnotes"] = "numeric"  # [doc 1] as checked, or [^1] + footnotes
    quotes: bool = True  # extras.citations: the supporting sentence of each source, with offsets
    max_quote_chars: int = Field(300, ge=40, le=2000)
    append_quotes: bool = False  # also show the quotes under the answer as "> …" lines


class CitationFormatter:
    """Inline numeric markers (`[doc 1]`, the default), or footnotes (`[^1]` with a list of sources
    at the end). With `quotes`, each cited source gets the sentence that best supports the answer
    sentences citing it, with its start/end character offsets in the chunk, so a reader (or a UI)
    can highlight exactly where the claim comes from."""

    def __init__(self, p: CitationParams) -> None:
        self.p = p

    def quote(self, n: int, claims: list[str], chunk: ScoredChunk) -> dict[str, Any]:
        text = chunk.chunk.text
        cands = spans(text) or [(0, len(text), text)]
        claim = " ".join(claims)
        start, end, best = max(cands, key=lambda c: (overlap(claim, c[2]) if claim else 0.0, -c[0]))
        if end - start > self.p.max_quote_chars:
            end = start + self.p.max_quote_chars
            best = text[start:end].rstrip() + "…"
        md = chunk.chunk.metadata
        return {"n": n, "title": str(md.get("title", "")), "chunk_id": chunk.chunk.id,
                "quote": best, "start": start, "end": end,
                **({"section": md["section"]} if md.get("section") else {}),
                **({"page": md["page"]} if md.get("page") else {})}  # fmt: skip

    def format(self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]) -> Answer:
        if answer.abstained or not answer.citations:
            return answer
        claims = _cited_by(answer.text)
        quotes = [self.quote(c.marker, claims.get(c.marker, []), sources[c.marker - 1])
                  for c in answer.citations if 1 <= c.marker <= len(sources)]  # fmt: skip
        text = answer.text
        if self.p.style == "footnotes":
            text = _MARK.sub(
                lambda m: "".join(f"[^{n}]" for n in re.findall(r"\d+", m.group(1))), text
            )
            notes = [
                f"[^{q['n']}]: {q['title'] or 'source ' + str(q['n'])}"
                + (f', "{q["quote"]}"' if self.p.quotes else "")
                for q in quotes
            ]
            text = text.rstrip() + "\n\n" + "\n".join(notes)
        if self.p.append_quotes and self.p.quotes and self.p.style != "footnotes":
            text = (
                text.rstrip()
                + "\n\n"
                + "\n".join(f'> "{q["quote"]}" [doc {q["n"]}]' for q in quotes)
            )
        extras: dict[str, Any] = {"citation_style": self.p.style}
        if self.p.quotes:
            extras["citations"] = quotes
        return _with(replace(answer, text=text), **extras)


@register("answer_formatter", "citations", params=CitationParams,
          summary="citation style (inline numeric or footnotes) plus quoted evidence with character offsets")  # fmt: skip
def _citations(p: CitationParams, c: Container) -> CitationFormatter:
    return CitationFormatter(p)


# ================================================================ confidence


class ConfidenceParams(_Strict):
    weights: dict[str, float] = Field(
        default_factory=lambda: {"support": 0.5, "citations": 0.25, "coverage": 0.25}
    )
    high: float = Field(0.75, ge=0, le=1)
    medium: float = Field(0.5, ge=0, le=1)
    abstain_below: float | None = Field(None, ge=0, le=1)  # turn a weak answer into "I don't know"
    min_support: float = Field(0.5, ge=0, le=1)  # as the groundedness guard

    @model_validator(mode="after")
    def _known(self) -> ConfidenceParams:
        unknown = set(self.weights) - {"support", "citations", "coverage"}
        if unknown or not any(v > 0 for v in self.weights.values()):
            raise ValueError("weights: use support, citations and coverage, at least one > 0")
        return self


class ConfidenceScorer:
    """How much to trust this answer, 0..1, from three signals that need no model:
    support (share of answer sentences whose words and numbers are in the sources), citations
    (share of sentences that cite a source) and coverage (share of the question's content words
    found in the sources). Not a probability: a ranking signal for UIs ("low confidence: check the
    source") and for abstaining when it is weak. Calibrate `abstain_below` on your own questions."""

    def __init__(self, p: ConfidenceParams) -> None:
        self.p = p
        self.ground = LexicalGroundedness(GroundednessParams(min_support=p.min_support))

    def signals(
        self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]
    ) -> dict[str, float]:
        body = [s for s in sentences(answer.text) if content_words(_MARK.sub("", s))]
        if not body or not sources:
            return {"support": 0.0, "citations": 0.0, "coverage": 0.0}
        unsupported = len(self.ground.unsupported(answer.text, sources))
        cited = sum(1 for s in body if _MARK.search(s))
        q = set(content_words(query.text))
        src = set(content_words(" ".join(h.chunk.text for h in sources)))
        return {"support": round(max(0.0, 1 - unsupported / len(body)), 3),
                "citations": round(cited / len(body), 3),
                "coverage": round(len(q & src) / len(q), 3) if q else 1.0}  # fmt: skip

    def score(self, signals: Mapping[str, float]) -> float:
        total = sum(self.p.weights.values())
        return round(sum(signals.get(k, 0.0) * w for k, w in self.p.weights.items()) / total, 3)

    def format(self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]) -> Answer:
        if answer.abstained:
            return _with(answer, confidence={"score": None, "label": "abstained", "signals": {}})
        sig = self.signals(query, answer, sources)
        score = self.score(sig)
        label = "high" if score >= self.p.high else "medium" if score >= self.p.medium else "low"
        conf = {"score": score, "label": label, "signals": sig}
        if self.p.abstain_below is not None and score < self.p.abstain_below:
            return replace(answer, text=ABSTAIN, abstained=True, citations=(),
                           trace={**answer.trace, "abstained_reason": f"confidence {score} < {self.p.abstain_below}"},
                           extras={**answer.extras, "confidence": conf | {"label": "abstained"}})  # fmt: skip
        return _with(answer, confidence=conf)


@register("answer_formatter", "confidence", params=ConfidenceParams,
          summary="a 0..1 confidence score and label from support, citations and coverage; can abstain below a floor")  # fmt: skip
def _confidence(p: ConfidenceParams, c: Container) -> ConfidenceScorer:
    return ConfidenceScorer(p)


# ================================================================ follow-up questions


class FollowUpParams(_Strict):
    n: int = Field(3, ge=1, le=6)
    mode: Literal["heuristic", "llm"] = "heuristic"
    llm_slot: Literal["llm", "judge_llm", "answer_llm"] = "llm"
    max_tokens: int = Field(200, ge=20)
    min_overlap: float = Field(
        0.5, ge=0, le=1
    )  # an uncited source must share this much with the question


class FollowUps:
    """Suggest questions the person might ask next that THESE sources can answer (so a suggestion
    never leads to "I don't know", and never to a document the person can't see: the sources
    were already permission-filtered). Heuristic: the sources' topics the answer didn't use; with
    a model: n questions, kept only if their words come from the sources."""

    def __init__(self, p: FollowUpParams, llm: Any = None) -> None:
        self.p, self.llm = p, llm

    def heuristic(self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]) -> list[str]:
        asked = set(content_words(query.text)) | set(content_words(answer.text))
        texts = [h.chunk.text for h in sources]
        keys = tfidf_keywords(texts, k=6) if texts else []
        # the cited documents first (the person is reading about them), then other sources only
        # if they are about the question at all: no "what about the gift policy?" after a VPN fix
        cited = {c.document_uri for c in answer.citations}
        ranked = [
            (h, kw) for h, kw in zip(sources, keys, strict=True) if h.chunk.document_uri in cited
        ]
        ranked += [(h, kw) for h, kw in zip(sources, keys, strict=True)
                   if h.chunk.document_uri not in cited and overlap(query.text, h.chunk.text) >= self.p.min_overlap]  # fmt: skip
        out: list[str] = []
        for h, kws in ranked:
            fresh = [k for k in kws if k not in asked and not k.isdigit()][:2]
            if not fresh:
                continue
            md = h.chunk.metadata
            where = str(md.get("section") or md.get("title") or "the documents")
            q = f"What does {where} say about {' and '.join(fresh)}?"
            if q not in out:
                out.append(q)
                asked |= set(fresh)
            if len(out) >= self.p.n:
                break
        return out

    def by_llm(
        self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]
    ) -> list[str] | None:
        src = "\n\n".join(h.chunk.text for h in sources)
        try:
            reply = str(self.llm.complete(
                f"Suggest {self.p.n} short follow-up questions the user might ask next that the "
                "documents below can answer. One per line, no numbering, nothing else.",
                f"Question: {query.text}\nAnswer: {answer.text}\n\nDocuments:\n{src}",
                max_tokens=self.p.max_tokens))  # fmt: skip
        except Exception as e:  # a helper must never take the answer down
            log.warning("follow-up suggestions failed, using the heuristic: %s", e)
            return None
        lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", x).strip() for x in reply.splitlines()]
        good = [x for x in lines if x.endswith("?") and overlap(x, src) >= 0.5]
        return good[: self.p.n] or None

    def format(self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]) -> Answer:
        if answer.abstained or not sources:
            return answer
        found = None
        if self.p.mode == "llm" and self.llm is not None:
            found = self.by_llm(query, answer, sources)
        return _with(answer, follow_ups=found or self.heuristic(query, answer, sources))


@register("answer_formatter", "follow-ups", params=FollowUpParams,
          summary="suggest follow-up questions the shown sources can answer (heuristic offline, or LLM)")  # fmt: skip
def _follow_ups(p: FollowUpParams, c: Container) -> FollowUps:
    llm = c.get(p.llm_slot if c.has(p.llm_slot) else "llm") if p.mode == "llm" else None
    return FollowUps(p, llm)


# ================================================================ JSON answers


def validate_json(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """A small JSON Schema subset, enough for answer objects (no dependency): type (one or a
    list), enum, const, required, properties, additionalProperties (bool), items, minItems,
    maxItems, minLength, maxLength, minimum, maximum. Returns the problems, [] when valid."""
    errs: list[str] = []
    types = schema.get("type")
    if types is not None:
        names = [types] if isinstance(types, str) else list(types)
        checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
                  "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
                  "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                  "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
                  "null": lambda v: v is None}  # fmt: skip
        unknown = [n for n in names if n not in checks]
        if unknown:
            return [f"{path}: unsupported type {unknown[0]!r} in the schema"]
        if not any(checks[n](value) for n in names):
            return [f"{path}: expected {' or '.join(names)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: must be {schema['const']!r}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errs += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in props:
                errs += validate_json(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected {k!r}")
    if isinstance(value, list):
        if "items" in schema:
            for i, v in enumerate(value):
                errs += validate_json(v, schema["items"], f"{path}[{i}]")
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above {schema['maximum']}")
    return errs


ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer", "abstained", "citations"],
    "properties": {
        "answer": {"type": "string"},
        "abstained": {"type": "boolean"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["n", "title"],
                "properties": {
                    "n": {"type": "integer", "minimum": 1},
                    "title": {"type": "string"},
                    "quote": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
            },
        },
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
        "fields": {"type": "object"},
    },
}


class JsonParams(_Strict):
    # extra fields a model extracts from the answer, as a JSON Schema object, e.g.
    #   fields: {type: object, required: [days], properties: {days: {type: integer}}}
    fields: dict[str, Any] | None = None
    fields_file: str | None = None  # or the same schema in a JSON/YAML file
    llm_slot: Literal["llm", "judge_llm", "answer_llm"] = "llm"
    retries: int = Field(1, ge=0, le=3)  # ask again, with the errors, when the reply is invalid
    as_text: bool = False  # also replace the answer text with the JSON (clients that parse text)
    max_tokens: int = Field(300, ge=20)


class JsonAnswer:
    """The answer as a JSON object checked against a schema: {answer, abstained, citations,
    confidence, follow_ups[, fields]}. Built from the checked answer, so it is always valid
    offline. With `fields`, a model fills a schema of your own (e.g. {"days": 20}) from the answer
    and its sources; an invalid reply is retried with the errors, then left out and reported
    (extras.json_errors), never passed on unchecked."""

    def __init__(self, p: JsonParams, llm: Any = None) -> None:
        self.p, self.llm = p, llm
        self.fields = p.fields
        if p.fields_file:
            import yaml

            self.fields = yaml.safe_load(Path(p.fields_file).read_text())
        if self.fields is not None and self.fields.get("type", "object") != "object":
            raise ValueError("json: fields must be a schema of type object")

    def extract(
        self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]
    ) -> tuple[Any, list[str]]:
        if self.llm is None or self.fields is None:
            return None, ["no model configured for fields"]
        src = "\n\n".join(h.chunk.text for h in sources)
        ask = (f"Question: {query.text}\nAnswer: {answer.text}\n\nSources:\n{src}\n\n"
               f"Reply with ONE JSON object matching this schema, using only facts from the answer "
               f"and sources (null when unknown):\n{json.dumps(self.fields)}")  # fmt: skip
        errors: list[str] = []
        for _ in range(self.p.retries + 1):
            try:
                reply = str(self.llm.complete("You extract structured data. Reply with JSON only.",
                                              ask + (f"\nYour last reply was invalid: {'; '.join(errors)}" if errors else ""),
                                              max_tokens=self.p.max_tokens))  # fmt: skip
                m = re.search(r"\{.*\}", reply, re.S)
                data = json.loads(m.group(0)) if m else None
            except Exception as e:  # a model failure or invalid JSON: retry, then report
                data, errors = None, [f"{type(e).__name__}: {e}"]
                continue
            if data is None:
                errors = ["no JSON object in the reply"]
                continue
            errors = validate_json(data, self.fields, "$.fields")
            if not errors:
                return data, []
        return None, errors

    def format(self, query: Query, answer: Answer, sources: Sequence[ScoredChunk]) -> Answer:
        quotes = {q["n"]: q for q in answer.extras.get("citations", [])}
        conf = answer.extras.get("confidence")
        obj: dict[str, Any] = {
            "answer": answer.text,
            "abstained": answer.abstained,
            "citations": [
                {
                    "n": c.marker,
                    "title": c.title,
                    **{
                        k: quotes[c.marker][k]
                        for k in ("quote", "start", "end")
                        if c.marker in quotes
                    },
                }
                for c in answer.citations
            ],
            "confidence": conf.get("score") if isinstance(conf, Mapping) else None,
            "follow_ups": list(answer.extras.get("follow_ups", [])),
        }
        problems: list[str] = []
        if self.fields is not None and not answer.abstained:
            fields, problems = self.extract(query, answer, sources)
            if fields is not None:
                obj["fields"] = fields
        problems += validate_json(obj, ANSWER_SCHEMA)
        extras: dict[str, Any] = {"json": obj, "json_valid": not problems}
        if problems:
            extras["json_errors"] = problems
        out = _with(answer, **extras)
        return replace(out, text=json.dumps(obj, ensure_ascii=False)) if self.p.as_text else out


@register("answer_formatter", "json", params=JsonParams,
          summary="the answer as a schema-checked JSON object; optional model-extracted fields with retries")  # fmt: skip
def _json(p: JsonParams, c: Container) -> JsonAnswer:
    needs = p.fields is not None or p.fields_file is not None
    llm = c.get(p.llm_slot if c.has(p.llm_slot) else "llm") if needs and c.has("llm") else None
    return JsonAnswer(p, llm)


def format_all(formatters: Sequence[Any], query: Query, answer: Answer,
               sources: Sequence[ScoredChunk], trace: dict[str, Any]) -> Answer:  # fmt: skip
    """Run the formatters in order; one that fails is skipped and named in the trace."""
    if answer.blocked:
        return answer
    for f in formatters:
        try:
            answer = f.format(query, answer, sources)
        except Exception as e:  # formatting must never take an answer down
            log.warning("answer formatter %s failed: %s", type(f).__name__, e)
            trace.setdefault("flags", []).append(
                f"formatter {type(f).__name__} failed: {type(e).__name__}"
            )
    return answer


__all__ = ["ANSWER_SCHEMA", "CitationFormatter", "ConfidenceScorer", "FollowUps", "JsonAnswer",
           "format_all", "spans", "validate_json"]  # fmt: skip
