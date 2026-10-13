"""The project template (Step 38): every combination of answers produces a project that passes
its own tests, its quality gates and `rag doctor`, using only rag-core.

Copier runs as an isolated tool (`uvx copier`), not as a dependency: one of its dependencies is
GPL-3.0, which the licence policy (Step 27) denies for anything we ship. A tool we only run to
generate files doesn't become part of the product."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates/rag-project"

CASES: list[dict[str, object]] = [
    {"project_name": "HR policy assistant"},
    {"project_name": "IT Helpdesk", "architecture": "adaptive", "search_engine": "engines",
     "personal_data": False, "retention_days": 365, "highest_classification": "confidential"},
    {"project_name": "Legal research", "architecture": "corrective"},
]  # fmt: skip

COPIER = "copier==9.19.0"


def copier(dest: Path, answers: dict[str, object]) -> subprocess.CompletedProcess[str]:
    if shutil.which("uvx") is None:
        pytest.skip("uvx (from uv) is needed to run copier as a tool")
    data = [
        f"--data={k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in answers.items()
    ]
    cmd = [
        "uvx",
        "--from",
        COPIER,
        "copier",
        "copy",
        "--trust",
        "--defaults",
        "--quiet",
        *data,
        str(TEMPLATE),
        str(dest),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)  # noqa: S603


def generate(dest: Path, answers: dict[str, object]) -> Path:
    r = copier(dest, answers)
    assert r.returncode == 0, r.stderr
    return dest


def run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
    module = answers["slug"].replace("-", "_")
    env = {**os.environ, "PYTHONPATH": str(project / "src"), "RAG_PLUGINS": f"{module}.components"}
    env.pop("RAG_PROFILE", None)
    cmd = [sys.executable, *args]
    return subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, timeout=300)  # noqa: S603


@pytest.mark.parametrize("answers", CASES, ids=[str(c["project_name"]) for c in CASES])
def test_generated_project_passes_its_gates(tmp_path: Path, answers: dict[str, object]) -> None:
    project = generate(tmp_path / "p", answers)
    for args in (["-m", "ruff", "check", "--no-cache", "."],   # `just lint` in the project
                 ["-m", "ruff", "format", "--check", "--no-cache", "."],
                 ["-m", "pytest", "-q", "-p", "no:cacheprovider"],
                 ["-m", "rag_core.cli", "config", "readiness", "--profile", "production"],
                 ["-m", "rag_core.cli", "eval-search", "eval/questions.yaml", "--profile", "offline", "--fail-under", "recall=0.8"],
                 ["-m", "rag_core.cli", "eval-guards", "eval/guards.yaml", "--profile", "offline"],
                 ["-m", "rag_core.cli", "eval-answers", "eval/questions.yaml", "--profile", "offline",
                  "--variant", str(answers.get("architecture", "standard")), "--fail-under", "abstain_ok=1"],
                 ["-m", "rag_core.cli", "doctor", "."]):  # fmt: skip
        r = run(project, *args)
        assert r.returncode == 0, f"{' '.join(args)}\n{r.stdout}\n{r.stderr}"


def test_answers_shape_the_project(tmp_path: Path) -> None:
    project = generate(tmp_path / "p", CASES[1])
    rag = yaml.safe_load((project / "rag.yaml").read_text())
    assert rag["profiles"]["local"]["extends"] == "platform/local-engines"
    assert rag["profiles"]["production"]["pipeline"]["use"] == "adaptive"
    assert yaml.safe_load((project / "retention.yaml").read_text())["default_keep_days"] == 365
    card = (project / "docs/cards/system-it-helpdesk.md").read_text()
    assert "highest classification: **confidential**" in card
    assert "not expected" in card
    pyproject = (project / "pyproject.toml").read_text()
    assert 'it_helpdesk = "it_helpdesk.components"' in pyproject
    assert '"rag-core[postgres,valkey,pdf,docx]>=1.0.0,<2"' in pyproject
    for f in ("deploy/kustomization.yaml", "deploy/namespace.yaml", ".github/workflows/ci.yml"):
        assert yaml.safe_load((project / f).read_text()), f
    ns = yaml.safe_load((project / "deploy/namespace.yaml").read_text())
    assert ns["metadata"]["labels"]["rag-platform/policy"] == "enforced"


def test_bad_names_are_refused(tmp_path: Path) -> None:
    r = copier(tmp_path / "x", {"project_name": "X", "slug": "X!"})
    assert r.returncode != 0
    assert "lowercase" in r.stderr + r.stdout
    assert not (tmp_path / "x" / "rag.yaml").exists()
