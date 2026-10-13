"""scripts/doc_coverage.py: is there a document for everything?"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("doc_coverage", ROOT / "scripts/doc_coverage.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["doc_coverage"] = module
    spec.loader.exec_module(module)
    return module


dc = _load()


def test_the_repository_has_a_document_for_everything() -> None:
    # a fresh process: other tests register throwaway components into this process's registry
    out = subprocess.run(  # noqa: S603 - fixed arguments, test-only
        [sys.executable, str(ROOT / "scripts/doc_coverage.py"), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(out.stdout) == {"components": [], "recipes": [], "indexes": [], "links": []}
    assert out.returncode == 0


def test_heading_anchors_follow_github() -> None:
    assert dc.slug("20. Cheat sheet: situation → choice") == "20-cheat-sheet-situation--choice"
    assert dc.slug("7. Agents: `rag mcp`") == "7-agents-rag-mcp"
    assert dc.slug("Step 31 · Ingestion") == "step-31--ingestion"


def test_broken_links_and_missing_headings_are_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "b.md").write_text("# Title\n\n## Same\n\n## Same\n")
    page = tmp_path / "a.md"
    page.write_text(
        "[ok](b.md) [ok](b.md#title) [ok](b.md#same-1) [web](https://example.com) [self](#top)\n"
        "# Top\n"
        "[gone](missing.md) [no heading](b.md#nowhere)\n"
        "`[in code](missing.md)`\n"
        "```\n[in a block](missing.md)\n```\n"
    )
    monkeypatch.setattr(dc, "ROOT", tmp_path)
    problems = dc.check_links([page])
    assert problems == ["a.md:3: broken link 'missing.md'", "a.md:3: no heading #nowhere in b.md"]


def test_recipes_are_parsed_like_just_summary(tmp_path: Path) -> None:
    jf = tmp_path / "justfile"
    jf.write_text(
        'set shell := ["bash", "-c"]\ncompose := "docker compose"\n\n'
        "# a comment\nup:\n    echo up\n\n"
        'doctor path=".":\n    echo\n\n'
        "ci: lint test\n\n[positional-arguments]\nlicences *args:\n    echo\n\n_private:\n    echo\n"
    )
    assert dc.recipes(jf) == ["ci", "doctor", "licences", "up"]


def test_mentions_count_code_bold_and_yaml_blocks() -> None:
    named = dc._named_spans(
        "Use **unicode** first.\n```yaml\nqueue: {use: valkey-streams}\n```\nplain markdown\n"
    )
    assert dc._mentions(named, "unicode")
    assert dc._mentions(named, "valkey-streams")
    assert not dc._mentions(named, "markdown")
    assert not dc._mentions(named, "valkey")  # whole names only
