"""Prompt registry (Step 24): prompts are versioned, reviewed files, not strings buried in code.

Layout of the registry folder (the repository's `prompts/`):

    prompts/
      rag-answer/v1.yaml, v2.yaml …   one file per VERSION; a released version never changes
      query-instruction/v1.yaml
      labels.yaml                     which version each environment uses (production, staging…)
      prompts.lock.json               SHA-256 of every released version: proof nothing was edited

Rules enforced here (and therefore in tests, pre-commit and CI):
  * every {{placeholder}} is declared, and every declared variable is used
  * variables marked `untrusted` (user questions, retrieved documents) never appear in a system
    message, and must sit inside an XML-style tag; the renderer neutralises that closing tag
    inside the value, so a document can't "close the box" and pose as instructions
  * released versions match their locked hash exactly; locked entries can be added, never changed
  * labels point at versions that exist
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

NAME = r"^[a-z][a-z0-9-]{1,62}$"
LABEL = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
VERSION_FILE = re.compile(r"^v([1-9][0-9]*)\.yaml$")
LOCK_FILE = "prompts.lock.json"
LABELS_FILE = "labels.yaml"


class PromptError(Exception):
    """The registry or a render request is invalid. The message says exactly what and where."""


class Variable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: str = Field(min_length=3)
    max_chars: int = Field(gt=0, le=200_000)  # an upper bound on what may be inserted
    untrusted: bool = False  # True for anything a user or a document controls


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset: str  # filled in by the evaluation harness (Step 26)
    min_score: float = Field(ge=0, le=1)


class PromptVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(pattern=NAME)
    version: int = Field(ge=1)
    kind: Literal["chat", "text"]  # chat = messages for an LLM; text = one string (e.g. embeddings)
    description: str = Field(min_length=10)
    owner: str = Field(min_length=2)  # the team answerable for it
    model: str | None = None  # a gateway alias (Step 9), never a provider model id
    params: dict[str, float | int | bool | str] = Field(default_factory=dict)
    messages: tuple[Message, ...] = ()
    template: str | None = None
    variables: dict[str, Variable] = Field(default_factory=dict)
    evaluation: Evaluation | None = None
    changelog: str = Field(min_length=3)

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def parts(self) -> list[tuple[str, str]]:
        """(role, text) pairs; a text prompt is one part with role "text"."""
        if self.kind == "text":
            return [("text", self.template or "")]
        return [(m.role, m.content) for m in self.messages]

    @model_validator(mode="after")
    def _check(self) -> PromptVersion:
        if self.kind == "chat" and (not self.messages or self.template is not None):
            raise ValueError("a chat prompt needs `messages` and no `template`")
        if self.kind == "text" and (self.template is None or self.messages):
            raise ValueError("a text prompt needs `template` and no `messages`")
        used: set[str] = set()
        for role, text in self.parts():
            names = set(PLACEHOLDER.findall(text))
            used |= names
            for n in names:
                v = self.variables.get(n)
                if v is not None and v.untrusted and role == "system":
                    raise ValueError(
                        f"untrusted variable '{n}' must not appear in a system message"
                    )
                if v is not None and v.untrusted and not _boxed(text, n):
                    raise ValueError(
                        f"untrusted variable '{n}' must sit alone inside a tag, "
                        f"e.g. <{n}>{{{{{n}}}}}</{n}>"
                    )
        if undeclared := used - self.variables.keys():
            raise ValueError(f"placeholders not declared in `variables`: {sorted(undeclared)}")
        if unused := self.variables.keys() - used:
            raise ValueError(f"variables declared but never used: {sorted(unused)}")
        return self


def _box_pattern(var: str) -> re.Pattern[str]:
    return re.compile(r"<([a-z][a-z0-9_-]*)>\s*\{\{\s*" + re.escape(var) + r"\s*\}\}\s*</\1>")


def _boxed(text: str, var: str) -> bool:
    """Every occurrence of {{var}} is wrapped directly in <tag>…</tag>."""
    total = len([m for m in PLACEHOLDER.finditer(text) if m.group(1) == var])
    return total > 0 and len(_box_pattern(var).findall(text)) == total


def _neutralise(value: str, tags: set[str]) -> str:
    """A value must not be able to close its own box: `</documents>` becomes `<\\/documents>`."""
    for tag in tags:
        value = re.sub(rf"</(\s*){re.escape(tag)}", rf"<\\/\1{tag}", value, flags=re.IGNORECASE)
    return value


@dataclass(frozen=True)
class Rendered:
    ref: str  # "rag-answer@2": record this with every call that used it
    sha256: str  # the exact file that produced it
    model: str | None
    params: Mapping[str, float | int | bool | str]
    messages: tuple[dict[str, str], ...]  # chat prompts
    text: str | None  # text prompts


def render(p: PromptVersion, sha256: str, values: Mapping[str, str]) -> Rendered:
    missing = p.variables.keys() - values.keys()
    extra = values.keys() - p.variables.keys()
    if missing or extra:
        raise PromptError(f"{p.ref}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    safe: dict[str, str] = {}
    for name, var in p.variables.items():
        value = values[name]
        if not isinstance(value, str):
            raise PromptError(f"{p.ref}: '{name}' must be text")
        if len(value) > var.max_chars:
            raise PromptError(f"{p.ref}: '{name}' is {len(value)} chars (max {var.max_chars})")
        if var.untrusted:
            tags = {m.group(1) for _, t in p.parts() for m in _box_pattern(name).finditer(t)}
            value = _neutralise(value, tags)
        safe[name] = value

    def fill(text: str) -> str:  # ONE pass: inserted values are never scanned for placeholders
        return PLACEHOLDER.sub(lambda m: safe[m.group(1)], text)

    if p.kind == "text":
        return Rendered(p.ref, sha256, p.model, p.params, (), fill(p.template or ""))
    msgs = tuple({"role": m.role, "content": fill(m.content)} for m in p.messages)
    return Rendered(p.ref, sha256, p.model, p.params, msgs, None)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lock(root: Path) -> dict[str, dict[str, str]]:
    path = root / LOCK_FILE
    data: dict[str, dict[str, str]] = json.loads(path.read_text()) if path.exists() else {}
    return data


def write_lock(root: Path, lock: Mapping[str, Mapping[str, str]]) -> None:
    ordered = {
        n: dict(sorted(v.items(), key=lambda kv: int(kv[0]))) for n, v in sorted(lock.items())
    }
    (root / LOCK_FILE).write_text(json.dumps(ordered, indent=2) + "\n")


def lock_only_grew(
    old: Mapping[str, Mapping[str, str]], new: Mapping[str, Mapping[str, str]]
) -> list[str]:
    """Compare with the lock on main: entries may be added, never changed or removed."""
    problems = []
    for name, versions in old.items():
        for v, sha in versions.items():
            now = new.get(name, {}).get(v)
            if now is None:
                problems.append(f"{name}@{v} was released and can't be removed")
            elif now != sha:
                problems.append(f"{name}@{v} was released and can't be changed: add a new version")
    return problems


def load_version(path: Path) -> PromptVersion:
    try:
        data = yaml.safe_load(path.read_text())  # safe_load: YAML can't create Python objects
        return PromptVersion.model_validate(data)
    except (yaml.YAMLError, ValidationError) as e:
        raise PromptError(f"{path}: {e}") from e


class Registry:
    def __init__(
        self,
        versions: Mapping[tuple[str, int], tuple[PromptVersion, str]],
        labels: Mapping[str, Mapping[str, int]],
    ) -> None:
        self._versions = dict(versions)
        self._labels = {n: dict(v) for n, v in labels.items()}

    @classmethod
    def load(cls, root: Path, *, require_lock: bool = True) -> Registry:
        if not root.is_dir():
            raise PromptError(f"prompt registry not found: {root}")
        versions: dict[tuple[str, int], tuple[PromptVersion, str]] = {}
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            for path in sorted(folder.iterdir()):
                m = VERSION_FILE.match(path.name)
                if not m:
                    raise PromptError(f"{path}: prompt files are named v1.yaml, v2.yaml, …")
                p = load_version(path)
                if (p.name, p.version) != (folder.name, int(m.group(1))):
                    raise PromptError(f"{path}: says {p.ref}, but its path says "
                                      f"{folder.name}@{m.group(1)}")  # fmt: skip
                versions[(p.name, p.version)] = (p, file_sha256(path))
        if require_lock:
            lock = read_lock(root)
            for (name, v), (_, sha) in versions.items():
                locked = lock.get(name, {}).get(str(v))
                if locked is None:
                    raise PromptError(f"{name}@{v} is not released yet: run `just prompts lock`")
                if locked != sha:
                    raise PromptError(f"{name}@{v} changed after release (hash mismatch): "
                                      "revert it and create a new version")  # fmt: skip
            for name, released in lock.items():
                for ver in released:
                    if (name, int(ver)) not in versions:
                        raise PromptError(f"{name}@{ver} was released but its file is missing")
        raw = (
            yaml.safe_load((root / LABELS_FILE).read_text())
            if (root / LABELS_FILE).exists()
            else {}
        )
        labels: dict[str, dict[str, int]] = {}
        for name, mapping in (raw or {}).items():
            for label, v in (mapping or {}).items():
                if not LABEL.match(label):
                    raise PromptError(f"labels.yaml: bad label name '{label}'")
                if (name, v) not in versions:
                    raise PromptError(f"labels.yaml: {name}.{label} points at missing version {v}")
                labels.setdefault(name, {})[label] = v
        return cls(versions, labels)

    def names(self) -> list[str]:
        return sorted({n for n, _ in self._versions})

    def versions_of(self, name: str) -> list[int]:
        return sorted(v for n, v in self._versions if n == name)

    def labels_of(self, name: str) -> dict[str, int]:
        return dict(self._labels.get(name, {}))

    def get(self, name: str, *, label: str | None = None, version: int | None = None
            ) -> tuple[PromptVersion, str]:  # fmt: skip
        if version is None:
            label = label or "production"
            if (version := self._labels.get(name, {}).get(label)) is None:
                raise PromptError(f"no '{label}' version of prompt '{name}'")
        try:
            return self._versions[(name, version)]
        except KeyError:
            raise PromptError(f"prompt {name}@{version} does not exist") from None

    def render(self, name: str, values: Mapping[str, str], *, label: str | None = None,
               version: int | None = None) -> Rendered:  # fmt: skip
        p, sha = self.get(name, label=label, version=version)
        return render(p, sha, values)

    def active(self, label: str) -> dict[str, tuple[PromptVersion, str]]:
        """Every prompt that has a version under this label, e.g. what production runs."""
        return {n: self._versions[(n, ls[label])] for n, ls in self._labels.items() if label in ls}
