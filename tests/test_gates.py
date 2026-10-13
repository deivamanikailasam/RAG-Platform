"""Promotion gates (Step 37): staging needs evidence; prod needs the same digest soaked in staging,
fresh evidence including online evaluation, no critical alert, and no change freeze."""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
OFFLINE = ["image-verify", "readiness", "search-eval", "guard-eval", "answer-eval"]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gates, promote = _load("gates"), _load("promote")


def at(day: str, hour: int = 12) -> Any:
    return lambda: dt.datetime.fromisoformat(f"{day}T{hour:02}:00:00+00:00")


def git(repo: Path, *args: str, when: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}  # fmt: skip
    if when:
        env |= {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def envs(tmp_path: Path) -> Path:
    """A copy of deploy/envs in its own git repository, so 'when did staging get it' is real git."""
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    shutil.copytree(ROOT / "deploy/envs", tmp_path / "envs")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "start", when="2026-10-01T09:00:00+00:00")
    return tmp_path / "envs"


def staged(envs: Path, digest: str, when: str) -> None:
    promote.promote("staging", digest, envs)
    git(envs.parent, "commit", "-qam", f"deploy(staging): {digest}", when=when)


def evidence(
    folder: Path, digest: str, names: list[str], when: str = "2026-10-10", status: str = "pass"
) -> Path:
    for n in names:
        gates.record(n, digest, status, "ok", folder, now=at(when))
    return folder


def no_alerts(env: str, matchers: dict[str, str]) -> list[dict[str, Any]]:
    return []


def test_staging_needs_every_offline_check(envs: Path, tmp_path: Path) -> None:
    folder = evidence(tmp_path / "ev", A, OFFLINE[:-1])
    problems = gates.check("staging", A, evidence=folder, envs=envs, now=at("2026-10-12"))
    assert problems == ["evidence answer-eval: missing (aaaaaaaaaaaa-answer-eval.json)"]
    evidence(folder, A, ["answer-eval"])
    assert gates.check("staging", A, evidence=folder, envs=envs, now=at("2026-10-12")) == []


def test_evidence_must_be_for_this_digest_passing_and_fresh(envs: Path, tmp_path: Path) -> None:
    folder = evidence(tmp_path / "ev", A, OFFLINE)
    (folder / f"{A[7:19]}-search-eval.json").write_text(
        (folder / f"{A[7:19]}-search-eval.json").read_text().replace(A, B)
    )
    evidence(folder, A, ["guard-eval"], status="fail")
    evidence(folder, A, ["readiness"], when="2026-09-01")
    problems = gates.check("staging", A, evidence=folder, envs=envs, now=at("2026-10-12"))
    assert len(problems) == 3
    assert any("recorded for sha256:bbb" in p for p in problems)
    assert any("guard-eval: status 'fail'" in p for p in problems)
    assert any("readiness: 41 days old" in p for p in problems)


def test_prod_needs_the_same_digest_in_staging_first(envs: Path, tmp_path: Path) -> None:
    folder = evidence(tmp_path / "ev", A, [*OFFLINE, "online-eval"])
    problems = gates.check(
        "prod", A, evidence=folder, envs=envs, alerts=no_alerts, now=at("2026-10-12")
    )
    assert problems == ["staging runs nothing, not this digest: promote to staging first"]
    staged(envs, B, "2026-10-05T09:00:00+00:00")
    problems = gates.check(
        "prod", A, evidence=folder, envs=envs, alerts=no_alerts, now=at("2026-10-12")
    )
    assert problems == [f"staging runs {B}, not this digest: promote to staging first"]


def test_prod_waits_for_the_soak_period(envs: Path, tmp_path: Path) -> None:
    folder = evidence(tmp_path / "ev", A, [*OFFLINE, "online-eval"])
    staged(envs, A, "2026-10-12T02:00:00+00:00")
    problems = gates.check(
        "prod", A, evidence=folder, envs=envs, alerts=no_alerts, now=at("2026-10-12", 12)
    )
    assert problems == ["soaking in staging for 10.0 h of 24.0 h: 14.0 h to go"]
    assert (
        gates.check(
            "prod", A, evidence=folder, envs=envs, alerts=no_alerts, now=at("2026-10-13", 3)
        )
        == []
    )


def test_soak_starts_when_the_digest_came_back(envs: Path, tmp_path: Path) -> None:
    """A -> B -> A again (a rollback): the clock restarts at the latest arrival, not the first."""
    folder = evidence(tmp_path / "ev", A, [*OFFLINE, "online-eval"])
    staged(envs, A, "2026-10-01T10:00:00+00:00")
    staged(envs, B, "2026-10-05T10:00:00+00:00")
    staged(envs, A, "2026-10-12T10:00:00+00:00")
    problems = gates.check(
        "prod", A, evidence=folder, envs=envs, alerts=no_alerts, now=at("2026-10-12", 20)
    )
    assert problems == ["soaking in staging for 10.0 h of 24.0 h: 14.0 h to go"]


def test_prod_needs_online_evaluation_and_no_critical_alerts(envs: Path, tmp_path: Path) -> None:
    folder = evidence(tmp_path / "ev", A, OFFLINE)
    staged(envs, A, "2026-10-10T00:00:00+00:00")
    seen: list[tuple[str, dict[str, str]]] = []

    def firing(env: str, matchers: dict[str, str]) -> list[dict[str, Any]]:
        seen.append((env, matchers))
        return [{"labels": {"alertname": "RagAbstentionSpike", "severity": "critical"}}]

    problems = gates.check(
        "prod", A, evidence=folder, envs=envs, alerts=firing, now=at("2026-10-12")
    )
    assert problems == ["evidence online-eval: missing (aaaaaaaaaaaa-online-eval.json)",
                        "alert firing in staging: RagAbstentionSpike"]  # fmt: skip
    assert seen == [("staging", {"severity": "critical"})]
    assert (
        "alerts can't be checked"
        in gates.check("prod", A, evidence=folder, envs=envs, now=at("2026-10-12"))[-1]
    )


def test_change_freeze(envs: Path, tmp_path: Path) -> None:
    folder = evidence(tmp_path / "ev", A, [*OFFLINE, "online-eval"], when="2026-12-22")
    staged(envs, A, "2026-12-01T00:00:00+00:00")
    problems = gates.check(
        "prod", A, evidence=folder, envs=envs, alerts=no_alerts, now=at("2026-12-24")
    )
    assert problems == ["change freeze until 2027-01-04: year-end change freeze"]


def test_every_environment_with_an_overlay_has_rules() -> None:
    rules = gates.load_rules()
    overlays = sorted(p.parent.name for p in (ROOT / "deploy/envs").glob("*/kustomization.yaml"))
    assert sorted(rules["environments"]) == overlays
    assert rules["order"] == ["local", "staging", "prod"]


def test_cli(envs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "ev"
    for n in OFFLINE:
        assert gates.main(["record", n, A, "pass", "--summary", "fine", "--out", str(out)]) == 0
    assert gates.main(["check", "staging", A, "--evidence", str(out)]) == 0
    assert gates.main(["check", "staging", B, "--evidence", str(out)]) == 1
    assert "BLOCKED: evidence image-verify: missing" in capsys.readouterr().err
