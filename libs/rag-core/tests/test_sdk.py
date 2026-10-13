"""The SDK, rag.yaml includes and plugins (Step 38)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_core import config, registry
from rag_core.registry import ComponentError
from rag_core.sdk import Access, Principal, RagApp

ROOT = Path(__file__).resolve().parents[3]
HANDBOOK = ROOT / "examples/corpus/handbook"
STAFF = Principal("u1", ("all-staff",), ("public", "internal"))


@pytest.fixture
def app(tmp_path: Path) -> RagApp:
    """The handbook without the restricted file: one folder = one access (ingest it separately)."""
    for f in HANDBOOK.glob("*.md"):
        if f.name != "exec-compensation.md":
            (tmp_path / f.name).write_text(f.read_text())
    a = RagApp.load(ROOT / "rag.yaml", "offline", env={})
    results = a.ingest_folder(tmp_path, access=Access("internal", ("all-staff",)))
    assert len(results) == 16
    assert all(r.status == "indexed" for r in results)
    return a


def test_ingest_search_answer_in_a_few_lines(app: RagApp) -> None:
    hits = app.search("How many days of annual leave do full-time staff get?", STAFF).hits
    # without "updated" dates, recency can't demote the 2021 version: both lead the results
    assert {h.chunk.document_uri.rsplit("/", 1)[1] for h in hits[:2]} == {
        "annual-leave.md",
        "annual-leave-2021.md",
    }
    answer = app.answer("How many days of annual leave do full-time staff get?", STAFF)
    assert answer.citations
    assert not answer.abstained
    events = list(app.stream("Can I carry unused holidays over?", STAFF))
    assert events[0].kind == "meta"
    assert events[-1].kind == "done"


def test_access_is_enforced_through_the_sdk(app: RagApp) -> None:
    app.ingest(
        (HANDBOOK / "exec-compensation.md").as_uri(),
        Access("restricted", ("executives",)),
        force=True,
    )
    hits = app.search("executive bonus pool", STAFF, k=10).hits
    assert all("exec-compensation" not in h.chunk.document_uri for h in hits)
    boss = Principal("ceo", ("executives",), ("public", "internal", "restricted"))
    assert any(
        "exec-compensation" in h.chunk.document_uri
        for h in app.search("executive bonus pool", boss, k=10).hits
    )


def test_check_validate_and_components() -> None:
    assert RagApp.load(ROOT / "rag.yaml", "production", env={}).check() == []
    assert RagApp.load(ROOT / "rag.yaml", "offline", env={}).validate() == []
    assert {r["name"] for r in RagApp.components("fusion")} == {"rrf", "weighted", "dbsf"}
    inline = RagApp.from_dict({"embedder": {"use": "hashing", "dimensions": 32}})
    assert inline.validate() == []


def test_a_project_includes_the_platform_profiles(tmp_path: Path) -> None:
    (tmp_path / "rag.yaml").write_text(
        "version: 1\n"
        'include: {platform: "rag-core:platform.yaml"}\n'
        "profiles:\n"
        "  offline: {extends: platform/offline, chunker: {max_tokens: 250}}\n"
        "  production: {extends: platform/production, pipeline: {use: corrective}}\n"
    )
    off = config.load(tmp_path / "rag.yaml", "offline", env={}).config
    assert off["chunker"] == {
        "use": "structure",
        "max_tokens": 250,
        "overlap_tokens": 40,
        "min_tokens": 60,
    }
    assert off["embedder"]["use"] == "hashing"  # everything else from the platform
    prod = config.load(tmp_path / "rag.yaml", "production", env={}).config
    assert prod["pipeline"] == {"use": "corrective"}  # another component: replaced, not merged
    assert prod["memory"]["use"] == "valkey"  # platform/production extends platform/local
    (tmp_path / "bad.yaml").write_text("version: 1\ninclude: {x: missing.yaml}\nprofiles: {}\n")
    with pytest.raises(ComponentError, match="not found"):
        config.load(tmp_path / "bad.yaml", "x/y", env={})


def test_packaged_profiles_are_the_platforms() -> None:
    packaged = (ROOT / "libs/rag-core/src/rag_core/profiles/platform.yaml").read_text()
    body = "\n".join(line for line in packaged.splitlines()[4:])  # after the 4-line header
    assert body.strip() == (ROOT / "rag.yaml").read_text().strip(), "run `just sync-profiles`"


def test_plugins_named_in_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "acme_plugin.py").write_text(
        "from rag_core import register\n"
        "@register('normalizer', 'acme-upper', summary='test plugin')\n"
        "def _f(p, c):\n    return None\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("RAG_PLUGINS", "acme_plugin")
    monkeypatch.setattr(registry, "_loaded", False)
    try:
        assert registry.spec("normalizer", "acme-upper").summary == "test plugin"
        monkeypatch.setenv("RAG_PLUGINS", "no_such_module_xyz")
        monkeypatch.setattr(registry, "_loaded", False)
        with pytest.raises(ComponentError, match="can't be imported"):
            registry.kinds()
    finally:
        registry._REGISTRY.get("normalizer", {}).pop("acme-upper", None)
        monkeypatch.setattr(registry, "_loaded", True)
