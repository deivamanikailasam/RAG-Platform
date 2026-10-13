"""Extension 04, the evaluation loop: retrieval and answer metrics against hand-computed values,
judges (lexical, and an LLM judge that falls back), run files, the paired A/B test, sweeps,
synthetic test sets with the review gate, feedback -> candidate items, and the exporters."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_core import evaluate as ev
from rag_core.cli import main
from rag_core.components.basics import ScriptedLLM
from rag_core.components.judges import (
    LexicalJudge,
    LexicalParams,
    LlmJudge,
    LlmJudgeParams,
    parse_scores,
)
from rag_core.evalkit import export, feedback, runs, stats, sweep, synth
from rag_core.evalkit import metrics as m
from rag_core.registry import ComponentError, Container
from rag_core.types import Access, Source

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "examples/eval/handbook.yaml"
RAG_YAML = ROOT / "rag.yaml"


# ================================================================ metrics, by hand


def test_retrieval_metrics_by_hand() -> None:
    ranked, rel = ["a", "x", "b", "y", "c"], {"a", "b", "z"}
    assert m.hit_rate(ranked, rel, 1) == 1.0
    assert m.hit_rate(["x"], rel, 1) == 0.0
    assert m.recall(ranked, rel, 5) == pytest.approx(2 / 3)
    assert m.precision(ranked, rel, 5) == pytest.approx(2 / 5)
    assert m.precision([], rel, 5) == 0.0
    assert m.reciprocal_rank(["x", "y", "b"], rel) == pytest.approx(1 / 3)
    # AP@5: hits at ranks 1 and 3 -> (1/1 + 2/3) / min(3, 5)
    assert m.average_precision(ranked, rel, 5) == pytest.approx((1 + 2 / 3) / 3)
    dcg = 1 / math.log2(2) + 1 / math.log2(4)
    idcg = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
    assert m.ndcg(ranked, rel, 5) == pytest.approx(dcg / idcg)
    assert m.retrieval_scores(ranked, rel, 5)["map"] == pytest.approx((1 + 2 / 3) / 3)


def test_answer_metrics_by_hand() -> None:
    ctx = ["Full-time staff get 25 days of annual leave per year.", "Parental leave is 18 weeks."]
    good = "Full-time staff get 25 days of annual leave [doc 1]."
    half = good + " Staff also receive a free company car and gym membership [doc 2]."
    assert m.faithfulness(good, ctx) == 1.0
    assert m.faithfulness(half, ctx) == 0.5
    assert m.faithfulness("Staff get 30 days of annual leave.", ctx) == 0.0  # the number must match
    assert m.faithfulness("I don't know [doc 1].", ctx) is None or m.faithfulness("", ctx) is None
    assert m.answer_relevance("How many days of annual leave?", good) == 0.75  # "many" is not in it
    assert m.answer_relevance("How many days of annual leave?", "[doc 1]") is None
    assert m.context_precision(["a", "x", "b"], {"a", "b"}) == pytest.approx((1 + 2 / 3) / 2)
    assert m.context_precision([], {"a"}) is None
    assert m.context_recall("Staff get 25 days of annual leave.", ctx) == 1.0
    assert m.context_recall(None, ctx, ["a"], {"a", "b"}) == 0.5
    assert m.correctness(good, "Full-time staff get 25 days of annual leave.") == pytest.approx(1.0)
    assert (
        m.correctness("Staff get 20 days of annual leave.", "Staff get 25 days of annual leave.")
        == 0.0
    )
    assert m.correctness(good, None) is None
    assert m.citation_precision({"a", "x"}, {"a"}) == 0.5
    assert m.citation_recall({"a"}, {"a", "b"}) == 0.5
    assert m.citation_precision(set(), {"a"}) is None
    assert m.abstention_correct(True, False) == 1.0
    assert m.abstention_correct(True, True) == 0.0
    assert m.mean([1.0, None, 0.0]) == 0.5
    assert m.mean([None]) is None


# ================================================================ judges


def test_lexical_and_llm_judges() -> None:
    ctx = ["Full-time staff get 25 days of annual leave per year."]
    lex = LexicalJudge(LexicalParams()).score(
        "How many days?", "Staff get 25 days [doc 1].", ctx, None
    )
    assert lex["faithfulness"] == 1.0
    assert lex["correctness"] is None
    good = LlmJudge(ScriptedLLM(default='{"faithfulness": 0.9, "answer_relevance": 1, "correctness": null}'),
                    LlmJudgeParams())  # fmt: skip
    got = good.score("q", "Staff get 25 days.", ctx, None)
    assert got == {"faithfulness": 0.9, "answer_relevance": 1.0, "correctness": None}
    bad = LlmJudge(ScriptedLLM(default='{"faithfulness": "high"}'), LlmJudgeParams())
    got = bad.score("How many days?", "Staff get 25 days.", ctx, None)
    assert got["judge_error"] == 1.0
    assert got["faithfulness"] == 1.0
    assert bad.errors == 1
    with pytest.raises(ValueError, match="no JSON"):
        parse_scores("no json here")
    with pytest.raises(ValueError, match="between 0 and 1"):
        parse_scores('{"faithfulness": 1.5}')
    assert (
        parse_scores(
            '<think>hmm</think>{"faithfulness": 1, "answer_relevance": 0, "correctness": 0.5}'
        )["correctness"]
        == 0.5
    )


# ================================================================ eval-search / eval-answers additions


def test_search_scores_have_hit_rate_precision_and_map() -> None:
    doc = ev.load_dataset(DATASET)
    conf = ev.variant_configs(RAG_YAML, "offline", doc, ["keyword"])["keyword"]
    s = ev.run_variant("keyword", conf, doc, DATASET.parent)
    row = s.row()
    assert {"hit_rate", "precision", "map"} <= set(row)
    assert row["hit_rate"] >= row["recall"] - 1e-9
    assert "hit@5" in ev.format_table([s], 5)
    assert "MAP" in ev.format_table([s], 5)


def _answers_run(tmp_path: Path, arch: str = "standard", **extra: Any) -> dict[str, Any]:
    doc = ev.load_dataset(DATASET)
    doc["questions"] = doc["questions"][:8]
    doc["questions"][0] = {
        **doc["questions"][0],
        "reference": "Full-time staff get 25 days of annual leave per year.",
    }
    conf = ev.variant_configs(RAG_YAML, "offline", doc, [arch], key="architectures")[arch] | extra
    s = ev.run_answers(arch, conf, doc, DATASET.parent)
    return runs.make_run(s, suite="answers", profile="offline", dataset=DATASET)


def test_answer_scores_judged_metrics_and_run_file(tmp_path: Path) -> None:
    run = _answers_run(tmp_path)
    summary = run["summary"]
    assert summary["faithfulness"] is not None
    assert summary["correctness"] is not None
    first = run["cases"][0]
    assert first["reference"]
    assert first["contexts"]
    assert first["answer"]
    assert {"faithfulness", "relevance", "context_precision", "correctness", "citation_precision",
            "citation_recall", "context_recall", "abstention_correct"} <= set(first["metrics"])  # fmt: skip
    [path] = runs.write_runs(tmp_path / "out", [run])
    assert path.name == "standard.answers.json"
    assert runs.load_run(path)["format"] == runs.FORMAT
    assert "faithfulness" in runs.metrics_in(run)
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(ComponentError):
        runs.load_run(bad)


def test_a_configured_llm_judge_is_used(tmp_path: Path) -> None:
    run = _answers_run(tmp_path, judge={"use": "llm", "llm_slot": "llm"},
                       llm={"use": "scripted", "default": '{"faithfulness": 0.5, "answer_relevance": 0.5, "correctness": 0.5}'})  # fmt: skip
    assert run["judge"] == "llm"
    assert run["summary"]["faithfulness"] == 0.5


def test_reviewed_only_drops_pending_questions() -> None:
    doc = {"questions": [{"id": "a"}, {"id": "b", "review": "pending"}, {"id": "c", "review": "rejected"},
                         {"id": "d", "review": "approved"}]}  # fmt: skip
    kept, skipped = ev.reviewed_only(doc)
    assert [q["id"] for q in kept["questions"]] == ["a", "d"]
    assert skipped == 2
    kept, skipped = ev.reviewed_only(doc, include_unreviewed=True)
    assert [q["id"] for q in kept["questions"]] == ["a", "b", "d"]
    assert skipped == 1


# ================================================================ A/B statistics


def test_bootstrap_and_permutation() -> None:
    assert stats.permutation_p([0, 0, 0]) == 1.0
    # five positive differences: only the all-positive and all-negative sign patterns are as extreme
    assert stats.permutation_p([1, 1, 1, 1, 1]) == pytest.approx(2 / 32)
    lo, hi = stats.bootstrap_ci([1.0] * 10)
    assert lo == hi == 1.0
    big = stats.permutation_p([0.1] * 30, resamples=2000)
    assert big < 0.01


def test_compare_verdicts() -> None:
    a = {str(i): 0.5 for i in range(20)}
    b = {str(i): 0.9 for i in range(20)}
    assert stats.compare(a, b, "faithfulness").verdict == "B better"
    assert stats.compare(b, a, "faithfulness").verdict == "A better"
    assert stats.compare(a, a, "faithfulness").verdict == "no significant difference"
    assert stats.compare({"1": 1.0}, {"1": 0.0}, "x").verdict == "too few"
    assert stats.compare(a, b, "p50_ms").verdict == "A better"  # lower is better for latency
    noisy = {str(i): (0.9 if i % 2 else 0.1) for i in range(20)}
    shifted = {
        str(i): (0.95 if i % 2 else 0.06) for i in range(20)
    }  # +0.05 half the time, -0.04 the rest
    assert stats.compare(noisy, shifted, "x").verdict == "no significant difference"


def test_eval_compare_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "runs"
    assert (
        main(
            [
                "eval-answers",
                str(DATASET),
                "--file",
                str(RAG_YAML),
                "--profile",
                "offline",
                "--variant",
                "naive",
                "--variant",
                "standard",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["eval-compare", "--runs", str(out / "naive.answers.json"), str(out / "standard.answers.json"),
                 "--json"]) == 0  # fmt: skip
    res = json.loads(capsys.readouterr().out)
    cp = next(c for c in res["comparisons"] if c["metric"] == "context_precision")
    assert cp["verdict"] == "B better"
    assert cp["diff"] > 0
    assert main(["eval-compare", "--runs", str(out / "standard.answers.json"), str(out / "naive.answers.json"),
                 "--metric", "context_precision", "--fail-if-worse"]) == 1  # fmt: skip
    assert main(["eval-compare", str(DATASET), "--file", str(RAG_YAML), "--profile", "offline", "--suite", "search",
                 "--a", "dense", "--b", "hybrid+rerank", "--metric", "recall"]) == 0  # fmt: skip
    assert "hybrid+rerank" in capsys.readouterr().out


# ================================================================ sweeps


def test_grid_overrides_and_ranking() -> None:
    assert sweep.overrides({"chunker.max_tokens": 200, "fusion": "rrf"}) == {
        "chunker": {"max_tokens": 200},
        "fusion": "rrf",
    }
    assert sweep.overrides({"fusion": "weighted", "fusion.k": 10}) == {
        "fusion": {"use": "weighted", "k": 10}
    }
    combos = sweep.combinations({"a": [1, 2], "b": ["x", {"use": "y", "n": 3}]})
    assert [c[0] for c in combos] == ["a=1 b=x", "a=1 b=y(n=3)", "a=2 b=x", "a=2 b=y(n=3)"]
    assert sweep.parse_set(["reranker=none,term-overlap", "chunker.max_tokens=200,400"]) == {
        "reranker": ["none", "term-overlap"], "chunker.max_tokens": [200, 400]}  # fmt: skip
    rows = [{"variant": "a", "ndcg": 0.9, "leaks": 1}, {"variant": "b", "ndcg": 0.8, "leaks": 0, "p50_ms": 2.0},
            {"variant": "c", "ndcg": 0.8, "leaks": 0, "p50_ms": 1.0}]  # fmt: skip
    assert [r["variant"] for r in sweep.rank(rows, "ndcg")] == [
        "c",
        "b",
        "a",
    ]  # leaks last, ties by speed
    with pytest.raises(ComponentError):
        sweep.check_grid({"a": []})
    with pytest.raises(ComponentError):
        sweep.parse_set(["novalue"])


def test_eval_sweep_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    grid = tmp_path / "sweep.yaml"
    grid.write_text(
        "grid:\n  retriever: [dense, hybrid]\n  chunker.max_tokens: [200, 400]\nfixed: {reranker: none}\n"
    )
    assert main(["eval-sweep", str(DATASET), "--file", str(RAG_YAML), "--profile", "offline",
                 "--grid", str(grid), "--rank-by", "mrr", "--json"]) == 0  # fmt: skip
    res = json.loads(capsys.readouterr().out)
    assert res["rank_by"] == "mrr"
    assert len(res["rows"]) == 4
    assert res["rows"][0]["mrr"] >= res["rows"][-1]["mrr"]
    assert main(["eval-sweep", str(DATASET), "--file", str(RAG_YAML), "--profile", "offline",
                 "--set", "retriever=dense,keyword", "--rank-by", "nonsense"]) == 1  # fmt: skip
    assert (
        main(
            [
                "eval-sweep",
                str(DATASET),
                "--set",
                "a=1,2,3",
                "--set",
                "b=1,2",
                "--max-combinations",
                "4",
            ]
        )
        == 1
    )


# ================================================================ synthetic test sets and review


def test_template_questions() -> None:
    q = synth.template_question(
        "Full-time staff get 25 days of annual leave per year.", "Leave", ["staff"]
    )
    assert (
        q
        == 'In "Leave", what number fills the gap: "Full-time staff get ___ days of annual leave per year"?'
    )
    q = synth.template_question(
        "Gifts must be declared to your manager.", "Code of conduct", ["gifts", "declared", "gifts"]
    )
    assert q == 'What does "Code of conduct" say about gifts and declared?'


def _corpus_container() -> Container:
    import yaml as _y

    from rag_core import config as cfg

    return Container(cfg.resolve(_y.safe_load(RAG_YAML.read_text()), "offline", env={}), "gen")


def test_generate_items_with_evidence_offsets() -> None:
    text = (b"# Expenses\n\nSubmit expense claims within 30 days of spending. Receipts are required for "
            b"anything over 20 dollars. Alcohol is reimbursed only at client dinners.\n")  # fmt: skip
    src = Source("file:///x/expenses.md", text, "text/markdown", Access("internal", ("all-staff",)))
    items = synth.generate(_corpus_container(), [src], per_document=3)
    assert 2 <= len(items) <= 3
    assert len({i["question"] for i in items}) == len(items)
    for it in items:
        assert it["review"] == "pending"
        assert it["relevant"] == ["expenses.md"]
        assert "synthetic" in it["tags"]
        ev_ = it["evidence"]
        assert ev_["quote"] == it["reference"]
    # the LLM path: a reply whose quote isn't in the passage is refused (template used instead)
    liar = ScriptedLLM(
        default='{"question": "Q?", "answer": "Claims within 30 days", "quote": "made up sentence entirely"}'
    )
    items = synth.generate(_corpus_container(), [src], per_document=1, mode="llm", llm=liar)
    assert items[0]["generated_by"] == "template"
    honest = ScriptedLLM(default='{"question": "How long do I have to claim expenses?", "answer": "Within 30 days of spending.", '
                                 '"quote": "Submit expense claims within 30 days of spending."}')  # fmt: skip
    items = synth.generate(_corpus_container(), [src], per_document=1, mode="llm", llm=honest)
    assert items[0]["question"] == "How long do I have to claim expenses?"
    assert items[0]["generated_by"].startswith("llm:")


def test_generate_review_and_evaluate_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "gen" / "generated.yaml"
    assert main(["eval-generate", "--from", str(DATASET), "--file", str(RAG_YAML), "--profile", "offline",
                 "--per-document", "1", "--out", str(out)]) == 0  # fmt: skip
    doc = yaml.safe_load(out.read_text())
    assert (
        len(doc["questions"]) == 16
    )  # every document the dataset's person may read: not the exec one
    assert all(q["review"] == "pending" for q in doc["questions"])
    assert (out.parent / doc["corpus"][0]["uri"]).resolve().is_file()  # corpus paths still resolve
    assert main(["eval-review", str(out), "--check"]) == 1
    first, second = doc["questions"][0]["id"], doc["questions"][1]["id"]
    assert main(["eval-review", str(out), "--approve", first, "--reject", second]) == 0
    after = {q["id"]: q["review"] for q in yaml.safe_load(out.read_text())["questions"]}
    assert after[first] == "approved"
    assert after[second] == "rejected"
    assert list(after.values()).count("pending") == 14
    capsys.readouterr()
    # only the approved question is evaluated
    assert (
        main(["eval-search", str(out), "--file", str(RAG_YAML), "--profile", "offline", "--json"])
        == 0
    )
    res = json.loads(capsys.readouterr().out)
    assert list(res[0]["per_case"]) == [first]


def test_generate_from_source_folder(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.md").write_text(
        "# Laptops\n\nReport a lost laptop to IT within 24 hours of noticing.\n"
    )
    out = tmp_path / "g.yaml"
    assert main(["eval-generate", "--source", str(folder), "--group", "all-staff", "--file", str(RAG_YAML),
                 "--profile", "offline", "--out", str(out)]) == 0  # fmt: skip
    doc = yaml.safe_load(out.read_text())
    assert doc["corpus"][0]["uri"] == "docs/a.md"
    assert doc["principal"]["groups"] == ["all-staff"]


# ================================================================ feedback -> candidates


EVENTS = [
    {"action": "answer", "outcome": "success", "trace_id": "t1",
     "details": {"answer_id": "ans-1", "result": "answered", "cited_ids": [3], "context_ids": [3, 4], "release": "r2"}},
    {"action": "answer", "outcome": "success", "trace_id": "t2",
     "details": {"answer_id": "ans-2", "result": "answered", "cited_ids": [1], "release": "r2",
                 "guards": [{"guard": "groundedness", "action": "flag"}]}},
    {"action": "answer", "outcome": "success", "trace_id": "t3",
     "details": {"answer_id": "ans-3", "result": "answered", "cited_ids": [1], "release": "r2"}},
    {"action": "feedback", "outcome": "success", "resource": "answer:ans-1", "details": {"rating": "down", "reason": "wrong"}},
    {"action": "feedback", "outcome": "success", "resource": "answer:ans-3", "details": {"rating": "up"}},
]  # fmt: skip


def test_feedback_candidates(tmp_path: Path) -> None:
    texts = {
        "ans-1": {"answer_id": "ans-1", "question": "How many leave days?", "answer": "40 days."}
    }
    items = feedback.candidates(EVENTS, texts)
    by = {i["source"]["answer_id"]: i for i in items}
    assert set(by) == {"ans-1", "ans-2"}  # the thumbs-up answer is not a candidate
    assert by["ans-1"]["question"] == "How many leave days?"
    assert by["ans-1"]["rated_answer"] == "40 days."
    assert by["ans-2"]["question"].startswith("TODO: copy the question from trace t2")
    assert all(i["review"] == "pending" and i["relevant"] == [] for i in items)
    assert "thumbs" in by["ans-1"]["tags"]
    assert by["ans-1"]["source"]["why"] == ["thumbs down (wrong)"]
    # appending keeps the file's comments and doesn't add an answer twice
    ds = tmp_path / "ds.yaml"
    ds.write_text(
        '# my dataset\nversion: 1\nquestions:\n  - {id: q1, question: "Hi?", relevant: [a.md]}\n'
    )
    assert feedback.append_to(ds, items) == 2
    assert (
        feedback.append_to(
            ds,
            feedback.candidates(EVENTS, texts, feedback.existing_answer_ids(ev.load_dataset(ds))),
        )
        == 0
    )
    text = ds.read_text()
    assert text.startswith("# my dataset")
    assert len(yaml.safe_load(text)["questions"]) == 3
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nquestions: []\nk: 5\n")
    with pytest.raises(ValueError, match="last top-level key"):
        feedback.append_to(bad, items)


def test_eval_candidates_command(tmp_path: Path) -> None:
    events = tmp_path / "audit.jsonl"
    events.write_text("".join(json.dumps(e) + "\n" for e in EVENTS))
    out = tmp_path / "cand.yaml"
    assert main(["eval-candidates", "--events", str(events), "--out", str(out)]) == 0
    assert len(yaml.safe_load(out.read_text())["questions"]) == 2


# ================================================================ exporters


def test_exporters_shapes(tmp_path: Path) -> None:
    run = _answers_run(tmp_path)
    ragas = [json.loads(x) for x in export.export(run, "ragas").splitlines()]
    assert set(ragas[0]) == {"user_input", "retrieved_contexts", "response", "reference"}
    assert "reference" not in ragas[1]
    deep = json.loads(export.export(run, "deepeval"))
    assert {"input", "actual_output", "expected_output", "retrieval_context"} <= set(deep[0])
    pf = yaml.safe_load(export.export(run, "promptfoo"))
    assert pf["providers"] == ["echo"]
    assert pf["prompts"] == ["{{answer}}"]
    assert {a["type"] for a in pf["tests"][0]["assert"]} >= {"context-faithfulness", "factuality"}
    tl = json.loads(export.export(run, "trulens"))
    assert tl[0]["calls"]["retriever"]["rets"]
    assert tl[0]["main_output"]
    spans = [json.loads(x) for x in export.export(run, "phoenix").splitlines()]
    root, child = spans[0], spans[1]
    assert root["span_kind"] == "CHAIN"
    assert child["span_kind"] == "RETRIEVER"
    assert child["parent_id"] == root["context.span_id"]
    assert child["context.trace_id"] == root["context.trace_id"]
    with pytest.raises(ValueError, match="unknown export target"):
        export.export(run, "nope")
    with pytest.raises(ValueError, match="answers run"):
        export.export({**run, "suite": "search"}, "ragas")
    path = tmp_path / "run.json"
    path.write_text(json.dumps(run))
    assert (
        main(["eval-export", str(path), "--to", "ragas", "--out", str(tmp_path / "r.jsonl")]) == 0
    )
    assert (tmp_path / "r.jsonl").read_text().count("\n") == len(run["cases"])
