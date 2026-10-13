"""Evaluation datasets: versioned JSONL files with a manifest that pins their hash.

    evals/datasets/<name>/
      dataset.yaml      name, card, owner, and for each version: file + sha256
      v1.jsonl          one test case per line

Like prompts (Step 24), a released version never changes: a changed file is a new version,
otherwise "recall went from 0.82 to 0.86" might just mean "someone edited the questions".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Text = Annotated[str, Field(min_length=1)]


class EvalError(Exception):
    """A dataset, target or gate is unusable. The message says exactly what and where."""


class Persona(BaseModel):
    """Who is asking. Retrieval is evaluated AS this person, through the real policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    groups: tuple[str, ...]
    roles: tuple[str, ...] = ("rag-user",)


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["retrieval"]
    id: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    question: Text
    persona: Persona
    relevant: tuple[int, ...] = ()  # document ids that answer it AND this person may read
    forbidden: tuple[int, ...] = ()  # ids this person must never receive (policy checks)
    tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> RetrievalCase:
        if not self.relevant and not self.forbidden:
            raise ValueError("a retrieval case needs relevant and/or forbidden ids")
        if set(self.relevant) & set(self.forbidden):
            raise ValueError("an id can't be both relevant and forbidden")
        return self


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    text: Text


class AnswerCase(BaseModel):
    """A question with FIXED contexts: tests the prompt and model, independent of retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["answer"]
    id: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    question: Text
    contexts: tuple[Context, ...] = Field(min_length=1)
    reference: str = ""  # a correct answer, for the judge; empty when it should refuse
    must_cite: tuple[int, ...] = ()
    should_refuse: bool = False  # the contexts don't contain the answer
    must_not_contain: tuple[str, ...] = ()  # e.g. text an injected instruction tries to extract
    tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> AnswerCase:
        ids = {c.id for c in self.contexts}
        if not set(self.must_cite) <= ids:
            raise ValueError("must_cite ids must be among the contexts")
        if self.should_refuse and (self.must_cite or self.reference):
            raise ValueError("a refusal case has no citations and no reference answer")
        if not self.should_refuse and not (self.must_cite and self.reference):
            raise ValueError("an answer case needs must_cite and a reference answer")
        return self


Case = Annotated[RetrievalCase | AnswerCase, Field(discriminator="kind")]


class _CaseLine(BaseModel):
    case: Case


class VersionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    card: str  # the dataset card (Step 25), e.g. dataset:rag-answer-golden
    owner: str
    description: str
    versions: dict[int, VersionEntry]


class Dataset(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    version: int
    sha256: str
    card: str
    cases: tuple[RetrievalCase | AnswerCase, ...]

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


def load_dataset(root: Path, name: str, version: int | None = None) -> Dataset:
    folder = root / name
    try:
        manifest = Manifest.model_validate(yaml.safe_load((folder / "dataset.yaml").read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise EvalError(f"{folder / 'dataset.yaml'}: {e}") from e
    if not manifest.versions:
        raise EvalError(f"{name}: nothing released yet: run `just evals release {name}`")
    version = version or max(manifest.versions)
    entry = manifest.versions.get(version)
    if entry is None:
        raise EvalError(f"{name}: no version {version} (have {sorted(manifest.versions)})")
    path = folder / entry.file
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry.sha256:
        raise EvalError(
            f"{path} changed after release: create v{max(manifest.versions) + 1} instead"
        )
    cases = load_case_lines(path)
    ids = [c.id for c in cases]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        raise EvalError(f"{path}: duplicate case ids {dupes}")
    return Dataset(name=name, version=version, sha256=entry.sha256, card=manifest.card,
                   cases=tuple(cases))  # fmt: skip


def release(root: Path, name: str) -> list[int]:
    """Record the SHA-256 of every new v<N>.jsonl in the manifest. Released files never change."""
    folder = root / name
    path = folder / "dataset.yaml"
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise EvalError(f"{path}: {e}") from e
    versions: dict[int, dict[str, str]] = {
        int(k): v for k, v in (data.get("versions") or {}).items()
    }
    added = []
    for f in sorted(folder.glob("v*.jsonl"), key=lambda p: int(p.stem[1:])):
        n = int(f.stem[1:])
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        if n in versions:
            if versions[n]["sha256"] != sha:
                raise EvalError(
                    f"{f} was released and has been edited: revert it, add v{max(versions) + 1}"
                )
            continue
        load_case_lines(f)  # only valid files can be released
        versions[n] = {"file": f.name, "sha256": sha}
        added.append(n)
    data["versions"] = dict(sorted(versions.items()))
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
    return added


def load_case_lines(path: Path) -> list[RetrievalCase | AnswerCase]:
    cases: list[RetrievalCase | AnswerCase] = []
    for n, line in enumerate(path.read_text().splitlines(), start=1):
        if line.strip():
            try:
                cases.append(_CaseLine.model_validate({"case": json.loads(line)}).case)
            except (json.JSONDecodeError, ValidationError) as e:
                raise EvalError(f"{path}:{n}: {e}") from e
    return cases
