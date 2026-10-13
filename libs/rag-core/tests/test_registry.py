"""Switching components by configuration (Step 30)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from rag_core import config
from rag_core.cli import main as rag_cli
from rag_core.components.basics import HashingEmbedder, MemoryVectorStore, ScriptedLLM
from rag_core.registry import ComponentError, Container, describe, register, spec

ROOT = Path(__file__).resolve().parents[3]


def doc(**profiles: object) -> dict[str, object]:
    return {"version": 1, "profiles": profiles}


def test_a_profile_builds_its_components() -> None:
    c = Container(config.resolve(doc(p={"embedder": {"use": "hashing", "dimensions": 32},
                                        "vector_store": "memory"}), "p", env={}))  # fmt: skip
    assert isinstance(c.get("embedder"), HashingEmbedder)
    assert c.get("embedder").dimensions == 32
    assert c.get("embedder") is c.get("embedder")  # built once
    assert isinstance(c.get("vector_store"), MemoryVectorStore)


def test_extends_merges_parameters_and_replaces_components() -> None:
    d = doc(base={"embedder": {"use": "hashing", "dimensions": 32}, "llm": {"use": "scripted", "default": "x"},
                  "keyword_index": "memory-bm25"},
            child={"extends": "base", "embedder": {"dimensions": 64}, "llm": {"use": "gateway"},
                   "keyword_index": "none"})  # fmt: skip
    r = config.resolve(d, "child", env={})
    assert r["embedder"] == {
        "use": "hashing",
        "dimensions": 64,
    }  # same component: parameter changed
    assert r["llm"] == {"use": "gateway"}  # another component: replaced, the old parameters dropped
    assert "keyword_index" not in r  # "none" switches a slot off


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    d = doc(
        p={"embedder": {"use": "hashing", "dimensions": 32}, "reranker": {"use": "x", "top_n": 8}}
    )
    r = config.resolve(
        d, "p", env={"RAG__EMBEDDER__DIMENSIONS": "128", "RAG__RERANKER__USE": "none", "OTHER": "1"}
    )
    assert r["embedder"]["dimensions"] == 128  # YAML-typed: an int, not "128"
    assert "reranker" not in r


@pytest.mark.parametrize(
    ("slot_cfg", "message"),
    [({"embedder": {"use": "hashng"}}, "no embedder named 'hashng'; did you mean 'hashing'?"),
     ({"embedder": {"use": "hashing", "dimension": 64}}, "embedder 'hashing': dimension: Extra inputs are not permitted"),
     ({"embedder": {"use": "hashing", "dimensions": 8}}, "dimensions: Input should be greater than or equal to 16"),
     ({"embedder": 42}, "expected {use: <name>"),
     ({"rerankr": "none2"}, "unknown slot 'rerankr'")],
)  # fmt: skip
def test_mistakes_are_explained(slot_cfg: dict[str, object], message: str) -> None:
    c = Container(slot_cfg)
    with pytest.raises(
        ComponentError, match=message.replace("(", r"\(").replace("?", r"\?").replace("{", r"\{")
    ):
        c.build_all() if "rerankr" not in slot_cfg else c.get("rerankr")


def test_profiles_extending_in_a_circle_are_refused() -> None:
    with pytest.raises(ComponentError, match="circle: a -> b -> a"):
        config.resolve(doc(a={"extends": "b"}, b={"extends": "a"}), "a", env={})


def test_a_missing_dependency_names_the_slot() -> None:
    @register("query_transformer", "needs-llm-test", summary="test only")
    def _needs(p: BaseModel, c: Container) -> object:
        return c.get("llm")

    with pytest.raises(ComponentError, match="doesn't configure 'llm', but something needs it"):
        Container({"query_transformer": "needs-llm-test"}).get("query_transformer")


def test_projects_register_their_own_components() -> None:
    @register("llm", "my-company-llm-test", summary="our own")
    def _mine(p: BaseModel, c: Container) -> ScriptedLLM:
        return ScriptedLLM(default="hello from my component")

    assert (
        Container({"llm": "my-company-llm-test"}).get("llm").complete("s", "u")
        == "hello from my component"
    )
    assert spec("llm", "my-company-llm-test").summary == "our own"
    with pytest.raises(ComponentError, match="registered twice"):
        register("llm", "my-company-llm-test")(_mine)


def test_every_component_is_documented() -> None:
    for row in describe():
        assert row["summary"], f"{row['kind']} {row['name']} has no summary"
        assert row["status"] in ("live", "mocked", "reference")


def test_the_repository_profiles_build(capsys: pytest.CaptureFixture[str]) -> None:
    """Every profile is valid; the offline one also BUILDS (the others need their services)."""
    profiles = yaml.safe_load((ROOT / "rag.yaml").read_text())["profiles"]
    for name in profiles:
        assert (
            rag_cli(["config", "validate", "--file", str(ROOT / "rag.yaml"), "--profile", name])
            == 0
        ), name
    assert (
        rag_cli(["config", "check", "--file", str(ROOT / "rag.yaml"), "--profile", "offline"]) == 0
    )
    assert "slot(s) built" in capsys.readouterr().out


def test_validate_finds_problems_without_connecting() -> None:
    # The guide uses `pgvector` here; it arrives in Step 31, so this step checks the built-in
    # `memory` store, which takes no parameters at all: any key is an extra input.
    c = Container(
        {"vector_store": {"use": "memory", "dimensons": 3}, "guards": [{"use": "nope"}], "x": 1}
    )
    problems = c.validate()
    assert any("dimensons: Extra inputs are not permitted" in p for p in problems)
    assert any(
        "no guard named 'nope'" in p or "unknown component kind 'guard'" in p for p in problems
    )
    assert "unknown slot 'x'" in problems


def test_startup_errors_name_the_slot() -> None:
    # The guide's version starts Step 31's `pii: regex` without its key. Until that component
    # exists, a test-only one fails at start-up in exactly the same way.
    class KeyParams(BaseModel):
        strategy: str = "mask"
        key_env: str = "PII_KEY"

    @register("pii", "regex-startup-test", params=KeyParams, summary="test only")
    def _pii(p: KeyParams, c: Container) -> object:
        if p.strategy == "pseudonymise" and not os.environ.get(p.key_env):
            raise ValueError("pseudonymise needs a key")
        return object()

    with pytest.raises(
        ComponentError,
        match="pii 'regex-startup-test' could not start: ValueError: pseudonymise needs a key",
    ):
        Container(
            {"pii": {"use": "regex-startup-test", "strategy": "pseudonymise",
                     "key_env": "NOT_SET_ANYWHERE"}}
        ).get("pii")  # fmt: skip
