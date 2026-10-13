"""Model, dataset and system cards, and the lineage between them (Step 25).

A card is a short, versioned, reviewed YAML file answering the questions people ask about an AI
component: what is it, who owns it, where did it come from, what may it be used for, what is it
bad at, which personal data does it hold, and what depends on it.

    cards/
      policy.yaml            allowed licences, review intervals
      models/<id>.yaml       one per gateway alias (qwen-quality, embedder, …)
      datasets/<id>.yaml     source data, derived indexes, traces, evaluation sets
      systems/<id>.yaml      the applications people actually use (rag-api)

Facts already recorded elsewhere are NOT repeated, they're checked: repository and revision come
from infra/model-serving/models.yaml, aliases and fallbacks from the LiteLLM config, prompt-model
links from the prompt registry (Step 24). Cards hold the judgement: intended use, limits, risks.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rag_common.prompts import PromptError, Registry

ID = r"^[a-z][a-z0-9-]{1,62}$"
NODE = re.compile(r"^(model|dataset|system|prompt):[a-z][a-z0-9-]{1,62}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
# The unfilled template value Steps 7-8 leave in models.yaml ("<40-char SHA>") until the model is
# downloaded on the Mac. Reported as a warning (see _check_model), anything else unpinned is an error.
PLACEHOLDER = re.compile(r"^<[^>]*>$")
Status = Literal["planned", "candidate", "approved", "deprecated", "retired"]
Text = Annotated[str, Field(min_length=3)]


class CardError(Exception):
    """A card is malformed. (Rule violations are collected as findings instead.)"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Licence(_Strict):
    id: str  # an SPDX identifier (apache-2.0, mit…) or "internal"
    url: str
    verified_on: dt.date | None = None  # when someone last read the actual licence text


class Approval(_Strict):
    by: str
    date: dt.date  # not "on": YAML 1.1 reads a bare `on` as the boolean true
    note: str = ""


class EvalResult(_Strict):
    metric: str
    value: float
    dataset: str
    date: dt.date


class Card(_Strict):
    kind: str
    id: str = Field(pattern=ID)
    title: Text
    status: Status
    owner: Text  # the team answerable for it
    summary: Text
    inputs: tuple[str, ...] = ()  # lineage: what this was built from, as "kind:id"
    known_limitations: tuple[Text, ...] = Field(min_length=1)
    last_reviewed: dt.date
    review_every_days: int = Field(gt=0, le=730)
    approvals: tuple[Approval, ...] = ()

    @property
    def node(self) -> str:
        return f"{self.kind}:{self.id}"


class ModelCard(Card):
    kind: Literal["model"]
    task: Literal["generation", "embedding", "reranking", "classification"]
    licence: Licence
    intended_use: tuple[Text, ...] = Field(min_length=1)
    out_of_scope: tuple[Text, ...] = Field(min_length=1)
    risks: tuple[Text, ...] = ()
    training_data: Text  # what the publisher says (often: not disclosed in detail)
    data_handling: Text  # where prompts and outputs go when this model runs
    fallback_allowed: bool = True  # False: the gateway must never route this alias elsewhere
    evaluation: tuple[EvalResult, ...] = ()  # filled in by the evaluation harness (Step 26)


class DatasetCard(Card):
    kind: Literal["dataset"]
    role: Literal["source", "derived", "operational", "evaluation"]
    locations: tuple[Text, ...] = Field(min_length=1)
    provenance: Text  # where it comes from, and how
    classification_max: Literal["public", "internal", "confidential", "restricted"]
    personal_data: bool
    personal_data_notes: str = ""
    legal_basis: str = ""  # required when personal_data is true
    retention: Text
    deletion: Text  # how a deletion request reaches every copy
    access: Text
    terms: Licence | None = None


class SystemCard(Card):
    kind: Literal["system"]
    purpose: Text
    users: Text
    intended_use: tuple[Text, ...] = Field(min_length=1)
    out_of_scope: tuple[Text, ...] = Field(min_length=1)
    human_oversight: Text  # who can see, correct and stop it
    risk_assessment: Text  # e.g. the EU AI Act category you believe applies, and why


class Policy(_Strict):
    allowed_licences: tuple[str, ...]
    licence_review_days: int = Field(gt=0)


KINDS: dict[str, type[Card]] = {"models": ModelCard, "datasets": DatasetCard, "systems": SystemCard}


@dataclass
class Finding:
    level: Literal["error", "warning"]
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.where}: {self.message}"


@dataclass
class Catalogue:
    cards: dict[str, Card]  # by node, e.g. "model:embedder"
    policy: Policy
    inventory: dict[str, dict[str, Any]] = field(default_factory=dict)  # models.yaml, by id
    gateway: dict[str, Any] = field(default_factory=dict)  # LiteLLM config
    prompts: Registry | None = None

    # ------------------------------------------------------------------ loading

    @classmethod
    def load(cls, root: Path, *, inventory: Path | None = None, gateway: Path | None = None,
             prompts: Path | None = None) -> Catalogue:  # fmt: skip
        try:
            policy = Policy.model_validate(yaml.safe_load((root / "policy.yaml").read_text()))
        except (OSError, yaml.YAMLError, ValidationError) as e:
            raise CardError(f"{root / 'policy.yaml'}: {e}") from e
        cards: dict[str, Card] = {}
        for folder, model in KINDS.items():
            for path in sorted((root / folder).glob("*.yaml")):
                try:
                    card = model.model_validate(yaml.safe_load(path.read_text()))
                except (yaml.YAMLError, ValidationError) as e:
                    raise CardError(f"{path}: {e}") from e
                if card.id != path.stem:
                    raise CardError(f"{path}: id '{card.id}' must match the file name")
                cards[card.node] = card
        inv: dict[str, dict[str, Any]] = {}
        if inventory is not None:
            inv = {m["id"]: m for m in (yaml.safe_load(inventory.read_text()) or {})["models"]}
        gw = yaml.safe_load(gateway.read_text()) if gateway is not None else {}
        reg = Registry.load(prompts) if prompts is not None else None
        return cls(cards, policy, inv, gw or {}, reg)

    # ------------------------------------------------------------------ the lineage graph

    def gateway_aliases(self) -> set[str]:
        return {m["model_name"] for m in self.gateway.get("model_list", []) or []}

    def fallbacks(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for entry in (self.gateway.get("litellm_settings") or {}).get("fallbacks", []) or []:
            for src, targets in entry.items():
                out.setdefault(src, []).extend(targets)
        return out

    def edges(self) -> list[tuple[str, str, str]]:
        """(upstream, downstream, how). Cards declare inputs; prompts and the gateway add more."""
        out = [(i, node, "input") for node, c in self.cards.items() for i in c.inputs]
        if self.prompts is not None:
            fallbacks = self.fallbacks()
            for name in self.prompts.names():
                # Every version, not only the labelled ones: staging may run a different model.
                models = {self.prompts.get(name, version=v)[0].model
                          for v in self.prompts.versions_of(name)}  # fmt: skip
                for m in sorted(x for x in models if x):
                    out.append((f"model:{m}", f"prompt:{name}", "runs on"))
                    for fb in fallbacks.get(m, []):
                        out.append((f"model:{fb}", f"prompt:{name}", "fallback"))
        return out

    def nodes(self) -> set[str]:
        return set(self.cards) | {n for e in self.edges() for n in e[:2]}

    def downstream(self, node: str) -> list[tuple[int, str, str]]:
        """Everything affected if `node` changes: (depth, node, how), breadth-first."""
        children: dict[str, list[tuple[str, str]]] = {}
        for up, down, how in self.edges():
            children.setdefault(up, []).append((down, how))
        seen = {node}
        out: list[tuple[int, str, str]] = []
        frontier = [(node, 0)]
        while frontier:
            current, depth = frontier.pop(0)
            for child, how in sorted(children.get(current, [])):
                if child not in seen:
                    seen.add(child)
                    out.append((depth + 1, child, how))
                    frontier.append((child, depth + 1))
        return out

    def upstream(self, node: str) -> list[str]:
        """Everything `node` was built from, directly or indirectly."""
        parents: dict[str, list[str]] = {}
        for up, down, _ in self.edges():
            parents.setdefault(down, []).append(up)
        seen: list[str] = []
        stack = list(parents.get(node, []))
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.append(n)
                stack.extend(parents.get(n, []))
        return sorted(seen)

    def mermaid(self) -> str:
        shape = {"model": ("([", "])"), "dataset": ("[(", ")]"), "system": ("[[", "]]"),
                 "prompt": ("[/", "/]")}  # fmt: skip
        lines = ["flowchart LR"]
        for n in sorted(self.nodes()):
            kind, name = n.split(":", 1)
            a, b = shape[kind]
            lines.append(f'    {kind}_{name.replace("-", "_")}{a}"{n}"{b}')
        arrow = {"input": "-->", "runs on": "-->", "fallback": "-.->|fallback|"}
        for up, down, how in sorted(set(self.edges())):
            u, d = (x.replace(":", "_").replace("-", "_") for x in (up, down))
            lines.append(f"    {u} {arrow[how]} {d}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ the rules

    def check(self, today: dt.date) -> list[Finding]:
        f: list[Finding] = []
        nodes = self.nodes()
        for node, c in sorted(self.cards.items()):
            for i in c.inputs:
                if not NODE.match(i):
                    f.append(Finding("error", node, f"input '{i}' must look like kind:id"))
                elif i not in self.cards and not i.startswith("prompt:"):
                    f.append(Finding("error", node, f"input '{i}' has no card"))
                elif i.startswith("prompt:") and (
                    self.prompts is None or i[7:] not in self.prompts.names()
                ):
                    f.append(Finding("error", node, f"input '{i}' is not in the prompt registry"))
            if c.status == "approved" and not c.approvals:
                f.append(Finding("error", node, "approved, but no approval is recorded"))
            due = c.last_reviewed + dt.timedelta(days=c.review_every_days)
            if c.status in ("approved", "candidate") and due < today:
                f.append(
                    Finding("warning", node, f"review overdue since {due} (last {c.last_reviewed})")
                )
            for i in c.inputs:
                src = self.cards.get(i)
                if (
                    c.status == "approved"
                    and src is not None
                    and src.status in ("retired", "deprecated")
                ):
                    f.append(Finding("warning", node, f"depends on {src.status} {i}"))
            if isinstance(c, ModelCard):
                f += self._check_model(c, today)
            if isinstance(c, DatasetCard):
                f += self._check_dataset(c)
        f += self._check_gateway_and_inventory()
        f += self._check_prompts()
        f += self._check_cycles(nodes)
        return f

    def _check_model(self, c: ModelCard, today: dt.date) -> list[Finding]:
        f: list[Finding] = []
        node = c.node
        if c.licence.id not in self.policy.allowed_licences:
            f.append(Finding("error", node, f"licence '{c.licence.id}' is not on the allowed list"))
        if c.status == "approved":
            if c.licence.verified_on is None:
                f.append(Finding("error", node, "approved, but nobody has verified the licence"))
            elif (today - c.licence.verified_on).days > self.policy.licence_review_days:
                f.append(
                    Finding(
                        "warning",
                        node,
                        f"licence last verified {c.licence.verified_on}: re-check it",
                    )
                )
            inv = self.inventory.get(c.id)
            revision = str((inv or {}).get("revision", ""))
            if self.inventory and inv is None:
                f.append(Finding("error", node, "approved, but missing from models.yaml"))
            elif inv is not None and PLACEHOLDER.match(revision):
                # Not filled in yet (this repository ships the Step 7-8 template). A warning, so
                # the weekly strict run fails until someone pins it; any other value must be a SHA.
                f.append(
                    Finding(
                        "warning",
                        node,
                        "models.yaml revision is still a placeholder: pin the 40-character SHA "
                        "from the snapshots folder (Steps 7-8)",
                    )
                )
            elif inv is not None and not SHA40.match(revision):
                f.append(Finding("error", node, "models.yaml has no pinned 40-character revision"))
            if not c.evaluation:
                f.append(Finding("warning", node, "no evaluation results yet (Step 26 adds them)"))
        if not c.fallback_allowed and self.fallbacks().get(c.id):
            f.append(
                Finding(
                    "error",
                    node,
                    f"must never fall back, but the gateway sends it to {self.fallbacks()[c.id]}",
                )
            )
        return f

    @staticmethod
    def _check_dataset(c: DatasetCard) -> list[Finding]:
        f: list[Finding] = []
        node = c.node
        if c.personal_data and (not c.legal_basis.strip() or not c.personal_data_notes.strip()):
            f.append(Finding("error", node, "holds personal data: state what, and the legal basis"))
        if c.role == "derived" and not c.inputs:
            f.append(Finding("error", node, "a derived dataset must name what it was derived from"))
        if c.role == "evaluation" and c.personal_data:
            f.append(
                Finding(
                    "error",
                    node,
                    "evaluation sets must not contain personal data (anonymise or synthesise)",
                )
            )
        return f

    def _check_gateway_and_inventory(self) -> list[Finding]:
        f: list[Finding] = []
        models = {c.id: c for c in self.cards.values() if isinstance(c, ModelCard)}
        for alias in sorted(self.gateway_aliases()):
            card = models.get(alias)
            if card is None:
                f.append(
                    Finding(
                        "error", f"gateway:{alias}", "served by the gateway, but has no model card"
                    )
                )
            elif card.status not in ("approved", "candidate"):
                f.append(
                    Finding(
                        "error", f"gateway:{alias}", f"served, but its card says '{card.status}'"
                    )
                )
        for src, targets in sorted(self.fallbacks().items()):
            for t in targets:
                if t in models and models[t].status != "approved":
                    f.append(
                        Finding(
                            "error", f"gateway:{src}", f"falls back to {t}, which is not approved"
                        )
                    )
        for mid in sorted(self.inventory):
            if mid not in models:
                f.append(
                    Finding(
                        "error", f"models.yaml:{mid}", "in the inventory, but has no model card"
                    )
                )
        return f

    def _check_prompts(self) -> list[Finding]:
        if self.prompts is None:
            return []
        f: list[Finding] = []
        models = {c.id: c for c in self.cards.values() if isinstance(c, ModelCard)}
        for name in self.prompts.names():
            for label, v in sorted(self.prompts.labels_of(name).items()):
                p, _ = self.prompts.get(name, version=v)
                card = models.get(p.model or "")
                if p.model and (card is None or card.status != "approved"):
                    f.append(Finding("error", f"prompt:{name}@{v}",
                                     f"'{label}' runs it on {p.model}, which has no approved model card"))  # fmt: skip
        # The query instruction is part of the embedding contract (Steps 8, 24): they must agree.
        contract = (self.inventory.get("embedder") or {}).get("contract", {})
        if contract and "query-instruction" in self.prompts.names():
            for label in self.prompts.labels_of("query-instruction"):
                try:
                    text = self.prompts.render("query-instruction", {"query": ""}, label=label).text
                except PromptError as e:
                    f.append(Finding("error", "prompt:query-instruction", str(e)))
                    continue
                if text != contract.get("query_instruction"):
                    f.append(Finding("error", "prompt:query-instruction",
                                     f"'{label}' text differs from the embedder's contract in models.yaml: "
                                     "re-index, or keep them identical"))  # fmt: skip
        return f

    def _check_cycles(self, nodes: Iterable[str]) -> list[Finding]:
        children: dict[str, list[str]] = {}
        for up, down, _ in self.edges():
            children.setdefault(up, []).append(down)
        state: dict[str, int] = {}  # 1 = visiting, 2 = done

        def visit(n: str, path: list[str]) -> list[str] | None:
            if state.get(n) == 1:
                return [*path, n]
            if state.get(n) == 2:
                return None
            state[n] = 1
            for c in children.get(n, []):
                if (cycle := visit(c, [*path, n])) is not None:
                    return cycle
            state[n] = 2
            return None

        for n in sorted(nodes):
            if (cycle := visit(n, [])) is not None:
                return [Finding("error", "lineage", "cycle: " + " -> ".join(cycle))]
        return []


# ---------------------------------------------------------------------- human-readable cards


def _bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


def render_markdown(cat: Catalogue, node: str) -> str:
    """The card as a page people read. Generated: edit the YAML, never this output."""
    c = cat.cards[node]
    out = [f"# {c.title}", "", "<!-- generated from cards/ by `just cards docs`: do not edit -->", "",
           f"| | |\n|---|---|\n| **Id** | `{node}` |\n| **Status** | {c.status} |\n| **Owner** | {c.owner} |",
           f"| **Last reviewed** | {c.last_reviewed} (every {c.review_every_days} days) |"]  # fmt: skip
    if isinstance(c, ModelCard):
        inv = cat.inventory.get(c.id, {})
        out += [f"| **Task** | {c.task} |",
                f"| **Weights** | `{inv.get('repo', '?')}` @ `{str(inv.get('revision', '?'))[:12]}` |",
                f"| **Licence** | [{c.licence.id}]({c.licence.url}), verified {c.licence.verified_on or 'never'} |",
                f"| **Fallback allowed** | {'yes' if c.fallback_allowed else 'no'} |"]  # fmt: skip
    if isinstance(c, DatasetCard):
        out += [f"| **Role** | {c.role} |", f"| **Highest classification** | {c.classification_max} |",
                f"| **Personal data** | {'yes' if c.personal_data else 'no'} |",
                f"| **Retention** | {c.retention} |"]  # fmt: skip
    out += ["", "## Summary", "", c.summary.strip()]
    sections: list[tuple[str, Any]] = []
    if isinstance(c, ModelCard | SystemCard):
        sections += [("Intended use", c.intended_use), ("Out of scope", c.out_of_scope)]
    if isinstance(c, SystemCard):
        sections += [("Purpose", c.purpose), ("Users", c.users),
                     ("Human oversight", c.human_oversight), ("Risk assessment", c.risk_assessment)]  # fmt: skip
    if isinstance(c, ModelCard):
        sections += [("Training data", c.training_data), ("Data handling", c.data_handling),
                     ("Risks", c.risks)]  # fmt: skip
    if isinstance(c, DatasetCard):
        sections += [("Where it lives", c.locations), ("Provenance", c.provenance),
                     ("Personal data", c.personal_data_notes or "None."),
                     ("Legal basis", c.legal_basis or "Not applicable."),
                     ("Deletion", c.deletion), ("Access", c.access)]  # fmt: skip
    sections.append(("Known limitations", c.known_limitations))
    for title, value in sections:
        body = value.strip() if isinstance(value, str) else _bullets(value)
        out += ["", f"## {title}", "", body]
    if isinstance(c, ModelCard):
        rows = [f"| {r.metric} | {r.value} | {r.dataset} | {r.date} |" for r in c.evaluation]
        out += ["", "## Evaluation", "",
                "| Metric | Value | Dataset | Date |\n|---|---|---|---|\n" + "\n".join(rows)
                if rows else "No results yet (Step 26)."]  # fmt: skip
    up = cat.upstream(node)
    down = [f"{'  ' * (d - 1)}- {n} ({how})" for d, n, how in cat.downstream(node)]
    out += ["", "## Lineage", "", "Built from:", "", _bullets(up), "", "Affects if changed:", "",
            "\n".join(down) or "- (nothing)"]  # fmt: skip
    out += [
        "",
        "## Approvals",
        "",
        _bullets(f"{a.date} · {a.by}{' · ' + a.note if a.note else ''}" for a in c.approvals),
    ]
    return "\n".join(out) + "\n"


def render_index(cat: Catalogue) -> str:
    rows = [f"| [{n}]({n.replace(':', '-')}.md) | {c.title} | {c.status} | {c.owner} | {c.last_reviewed} |"
            for n, c in sorted(cat.cards.items())]  # fmt: skip
    return ("# Cards: models, datasets and systems\n\n"
            "<!-- generated from cards/ by `just cards docs`: do not edit -->\n\n"
            "| Card | Title | Status | Owner | Last reviewed |\n|---|---|---|---|---|\n"
            + "\n".join(rows) + "\n\n## Lineage\n\n```mermaid\n" + cat.mermaid() + "```\n")  # fmt: skip


def documents(cat: Catalogue) -> Mapping[str, str]:
    docs = {f"{n.replace(':', '-')}.md": render_markdown(cat, n) for n in cat.cards}
    docs["README.md"] = render_index(cat)
    return docs
