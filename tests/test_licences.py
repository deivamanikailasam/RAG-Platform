"""Dependency licences: SPDX expressions, old-style metadata, and the policy's verdicts."""

from __future__ import annotations

import importlib.util
import sys
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("licences", ROOT / "scripts/licences.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["licences"] = module
    spec.loader.exec_module(module)
    return module


lc = _load()
POLICY: dict[str, Any] = yaml.safe_load((ROOT / "ci/licence-policy.yaml").read_text())


class FakeDist:
    def __init__(self, name: str, **fields: Any) -> None:
        self.metadata = Message()
        self.metadata["Name"] = name
        for key, value in fields.items():
            for v in value if isinstance(value, list) else [value]:
                self.metadata[key.replace("_", "-")] = v
        self.version = "1.0"


def test_expressions() -> None:
    assert lc.judge("MIT", POLICY) == ("ok", "")
    assert lc.judge("Apache-2.0 OR BSD-3-Clause", POLICY)[0] == "ok"
    assert lc.judge("GPL-3.0-only OR MIT", POLICY)[0] == "ok"  # OR: we may choose MIT
    assert lc.judge("MIT AND GPL-3.0-only", POLICY)[0] == "denied"  # AND: we must comply with both
    assert lc.judge("LGPL-3.0-only", POLICY)[0] == "review"
    assert lc.judge("WTFPL", POLICY) == ("unknown", "'WTFPL' is not in the policy")


def test_where_the_licence_is_read_from() -> None:
    assert lc.declared_licence(FakeDist("a", License_Expression="MIT")) == "MIT"
    assert lc.declared_licence(FakeDist("b", License="Apache License 2.0")) == "Apache-2.0"
    assert lc.declared_licence(FakeDist("c", Classifier=[
        "License :: OSI Approved :: MIT License", "License :: OSI Approved :: Apache Software License"])) == "Apache-2.0 OR MIT"  # fmt: skip
    assert (
        lc.declared_licence(FakeDist("d", Classifier=["License :: OSI Approved :: BSD License"]))
        is None
    )  # ambiguous
    assert (
        lc.declared_licence(
            FakeDist(
                "e", License="Permission is hereby granted, free of charge, to any person…" * 2
            )
        )
        is None
    )


def test_verdicts() -> None:
    dists = [FakeDist("ok-pkg", License_Expression="MIT"), FakeDist("copyleft", License_Expression="AGPL-3.0-only"),
             FakeDist("mystery"), FakeDist("python-dateutil", License="Dual License"), FakeDist("rag-api")]  # fmt: skip
    verdicts = {v.package: v.status for v in lc.check(dists, POLICY)}
    assert verdicts == {
        "ok-pkg": "ok",
        "copyleft": "denied",
        "mystery": "unknown",
        "python-dateutil": "ok",
    }


def test_the_real_environment_passes() -> None:
    """What uv.lock installed: everything allowed, psycopg (LGPL) allowed with its recorded reason."""
    from importlib.metadata import distributions

    verdicts = lc.check(distributions(), POLICY)
    assert {v.status for v in verdicts} <= {"ok", "review"}
    assert {v.package for v in verdicts if v.status == "review"} == {
        "psycopg",
        "psycopg-binary",
        "psycopg-pool",
    }
