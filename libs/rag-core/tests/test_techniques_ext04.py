"""Extension 04, techniques: answer formatters (citation styles and quotes, JSON with a schema,
confidence, follow-ups), query normalisation and spelling, translation, synonyms, recency only
when asked and rolling date windows. Offline, with scripted models."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_core import config as cfg
from rag_core import evaluate as ev
from rag_core.answer import AnswerPipeline, answer_dict
from rag_core.components.basics import MemoryKeywordIndex, ScriptedLLM
from rag_core.components.formatting import (
    ANSWER_SCHEMA,
    CitationFormatter,
    CitationParams,
    ConfidenceParams,
    ConfidenceScorer,
    FollowUpParams,
    FollowUps,
    JsonAnswer,
    JsonParams,
    format_all,
    spans,
    validate_json,
)
from rag_core.components.querytext import (
    NormalizeParams,
    QueryNormalizer,
    QueryTranslator,
    TranslateParams,
    detect_query_language,
    edit_distance,
)
from rag_core.components.retrieval import RecencyBoost, RecencyParams, TermExpander
from rag_core.components.selfquery import SelfQuery, SelfQueryParams
from rag_core.registry import Container
from rag_core.types import Access, Answer, Chunk, Citation, Principal, Query, ScoredChunk

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "examples/eval/handbook.yaml"
STAFF = Principal("ann", ("all-staff",), ("public", "internal"))
EXEC = Principal("eve", ("executives",), ("public", "internal", "restricted"))


def offline(**slots: Any) -> dict[str, Any]:
    config = cfg.resolve(yaml.safe_load((ROOT / "rag.yaml").read_text()), "offline", env={})
    config.update(slots)
    return {k: v for k, v in config.items() if v != "none"}


def handbook(**slots: Any) -> Container:
    c = Container(offline(**slots), "test")
    ev.ingest_corpus(c, ev.load_dataset(DATASET), DATASET.parent)
    return c


def chunk(text: str, cid: str = "c1", uri: str = "doc://a", **md: Any) -> ScoredChunk:
    return ScoredChunk(
        Chunk(cid, uri, 0, text, len(text.split()), Access("public"), metadata=md), 1.0
    )


Q = Query("How many days of annual leave do staff get?", STAFF)
SOURCES = [
    chunk("Leave policy. Full-time staff get 25 days of annual leave per year. Book it in the portal.",
          "c1", "doc://leave", title="Leave policy", section="Annual leave"),
    chunk("Parental leave is 18 weeks at full pay for the primary carer.", "c2", "doc://parental",
          title="Parental leave"),
]  # fmt: skip
ANSWER = Answer("Full-time staff get 25 days of annual leave per year [doc 1].",
                (Citation(1, "c1", "doc://leave", "Leave policy"),))  # fmt: skip


# ================================================================ formatters


def test_spans_keep_character_offsets() -> None:
    text = "First one.  Second one here. Third."
    for start, end, s in spans(text):
        assert text[start:end] == s
    assert [s for _, _, s in spans(text)] == ["First one.", "Second one here.", "Third."]


def test_quotes_point_at_the_supporting_sentence() -> None:
    out = CitationFormatter(CitationParams()).format(Q, ANSWER, SOURCES)
    q = out.extras["citations"][0]
    assert q["quote"] == "Full-time staff get 25 days of annual leave per year."
    assert SOURCES[0].chunk.text[q["start"] : q["end"]] == q["quote"]
    assert q["section"] == "Annual leave"
    assert out.text == ANSWER.text


def test_footnotes_replace_markers_and_list_sources() -> None:
    out = CitationFormatter(CitationParams(style="footnotes")).format(Q, ANSWER, SOURCES)
    assert "[^1]" in out.text
    assert "[doc 1]" not in out.text
    assert out.text.endswith(
        '[^1]: Leave policy, "Full-time staff get 25 days of annual leave per year."'
    )


def test_append_quotes_and_abstentions_untouched() -> None:
    out = CitationFormatter(CitationParams(append_quotes=True)).format(Q, ANSWER, SOURCES)
    assert '> "Full-time staff get 25 days' in out.text
    idk = Answer("I don't know based on the available documents.", abstained=True)
    assert CitationFormatter(CitationParams()).format(Q, idk, SOURCES) == idk


def test_confidence_signals_and_labels() -> None:
    scorer = ConfidenceScorer(ConfidenceParams())
    out = scorer.format(Q, ANSWER, SOURCES)
    conf = out.extras["confidence"]
    assert conf["signals"]["support"] == 1.0
    assert conf["signals"]["citations"] == 1.0
    assert conf["label"] == "high"
    assert 0.75 <= conf["score"] <= 1.0
    wrong = Answer("Staff get 40 days of paid sabbatical every month.")  # unsupported, uncited
    low = scorer.format(Q, wrong, SOURCES).extras["confidence"]
    assert low["label"] == "low"
    assert low["signals"]["support"] == 0.0


def test_confidence_can_abstain_below_a_floor() -> None:
    wrong = Answer("Staff get 40 days of paid sabbatical every month.")
    out = ConfidenceScorer(ConfidenceParams(abstain_below=0.5)).format(Q, wrong, SOURCES)
    assert out.abstained
    assert out.text.startswith("I don't know")
    assert not out.citations
    assert "confidence" in out.trace["abstained_reason"]
    with pytest.raises(ValueError, match="weights"):
        ConfidenceParams(weights={"vibes": 1.0})


def test_follow_ups_heuristic_and_llm_checked_against_sources() -> None:
    f = FollowUps(FollowUpParams(n=2))
    got = f.format(Q, ANSWER, SOURCES).extras["follow_ups"]
    assert got
    assert all(q.endswith("?") for q in got)
    assert all("Parental" not in q for q in got)  # an uncited, unrelated source isn't suggested
    llm = ScriptedLLM(
        default="- Where do I book annual leave in the portal?\n- What is the CEO's salary?"
    )
    got = FollowUps(FollowUpParams(mode="llm"), llm).format(Q, ANSWER, SOURCES).extras["follow_ups"]
    assert got == ["Where do I book annual leave in the portal?"]  # the ungrounded one is dropped
    broken = ScriptedLLM(fn=lambda s, u: (_ for _ in ()).throw(RuntimeError("down")))
    assert (
        FollowUps(FollowUpParams(mode="llm"), broken)
        .format(Q, ANSWER, SOURCES)
        .extras["follow_ups"]
    )


def test_json_schema_validator() -> None:
    schema = {"type": "object", "required": ["days"], "additionalProperties": False,
              "properties": {"days": {"type": "integer", "minimum": 0}, "unit": {"enum": ["days", "weeks"]}}}  # fmt: skip
    assert validate_json({"days": 25, "unit": "days"}, schema) == []
    errs = validate_json({"days": "25", "unit": "years", "x": 1}, schema)
    assert any("expected integer" in e for e in errs)
    assert any("not one of" in e for e in errs)
    assert any("unexpected 'x'" in e for e in errs)
    assert validate_json({}, schema) == ["$: missing 'days'"]
    assert validate_json(True, {"type": "integer"})  # a bool is not an integer
    assert validate_json([1, 2, 3], {"type": "array", "maxItems": 2, "items": {"type": "number"}})


def test_json_answer_offline_and_with_model_fields() -> None:
    out = JsonAnswer(JsonParams()).format(Q, ANSWER, SOURCES)
    obj = out.extras["json"]
    assert out.extras["json_valid"]
    assert validate_json(obj, ANSWER_SCHEMA) == []
    assert obj["citations"] == [{"n": 1, "title": "Leave policy"}]
    assert obj["abstained"] is False
    fields = {"type": "object", "required": ["days"], "properties": {"days": {"type": "integer"}}}
    replies = iter(
        ['{"days": "twenty-five"}', 'Sure: {"days": 25}']
    )  # invalid, then fixed on retry
    llm = ScriptedLLM(fn=lambda s, u: next(replies))
    out = JsonAnswer(JsonParams(fields=fields, as_text=True), llm).format(Q, ANSWER, SOURCES)
    assert out.extras["json"]["fields"] == {"days": 25}
    assert json.loads(out.text)["fields"] == {"days": 25}
    bad = ScriptedLLM(default='{"days": "many"}')
    out = JsonAnswer(JsonParams(fields=fields, retries=1), bad).format(Q, ANSWER, SOURCES)
    assert "fields" not in out.extras["json"]
    assert not out.extras["json_valid"]
    assert any("expected integer" in e for e in out.extras["json_errors"])


def test_formatters_in_the_pipeline_and_a_failing_one_is_skipped() -> None:
    c = handbook(
        answer_formatters=["confidence", {"use": "citations", "style": "footnotes"}, "json"]
    )
    a = AnswerPipeline(c).answer("How many days a week can I work from home?", STAFF)
    assert a.extras["confidence"]["label"] in ("high", "medium")
    assert "[^1]" in a.text
    assert a.extras["json"]["confidence"] == a.extras["confidence"]["score"]
    assert answer_dict(a)["extras"]["json_valid"] is True
    idk = AnswerPipeline(c).answer("How big is the executive bonus pool?", STAFF)
    assert idk.abstained
    assert idk.extras["json"]["abstained"] is True

    class Boom:
        def format(self, *a: Any) -> Answer:
            raise RuntimeError("bug")

    trace: dict[str, Any] = {}
    out = format_all([Boom(), ConfidenceScorer(ConfidenceParams())], Q, ANSWER, SOURCES, trace)
    assert "confidence" in out.extras
    assert any("Boom failed" in f for f in trace["flags"])
    blocked = Answer("no", blocked="injection")
    assert format_all([ConfidenceScorer(ConfidenceParams())], Q, blocked, SOURCES, {}) is blocked


# ================================================================ query text


def test_edit_distance_counts_swaps_once() -> None:
    assert edit_distance("leave", "leave") == 0
    assert edit_distance("laeve", "leave") == 1  # adjacent swap
    assert edit_distance("anual", "annual") == 1
    assert edit_distance("abc", "xyz123", limit=2) == 3  # stopped early


def test_normalize_cleans_and_corrects_against_what_the_person_may_read() -> None:
    index = MemoryKeywordIndex()
    index.index([Chunk("1", "doc://a", 0, "annual leave and parental leave", 5, Access("internal", ("all-staff",))),
                 Chunk("2", "doc://b", 0, "executive bonus pool", 3, Access("restricted", ("executives",)))])  # fmt: skip
    n = QueryNormalizer(NormalizeParams(), index)
    assert n.clean("  How  many\u00a0days?? \u2019quoted\u2019 ") == "How many days? 'quoted'"
    assert n.transform(Query("anual leeve", STAFF)) == ["annual leave", "anual leeve"]
    # "bonuss" is one letter from a word in a document only executives may read: not corrected
    assert n.transform(Query("bonuss", STAFF))[0] == "bonuss"
    assert n.transform(Query("bonuss", EXEC))[0] == "bonus"
    keep = QueryNormalizer(NormalizeParams(protected=["leeve"], include_original=False), index)
    assert keep.transform(Query("E-4021 leeve", STAFF)) == [
        "E-4021 leeve"
    ]  # codes and protected words


def test_normalize_in_a_pipeline_finds_the_misspelt_question() -> None:
    from rag_core.search import SearchPipeline

    c = handbook(query_transformer={"use": "normalize"}, reranker="none")
    hits = (
        SearchPipeline(c).search(Query("How meny days of anual leave do I get?", STAFF, k=3)).hits
    )
    assert hits[0].chunk.document_uri.endswith("annual-leave.md")


def test_translate_passthrough_glossary_and_llm() -> None:
    assert detect_query_language("Wie viele Tage Urlaub habe ich und wann?") == "de"
    assert detect_query_language("vpn") == "und"
    q = Query("Wie viele Tage Urlaub habe ich und wann?", STAFF)
    assert QueryTranslator(TranslateParams()).transform(q) == [q.text]
    t = QueryTranslator(
        TranslateParams(mode="glossary", glossary={"urlaub": "annual leave", "tage": "days"})
    )
    out = t.transform(q)
    assert "annual leave" in out[0]
    assert "days" in out[0]
    assert out[1] == q.text
    llm = QueryTranslator(TranslateParams(mode="llm", include_original=False),
                          ScriptedLLM(default="How many days of leave do I have and when?"))  # fmt: skip
    assert llm.transform(q) == ["How many days of leave do I have and when?"]
    down = QueryTranslator(TranslateParams(mode="llm"), ScriptedLLM(fn=lambda s, u: 1 / 0))  # type: ignore[arg-type,return-value]
    assert down.transform(q) == [q.text]  # falls back to the question as asked
    english = Query("How many days of leave do I have?", STAFF)
    assert llm.transform(english) == [english.text]  # already the corpus language: no call


def test_expand_terms_synonyms_phrases_and_file(tmp_path: Path) -> None:
    old = TermExpander({"wfh": "work from home"})
    assert old.transform(Query("Can I WFH on Fridays?", STAFF)) == [
        "Can I WFH on Fridays? (work from home)"
    ]
    syn = TermExpander(
        {}, {"holiday": ["annual leave", "vacation"], "sick note": ["medical certificate"]}
    )
    assert syn.transform(Query("Do I need a sick note?", STAFF)) == [
        "Do I need a sick note? (medical certificate)"
    ]
    assert "holiday" in syn.transform(Query("How much vacation?", STAFF))[0]  # both directions
    v = TermExpander({"mfa": "multi-factor authentication"}, mode="variants")
    assert v.transform(Query("mfa codes", STAFF)) == [
        "mfa codes",
        "mfa codes multi-factor authentication",
    ]
    f = tmp_path / "glossary.yaml"
    f.write_text("terms: {sev1: severity one incident}\nsynonyms: {laptop: [notebook]}\n")
    c = Container({"query_transformer": {"use": "expand-terms", "file": str(f)}})
    assert (
        "severity one"
        in c.get("query_transformer").transform(Query("sev1 on my notebook", STAFF))[0]
    )


def test_recency_only_when_asked() -> None:
    old = ScoredChunk(Chunk("o", "doc://old", 0, "x", 1, metadata={"updated": "2021-01-01"}), 1.0)
    new = ScoredChunk(Chunk("n", "doc://new", 0, "x", 1, metadata={"updated": "2026-01-01"}), 0.9)
    boost = RecencyBoost(RecencyParams(weight=0.8, when="asked"), today=date(2026, 6, 1))
    plain = boost.process(Query("what was the leave policy?", STAFF), [old, new])
    assert [h.chunk.id for h in plain] == ["o", "n"]  # untouched
    latest = boost.process(Query("what is the latest leave policy?", STAFF), [old, new])
    assert latest[0].chunk.id == "n"


def test_self_query_rolling_windows() -> None:
    sq = SelfQuery(SelfQueryParams(fields={"updated": {"type": "date"}}), today=date(2026, 10, 13))
    assert sq.by_rules("policies changed in the last 6 months") == {
        "updated": {"gte": "2026-04-16"}
    }
    assert sq.by_rules("what changed over the past year") == {"updated": {"gte": "2025-10-13"}}
    assert sq.by_rules("past 2 weeks") == {"updated": {"gte": "2026-09-29"}}
    # plain "last year" is still the calendar year
    assert sq.by_rules("what changed last year") == {
        "updated": {"gte": "2025-01-01", "lt": "2026-01-01"}
    }
