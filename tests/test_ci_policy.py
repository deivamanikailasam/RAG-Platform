"""Rules for the pipeline itself, checked like code (Step 27). zizmor and actionlint check more;
these are the rules this platform insists on, in a form anyone can read."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def load(path: Path) -> dict[str, Any]:
    data: dict[Any, Any] = yaml.safe_load(path.read_text())
    data["on"] = data.pop(
        True, data.get("on")
    )  # YAML 1.1 reads the key `on` as true (Step 25's trap)
    return data


def steps(wf: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for job in wf["jobs"].values() for s in job.get("steps", [])]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_a_commit_with_its_version_noted(path: Path) -> None:
    """A tag can be moved to malicious code (it happened to tj-actions/changed-files in 2025); a commit SHA can't."""
    for line in path.read_text().splitlines():
        if m := re.search(r"uses:\s*(\S+)(.*)$", line):
            assert PINNED.match(m.group(1)), f"{path.name}: not pinned to a SHA: {m.group(1)}"
            assert re.search(r"#\s*v\d+\.\d+\.\d+", m.group(2)), (
                f"{path.name}: add '# vX.Y.Z' after {m.group(1)}"
            )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_least_privilege_and_no_dangerous_triggers(path: Path) -> None:
    wf = load(path)
    assert "permissions" in wf, f"{path.name}: set top-level permissions explicitly"
    assert wf["permissions"] in ({}, {"contents": "read"}), (
        f"{path.name}: top level must be read-only"
    )
    assert "pull_request_target" not in wf["on"], "runs fork code with secrets: never"
    for s in steps(wf):
        if str(s.get("uses", "")).startswith("actions/checkout@"):
            assert s["with"]["persist-credentials"] is False, (
                f"{path.name}: checkout must not keep its token"
            )


def test_writes_are_granted_only_where_needed() -> None:
    granted = {(p.name, name): job.get("permissions", {}) for p in WORKFLOWS
               for name, job in load(p)["jobs"].items()}  # fmt: skip
    writers = {k: v for k, v in granted.items() if any(x == "write" for x in v.values())}
    assert writers == {("release.yml", "publish"): {"contents": "read", "packages": "write",
                                                    "id-token": "write", "attestations": "write"}}  # fmt: skip


def test_self_hosted_runner_never_runs_fork_code() -> None:
    for p in WORKFLOWS:
        for name, job in load(p)["jobs"].items():
            if "self-hosted" in job.get("runs-on", []):
                assert "head.repo.full_name == github.repository" in job["if"], f"{p.name}:{name}"
                assert job.get("environment"), f"{p.name}:{name}: needs an approval environment"
                # skipped, not queued forever, until the Mac runner is registered
                assert "vars.RAG_MODELS_RUNNER == 'true'" in job["if"], f"{p.name}:{name}"


def test_ci_postgres_client_matches_the_service_container() -> None:
    ci = load(ROOT / ".github/workflows/ci.yml")
    image = ci["jobs"]["checks"]["services"]["postgres"]["image"]
    major = image.split("-pg")[1].split("@")[0]
    runs = "\n".join(s.get("run", "") for s in ci["jobs"]["checks"]["steps"])
    assert f"postgresql-client-{major}" in runs  # pg_dump refuses to dump a newer server
    assert f"/usr/lib/postgresql/{major}/bin" in runs


def test_ci_runs_the_same_recipes_as_your_mac() -> None:
    ci = load(ROOT / ".github/workflows/ci.yml")
    runs = [s.get("run", "") for s in steps(ci)]
    for recipe in (
        "just ci-static",
        "just ci-test",
        "just ci-config",
        "just policy-check",
        "just ci-supply-chain",
    ):
        assert recipe in runs, recipe


def test_dockerfile_copies_every_workspace_member_manifest() -> None:
    """`uv sync --locked` inside the image fails if any member's pyproject.toml is missing.
    Step 26 added libs/rag-evals and the image build broke; this test would have caught it."""
    members = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"][
        "members"
    ]
    manifests = sorted(str(p.relative_to(ROOT)) for pattern in members
                       for p in ROOT.glob(f"{pattern}/pyproject.toml"))  # fmt: skip
    dockerfile = (ROOT / "services/rag-api/Dockerfile").read_text()
    for manifest in manifests:
        assert re.search(rf"^COPY {re.escape(manifest)} ", dockerfile, re.M), (
            f"Dockerfile misses {manifest}"
        )
    assert (
        "COPY prompts /app/prompts" in dockerfile
    )  # the registry rag-api needs at start-up (Step 24)
