"""rag.yaml: which component fills each slot, per profile (Step 30).

    version: 1
    profiles:
      base:
        chunker: {use: structure, max_tokens: 400}
        reranker: {use: cross-encoder, top_n: 8}
      dev:
        extends: base
        reranker: none          # switched off for this profile

Selecting: `RAG_PROFILE=dev` (or an argument). Overriding one value without editing the file:
`RAG__RERANKER__TOP_N=5`, `RAG__RERANKER__USE=none` (double underscores = nesting; values are YAML).

Including the platform's tested profiles (Step 38), so a project's rag.yaml holds only what differs:

    version: 1
    include: {platform: "rag-core:platform.yaml"}     # or a path relative to this file
    profiles:
      offline: {extends: platform/offline, chunker: {max_tokens: 250}}
"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from rag_core.registry import ComponentError, Container

ENV_PREFIX = "RAG__"
# The platform's profiles, shipped inside rag-core (Step 38): `include: {platform: rag-core:platform.yaml}`
PACKAGED = Path(__file__).parent / "profiles"


def read(path: Path | str, _depth: int = 0) -> dict[str, Any]:
    """A rag.yaml with its includes expanded: included profiles appear as '<name>/<profile>'."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, Mapping):
        raise ComponentError(f"{path}: expected a mapping with 'version' and 'profiles'")
    doc = dict(raw)
    includes = doc.pop("include", None) or {}
    if not includes:
        return doc
    if _depth > 3:
        raise ComponentError(f"{path}: includes nested more than 3 deep")
    if not isinstance(includes, Mapping):
        raise ComponentError(
            f"{path}: include must map names to files, e.g. {{platform: rag-core:platform.yaml}}"
        )
    profiles = dict(doc.get("profiles") or {})
    for name, ref in includes.items():
        ref = str(ref)
        source = (
            PACKAGED / ref.removeprefix("rag-core:")
            if ref.startswith("rag-core:")
            else path.parent / ref
        )
        if not source.is_file():
            raise ComponentError(f"{path}: include {name!r}: {source} not found")
        for pname, body in (read(source, _depth + 1).get("profiles") or {}).items():
            body = dict(body or {})
            if body.get("extends"):  # an included profile extends profiles of its own file
                body["extends"] = f"{name}/{body['extends']}"
            profiles[f"{name}/{pname}"] = body
    doc["profiles"] = profiles
    return doc


def _merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k == "extends":
            continue
        if (
            isinstance(v, Mapping)
            and isinstance(out.get(k), dict)
            and v.get("use", out[k].get("use")) == out[k].get("use")
        ):
            out[k] = _merge(out[k], v)  # same component: change some parameters
        else:
            out[k] = copy.deepcopy(v)  # another component (or a list): replace entirely
    return out


def resolve(
    doc: Mapping[str, Any], profile: str, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    profiles = doc.get("profiles") or {}
    if doc.get("version") != 1:
        raise ComponentError("rag.yaml: expected 'version: 1'")
    if profile not in profiles:
        raise ComponentError(f"rag.yaml: no profile {profile!r} (have: {', '.join(profiles)})")
    chain: list[str] = []
    name: str | None = profile
    while name is not None:
        if name in chain:
            raise ComponentError(
                f"rag.yaml: profiles extend each other in a circle: {' -> '.join([*chain, name])}"
            )
        if name not in profiles:
            raise ComponentError(f"rag.yaml: profile {chain[-1]!r} extends unknown {name!r}")
        chain.append(name)
        name = (profiles[name] or {}).get("extends")
    merged: dict[str, Any] = {}
    for link in reversed(chain):
        merged = _merge(merged, profiles[link] or {})
    for key, raw in sorted((env if env is not None else os.environ).items()):
        if not key.startswith(ENV_PREFIX):
            continue
        path = [p.lower() for p in key[len(ENV_PREFIX) :].split("__")]
        value = yaml.safe_load(raw)
        target: dict[str, Any] = merged
        for p in path[:-1]:
            current = target.get(p)
            if isinstance(current, str):  # "reranker: none" -> {use: none}
                current = {"use": current}
            target[p] = current if isinstance(current, dict) else {}
            target = target[p]
        target[path[-1]] = value
    # "none" switches a slot off
    return {
        k: v
        for k, v in merged.items()
        if v not in ("none", None) and not (isinstance(v, Mapping) and v.get("use") == "none")
    }


def load(
    path: Path | str, profile: str | None = None, env: Mapping[str, str] | None = None
) -> Container:
    profile = profile or (env if env is not None else os.environ).get("RAG_PROFILE", "default")
    try:
        doc = read(path)  # includes expanded (Step 38)
    except OSError as e:
        raise ComponentError(f"cannot read {path}: {e.strerror}") from None
    except yaml.YAMLError as e:
        raise ComponentError(f"{path} is not valid YAML: {e}") from None
    if not isinstance(doc, Mapping):
        raise ComponentError(f"{path}: expected a mapping with 'version' and 'profiles'")
    return Container(resolve(doc, profile, env), profile)
