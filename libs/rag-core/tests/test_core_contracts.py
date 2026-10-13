"""The vocabulary, the contracts, rag.yaml loading, plugins and the `rag` command (Step 30).

These go beyond the guide's 21 tests: they pin down the parts every later step relies on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from rag_core import config, contracts, registry
from rag_core.cli import main as rag_cli
from rag_core.components.basics import (
    ApproxTokenCounter,
    GatewayLLM,
    HashingEmbedder,
    MemoryKeywordIndex,
    MemoryVectorStore,
    ScriptedLLM,
    matches_filters,
)
from rag_core.registry import ComponentError, Container
from rag_core.testing.conformance import ALICE, BOB, OTHER_TENANT, sample_chunks
from rag_core.types import Access, Chunk, Principal, ScoredChunk

# ---------------------------------------------------------------- the vocabulary


@pytest.mark.parametrize(
    ("access", "principal", "allowed"),
    [
        (Access("public"), Principal("anyone"), True),  # public needs no group
        (Access("internal", ("hr",)), ALICE, True),  # cleared and in the group
        (Access("internal", ("hr",)), BOB, False),  # cleared, wrong group
        (Access("confidential", ("eng",)), BOB, False),  # right group, not cleared
        (Access("internal", ("hr",)), OTHER_TENANT, False),  # everything right but the tenant
        (Access("restricted", ("hr",)), ALICE, False),  # restricted needs explicit clearance
    ],
)
def test_access_rules(access: Access, principal: Principal, allowed: bool) -> None:
    assert access.allows(principal) is allowed


def test_principal_fingerprint_ignores_order_and_identity() -> None:
    a = Principal("a", groups=("hr", "eng"), classifications=("internal", "public"))
    b = Principal("b", groups=("eng", "hr"), classifications=("public", "internal"))
    assert a.fingerprint == b.fingerprint  # same visible documents, same cache entries
    assert a.fingerprint != Principal("a", groups=("hr",)).fingerprint
    assert len(a.fingerprint) == 16


def test_chunk_ids_are_stable_and_position_sensitive() -> None:
    assert Chunk.make_id("doc://a", 0, "x") == Chunk.make_id("doc://a", 0, "x")
    assert Chunk.make_id("doc://a", 0, "x") != Chunk.make_id("doc://a", 1, "x")
    ch = Chunk("id", "doc://a", 0, "shown", 1)
    assert ch.indexed_text == "shown"
    assert Chunk("id", "doc://a", 0, "shown", 1, embed_text="A > B\nshown").indexed_text != "shown"


def test_scored_chunk_keeps_every_stage() -> None:
    sc = ScoredChunk(sample_chunks()[0], 0.4, {"dense": 0.4}).with_score(0.9, "rerank")
    assert sc.score == 0.9
    assert sc.scores == {"dense": 0.4, "rerank": 0.9}


def test_metadata_filters() -> None:
    ch = sample_chunks()[0]
    assert matches_filters(ch, None)
    assert matches_filters(ch, {"lang": "en"})
    assert matches_filters(ch, {"lang": ["de", "en"]})  # a list means "any of"
    assert not matches_filters(ch, {"lang": "de"})
    assert not matches_filters(ch, {"missing": "x"})


# ---------------------------------------------------------------- the contracts


def test_the_built_ins_satisfy_their_contracts() -> None:
    assert isinstance(ApproxTokenCounter(), contracts.TokenCounter)
    assert isinstance(HashingEmbedder(), contracts.Embedder)
    assert isinstance(ScriptedLLM(), contracts.LLM)
    assert isinstance(MemoryVectorStore(), contracts.VectorStore)
    assert isinstance(MemoryKeywordIndex(), contracts.KeywordIndex)
    assert isinstance(GatewayLLM("m", "http://gw/v1", SecretStr("")), contracts.LLM)
    assert not isinstance(MemoryKeywordIndex(), contracts.VectorStore)  # shape matters


def test_vector_store_refuses_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="differ in length"):
        MemoryVectorStore().upsert(sample_chunks(), [[1.0]])


def test_scripted_llm_matches_prompt_parts_and_records_calls() -> None:
    llm = ScriptedLLM({"leave": "20 days"}, default="I don't know.")
    assert llm.complete("system", "how much annual leave?") == "20 days"
    assert llm.complete("system", "weather?") == "I don't know."
    assert ScriptedLLM(fn=lambda s, u: u.upper()).complete("s", "hi") == "HI"
    assert len(llm.calls) == 2


# ---------------------------------------------------------------- rag.yaml


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "rag.yaml"
    p.write_text(text)
    return p


def test_load_picks_the_profile_from_the_environment(tmp_path: Path) -> None:
    p = write(
        tmp_path, "version: 1\nprofiles:\n  a: {embedder: hashing}\n  b: {vector_store: memory}\n"
    )
    assert config.load(p, env={"RAG_PROFILE": "b"}).profile == "b"
    assert config.load(p, "a", env={"RAG_PROFILE": "b"}).config == {"embedder": "hashing"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("version: 2\nprofiles: {p: {}}\n", "expected 'version: 1'"),
        ("version: 1\nprofiles: {q: {}}\n", "no profile 'p'"),
        ("version: 1\nprofiles: {p: {extends: ghost}}\n", "extends unknown 'ghost'"),
        ("- just\n- a list\n", "expected a mapping"),
        ("version: [1\n", "not valid YAML"),
    ],
)
def test_bad_files_are_explained(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ComponentError, match=message):
        config.load(write(tmp_path, text), "p", env={})


def test_a_missing_file_is_explained(tmp_path: Path) -> None:
    with pytest.raises(ComponentError, match="cannot read"):
        config.load(tmp_path / "nope.yaml", "p", env={})


def test_an_override_can_switch_on_a_slot_and_replace_a_string_entry() -> None:
    d = {"version": 1, "profiles": {"p": {"vector_store": "memory"}}}
    r = config.resolve(d, "p", env={"RAG__KEYWORD_INDEX__USE": "memory-bm25",
                                    "RAG__KEYWORD_INDEX__K1": "1.2",
                                    "RAG__VECTOR_STORE": "none"})  # fmt: skip
    assert r == {"keyword_index": {"use": "memory-bm25", "k1": 1.2}}


def test_extends_does_not_change_the_parent() -> None:
    d = {"version": 1, "profiles": {"base": {"embedder": {"use": "hashing", "dimensions": 32}},
                                    "child": {"extends": "base", "embedder": {"dimensions": 64}}}}  # fmt: skip
    config.resolve(d, "child", env={})
    assert config.resolve(d, "base", env={})["embedder"]["dimensions"] == 32


# ---------------------------------------------------------------- the Container


def test_plural_slots_build_a_list_in_order_and_refuse_a_single_entry() -> None:
    @registry.register("guard", "allow-test-a", summary="test only")
    @registry.register("guard", "allow-test-b", summary="test only")
    def _guard(p: BaseModel, c: Container) -> str:
        return "guard"

    c = Container({"guards": ["allow-test-a", {"use": "allow-test-b"}]})
    assert c.get("guards") == ["guard", "guard"]
    assert c.has("guards")
    assert not Container({"guards": []}).has("guards")
    with pytest.raises(ComponentError, match="expected a list"):
        Container({"guards": "allow-test-a"}).get("guards")
    assert Container({"guards": "allow-test-a"}).validate() == [
        "guards: expected a list of components, got 'allow-test-a'"
    ]


def test_circular_dependencies_between_components_are_refused() -> None:
    @registry.register("cache", "needs-memory-test", summary="test only")
    def _cache(p: BaseModel, c: Container) -> Any:
        return c.get("memory")

    @registry.register("memory", "needs-cache-test", summary="test only")
    def _memory(p: BaseModel, c: Container) -> Any:
        return c.get("cache")

    c = Container({"cache": "needs-memory-test", "memory": "needs-cache-test"})
    with pytest.raises(ComponentError, match="circular dependency: cache -> memory -> cache"):
        c.get("cache")


def test_a_missing_package_names_the_extra(tmp_path: Path) -> None:
    c = Container(
        {"token_counter": {"use": "hf-tokenizer", "tokenizer_file": str(tmp_path / "t.json")}}
    )
    try:
        import tokenizers  # noqa: F401
    except ImportError:
        with pytest.raises(ComponentError, match=r"install the extra: rag-core\[tokenizers\]"):
            c.get("token_counter")
    else:  # installed: the missing file is a start-up error that names the slot instead
        with pytest.raises(ComponentError, match="token_counter 'hf-tokenizer' could not start"):
            c.get("token_counter")


def test_unknown_kinds_are_explained() -> None:
    with pytest.raises(ComponentError, match="unknown component kind 'nothing'"):
        registry.spec("nothing", "x")


def test_projects_add_components_through_an_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """A package declaring `[project.entry-points."rag_core.components"]` is loaded with the built-ins."""
    loaded: list[str] = []

    class FakeEntryPoint:
        def load(self) -> None:
            @registry.register("parser", "entry-point-test", summary="from another package")
            def _p(p: BaseModel, c: Container) -> str:
                return "parser"

            loaded.append("yes")

    def fake_entry_points(group: str) -> list[FakeEntryPoint]:
        return [FakeEntryPoint()] if group == "rag_core.components" else []

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)
    monkeypatch.setattr(registry, "_loaded", False)
    assert registry.spec("parser", "entry-point-test").summary == "from another package"
    assert loaded == ["yes"]


# ---------------------------------------------------------------- the command line


def test_rag_components_lists_and_filters(capsys: pytest.CaptureFixture[str]) -> None:
    assert rag_cli(["components", "--kind", "embedder", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    # Step 31 added two; extension 02 added instructed, late-chunking and matryoshka
    names = [r["name"] for r in rows]
    assert names == ["cached", "gateway", "hashing", "instructed", "late-chunking", "matryoshka"]
    assert rows[names.index("hashing")]["params"]["dimensions"][1] == 256
    assert rag_cli(["components"]) == 0
    out = capsys.readouterr().out
    assert "hf-tokenizer" in out
    assert "[extra: tokenizers]" in out
    assert "tokenizer_file=<required>" in out


def test_rag_config_show_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    p = write(tmp_path, "version: 1\nprofiles:\n  p: {embedder: {use: hashing, dimensions: 32}}\n")
    monkeypatch.setenv("RAG__EMBEDDER__DIMENSIONS", "64")
    assert rag_cli(["config", "show", "--file", str(p), "--profile", "p"]) == 0
    assert "dimensions: 64" in capsys.readouterr().out
    monkeypatch.setenv("RAG__EMBEDDER__USE", "hashng")
    assert rag_cli(["config", "check", "--file", str(p), "--profile", "p"]) == 1
    assert "did you mean 'hashing'?" in capsys.readouterr().err
    assert rag_cli(["config", "validate", "--file", str(p), "--profile", "p"]) == 1
    assert "1 problem(s)" in capsys.readouterr().out
