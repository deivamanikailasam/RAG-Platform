"""Metadata filters (extension 01): one expression, validated once, translated for every store.
The live translations are checked on real Postgres, Qdrant and OpenSearch in test_stores.py; here
the parser, the Python reference and the exact shape of what each store is sent."""

from __future__ import annotations

from typing import Any

import pytest

from rag_core import filters as flt
from rag_core.cli import parse_filters
from rag_core.testing.conformance import FILTER_CASES, filter_chunks


def docs(expr: dict[str, Any] | None) -> set[str]:
    test = flt.matcher(expr)
    return {c.document_uri.removeprefix("doc://") for c in filter_chunks() if test(c)}


@pytest.mark.parametrize(("expr", "want"), FILTER_CASES, ids=[str(f) for f, _ in FILTER_CASES])
def test_python_reference_semantics(expr: dict[str, Any], want: set[str]) -> None:
    # the Python matcher sees f6 too (no permission filter here): only where the case can match it
    got = docs(expr) - {"f6"}
    assert got == want


def test_step_32_forms_still_mean_equal_and_any_of() -> None:
    assert flt.parse({"lang": "en"}) == flt.Cmp("lang", "eq", "en")
    assert flt.parse({"lang": ["de", "en"]}) == flt.Cmp("lang", "in", ("de", "en"))
    assert flt.parse({}) is None
    assert flt.parse(None) is None


def test_several_keys_are_anded_and_round_trip() -> None:
    node = flt.parse({"department": "hr", "updated": {"gte": "2025-01-01", "lt": "2026-01-01"}})
    assert node == flt.And((flt.Cmp("department", "eq", "hr"), flt.Cmp("updated", "gte", "2025-01-01"),
                          flt.Cmp("updated", "lt", "2026-01-01")))  # fmt: skip
    assert node is not None
    assert flt.parse(flt.to_dict(node)) == node
    assert flt.canonical({"b": 1, "a": 2}) == flt.canonical({"a": 2, "b": 1})


@pytest.mark.parametrize(("bad", "message"), [
    ({"department": {"like": "h%"}}, "unknown operator"),
    ({"bad field!": "x"}, "not a valid field name"),
    ({"updated": {"gte": "last tuesday"}}, "ISO date"),
    ({"archived": {"gt": True}}, "can't compare booleans"),
    ({"tags": {"in": []}}, "non-empty list"),
    ({"tags": None}, "use {exists: false}"),
    ({"tags": {"exists": "yes"}}, "true or false"),
    ({"or": {"a": 1}}, "non-empty list"),
    ({"a": {"range": {"near": 3}}}, "gte/gt/lte/lt"),
    ({"a": {"eq": {"nested": 1}}}, "string, number or boolean"),
    ({"a": "x" * 600}, "longer than"),
    ({"a": list(range(101))}, "more than 100 values"),
    ({"not": {"not": {"not": {"not": {"not": {"not": {"not": {"a": 1}}}}}}}}, "nested more than"),
], ids=lambda v: str(v)[:40])  # fmt: skip
def test_invalid_filters_say_what_is_wrong(bad: dict[str, Any], message: str) -> None:
    with pytest.raises(flt.FilterError, match=message):
        flt.parse(bad)


def test_filters_have_a_size_limit() -> None:
    with pytest.raises(flt.FilterError, match="too large"):
        flt.parse({"or": [{f"f{i}": i} for i in range(70)]})


def test_true_is_not_one() -> None:
    chunk = filter_chunks()[0]  # f1: version 3, archived False
    assert not flt.matcher({"archived": 0})(chunk)
    assert flt.matcher({"archived": False})(chunk)
    assert flt.matcher({"version": 3.0})(chunk)


def test_sql_binds_every_value_and_field() -> None:
    params: dict[str, Any] = {}
    sql = flt.to_sql({"department": "hr'; DROP TABLE x; --", "updated": {"gte": "2025-01-01"},
                    "document": {"in": ["doc://a"]}}, params)  # fmt: skip
    assert sql.startswith(" AND (")
    assert "DROP" not in sql
    assert "department" not in sql
    assert "2025" not in sql
    assert '"hr\'; DROP TABLE x; --"' in params.values()
    assert "department" in params.values()
    assert "rag.safe_timestamptz" in sql  # bad dates in the data are no match, never an error
    assert "d.source_uri = ANY(" in sql
    assert flt.to_sql(None, params) == ""


def test_qdrant_translation() -> None:
    q = flt.to_qdrant({"department": {"in": ["hr", "it"]}, "tags": {"exists": False},
                     "updated": {"gt": "2025-06-15"}, "score": 0.5, "not": {"document": "doc://x"}})  # fmt: skip
    assert q == {"must": [
        {"key": "metadata.department", "match": {"any": ["hr", "it"]}},
        {"must": [{"is_empty": {"key": "metadata.tags"}}]},
        {"key": "metadata.updated", "range": {"gt": "2025-06-15T00:00:00+00:00"}},
        {"key": "metadata.score", "range": {"gte": 0.5, "lte": 0.5}},  # floats: Qdrant matches no floats
        {"must_not": [{"key": "source_uri", "match": {"value": "doc://x"}}]},
    ]}  # fmt: skip
    assert flt.to_qdrant({"or": [{"a": 1}, {"b": True}]}) == {"should": [
        {"key": "metadata.a", "match": {"value": 1}}, {"key": "metadata.b", "match": {"value": True}}]}  # fmt: skip


def test_opensearch_translation() -> None:
    q = flt.to_opensearch({"department": {"nin": ["hr"]}, "version": {"lte": 3}, "lang": "en",
                         "updated": {"gte": "2025-01-01"}}, keyword_suffix=".keyword")  # fmt: skip
    assert q == {"bool": {"filter": [
        {"bool": {"must_not": [{"terms": {"metadata.department.keyword": ["hr"]}}]}},
        {"range": {"metadata.version": {"lte": 3}}},
        {"term": {"metadata.lang.keyword": "en"}},
        {"range": {"metadata.updated": {"gte": "2025-01-01T00:00:00+00:00"}}},
    ]}}  # fmt: skip


def test_document_field_takes_only_equality() -> None:
    with pytest.raises(flt.FilterError, match="only eq, ne, in, nin"):
        flt.to_qdrant({"document": {"gt": 3}})


def test_combine_ands_and_drops_empty() -> None:
    assert flt.combine({"a": 1}, None, {}) == {"a": {"eq": 1}}
    assert flt.combine({"a": 1}, {"b": 2}) == {"and": [{"a": {"eq": 1}}, {"b": {"eq": 2}}]}
    assert flt.combine() == {}


def test_cli_filter_syntax() -> None:
    assert parse_filters(["department=hr"]) == {"department": {"eq": "hr"}}
    assert parse_filters(["department=hr,it", "updated>=2025-01-01", "tags?", "version<3"]) == {"and": [
        {"department": {"in": ["hr", "it"]}}, {"updated": {"gte": "2025-01-01"}},
        {"tags": {"exists": True}}, {"version": {"lt": 3}}]}  # fmt: skip
    assert parse_filters(['{"or": [{"a": 1}, {"b": 2}]}']) == {
        "or": [{"a": {"eq": 1}}, {"b": {"eq": 2}}]
    }
    with pytest.raises(flt.FilterError):
        parse_filters(["no operator here"])
    assert parse_filters([]) == {}
