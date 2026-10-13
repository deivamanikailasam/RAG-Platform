"""Metadata extraction at ingestion (extension 02): facts ABOUT a chunk, stored next to it so a
metadata filter (extension 01) can use them: "only contracts", "only 2025", "only German",
"only chunks that mention POL-117".

    enrichers:
      - {use: metadata, keywords: 5}                       # rules: free, offline, predictable
      - use: llm-metadata                                  # a model fills a schema YOU declare
        fields:
          department: {type: keyword, values: [hr, finance, it]}
          effective:  {type: date}
          audience:   {type: list, values: [staff, managers, contractors]}

Extracted values are never embedded (the chunk's text and embed_text don't change): they are for
filtering, faceting, routing and the trace. Every value is a scalar or a list of scalars, which
is what every store can filter on.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core import filters as _filters
from rag_core.registry import Container, register
from rag_core.text import (
    DOC_TYPES,
    ENTITY_PATTERNS,
    detect_language,
    extract_dates,
    extract_entities,
    guess_doc_type,
    tfidf_keywords,
    yake_keywords,
)
from rag_core.types import Chunk, Document

log = logging.getLogger("rag_core.metadata")

Extract = Literal["dates", "language", "doc_type", "keywords", "entities"]
EXTRACT_ALL: tuple[Extract, ...] = ("dates", "language", "doc_type", "keywords", "entities")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleMetadataParams(_Strict):
    extract: list[Extract] = Field(default_factory=lambda: list(EXTRACT_ALL))
    keywords: int = Field(5, ge=1, le=30)  # per chunk; doc_keywords gets the same number
    keyword_method: Literal["tfidf", "yake"] = "tfidf"
    # emails are left out by default: PII redaction has normally masked them anyway
    entity_kinds: list[str] = Field(
        default_factory=lambda: ["code", "money", "percent", "url", "org", "name"]
    )
    doc_types: dict[str, list[str]] | None = (
        None  # your own types and cue words (default: built-in)
    )
    day_first: bool = True  # 1/3/2025 is 1 March (False: 3 January)
    prefix: str = ""  # e.g. "x_" to keep extracted keys apart from the source system's
    overwrite: bool = False  # replace a value the source already gave (e.g. its own doc_type)

    @model_validator(mode="after")
    def _kinds(self) -> RuleMetadataParams:
        unknown = sorted(set(self.entity_kinds) - set(ENTITY_PATTERNS))
        if unknown:
            raise ValueError(f"unknown entity kinds {unknown} (known: {sorted(ENTITY_PATTERNS)})")
        return self


class RuleMetadata:
    """Rule-based extraction, per chunk and per document:
    dates, date_latest     ISO dates written in the chunk (filter: {"date_latest": {"gte": …}})
    language               detected from stop words (en, de, fr, es, nl, it, pt), when confident
    doc_type               policy, procedure, contract, invoice, minutes, faq, guide, report, …
    keywords, doc_keywords TF-IDF across the document's chunks, or YAKE-style for the document
    entities               codes (POL-117), money, percentages, URLs, organisations, names"""

    def __init__(self, p: RuleMetadataParams) -> None:
        self.p = p

    def _set(self, meta: dict[str, Any], key: str, value: Any) -> None:
        if value in (None, [], ""):
            return
        k = self.p.prefix + key
        if self.p.overwrite or k not in meta or key == "language":
            meta[k] = value

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]:
        want = set(self.p.extract)
        doc_meta: dict[str, Any] = {}
        text = document.text
        if "language" in want:
            lang, confidence = detect_language(text)
            if lang != "und" and confidence >= 0.5:
                doc_meta["language"] = lang
        if "doc_type" in want:
            doc_meta["doc_type"] = guess_doc_type(document.uri, document.title, text,
                                                  self.p.doc_types or DOC_TYPES)  # fmt: skip
        if "keywords" in want:
            doc_meta["doc_keywords"] = (yake_keywords(text, self.p.keywords) if self.p.keyword_method == "yake"
                                        else tfidf_keywords([text, *[c.text for c in chunks]], self.p.keywords)[0])  # fmt: skip
        per_chunk = (
            tfidf_keywords([c.text for c in chunks], self.p.keywords) if "keywords" in want else []
        )
        out = []
        for i, c in enumerate(chunks):
            meta = dict(c.metadata)
            for k, v in doc_meta.items():
                if (
                    k == "language"
                    and not self.p.overwrite
                    and meta.get("language") not in (None, "", "en", "und")
                ):
                    continue  # the parser or the source said otherwise: trust it
                self._set(meta, k, v)
            if "dates" in want:
                dates = extract_dates(c.text, self.p.day_first)
                self._set(meta, "dates", dates)
                self._set(meta, "date_latest", dates[-1] if dates else None)
            if per_chunk:
                self._set(meta, "keywords", per_chunk[i])
            if "entities" in want:
                found = extract_entities(c.text, self.p.entity_kinds)
                self._set(
                    meta,
                    "entities",
                    [e for kind in self.p.entity_kinds for e in found.get(kind, [])],
                )
                self._set(meta, "entity_kinds", sorted(found))
            out.append(replace(c, metadata=meta))
        return out


@register("enricher", "metadata", params=RuleMetadataParams,
          summary="rule-based metadata for filters: dates, language, doc type, keywords (TF-IDF/YAKE), entities (regex)")  # fmt: skip
def _rule_metadata(p: RuleMetadataParams, c: Container) -> RuleMetadata:
    return RuleMetadata(p)


# ================================================================ LLM-based, against a declared schema

FieldType = Literal["keyword", "string", "number", "integer", "boolean", "date", "list"]


class MetaField(_Strict):
    type: FieldType = "keyword"
    description: str = ""  # what the model reads about this field
    values: list[str] = Field(default_factory=list)  # keyword / list: the ONLY values accepted
    required: bool = False  # missing or invalid: ask again once, then store nothing from this call
    max_chars: int = Field(200, ge=1, le=2000)  # string fields are cut to this


class LlmMetadataParams(_Strict):
    fields: dict[str, MetaField] = Field(min_length=1)
    scope: Literal["document", "chunk"] = "document"  # one call per document, or per chunk
    llm_slot: Literal["llm", "judge_llm", "answer_llm"] = "llm"
    max_chars: int = Field(8000, ge=500)  # of the document/chunk the model reads
    retries: int = Field(1, ge=0, le=3)
    prefix: str = ""

    @model_validator(mode="after")
    def _names(self) -> LlmMetadataParams:
        for name in self.fields:
            if not _filters.FIELD.match(name):
                raise ValueError(f"{name!r} is not a valid field name")
        return self


METADATA_SYSTEM = "You extract metadata from documents as JSON. You never guess: unknown is null."
METADATA_PROMPT = """Extract these fields from the text and answer with ONE JSON object, nothing else.
Use null for anything the text doesn't state.

Fields:
{fields}

Title: {title}
Text:
{text}"""


def _describe(name: str, f: MetaField) -> str:
    kind = {"keyword": "one of", "list": "a list of values from"}.get(f.type, f.type)
    allowed = f" {f.values}" if f.values and f.type in ("keyword", "list") else ""
    shape = {"date": " (ISO 8601, YYYY-MM-DD)", "boolean": " (true/false)"}.get(f.type, "")
    return f"- {name}: {kind}{allowed}{shape}" + (f". {f.description}" if f.description else "")


def _json_object(reply: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def check_value(f: MetaField, value: Any) -> Any:
    """The value converted to the declared type, or ValueError. None stays None (unknown)."""
    if value is None:
        return None
    if f.type == "keyword":
        v = str(value).strip().lower() if f.values else str(value).strip()
        allowed = {x.lower(): x for x in f.values}
        if f.values and v not in allowed:
            raise ValueError(f"{value!r} is not one of {f.values}")
        return allowed.get(v, v)
    if f.type == "string":
        return str(value).strip()[: f.max_chars]
    if f.type == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "yes"):
            return True
        if str(value).lower() in ("false", "no"):
            return False
        raise ValueError(f"{value!r} is not true/false")
    if f.type in ("number", "integer"):
        if isinstance(value, bool):
            raise ValueError("a boolean is not a number")
        num = float(str(value).replace(",", ""))
        return int(num) if f.type == "integer" else num
    if f.type == "date":
        return date.fromisoformat(str(value)[:10]).isoformat()
    # list
    items = value if isinstance(value, list) else [value]
    out = []
    allowed = {x.lower(): x for x in f.values}
    for item in items:
        s = str(item).strip()
        if f.values:
            if s.lower() not in allowed:
                raise ValueError(f"{item!r} is not one of {f.values}")
            s = allowed[s.lower()]
        out.append(s)
    return list(dict.fromkeys(out))


class LlmMetadata:
    """An LLM fills a schema you declare; every value is checked against it (type, allowed
    values, ISO dates) before it is stored, so the index never holds a value no filter expects.
    Invalid values are dropped; a missing required field gets one more try with the error, and
    if still wrong nothing from that call is stored (logged)."""

    def __init__(self, llm: Any, p: LlmMetadataParams) -> None:
        self.llm, self.p = llm, p

    def extract(self, title: str, text: str) -> dict[str, Any]:
        prompt = METADATA_PROMPT.format(fields="\n".join(_describe(n, f) for n, f in self.p.fields.items()),
                                        title=title, text=text[: self.p.max_chars])  # fmt: skip
        for attempt in range(self.p.retries + 1):
            try:
                reply = self.llm.complete(METADATA_SYSTEM, prompt, max_tokens=400)
            except (RuntimeError, OSError, ValueError) as e:
                log.warning("llm-metadata: the model call failed: %s", e)
                return {}
            data = _json_object(reply)
            problems: list[str] = []
            out: dict[str, Any] = {}
            if data is None:
                problems.append("the answer was not a JSON object")
            else:
                for name, f in self.p.fields.items():
                    try:
                        v = check_value(f, data.get(name))
                    except (ValueError, TypeError) as e:
                        problems.append(f"{name}: {e}")
                        v = None
                    if v is None or v == []:
                        if f.required:
                            problems.append(f"{name} is required")
                        continue
                    out[name] = v
            missing = [p for p in problems if "required" in p or "JSON" in p]
            if not missing:
                return out
            if attempt < self.p.retries:
                prompt += (
                    "\n\nYour previous answer was invalid: " + "; ".join(problems) + ". Try again."
                )
        log.warning("llm-metadata: no valid answer for %r", title)
        return {}

    def enrich(self, document: Document, chunks: list[Chunk]) -> list[Chunk]:
        def put(c: Chunk, found: dict[str, Any]) -> Chunk:
            return replace(
                c, metadata={**c.metadata, **{self.p.prefix + k: v for k, v in found.items()}}
            )

        if self.p.scope == "document":
            found = self.extract(document.title, document.text)
            return [put(c, found) for c in chunks]
        return [put(c, self.extract(document.title, c.text)) for c in chunks]


@register("enricher", "llm-metadata", params=LlmMetadataParams, status="mocked",
          summary="an LLM fills a declared metadata schema (per document or chunk); values type- and enum-checked")  # fmt: skip
def _llm_metadata(p: LlmMetadataParams, c: Container) -> LlmMetadata:
    return LlmMetadata(c.get(p.llm_slot), p)
