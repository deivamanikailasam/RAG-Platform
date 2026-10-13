# The SQL compiler below builds fragments from CONSTANT pieces (operators chosen from a fixed
# table, column names given by the caller's code); every VALUE and field name is a bound
# parameter. Hence S608 is checked and waived for this file.
# ruff: noqa: S608
"""Metadata filters (extension 01): "only HR documents updated since 2025, in English".

A filter is a small JSON/YAML expression over chunk metadata. It travels in `Query.filters`, is
validated ONCE (parse), and is then translated by each store into its own language: a SQL WHERE
clause (pgvector, Postgres full-text), a Qdrant payload filter, an OpenSearch bool filter, or a
Python test (the in-memory stores). It is ALWAYS added to the permission filter (tenant,
classification, groups), never a replacement for it: a filter can only narrow what a person sees.

    {"department": "hr"}                                  equal (shorthand)
    {"department": ["hr", "finance"]}                     any of (shorthand, the Step 32 form)
    {"department": {"in": ["hr", "finance"]}}             in / nin (not in)
    {"doc_type": {"ne": "draft"}}                         not equal (also true when the field is missing)
    {"updated": {"gte": "2025-01-01", "lt": "2026-01-01"}}  gt / gte / lt / lte: numbers or ISO dates
    {"updated": {"range": {"gte": "2025-01-01"}}}          the same, spelled as a range
    {"tags": {"exists": true}}                            has a value (not missing, null or [])
    {"and": [...]}, {"or": [...]}, {"not": {...}}          combine
    {"document": "file:///docs/leave.md"}                 the source document itself

Several keys in one mapping are ANDed. For a list-valued field (tags), `eq` means "contains",
`in` means "contains any of", `ne`/`nin` mean "contains none of". Dates are ISO 8601 strings
(2025-03-01 or 2025-03-01T09:00:00Z); a date without a time is midnight UTC.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

Op = Literal["eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "exists"]
Scalar = str | int | float | bool
COMPARE: tuple[Op, ...] = ("gt", "gte", "lt", "lte")
OPS: tuple[str, ...] = ("eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "exists", "range")
FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")
ISO_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
DOCUMENT = "document"  # the virtual field: the chunk's source document URI
MAX_DEPTH, MAX_NODES, MAX_VALUES, MAX_CHARS = 6, 64, 100, 512


class FilterError(ValueError):
    """A filter that can't be applied: says exactly what is wrong and where."""


# ================================================================ the expression tree


@dataclass(frozen=True)
class Cmp:
    field: str
    op: Op
    value: Any = None  # a scalar; a tuple for in/nin; a bool for exists

    @property
    def is_date(self) -> bool:
        return self.op in COMPARE and isinstance(self.value, str)


@dataclass(frozen=True)
class And:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Or:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Not:
    item: Node


Node = Cmp | And | Or | Not


# ================================================================ parsing and validation


def _scalar(value: Any, where: str) -> Scalar:
    if isinstance(value, datetime):
        value = (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    elif isinstance(value, date):
        value = value.isoformat()
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) > MAX_CHARS:
            raise FilterError(f"{where}: value longer than {MAX_CHARS} characters")
        return value
    raise FilterError(f"{where}: expected a string, number or boolean, got {type(value).__name__}")


def _compare_value(value: Any, where: str) -> Scalar:
    v = _scalar(value, where)
    if isinstance(v, bool):
        raise FilterError(f"{where}: can't compare booleans with gt/gte/lt/lte")
    if isinstance(v, str) and not ISO_DATE.match(v):
        raise FilterError(
            f"{where}: gt/gte/lt/lte need a number or an ISO date (2025-01-31), got {v!r}"
        )
    return v


def _field(name: Any, where: str) -> str:
    if not isinstance(name, str) or not FIELD.match(name):
        raise FilterError(
            f"{where}: {name!r} is not a valid field name (letters, digits, _ and -, at most 64)"
        )
    return name


class _Counter:
    def __init__(self) -> None:
        self.n = 0

    def tick(self) -> None:
        self.n += 1
        if self.n > MAX_NODES:
            raise FilterError(f"filter too large: more than {MAX_NODES} conditions")


def _field_ops(name: str, spec: Any, where: str, count: _Counter) -> list[Node]:
    """The conditions on one field: a value, a list of values, or {op: value, …}."""
    if isinstance(spec, Mapping):
        if not spec:
            raise FilterError(f"{where}: empty condition")
        out: list[Node] = []
        for op, value in spec.items():
            at = f"{where}.{op}"
            if op == "range":
                if not isinstance(value, Mapping) or not value or set(value) - set(COMPARE):
                    raise FilterError(f"{at}: expected {{gte/gt/lte/lt: value}}")
                out += _field_ops(name, dict(value), where, count)
                continue
            if op not in OPS:
                raise FilterError(f"{at}: unknown operator (use one of: {', '.join(OPS)})")
            count.tick()
            if op in ("in", "nin"):
                if not isinstance(value, list | tuple) or not value:
                    raise FilterError(f"{at}: expected a non-empty list")
                if len(value) > MAX_VALUES:
                    raise FilterError(f"{at}: more than {MAX_VALUES} values")
                out.append(Cmp(name, op, tuple(_scalar(v, at) for v in value)))
            elif op == "exists":
                if not isinstance(value, bool):
                    raise FilterError(f"{at}: expected true or false")
                out.append(Cmp(name, "exists", value))
            elif op in COMPARE:
                out.append(Cmp(name, op, _compare_value(value, at)))
            else:
                out.append(Cmp(name, op, _scalar(value, at)))
        return out
    count.tick()
    if isinstance(spec, list | tuple | set):  # the Step 32 shorthand: any of
        values = sorted(spec, key=str) if isinstance(spec, set) else list(spec)
        if not values:
            raise FilterError(f"{where}: empty list")
        if len(values) > MAX_VALUES:
            raise FilterError(f"{where}: more than {MAX_VALUES} values")
        return [Cmp(name, "in", tuple(_scalar(v, where) for v in values))]
    if spec is None:
        raise FilterError(f"{where}: null is not a value; use {{exists: false}}")
    return [Cmp(name, "eq", _scalar(spec, where))]


def _parse(raw: Any, where: str, depth: int, count: _Counter) -> Node:
    if depth > MAX_DEPTH:
        raise FilterError(f"{where}: nested more than {MAX_DEPTH} levels")
    if not isinstance(raw, Mapping):
        raise FilterError(f"{where}: expected a mapping, got {type(raw).__name__}")
    items: list[Node] = []
    for key, value in raw.items():
        at = f"{where}.{key}" if where else str(key)
        if key in ("and", "or"):
            if not isinstance(value, list | tuple) or not value:
                raise FilterError(f"{at}: expected a non-empty list of conditions")
            parts = tuple(_parse(v, f"{at}[{i}]", depth + 1, count) for i, v in enumerate(value))
            items.append(And(parts) if key == "and" else Or(parts))
        elif key == "not":
            items.append(Not(_parse(value, at, depth + 1, count)))
        else:
            items += _field_ops(_field(key, at), value, at, count)
    if not items:
        raise FilterError(f"{where or 'filter'}: empty")
    return items[0] if len(items) == 1 else And(tuple(items))


def parse(raw: Mapping[str, Any] | Node | None) -> Node | None:
    """A filter mapping (or an already parsed one) as a validated tree; None or {} = no filter."""
    if raw is None or isinstance(raw, Cmp | And | Or | Not):
        return raw
    if not isinstance(raw, Mapping):
        raise FilterError(f"filter: expected a mapping, got {type(raw).__name__}")
    if not raw:
        return None
    return _parse(raw, "", 0, _Counter())


def validate(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Check a filter and return it as plain JSON-able data (what an API stores and caches)."""
    node = parse(raw)
    return to_dict(node) if node is not None else {}


def to_dict(node: Node) -> dict[str, Any]:
    """The canonical mapping of a tree: parse(to_dict(n)) == n."""
    if isinstance(node, And):
        return {"and": [to_dict(i) for i in node.items]}
    if isinstance(node, Or):
        return {"or": [to_dict(i) for i in node.items]}
    if isinstance(node, Not):
        return {"not": to_dict(node.item)}
    value = list(node.value) if isinstance(node.value, tuple) else node.value
    return {node.field: {node.op: value}}


def combine(*filters: Mapping[str, Any] | None) -> dict[str, Any]:
    """AND several filters (e.g. the caller's and the one self-query found); {} = none."""
    parts = [to_dict(n) for f in filters if (n := parse(f)) is not None]
    return {} if not parts else parts[0] if len(parts) == 1 else {"and": parts}


def canonical(raw: Mapping[str, Any] | None) -> str:
    """A stable string for cache keys: equal filters, equal strings (the order of the conditions
    of an and/or doesn't matter)."""

    def norm(d: Any) -> Any:
        if isinstance(d, dict):
            return {
                k: sorted((norm(i) for i in v), key=_dumps) if k in ("and", "or") else norm(v)
                for k, v in d.items()
            }
        return d

    return _dumps(norm(validate(raw)))


def _dumps(d: Any) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def fields(node: Node | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, And | Or):
        return set().union(*(fields(i) for i in node.items))
    if isinstance(node, Not):
        return fields(node.item)
    return {node.field}


# ================================================================ Python (the in-memory stores)


def _as_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str) and ISO_DATE.match(value):
        try:
            t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return t if t.tzinfo else t.replace(tzinfo=UTC)
    return None


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _compare(have: Any, op: str, want: Any) -> bool:
    if isinstance(want, str):  # dates: both sides must be dates
        a, b = _as_time(have), _as_time(want)
        if a is None or b is None:
            return False
    elif _number(have):
        a, b = have, want
    else:
        return False
    return bool(a > b if op == "gt" else a >= b if op == "gte" else a < b if op == "lt" else a <= b)


def _values(have: Any) -> list[Any]:
    if have is None:
        return []
    return list(have) if isinstance(have, list | tuple | set) else [have]


def _same(a: Any, b: Any) -> bool:
    """Equal, but True never equals 1 (JSON keeps them apart; so do the real stores)."""
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def _eval(node: Node, get: Callable[[str], Any]) -> bool:
    if isinstance(node, And):
        return all(_eval(i, get) for i in node.items)
    if isinstance(node, Or):
        return any(_eval(i, get) for i in node.items)
    if isinstance(node, Not):
        return not _eval(node.item, get)
    have = _values(get(node.field))
    if node.op == "exists":
        return bool(have) is bool(node.value)
    if node.op in ("eq", "ne"):
        found = any(_same(h, node.value) for h in have)
        return found if node.op == "eq" else not found
    if node.op in ("in", "nin"):
        found = any(_same(h, w) for h in have for w in node.value)
        return found if node.op == "in" else not found
    return any(_compare(h, node.op, node.value) for h in have)


def matcher(raw: Mapping[str, Any] | Node | None) -> Callable[[Any], bool]:
    """A test for a Chunk: does its metadata (and document) satisfy the filter?"""
    node = parse(raw)
    if node is None:
        return lambda chunk: True

    def test(chunk: Any) -> bool:
        def get(name: str) -> Any:
            return chunk.document_uri if name == DOCUMENT else chunk.metadata.get(name)

        return _eval(node, get)

    return test


# ================================================================ Postgres (pgvector, full-text)


class SqlBuilder:
    """A WHERE fragment with every VALUE as a bound parameter (never pasted into the SQL).
    Field names are validated identifiers but are ALSO passed as parameters."""

    def __init__(self, params: dict[str, Any], metadata: str = "c.metadata",
                 document: str = "d.source_uri", prefix: str = "f") -> None:  # fmt: skip
        self.params, self.meta, self.doc, self.prefix = params, metadata, document, prefix
        self._n = 0

    def _p(self, value: Any) -> str:
        name = f"{self.prefix}{self._n}"
        self._n += 1
        self.params[name] = value
        return f"%({name})s"

    def build(self, node: Node) -> str:
        if isinstance(node, And | Or):
            joiner = " AND " if isinstance(node, And) else " OR "
            return "(" + joiner.join(self.build(i) for i in node.items) + ")"
        if isinstance(node, Not):
            return f"(NOT coalesce({self.build(node.item)}, false))"
        return self._cmp(node)

    def _jsonb(self, value: Any) -> str:
        return f"{self._p(json.dumps(value))}::jsonb"

    def _cmp(self, n: Cmp) -> str:
        if n.field == DOCUMENT:
            return self._document(n)
        key = self._p(n.field)
        val = f"({self.meta} -> {key})"
        if n.op == "exists":
            present = f"coalesce({val} NOT IN ('null'::jsonb, '[]'::jsonb), false)"
            return present if n.value else f"(NOT {present})"
        if n.op in ("eq", "ne"):
            # jsonb containment: "hr" @> "hr", and an array contains its elements: ["a","hr"] @> "hr"
            hit = f"coalesce({val} @> {self._jsonb(n.value)}, false)"
            return hit if n.op == "eq" else f"(NOT {hit})"
        if n.op in ("in", "nin"):
            hit = (
                "("
                + " OR ".join(f"coalesce({val} @> {self._jsonb(v)}, false)" for v in n.value)
                + ")"
            )
            return hit if n.op == "in" else f"(NOT {hit})"
        sym = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[n.op]
        if isinstance(n.value, str):  # a date: compared as a timestamp; bad data is simply no match
            elems = f"jsonb_array_elements_text(CASE WHEN jsonb_typeof({val}) = 'array' THEN {val} ELSE jsonb_build_array({val}) END)"
            ts = self._p(n.value)
            return (f"coalesce(EXISTS (SELECT 1 FROM {elems} e(v) WHERE "
                    f"rag.safe_timestamptz(e.v) {sym} rag.safe_timestamptz({ts})), false)")  # fmt: skip
        elems = f"jsonb_array_elements(CASE WHEN jsonb_typeof({val}) = 'array' THEN {val} ELSE jsonb_build_array({val}) END)"
        num = self._p(n.value)
        return (f"coalesce(EXISTS (SELECT 1 FROM {elems} e(v) WHERE jsonb_typeof(e.v) = 'number' "
                f"AND (e.v #>> '{{}}')::numeric {sym} {num}), false)")  # fmt: skip

    def _document(self, n: Cmp) -> str:
        if n.op == "exists":
            return "true" if n.value else "false"
        if n.op in ("eq", "ne"):
            return f"({self.doc} {'=' if n.op == 'eq' else '<>'} {self._p(str(n.value))})"
        if n.op in ("in", "nin"):
            hit = f"({self.doc} = ANY({self._p([str(v) for v in n.value])}))"
            return hit if n.op == "in" else f"(NOT {hit})"
        raise FilterError(f"{DOCUMENT}: only eq, ne, in, nin and exists apply to the document")


def to_sql(raw: Mapping[str, Any] | Node | None, params: dict[str, Any], *,
           metadata: str = "c.metadata", document: str = "d.source_uri") -> str:  # fmt: skip
    """' AND (…)' to append to a WHERE clause that already holds the permission filter, or ''."""
    node = parse(raw)
    if node is None:
        return ""
    return f" AND {SqlBuilder(params, metadata, document).build(node)}"


# ================================================================ Qdrant


def _qkey(name: str) -> str:
    return "source_uri" if name == DOCUMENT else f"metadata.{name}"


def _qmatch(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, float) and not value.is_integer():
        return {
            "key": key,
            "range": {"gte": value, "lte": value},
        }  # Qdrant matches only exact keywords/ints
    if isinstance(value, float):
        value = int(value)
    return {"key": key, "match": {"value": value}}


def _qany(key: str, values: Sequence[Any]) -> dict[str, Any]:
    if all(isinstance(v, str) for v in values) or all(
        isinstance(v, int) and not isinstance(v, bool) for v in values
    ):
        return {"key": key, "match": {"any": list(values)}}
    return {"should": [_qmatch(key, v) for v in values]}


def to_qdrant(raw: Mapping[str, Any] | Node | None) -> dict[str, Any] | None:
    """A Qdrant condition (a nested filter), to put in the `must` list after the access filter."""
    node = parse(raw)
    return None if node is None else _q(node)


def _q(node: Node) -> dict[str, Any]:
    if isinstance(node, And):
        return {"must": [_q(i) for i in node.items]}
    if isinstance(node, Or):
        return {"should": [_q(i) for i in node.items]}
    if isinstance(node, Not):
        return {"must_not": [_q(node.item)]}
    key = _qkey(node.field)
    if node.op == "exists":
        empty = {"is_empty": {"key": key}}
        return {"must_not": [empty]} if node.value else {"must": [empty]}
    if node.op == "eq":
        return _qmatch(key, node.value)
    if node.op == "ne":
        return {"must_not": [_qmatch(key, node.value)]}
    if node.op == "in":
        return _qany(key, node.value)
    if node.op == "nin":
        return {"must_not": [_qany(key, node.value)]}
    if node.field == DOCUMENT:
        raise FilterError(f"{DOCUMENT}: only eq, ne, in, nin and exists apply to the document")
    value = node.value
    if isinstance(value, str):  # RFC 3339 for Qdrant's datetime range
        t = _as_time(value)
        if t is None:
            raise FilterError(f"{node.field}: {value!r} is not a valid date")
        value = t.isoformat()
    return {"key": key, "range": {node.op: value}}


# ================================================================ OpenSearch


def to_opensearch(raw: Mapping[str, Any] | Node | None, *, keyword_suffix: str = "") -> dict[str, Any] | None:  # fmt: skip
    """An OpenSearch query clause, to put in the bool `filter` list after the access filter.
    `keyword_suffix` (".keyword") targets the keyword sub-field of dynamically mapped strings."""
    node = parse(raw)
    return None if node is None else _os(node, keyword_suffix)


def _osfield(name: str, value: Any, suffix: str) -> str:
    if name == DOCUMENT:
        return "source_uri"
    return f"metadata.{name}{suffix if isinstance(value, str) else ''}"


def _os(node: Node, suffix: str) -> dict[str, Any]:
    if isinstance(node, And):
        return {"bool": {"filter": [_os(i, suffix) for i in node.items]}}
    if isinstance(node, Or):
        return {"bool": {"should": [_os(i, suffix) for i in node.items], "minimum_should_match": 1}}
    if isinstance(node, Not):
        return {"bool": {"must_not": [_os(node.item, suffix)]}}
    if node.op == "exists":
        field = "source_uri" if node.field == DOCUMENT else f"metadata.{node.field}"
        exists: dict[str, Any] = {"exists": {"field": field}}
        return exists if node.value else {"bool": {"must_not": [exists]}}
    if node.op in ("eq", "ne"):
        term: dict[str, Any] = {"term": {_osfield(node.field, node.value, suffix): node.value}}
        return term if node.op == "eq" else {"bool": {"must_not": [term]}}
    if node.op in ("in", "nin"):
        by_field: dict[str, list[Any]] = {}
        for v in node.value:
            by_field.setdefault(_osfield(node.field, v, suffix), []).append(v)
        parts: list[dict[str, Any]] = [{"terms": {f: vs}} for f, vs in by_field.items()]
        q: dict[str, Any] = (
            parts[0] if len(parts) == 1 else {"bool": {"should": parts, "minimum_should_match": 1}}
        )
        return q if node.op == "in" else {"bool": {"must_not": [q]}}
    if node.field == DOCUMENT:
        raise FilterError(f"{DOCUMENT}: only eq, ne, in, nin and exists apply to the document")
    value = node.value
    if isinstance(
        value, str
    ):  # a full timestamp: OpenSearch would round a bare date to its day's end
        t = _as_time(value)
        if t is None:
            raise FilterError(f"{node.field}: {value!r} is not a valid date")
        value = t.isoformat()
    return {"range": {f"metadata.{node.field}": {node.op: value}}}


__all__ = [
    "And", "Cmp", "FilterError", "Node", "Not", "Or", "canonical", "combine", "matcher", "parse",
    "to_dict", "to_opensearch", "to_qdrant", "to_sql", "validate",
]  # fmt: skip
