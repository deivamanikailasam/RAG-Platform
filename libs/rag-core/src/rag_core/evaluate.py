"""Compare search configurations on the same questions (Step 32).

    rag eval-search examples/eval/handbook.yaml --profile offline
    rag eval-search examples/eval/handbook.yaml --profile local --no-ingest --variant hybrid --variant hybrid+rerank

A dataset names its corpus, the person asking, the questions with the documents that answer
them (and documents that must NEVER appear), and variants: small changes to the profile.
Each variant is built fresh, ingests the corpus (unless --no-ingest), answers every question and
gets document-level scores: recall@k, MRR, nDCG@k, leaks and latency.
"""

from __future__ import annotations

import copy
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from rag_core import config as cfg
from rag_core.registry import ComponentError, Container
from rag_core.types import Access, Principal, Query, Turn


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    relevant: tuple[str, ...]  # document names (end of the URI) that answer it
    forbidden: tuple[str, ...] = ()  # documents this person must never get
    history: tuple[Turn, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass
class Scores:
    variant: str
    recall: float
    mrr: float
    ndcg: float
    leaks: int
    p50_ms: float
    per_case: dict[str, dict[str, Any]] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        return {"variant": self.variant, "recall": self.recall, "mrr": self.mrr, "ndcg": self.ndcg,
                "leaks": self.leaks, "p50_ms": self.p50_ms}  # fmt: skip


def doc_name(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


def metrics(ranked_docs: list[str], relevant: set[str], k: int) -> tuple[float, float, float]:
    """Document-level recall@k, reciprocal rank and nDCG@k (binary relevance)."""
    top = ranked_docs[:k]
    found = [d for d in top if d in relevant]
    recall = len(set(found)) / len(relevant)
    rr = next((1.0 / i for i, d in enumerate(ranked_docs, 1) if d in relevant), 0.0)
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(top, 1) if d in relevant)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return recall, rr, dcg / idcg


def load_dataset(path: Path) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ComponentError(f"{path}: {e}") from None
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ComponentError(f"{path}: expected 'version: 1'")
    return doc


def _cases(doc: dict[str, Any]) -> list[Case]:
    out = []
    for q in doc["questions"]:
        hist = tuple(Turn(t["role"], t["text"]) for t in q.get("history", []))
        out.append(Case(str(q["id"]), q["question"], tuple(q.get("relevant", [])),
                        tuple(q.get("forbidden", [])), hist, tuple(q.get("tags", []))))  # fmt: skip
    return out


def ingest_corpus(container: Container, doc: dict[str, Any], base: Path) -> int:
    """Ingest a dataset's corpus with its real access rules (used by eval-search, `rag ask --corpus`
    and the answer tests, Step 33)."""
    from rag_core.ingest import IngestionPipeline, load_source

    pipe = IngestionPipeline(container)
    n = 0
    for item in doc.get("corpus", []):
        acc = item.get("access", {})
        access = Access(acc.get("classification", "internal"), tuple(acc.get("groups", ())),
                        acc.get("tenant", "default"))  # fmt: skip
        uri = item["uri"] if "://" in item["uri"] else f"file://{(base / item['uri']).resolve()}"
        r = pipe.ingest(load_source(uri, access, item.get("metadata", {})))
        if r.status == "failed":
            raise ComponentError(f"corpus file failed to ingest: {uri}: {r.detail}")
        n += r.chunks
    return n


def run_variant(name: str, config: dict[str, Any], doc: dict[str, Any], base: Path,
                ingest: bool = True) -> Scores:  # fmt: skip
    from rag_core.search import SearchPipeline

    container = Container(config, name)
    if ingest:
        ingest_corpus(container, doc, base)
    pipeline = SearchPipeline(container)
    p = doc.get("principal", {})
    who = Principal(p.get("subject", "eval"), tuple(p.get("groups", ())),
                    tuple(p.get("classifications", ("public", "internal"))), p.get("tenant", "default"))  # fmt: skip
    k = int(doc.get("k", 5))
    recalls: list[float] = []
    rrs: list[float] = []
    ndcgs: list[float] = []
    times: list[float] = []
    leaks = 0
    per_case: dict[str, dict[str, Any]] = {}
    for case in _cases(doc):
        t0 = time.perf_counter()
        result = pipeline.search(Query(case.question, who, history=case.history, k=k))
        times.append((time.perf_counter() - t0) * 1000)
        ranked = list(dict.fromkeys(doc_name(h.chunk.document_uri) for h in result.hits))
        bad = [d for d in ranked if d in case.forbidden]
        leaks += len(bad)
        entry: dict[str, Any] = {"docs": ranked, "leaks": bad}
        if case.relevant:
            r, rr, nd = metrics(ranked, set(case.relevant), k)
            recalls.append(r)
            rrs.append(rr)
            ndcgs.append(nd)
            entry |= {"recall": round(r, 3), "rr": round(rr, 3)}
        per_case[case.id] = entry

    def avg(xs: list[float]) -> float:
        return round(statistics.fmean(xs), 3) if xs else 0.0

    return Scores(name, avg(recalls), avg(rrs), avg(ndcgs), leaks,
                  round(statistics.median(times), 1) if times else 0.0, per_case)  # fmt: skip


def variant_configs(rag_yaml: Path, profile: str, doc: dict[str, Any],
                    only: list[str] | None = None) -> dict[str, dict[str, Any]]:  # fmt: skip
    """The profile, with each variant's changes merged on top (same rules as `extends`)."""
    try:
        base_doc = yaml.safe_load(rag_yaml.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ComponentError(f"{rag_yaml}: {e}") from None
    variants = doc.get("variants") or {"as-configured": {}}
    unknown = set(only or []) - set(variants)
    if unknown:
        raise ComponentError(f"unknown variant(s) {sorted(unknown)} (have: {', '.join(variants)})")
    out = {}
    for name, changes in variants.items():
        if only and name not in only:
            continue
        d = copy.deepcopy(base_doc)
        d["profiles"]["__variant__"] = {"extends": profile, **(changes or {})}
        out[name] = cfg.resolve(d, "__variant__")
    return out


def format_table(rows: list[Scores], k: int) -> str:
    head = f"{'variant':34} {'recall@' + str(k):>9} {'MRR':>6} {'nDCG@' + str(k):>8} {'leaks':>6} {'p50 ms':>7}"
    lines = [head, "-" * len(head)]
    for s in rows:
        lines.append(
            f"{s.variant:34} {s.recall:9.3f} {s.mrr:6.3f} {s.ndcg:8.3f} {s.leaks:6d} {s.p50_ms:7.1f}"
        )
    return "\n".join(lines)


# ================================================================ guardrails (Step 34)


@dataclass
class GuardScores:
    cases: int
    attacks: int
    caught: int  # attacks the guards stopped, redacted or flagged
    benign: int
    false_positives: int  # benign cases the guards did NOT allow
    wrong: list[dict[str, Any]] = field(default_factory=list)
    known_gaps: list[dict[str, Any]] = field(
        default_factory=list
    )  # attacks we KNOW these guards miss

    @property
    def catch_rate(self) -> float:
        return round(self.caught / self.attacks, 3) if self.attacks else 1.0

    @property
    def false_positive_rate(self) -> float:
        return round(self.false_positives / self.benign, 3) if self.benign else 0.0

    def row(self) -> dict[str, Any]:
        return {"cases": self.cases, "attacks": self.attacks, "caught": self.caught,
                "catch_rate": self.catch_rate, "benign": self.benign,
                "false_positives": self.false_positives, "false_positive_rate": self.false_positive_rate,
                "wrong": self.wrong, "known_gaps": self.known_gaps}  # fmt: skip


def eval_guards(container: Container, doc: dict[str, Any]) -> GuardScores:
    """Run every case through the configured guards of its stage. `expect` is what at least one
    guard must do: block, redact, flag, or allow (= no guard may object)."""
    from dataclasses import replace

    from rag_core.components.generation import is_abstention
    from rag_core.components.guards import GeneratedAnswer
    from rag_core.types import Access, Answer, Chunk, ScoredChunk

    guards = container.get("guards") if container.has("guards") else []
    who = Principal("eval", ("all-staff",), ("public", "internal"))
    s = GuardScores(0, 0, 0, 0, 0)
    for case in doc["cases"]:
        stage, expect = case["stage"], case["expect"]
        sources = tuple(ScoredChunk(Chunk(f"s{i}", f"doc://source-{i}", i, t, len(t.split()), Access("public")), 1.0)
                        for i, t in enumerate(case.get("sources", [])))  # fmt: skip
        if stage == "output":
            payload: Any = GeneratedAnswer(
                Answer(case["text"], abstained=is_abstention(case["text"])), sources
            )
        elif stage == "context":
            payload = list(sources)
        else:
            payload = case["text"]
        actions = []
        for g in guards:
            if g.stage == stage:
                v = g.check(Query(case.get("question", case.get("text", "")), who), payload)
                if v.action != "allow":
                    actions.append(v.action)
                    if v.action == "redact" and v.replacement is not None:
                        # as in the pipeline: a corrected Answer keeps its sources
                        if isinstance(payload, GeneratedAnswer) and isinstance(
                            v.replacement, Answer
                        ):
                            payload = replace(payload, answer=v.replacement)
                        else:
                            payload = v.replacement
        if case.get("known_gap"):  # documented weakness: reported, not scored
            s.known_gaps.append({"id": case["id"], "caught": bool(actions)})
            continue
        s.cases += 1
        if expect == "allow":
            s.benign += 1
            ok = not actions
            s.false_positives += 0 if ok else 1
        else:
            s.attacks += 1
            ok = expect in actions
            s.caught += 1 if actions else 0
        if not ok:
            s.wrong.append(
                {"id": case["id"], "stage": stage, "expected": expect, "got": actions or ["allow"]}
            )
    return s


def format_guard_scores(s: GuardScores) -> str:
    lines = [
        f"{s.cases} cases: {s.attacks} attacks, {s.benign} benign",
        f"{'caught':20} {f'{s.caught}/{s.attacks}':12} catch rate {s.catch_rate:.3f}",
        f"{'false alarms ' + f'{s.false_positives}/{s.benign}':33} false positive rate {s.false_positive_rate:.3f}",
    ]  # fmt: skip
    for w in s.wrong:
        lines.append(f"   wrong {w['id']:34} expected {w['expected']}, got {', '.join(w['got'])}")
    for g in s.known_gaps:
        status = "now CAUGHT" if g["caught"] else "still missed (needs a model-based guard)"
        lines.append(f"   known gap {g['id']:38} {status}")
    return "\n".join(lines)
