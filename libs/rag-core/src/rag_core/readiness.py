"""Production readiness of a configuration profile (Step 37).

`rag config validate` says a profile CAN be built. This says whether it SHOULD run in production:
no in-memory stores, no stand-in models, no secrets written into the file, the guardrails that the
risk register (Step 36) relies on, and answers that are checked before anyone sees them.

Errors fail `rag config readiness` (and the promotion gate); warnings are printed for a person to
judge. Each finding names the slot, so the fix is obvious.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

IN_MEMORY = {"memory", "memory-bm25", "scripted", "hashing"}
DURABLE_SLOTS = ("vector_store", "keyword_index", "manifest", "queue", "memory")
MODEL_SLOTS = ("llm", "answer_llm", "embedder")
# The guards the risk register's controls rely on (docs/compliance/risk-register.yaml)
REQUIRED_GUARDS = {
    "injection": "prompt-injection screening on questions (C-INJECTION)",
    "context-injection": "instructions hidden in documents (C-INJECTION)",
    "secrets": "keys and passwords in answers (C-OUTPUT)",
    "groundedness": "unsupported sentences in answers (C-GROUND)",
}
SECRET_KEY = re.compile(r"(^|_)(api_key|password|secret|token|key)$")
SECRET_REFERENCE = re.compile(r"_(file|env)$")  # *_file / *_env name where the secret is: fine
DSN_WITH_PASSWORD = re.compile(r"://[^/\s:@]+:[^@\s]+@")


@dataclass(frozen=True)
class Finding:
    level: str  # error | warning
    slot: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.slot:18} {self.message}"


def _use(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        use = value.get("use")
        return str(use) if use is not None else None
    return None


def _walk(value: Any, path: str) -> Iterator[tuple[str, str, Any]]:
    """Every (path, key, value) in a nested config."""
    if isinstance(value, Mapping):
        for k, v in value.items():
            yield path, str(k), v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


def check(config: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for slot in DURABLE_SLOTS:
        if slot in config and _use(config[slot]) in IN_MEMORY:
            out.append(Finding("error", slot, f"'{_use(config[slot])}' keeps data in one process: it is lost on restart and not shared between replicas"))  # fmt: skip
    for slot in MODEL_SLOTS:
        if slot not in config:
            continue
        use = _use(config[slot])
        inner = config[slot].get("inner") if isinstance(config[slot], Mapping) else None
        if use in IN_MEMORY or _use(inner) in IN_MEMORY:
            out.append(Finding("error", slot, f"'{use if use in IN_MEMORY else _use(inner)}' is a test stand-in, not a model"))  # fmt: skip
    if _use(config.get("generator")) == "extractive":
        out.append(Finding("warning", "generator", "extractive copies sentences instead of writing answers: fine only if that's the product"))  # fmt: skip
    if _use(config.get("cache")) == "memory":
        out.append(Finding("warning", "cache", "an in-process cache isn't shared by replicas and isn't cleared by `rag reacl` in other pods: use valkey"))  # fmt: skip
    if _use(config.get("reranker")) == "term-overlap":
        out.append(Finding("warning", "reranker", "term-overlap is the offline stand-in: use a cross-encoder (gateway or tei)"))  # fmt: skip
    pii = config.get("pii")
    if not pii or _use(pii) in (None, "none"):
        out.append(
            Finding("error", "pii", "personal data would be stored as found: configure redaction")
        )
    guards = {_use(g) for g in config.get("guards") or []}
    for name, why in REQUIRED_GUARDS.items():
        if name not in guards:
            out.append(Finding("error", "guards", f"missing '{name}': {why}"))
    raw = config.get("pipeline")
    pipeline: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    if pipeline.get("stream", "live") != "checked":
        out.append(Finding("warning", "pipeline", "stream: live sends words before the output guards have run; use checked unless you accept that"))  # fmt: skip
    if pipeline.get("uncited", "flag") == "keep":
        out.append(Finding("error", "pipeline", "uncited: keep returns answers that cite nothing as if they were sourced"))  # fmt: skip
    for path, key, value in _walk(config, ""):
        where = path.lstrip(".").split(".")[0].split("[")[0] or key
        if (
            SECRET_KEY.search(key)
            and not SECRET_REFERENCE.search(key)
            and isinstance(value, str)
            and value
        ):
            out.append(
                Finding(
                    "error", where, f"'{key}' is written into the file: use {key}_file or {key}_env"
                )
            )
        if isinstance(value, str) and DSN_WITH_PASSWORD.search(value):
            out.append(Finding("error", where, f"'{key}' contains a password in a URL: use credentials_file or dsn_env"))  # fmt: skip
    return out
