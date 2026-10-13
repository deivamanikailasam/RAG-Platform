"""Promotion (Step 29): `just promote` changes exactly one line, the digest, and nothing else."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "deploy/envs/local/kustomization.yaml"
NEW = "sha256:" + "a" * 64
NEWER = "sha256:" + "b" * 64


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("promote", ROOT / "scripts/promote.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["promote"] = module
    spec.loader.exec_module(module)
    return module


pm = _load()


@pytest.fixture
def envs(tmp_path: Path) -> Path:
    """A copy of the REAL deploy/envs/local, so the test sees the file exactly as committed."""
    (tmp_path / "local").mkdir()
    shutil.copy(REAL, tmp_path / "local/kustomization.yaml")
    return tmp_path


def test_first_promotion_changes_only_the_digest_line(envs: Path) -> None:
    path = envs / "local/kustomization.yaml"
    before = path.read_text().splitlines()
    assert pm.promote("local", NEW, envs) is None  # the placeholder doesn't count as a release
    after = path.read_text().splitlines()
    assert len(before) == len(after)
    changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert len(changed) == 1
    old_line, new_line = changed[0]
    assert "<digest>" in old_line
    assert new_line == old_line.replace("sha256:<digest>", NEW)  # the comment stays too
    images = yaml.safe_load(path.read_text())["images"]
    assert images == [{"name": "rag-api", "newName": "ghcr.io/owner/rag-platform/rag-api",
                       "digest": NEW}]  # fmt: skip


def test_next_promotion_reports_what_it_replaces(
    envs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = pm.promote
    monkeypatch.setattr(pm, "promote", lambda env, digest: real(env, digest, envs))
    assert pm.main(["local", NEW]) == 0
    assert capsys.readouterr().out == f"local: rag-api (none) -> {NEW}\n"
    assert pm.main(["local", NEWER]) == 0
    assert capsys.readouterr().out == f"local: rag-api {NEW} -> {NEWER}\n"  # goes in the commit
    assert pm.main(["local", NEWER]) == 0
    assert capsys.readouterr().out == f"local already runs {NEWER}\n"
    assert pm.main(["local", "latest"]) == 1
    assert "not an image digest" in capsys.readouterr().err


@pytest.mark.parametrize(
    "digest", ["latest", "sha256:abc", "sha256:" + "A" * 64, "v1.2.3", "sha256:" + "a" * 63]
)
def test_only_digests_can_be_promoted(envs: Path, digest: str) -> None:
    before = (envs / "local/kustomization.yaml").read_text()
    with pytest.raises(pm.PromoteError, match="not an image digest"):
        pm.promote("local", digest, envs)
    assert (envs / "local/kustomization.yaml").read_text() == before


def test_unknown_environment(envs: Path) -> None:
    with pytest.raises(pm.PromoteError, match=r"unknown environment 'prod' \(known: local\)"):
        pm.promote("prod", NEW, envs)


def test_an_entry_without_a_digest_gets_one(tmp_path: Path) -> None:
    (tmp_path / "staging").mkdir()
    path = tmp_path / "staging/kustomization.yaml"
    path.write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "images:\n"
        "  - name: rag-api  # the app\n"
        "    newName: ghcr.io/owner/rag-platform/rag-api\n"
        "patches: []\n"
    )
    assert pm.promote("staging", NEW, tmp_path) is None
    doc = yaml.safe_load(path.read_text())
    assert doc["images"][0]["digest"] == NEW
    assert doc["patches"] == []
    assert "  - name: rag-api  # the app\n" in path.read_text()
