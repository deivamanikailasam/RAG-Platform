"""Named, switchable components (Step 30).

    @register("reranker", "cross-encoder", params=CrossEncoderParams, summary="…", status="live")
    def _cross_encoder(p: CrossEncoderParams, c: Container) -> Reranker: ...

A config file then says `reranker: {use: cross-encoder, top_n: 8}`, and the Container builds it,
with its parameters validated and its own dependencies (an LLM, an embedder) built on demand.
Switching an implementation is a one-word change in config: no code changes in the project.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

Status = Literal["live", "mocked", "reference"]  # how it was tested: see describe()


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentError(Exception):
    """A config names an unknown component, or gives it bad parameters. Says exactly which."""


@dataclass(frozen=True)
class Spec:
    kind: str
    name: str
    factory: Callable[[Any, Container], Any]
    params: type[BaseModel]
    summary: str
    status: Status
    requires: tuple[str, ...]  # optional extras that must be installed, e.g. ("pdf",)


_REGISTRY: dict[str, dict[str, Spec]] = {}


def register(kind: str, name: str, *, params: type[BaseModel] = NoParams, summary: str = "",
             status: Status = "live", requires: tuple[str, ...] = ()) -> Callable[[Any], Any]:  # fmt: skip
    def deco(factory: Callable[[Any, Container], Any]) -> Callable[[Any, Container], Any]:
        bucket = _REGISTRY.setdefault(kind, {})
        if name in bucket:
            raise ComponentError(f"{kind} '{name}' registered twice")
        bucket[name] = Spec(kind, name, factory, params, summary, status, requires)
        return factory

    return deco


def kinds() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


def specs(kind: str) -> list[Spec]:
    _load_builtins()
    return sorted(_REGISTRY.get(kind, {}).values(), key=lambda s: s.name)


def spec(kind: str, name: str) -> Spec:
    _load_builtins()
    bucket = _REGISTRY.get(kind)
    if bucket is None:
        raise ComponentError(
            f"unknown component kind {kind!r} (known: {', '.join(sorted(_REGISTRY))})"
        )
    if name not in bucket:
        close = difflib.get_close_matches(name, bucket, n=1)
        hint = f"; did you mean {close[0]!r}?" if close else ""
        raise ComponentError(
            f"no {kind} named {name!r}{hint} (available: {', '.join(sorted(bucket))})"
        )
    return bucket[name]


# A "slot" is a role in a pipeline; its kind says which components may fill it.
# Plural slots take a list of components applied in order.
SLOTS: dict[str, str] = {
    "llm": "llm", "judge_llm": "llm", "answer_llm": "llm", "token_counter": "token_counter", "embedder": "embedder",
    "parsers": "parser", "normalizers": "normalizer", "pii": "pii", "chunker": "chunker",
    "enrichers": "enricher", "vector_store": "vector_store", "keyword_index": "keyword_index",
    "query_transformer": "query_transformer", "retriever": "retriever", "fusion": "fusion",
    "reranker": "reranker", "postprocessors": "postprocessor", "context_builder": "context_builder",
    "generator": "generator", "guards": "guard", "cache": "cache", "memory": "memory",
    "queue": "queue", "manifest": "manifest", "pipeline": "pipeline", "graph_store": "graph_store",
    "search_cache": "search_cache",
}  # fmt: skip
PLURAL = {"parsers", "normalizers", "enrichers", "postprocessors", "guards"}


def _explain(e: ValidationError) -> str:
    """Pydantic's errors as one line: `dimensions: Input should be greater than or equal to 16`."""
    return "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())


@dataclass
class Container:
    """Builds the components a profile names, once each, wiring their dependencies."""

    config: Mapping[str, Any]
    profile: str = "default"
    _built: dict[str, Any] = field(default_factory=dict)
    _building: list[str] = field(default_factory=list)

    def get(self, slot: str) -> Any:
        if slot in self._built:
            return self._built[slot]
        if slot not in SLOTS:
            raise ComponentError(f"unknown slot {slot!r} (known: {', '.join(sorted(SLOTS))})")
        if slot in self._building:
            raise ComponentError(f"circular dependency: {' -> '.join([*self._building, slot])}")
        if slot not in self.config:
            raise ComponentError(
                f"profile {self.profile!r} doesn't configure {slot!r}, but something needs it"
            )
        raw = self.config[slot]
        if slot in PLURAL and not isinstance(raw, list):
            raise ComponentError(f"{slot}: expected a list of components, got {raw!r}")
        self._building.append(slot)
        try:
            built = (
                [self._build(slot, item) for item in raw]
                if slot in PLURAL
                else self._build(slot, raw)
            )
        finally:
            self._building.pop()
        self._built[slot] = built
        return built

    def has(self, slot: str) -> bool:
        return slot in self.config and self.config[slot] not in (None, [], {"use": "none"})

    def _build(self, slot: str, raw: Any) -> Any:
        if isinstance(raw, str):
            raw = {"use": raw}
        if not isinstance(raw, Mapping) or "use" not in raw:
            raise ComponentError(f"{slot}: expected {{use: <name>, …params}}, got {raw!r}")
        s = spec(SLOTS[slot], str(raw["use"]))
        try:
            params = s.params.model_validate({k: v for k, v in raw.items() if k != "use"})
        except ValidationError as e:
            raise ComponentError(f"{slot} '{s.name}': {_explain(e)}") from None
        try:
            return s.factory(params, self)
        except ImportError as e:
            extra = f" (install the extra: rag-core[{','.join(s.requires)}])" if s.requires else ""
            raise ComponentError(
                f"{slot} '{s.name}' needs a package that isn't installed: {e.name}{extra}"
            ) from None
        except (ValueError, KeyError, RuntimeError, OSError) as e:
            raise ComponentError(
                f"{slot} '{s.name}' could not start: {type(e).__name__}: {e}"
            ) from e

    def validate(self) -> list[str]:
        """Check every slot names a known component with valid parameters, WITHOUT building it
        (no connections, no secrets needed): what CI runs for profiles of other environments."""
        problems: list[str] = []
        for slot, raw in self.config.items():
            if slot == "extends":
                continue
            if slot not in SLOTS:
                problems.append(f"unknown slot {slot!r}")
                continue
            if slot in PLURAL and not isinstance(raw, list):
                problems.append(f"{slot}: expected a list of components, got {raw!r}")
                continue
            for entry in raw if slot in PLURAL else [raw]:
                item = {"use": entry} if isinstance(entry, str) else entry
                try:
                    if not isinstance(item, Mapping) or "use" not in item:
                        raise ComponentError(
                            f"{slot}: expected {{use: <name>, …params}}, got {item!r}"
                        )
                    s = spec(SLOTS[slot], str(item["use"]))
                    s.params.model_validate({k: v for k, v in item.items() if k != "use"})
                except ComponentError as e:
                    problems.append(str(e))
                except ValidationError as e:
                    problems.append(f"{slot} '{item['use']}': {_explain(e)}")
        return problems

    def build_all(self) -> dict[str, Any]:
        """Build every configured slot: what `rag config check` does."""
        return {slot: self.get(slot) for slot in self.config if slot in SLOTS}


class Overlay(Container):
    """Another container with some slots changed, sharing every other (already built) component:
    the ensemble retriever's members and the router's routes (extension 01) use one to search a
    second collection with the same embedder, or the same store with another retriever."""

    def __init__(self, parent: Container, overrides: Mapping[str, Any], name: str) -> None:
        own = {k: v for k, v in overrides.items() if k != "extends"}
        unknown = sorted(set(own) - set(SLOTS))
        if unknown:
            raise ComponentError(f"{name}: unknown slot(s) {', '.join(map(repr, unknown))}")
        merged = {**parent.config, **own}
        super().__init__({k: v for k, v in merged.items() if v not in ("none", None)}, name)
        self.parent, self.own = parent, set(own)

    def get(self, slot: str) -> Any:
        return super().get(slot) if slot in self.own else self.parent.get(slot)

    def has(self, slot: str) -> bool:
        return super().has(slot) if slot in self.own else self.parent.has(slot)


def describe() -> list[dict[str, Any]]:
    """Every component with its parameters, for `rag components` and the docs."""
    out = []
    for kind in kinds():
        for s in specs(kind):
            # get_default(call_default_factory=True): a `Field(default_factory=dict)` shows as {}
            fields = {n: (str(f.annotation).replace("typing.", ""),
                          f.get_default(call_default_factory=True) if not f.is_required() else "required")
                      for n, f in s.params.model_fields.items()}  # fmt: skip
            out.append({"kind": kind, "name": s.name, "status": s.status, "summary": s.summary,
                        "params": fields, "requires": list(s.requires)})  # fmt: skip
    return out


_loaded = False


def _load_builtins() -> None:
    """Import the built-in component modules once, so their @register calls run."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    import importlib
    import pkgutil

    from rag_core import components

    for mod in pkgutil.iter_modules(components.__path__):
        importlib.import_module(f"rag_core.components.{mod.name}")
    # A project's OWN components: any installed package can add some through an entry point,
    #   [project.entry-points."rag_core.components"]   my_parsers = "my_project.parsers"
    from importlib.metadata import entry_points

    for ep in entry_points(group="rag_core.components"):
        ep.load()
    # ... or named in RAG_PLUGINS (Step 38): for a container that copies a project's code next to
    # the platform image without installing it, e.g. RAG_PLUGINS=hr_assistant.components
    import os

    for name in filter(None, (m.strip() for m in os.environ.get("RAG_PLUGINS", "").split(","))):
        try:
            importlib.import_module(name)
        except ImportError as e:
            raise ComponentError(
                f"RAG_PLUGINS names {name!r}, which can't be imported: {e}"
            ) from None
