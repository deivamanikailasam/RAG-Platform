"""The starter configs in examples/profiles/ (decision guide): every profile names real components with
valid settings, including the components nested inside wrappers, chains, ensembles and routers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_core.config import load, read
from rag_core.registry import SLOTS, spec

ROOT = Path(__file__).resolve().parents[1]
RECIPES = sorted((ROOT / "examples/profiles").glob("*.yaml"))
GUIDE = ROOT / "docs/concepts/decision-guide.md"


def _profiles(path: Path) -> list[str]:
    return list((yaml.safe_load(path.read_text()) or {}).get("profiles") or {})


CASES = [(p, name) for p in RECIPES for name in _profiles(p)]


def _nested(kind: str, item: Any, where: str) -> list[str]:
    """Validate a nested {use: …} the way Container.validate does a slot, then look inside it."""
    item = {"use": item} if isinstance(item, str) else item
    if not isinstance(item, dict) or "use" not in item:
        return [f"{where}: expected {{use: <name>, …}}, got {item!r}"]
    problems: list[str] = []
    try:
        spec(kind, str(item["use"])).params.model_validate(
            {k: v for k, v in item.items() if k != "use"}
        )
    except Exception as e:  # every failure is a problem to report
        problems.append(f"{where} {item['use']!r}: {e}")
    if "inner" in item and item["inner"] is not None:
        problems += _nested(kind, item["inner"], f"{where}.inner")
    for i, step in enumerate(item.get("steps") or []):
        problems += _nested("query_transformer", step, f"{where}.steps[{i}]")
    members = list(item.get("members") or []) + list((item.get("routes") or {}).values())
    for i, m in enumerate(members):
        if isinstance(m, dict):
            if m.get("retriever") is not None:
                problems += _nested("retriever", m["retriever"], f"{where}.member[{i}].retriever")
            for slot, raw in (m.get("slots") or {}).items():
                problems += _nested(SLOTS[slot], raw, f"{where}.member[{i}].slots.{slot}")
    return problems


def test_there_are_starter_configs() -> None:
    assert RECIPES, "examples/profiles/*.yaml is missing"
    assert len(CASES) >= 10


@pytest.mark.parametrize(("path", "profile"), CASES, ids=[f"{p.stem}:{n}" for p, n in CASES])
def test_starter_config_validates(path: Path, profile: str) -> None:
    container = load(path, profile)
    assert container.validate() == []
    deep: list[str] = []
    for slot, raw in container.config.items():
        if slot == "extends" or slot not in SLOTS or raw in (None, "none"):
            continue
        entries = raw if isinstance(raw, list) else [raw]
        for i, entry in enumerate(entries):
            if isinstance(entry, dict) and any(
                k in entry for k in ("inner", "steps", "members", "routes")
            ):
                deep += _nested(SLOTS[slot], entry, f"{slot}[{i}]")
    assert deep == []


def test_every_starter_config_is_in_the_decision_guide() -> None:
    guide = GUIDE.read_text()
    for path, profile in CASES:
        assert f"`{profile}`" in guide, (
            f"{profile} ({path.name}) is not described in the decision guide"
        )


def test_starter_configs_only_extend_known_profiles() -> None:
    for path in RECIPES:
        doc = read(path)
        for name, body in (yaml.safe_load(path.read_text())["profiles"]).items():
            parent = (body or {}).get("extends")
            assert parent is None or parent in doc["profiles"], f"{name} extends unknown {parent}"
