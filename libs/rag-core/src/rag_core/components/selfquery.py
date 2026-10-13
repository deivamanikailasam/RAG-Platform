"""Self-query (extension 01): find the FILTER hidden in a question.

"HR policies updated after 2025" is two things: what to look for ("HR policies") and which
documents qualify (department = hr, updated >= 2026-01-01). Vector search is bad at the second
part: "after 2025" means nothing to an embedding. The self-query transformer pulls the conditions
out of the question, against a metadata schema YOU declare, and the search applies them as a
metadata filter (ANDed with the caller's filter and, always, the permission filter).

    query_transformer:
      use: self-query
      mode: rules                       # rules (offline, predictable) | llm (rules if the LLM fails)
      date_field: updated               # "after 2025" without naming a date: this field
      fields:
        department: {values: {hr: [human resources, people team], it: [tech support], finance: []}}
        doc_type:   {values: [policy, guide, form]}
        language:   {values: {en: [english], fr: [french], de: [german]}}
        updated:    {type: date, aliases: [updated, changed, modified, revised]}

Only declared fields and (for keyword fields) declared values are ever used, so a question can't
invent a filter on `classification` or on a field you don't index. If the filter finds nothing,
the search runs again without it (`fallback_on_empty`): a wrong guess costs recall, never an
empty answer.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_core import filters as _filters
from rag_core.components.basics import words
from rag_core.registry import Container, register
from rag_core.types import Query

log = logging.getLogger("rag_core.selfquery")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldSpec(_Strict):
    type: Literal["keyword", "date", "number", "boolean"] = "keyword"
    description: str = ""  # what the LLM reads about this field
    # keyword fields: the allowed values, optionally with the words people use for them
    values: list[str] | dict[str, list[str]] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)  # date fields: words that name it ("updated")


class SelfQueryParams(_Strict):
    fields: dict[str, FieldSpec] = Field(min_length=1)
    mode: Literal["rules", "llm"] = "rules"
    llm_slot: Literal["llm", "judge_llm"] = "llm"
    max_tokens: int = Field(300, ge=32)
    date_field: str | None = None  # the date a question means when it names none
    fallback_on_empty: bool = True  # nothing matched the extracted filter: search without it
    system: str | None = None  # replace the built-in LLM instruction

    @model_validator(mode="after")
    def _check(self) -> SelfQueryParams:
        for name in self.fields:
            if not _filters.FIELD.match(name):
                raise ValueError(f"{name!r} is not a valid field name")
        if self.date_field is not None and (self.fields.get(self.date_field) is None
                                            or self.fields[self.date_field].type != "date"):  # fmt: skip
            raise ValueError(
                f"date_field {self.date_field!r} must be a declared field of type date"
            )
        return self


MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m
}
_DATE = (r"(?P<d>\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|(?:" + "|".join(sorted(MONTHS, key=len, reverse=True))
         + r")\.?\s+\d{4}|\d{4}|this year|last year)")  # fmt: skip
AFTER = re.compile(r"\b(after|since|from|newer than|later than)\s+" + _DATE, re.I)
BEFORE = re.compile(
    r"\b(before|until|till|up to|prior to|older than|earlier than)\s+" + _DATE, re.I
)
BETWEEN = re.compile(
    r"\bbetween\s+"
    + _DATE.replace("?P<d>", "?P<a>")
    + r"\s+and\s+"
    + _DATE.replace("?P<d>", "?P<b>"),
    re.I,
)
DURING = re.compile(r"\b(in|during)\s+" + _DATE, re.I)
RELATIVE = re.compile(r"\b(?P<d>this year|last year)\b", re.I)
# extension 04: rolling windows. "in the last 6 months", "past 2 weeks", "over the past year".
# (Plain "last year" stays the calendar year above; "in the last year" is the rolling 12 months.)
WINDOW = re.compile(
    r"\b(?:(?:in|within|over|during)\s+the\s+(?:last|past)|past|last)\s+(?:(?P<n>\d+)\s+)?"
    r"(?P<unit>day|week|month|quarter|year)s?\b", re.I)  # fmt: skip
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 91, "year": 365}


def _window(m: re.Match[str], today: date) -> date | None:
    """The start of a rolling window, or None for "last year" without "in the"/"past"/a number."""
    text = m.group(0).lower()
    if m["n"] is None and text.startswith("last") and m["unit"].lower() == "year":
        return None  # "last year" = the calendar year (RELATIVE)
    n = int(m["n"] or 1)
    return date.fromordinal(today.toordinal() - n * _UNIT_DAYS[m["unit"].lower()])


def _period(text: str, today: date) -> tuple[date, date] | None:
    """A date expression as [start, end): "2025" -> 2025-01-01 .. 2026-01-01."""
    t = text.lower().strip()
    if t in ("this year", "last year"):
        y = today.year - (t == "last year")
        return date(y, 1, 1), date(y + 1, 1, 1)
    if re.fullmatch(r"\d{4}", t):
        y = int(t)
        return date(y, 1, 1), date(y + 1, 1, 1)
    m = re.fullmatch(r"(\d{4})-(\d{2})", t)
    if m:
        y, mo = int(m[1]), int(m[2])
    else:
        m = re.fullmatch(r"([a-z]+)\.?\s+(\d{4})", t)
        if m and m[1] in MONTHS:
            y, mo = int(m[2]), MONTHS[m[1]]
        else:
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
            if not m:
                return None
            try:
                d = date(int(m[1]), int(m[2]), int(m[3]))
            except ValueError:
                return None
            return d, date.fromordinal(d.toordinal() + 1)
    if not 1 <= mo <= 12:
        return None
    return date(y, mo, 1), date(y + (mo == 12), mo % 12 + 1, 1)


def _contains(text: str, phrase: str) -> bool:
    ws = words(phrase)
    return bool(ws) and f" {' '.join(ws)} " in text


class SelfQuery:
    """Question in; the same question plus the metadata filter it implies out (`analyze`)."""

    def __init__(self, p: SelfQueryParams, llm: Any = None, today: date | None = None) -> None:
        self.p, self.llm, self.today = p, llm, today
        self.fallback_on_empty = p.fallback_on_empty

    # ---- the declared schema ----

    def _values(self, spec: FieldSpec) -> dict[str, list[str]]:
        return {v: [] for v in spec.values} if isinstance(spec.values, list) else dict(spec.values)

    def allowed(self, node: _filters.Node) -> bool:
        """Only declared fields, operators that suit their type and (keyword) declared values."""
        if isinstance(node, _filters.And | _filters.Or):
            return all(self.allowed(i) for i in node.items)
        if isinstance(node, _filters.Not):
            return self.allowed(node.item)
        spec = self.p.fields.get(node.field)
        if spec is None:
            return False
        if node.op == "exists":
            return True
        vals = list(node.value) if isinstance(node.value, tuple) else [node.value]
        if spec.type == "keyword":
            known = self._values(spec)
            return node.op in ("eq", "ne", "in", "nin") and (
                not known or all(v in known for v in vals)
            )
        if spec.type == "date":
            return node.op in _filters.COMPARE and all(isinstance(v, str) for v in vals)
        if spec.type == "number":
            return all(isinstance(v, int | float) and not isinstance(v, bool) for v in vals)
        return node.op in ("eq", "ne") and all(isinstance(v, bool) for v in vals)

    # ---- rules: offline, deterministic ----

    def _date_field(self, text: str) -> str | None:
        dates = {n: s for n, s in self.p.fields.items() if s.type == "date"}
        named = [n for n, s in dates.items() if any(_contains(text, a) for a in [n, *s.aliases])]
        if named:
            return named[0]
        if self.p.date_field:
            return self.p.date_field
        return next(iter(dates)) if len(dates) == 1 else None

    def by_rules(self, question: str) -> dict[str, Any]:
        text = f" {' '.join(words(question))} "
        found: list[dict[str, Any]] = []
        for name, spec in self.p.fields.items():
            if spec.type != "keyword":
                continue
            hits = [
                v
                for v, syns in self._values(spec).items()
                if any(_contains(text, w) for w in [v, *syns])
            ]
            if hits:
                found.append({name: hits[0] if len(hits) == 1 else {"in": hits}})
        field = self._date_field(text)
        if field is not None:
            today = self.today or datetime.now(UTC).date()
            cond: dict[str, str] = {}
            if m := BETWEEN.search(question):
                a, b = _period(m["a"], today), _period(m["b"], today)
                if a and b:
                    cond = {"gte": a[0].isoformat(), "lt": b[1].isoformat()}
            else:
                if m := AFTER.search(question):
                    span = _period(m["d"], today)
                    if span:  # "after 2025" = from 2026; "since 2025" = from 2025 on
                        start = (
                            span[1]
                            if m[1].lower() in ("after", "newer than", "later than")
                            else span[0]
                        )
                        cond["gte"] = start.isoformat()
                if m := BEFORE.search(question):
                    span = _period(m["d"], today)
                    if span:  # "before 2025" = up to 2024; "until 2025" = up to the end of 2025
                        end = (
                            span[0]
                            if m[1].lower() in ("before", "prior to", "older than", "earlier than")
                            else span[1]
                        )
                        cond["lt"] = end.isoformat()
                if not cond and (w := WINDOW.search(question)) and (since := _window(w, today)):
                    cond = {"gte": since.isoformat()}
                if not cond and (m := DURING.search(question) or RELATIVE.search(question)):
                    span = _period(m["d"], today)
                    if span:
                        cond = {"gte": span[0].isoformat(), "lt": span[1].isoformat()}
            if cond:
                found.append({field: cond})
        return {} if not found else found[0] if len(found) == 1 else {"and": found}

    # ---- LLM: understands paraphrases; checked against the schema, rules if unusable ----

    def _prompt(self) -> str:
        if self.p.system:
            return self.p.system
        today = (self.today or datetime.now(UTC).date()).isoformat()
        schema = {n: {"type": s.type, **({"description": s.description} if s.description else {}),
                      **({"values": list(self._values(s))} if s.type == "keyword" and s.values else {})}
                  for n, s in self.p.fields.items()}  # fmt: skip
        return (
            "Extract search filters from the user's question. Today is " + today + ".\n"
            "Metadata fields (use ONLY these, and only the listed values):\n"
            + json.dumps(schema)
            + "\n"
            'Reply with JSON only: {"filter": {...}}. Filter syntax: {"field": value}, '
            '{"field": {"in": [..]}}, {"field": {"gte": "YYYY-MM-DD", "lt": "YYYY-MM-DD"}}, '
            '{"and": [..]}, {"or": [..]}. Use {"filter": {}} when the question sets no condition. '
            "Never guess a condition the question doesn't state."
        )

    def by_llm(self, question: str) -> dict[str, Any] | None:
        try:
            reply = str(self.llm.complete(self._prompt(), question, max_tokens=self.p.max_tokens))
            m = re.search(r"\{.*\}", reply, re.S)
            if m is None:
                raise ValueError(f"no JSON in the reply {reply[:60]!r}")
            data = json.loads(m[0])
            raw = data.get("filter", data) if isinstance(data, dict) else None
            node = _filters.parse(raw if isinstance(raw, dict) else None)
        except Exception as e:  # a helper must never take search down
            log.warning("self-query LLM reply unusable, using the rules: %s", e)
            return None
        if node is not None and not self.allowed(node):
            log.warning("self-query LLM used undeclared fields or values, using the rules")
            return None
        return _filters.to_dict(node) if node is not None else {}

    # ---- the transformer contract ----

    def analyze(self, query: Query) -> tuple[list[str], dict[str, Any]]:
        found = self.by_llm(query.text) if self.p.mode == "llm" and self.llm is not None else None
        if found is None:
            found = self.by_rules(query.text)
        return [query.text], found

    def transform(self, query: Query) -> list[str]:
        return [query.text]  # the filter comes from analyze(); the search text is the question


@register("query_transformer", "self-query", params=SelfQueryParams,
          summary="extract a metadata filter from the question against a declared schema (rules offline, or LLM)")  # fmt: skip
def _self_query(p: SelfQueryParams, c: Container) -> SelfQuery:
    return SelfQuery(p, c.get(p.llm_slot) if p.mode == "llm" else None)


__all__ = ["FieldSpec", "SelfQuery", "SelfQueryParams"]
