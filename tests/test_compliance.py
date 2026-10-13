"""The risk register (Step 36): valid, evidenced, linked, and its documents up to date."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compliance", ROOT / "scripts/compliance.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["compliance"] = module
    spec.loader.exec_module(module)
    return module


def test_the_real_register_is_valid_and_rendered() -> None:
    c = load()
    assert c.problems(c.load()) == []
    assert c.main(["docs", "--check"]) == 0


def test_every_kind_of_mistake_is_caught() -> None:
    c = load()
    doc = copy.deepcopy(c.load())
    doc["threats"][0]["controls"].append("C-NOPE")
    doc["threats"][1]["category"] = "Spoof"
    doc["controls"][0]["evidence"] = ["tests/does_not_exist.py"]
    doc["controls"][1]["evidence"] = [
        "services/rag-api/tests/test_policy.py::test_that_was_deleted"
    ]
    doc["controls"][2]["frameworks"]["eu_ai_act"] = ["Art 15"]  # missing the dot
    doc["controls"][3]["frameworks"]["nist"] = ["MEASURE 2.14"]  # there is no 2.14
    doc["controls"].append(
        {
            "id": "C-ORPHAN",
            "title": "x",
            "description": "x",
            "evidence": ["justfile"],
            "frameworks": {},
        }
    )
    found = "\n".join(c.problems(doc))
    for expected in ("unknown control C-NOPE", "unknown category 'Spoof'", "tests/does_not_exist.py does not exist",
                     "no test test_that_was_deleted", "EU AI Act reference 'Art 15'", "NIST AI RMF 1.0 reference 'MEASURE 2.14'",
                     "C-ORPHAN: treats no threat"):  # fmt: skip
        assert expected in found, expected


def test_every_threat_category_is_covered() -> None:
    c = load()
    cats = {t["category"] for t in c.load()["threats"]}
    assert cats == set(c.STRIDE)
