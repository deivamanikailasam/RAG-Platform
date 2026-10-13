"""`rag doctor` (Step 38): does a RAG project meet the platform's standards?

Each rule has an id from docs/standards/rag-standards.md, a level (MUST fails the check, SHOULD
warns) and a fix. Run it in any project made from the template, or in the platform itself:

    rag doctor                    # the current folder
    rag doctor ../hr-assistant --json

It reads files; it never calls a model or a service, so it runs anywhere CI does.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from rag_core import config as cfg
from rag_core import readiness
from rag_core.registry import ComponentError

PRODUCTION_PROFILES = ("production", "prod")
TEST_PROFILES = ("offline", "test", "ci")


@dataclass(frozen=True)
class Result:
    rule: str
    level: str  # MUST | SHOULD
    ok: bool
    message: str
    fix: str = ""

    def __str__(self) -> str:
        mark = "ok  " if self.ok else ("FAIL" if self.level == "MUST" else "warn")
        line = f"{mark} {self.rule:12} {self.level:6} {self.message}"
        return line if self.ok or not self.fix else f"{line}\n{'':25}fix: {self.fix}"


Rule = Callable[[Path, dict[str, Any]], Iterator[Result]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _yaml_files(root: Path, *globs: str) -> list[Path]:
    skip = {".venv", "node_modules", ".git", "__pycache__"}
    out = []
    for g in globs:
        out += [p for p in root.glob(g) if not skip & set(p.relative_to(root).parts)]
    return sorted(set(out))


def _load(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except (yaml.YAMLError, OSError):
        return None


EVAL_GLOBS = ("eval/**/*.yaml", "examples/eval/**/*.yaml", "evals/**/*.yaml")

# ---------------------------------------------------------------------------- configuration


@rule
def config_profiles(root: Path, ctx: dict[str, Any]) -> Iterator[Result]:
    path = root / "rag.yaml"
    try:
        doc = cfg.read(path) if path.is_file() else None
    except (ComponentError, yaml.YAMLError) as e:
        yield Result("CFG-1", "MUST", False, f"rag.yaml can't be read: {e}", "fix the YAML")
        return
    if not isinstance(doc, dict) or "profiles" not in doc:
        yield Result(
            "CFG-1", "MUST", False, "no rag.yaml with profiles", "copy one from the template"
        )
        return
    profiles = {p for p in doc["profiles"] if "/" not in p}  # this project's own, not included ones
    ctx["profiles"] = profiles
    test = next((p for p in TEST_PROFILES if p in profiles), None)
    prod = next((p for p in PRODUCTION_PROFILES if p in profiles), None)
    yield Result("CFG-1", "MUST", True, f"rag.yaml has {len(profiles)} profile(s)")
    yield Result("CFG-2", "MUST", test is not None, "a profile that runs with no services (offline/test/ci)"
                 + (f": {test}" if test else ""), "add an 'offline' profile with memory stores and hashing embedder")  # fmt: skip
    yield Result("CFG-3", "MUST", prod is not None, "a production profile" + (f": {prod}" if prod else ""),
                 "add a 'production' profile (extends your local one)")  # fmt: skip
    ctx["test_profile"], ctx["prod_profile"] = test, prod
    for name in sorted(profiles):
        try:
            problems = cfg.load(path, name, env={}).validate()
        except ComponentError as e:
            problems = [str(e)]
        yield Result("CFG-4", "MUST", not problems, f"profile '{name}' builds" if not problems
                     else f"profile '{name}': {problems[0]}", "rag components lists valid names and settings")  # fmt: skip


@rule
def production_ready(root: Path, ctx: dict[str, Any]) -> Iterator[Result]:
    prod = ctx.get("prod_profile")
    if not prod:
        return
    try:
        findings = readiness.check(cfg.load(root / "rag.yaml", prod, env={}).config)
    except ComponentError as e:
        yield Result("CFG-5", "MUST", False, f"production profile can't be read: {e}",
                     "rag config show --profile " + prod)  # fmt: skip
        return
    errors = [f for f in findings if f.level == "error"]
    yield Result("CFG-5", "MUST", not errors, "production profile passes readiness" if not errors
                 else f"readiness: {errors[0].slot}: {errors[0].message}", "rag config readiness --profile " + prod)  # fmt: skip
    gen = cfg.load(root / "rag.yaml", prod, env={}).config.get("generator")
    pinned = isinstance(gen, dict) and gen.get("use") == "llm" and bool(gen.get("prompt_label"))
    yield Result("PRM-1", "SHOULD", pinned or (isinstance(gen, dict) and gen.get("use") != "llm"),
                 "answers use a registered prompt with a label" if pinned else "generator prompt isn't pinned by label",
                 "generator: {use: llm, prompt: rag-answer, prompt_label: production}")  # fmt: skip


# ---------------------------------------------------------------------------- evaluation


@rule
def search_eval(root: Path, ctx: dict[str, Any]) -> Iterator[Result]:
    sets = [(p, d) for p in _yaml_files(root, *EVAL_GLOBS)
            if isinstance(d := _load(p), dict) and isinstance(d.get("questions"), list)]  # fmt: skip
    if not sets:
        yield Result("EVL-1", "MUST", False, "no labelled questions (a YAML with 'questions')",
                     "start from the template's eval/questions.yaml")  # fmt: skip
        return
    questions = [q for _, d in sets for q in d["questions"] if isinstance(q, dict)]
    yield Result(
        "EVL-1", "MUST", True, f"{len(questions)} labelled question(s) in {len(sets)} file(s)"
    )
    yield Result("EVL-2", "SHOULD", len(questions) >= 25, f"{len(questions)} questions (25+ recommended)",
                 "add real questions from users; aim for every document type and tag")  # fmt: skip
    unanswerable = [q for q in questions if q.get("relevant") == []]
    yield Result("EVL-3", "MUST", bool(unanswerable), f"{len(unanswerable)} question(s) with no answer in the documents",
                 "add questions whose answer is NOT there (relevant: []): they test honest abstention")  # fmt: skip
    access = [q for q in questions if q.get("forbidden")]
    yield Result("EVL-4", "MUST", bool(access), f"{len(access)} access-control question(s) (forbidden documents)",
                 "add a restricted document to the corpus and a question that must not reveal it")  # fmt: skip


@rule
def guard_eval(root: Path, ctx: dict[str, Any]) -> Iterator[Result]:
    sets = [d for p in _yaml_files(root, *EVAL_GLOBS)
            if isinstance(d := _load(p), dict) and isinstance(d.get("cases"), list)]  # fmt: skip
    cases = [c for d in sets for c in d["cases"] if isinstance(c, dict)]
    attacks = [c for c in cases if c.get("expect") in ("block", "redact", "flag")]
    benign = [c for c in cases if c.get("expect") == "allow"]
    yield Result("EVL-5", "MUST", bool(attacks) and bool(benign),
                 f"guard cases: {len(attacks)} attack(s), {len(benign)} ordinary question(s)",
                 "both kinds: a guard that blocks everything catches every attack")  # fmt: skip


@rule
def ci_gates(root: Path, ctx: dict[str, Any]) -> Iterator[Result]:
    text = "\n".join(p.read_text() for p in _yaml_files(root, ".github/workflows/*.yml", ".github/workflows/*.yaml",
                                                        ".gitlab-ci.yml"))  # fmt: skip
    text += "\n".join(p.read_text() for p in (root / "justfile", root / "Makefile") if p.is_file())
    for rid, words, what in (("CI-1", ("eval-search", "eval-answers"), "search/answer evaluation"),
                             ("CI-2", ("eval-guards", "guard-eval"), "guardrail evaluation"),
                             ("CI-3", ("readiness",), "production readiness")):  # fmt: skip
        found = any(w in text for w in words)
        yield Result(rid, "MUST", found, f"CI runs {what}" if found else f"CI doesn't run {what}",
                     f"run `{words[0]}` in CI with --fail-under thresholds")  # fmt: skip


# ---------------------------------------------------------------------------- governance


@rule
def governance(root: Path, ctx: dict[str, Any]) -> Iterator[Result]:
    checks = [
        ("GOV-1", "SHOULD", ("docs/cards/system-*.md", "docs/system-card.md"), "a system card (what it is for, limits, data)"),
        ("GOV-2", "SHOULD", ("docs/compliance/risk-register.yaml", "docs/risk-acceptance.md"), "a risk register or acceptance of the platform's"),
        ("GOV-3", "SHOULD", ("**/retention.yaml",), "retention rules for this project's documents"),
        ("GOV-4", "SHOULD", ("docs/adr/*.md", "docs/decisions/*.md"), "decision records"),
    ]  # fmt: skip
    for rid, level, globs, what in checks:
        found = [p for g in globs for p in root.glob(g) if ".venv" not in p.parts]
        yield Result(rid, level, bool(found), what + ("" if found else ": missing"),
                     "the template has a starting version of each")  # fmt: skip


def run(root: Path) -> list[Result]:
    ctx: dict[str, Any] = {}
    out: list[Result] = []
    for r in RULES:
        out += list(r(root.resolve(), ctx))
    return out


def as_dicts(results: list[Result]) -> list[dict[str, Any]]:
    return [asdict(r) for r in results]


def summary(results: list[Result]) -> str:
    """The last line of `rag doctor`: `21 ok, 0 MUST failed, 0 SHOULD to consider`."""
    ok = sum(r.ok for r in results)
    must = sum(not r.ok and r.level == "MUST" for r in results)
    should = sum(not r.ok and r.level != "MUST" for r in results)
    return f"{ok} ok, {must} MUST failed, {should} SHOULD to consider"
