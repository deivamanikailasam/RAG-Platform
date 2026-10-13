"""The rag-core SDK (Step 38): one object a project uses, so it never wires pipelines by hand.

    from rag_core.sdk import RagApp, Principal, Access

    app = RagApp.load("rag.yaml", profile="offline")
    app.ingest_folder("corpus/", access=Access("internal", ("staff",)))
    hits = app.search("How many days of annual leave?", Principal("u1", ("staff",), ("internal",)))
    answer = app.answer("How many days of annual leave?", principal)
    app.check()                   # readiness findings for this profile

Everything here is a thin layer over the same pipelines rag-api uses (Steps 31-35), so a script,
a notebook, a batch job and the API behave identically. A project adds its own components with
`@register` (re-exported here) and an entry point; see templates/rag-project.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_core import config as cfg
from rag_core.registry import ComponentError, Container, describe, register
from rag_core.types import Access, Principal, Query

__all__ = ["Access", "ComponentError", "Principal", "RagApp", "register"]

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx", ".csv"}


@dataclass
class RagApp:
    container: Container
    _answer_pipeline: Any = field(default=None, init=False, repr=False)

    # ---- construction ------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path = "rag.yaml", profile: str | None = None,
             env: Mapping[str, str] | None = None) -> RagApp:  # fmt: skip
        """A profile from a rag.yaml (with `extends` and RAG__SLOT__PARAM overrides, Step 30)."""
        return cls(cfg.load(path, profile, env=env))

    @classmethod
    def from_dict(cls, slots: Mapping[str, Any], name: str = "inline") -> RagApp:
        """Slots given directly, e.g. in a test: {"embedder": {"use": "hashing"}, …}."""
        return cls(Container(dict(slots), name))

    @property
    def profile(self) -> str:
        return self.container.profile

    # ---- ingestion -----------------------------------------------------------------------------

    def ingest(self, uri: str, access: Access | None = None, metadata: Mapping[str, Any] | None = None,
               *, force: bool = False) -> Any:  # fmt: skip
        """One source (file:// or s3://): parsed, redacted, chunked, embedded, indexed (Step 31)."""
        from rag_core.ingest import IngestionPipeline, load_source

        source = load_source(uri, access, dict(metadata or {}))
        return IngestionPipeline(self.container).ingest(source, force=force)

    def ingest_folder(
        self, folder: str | Path, access: Access | None = None, *, force: bool = False
    ) -> list[Any]:
        """Every document under a folder, with the same access. Returns one result per file."""
        root = Path(folder).resolve()
        files = sorted(
            p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
        )
        return [self.ingest(p.as_uri(), access, force=force) for p in files]

    def delete(self, uri: str) -> Any:
        from rag_core.ingest import IngestionPipeline

        return IngestionPipeline(self.container).delete(uri)

    # ---- search and answers ------------------------------------------------------------------

    def search(self, question: str, principal: Principal, *, k: int = 5,
               filters: Mapping[str, Any] | None = None) -> Any:  # fmt: skip
        """Ranked chunks this person may see, with every score (Step 32)."""
        from rag_core.search import SearchPipeline

        return SearchPipeline(self.container).search(
            Query(question, principal, dict(filters or {}), k=k)
        )

    def answer(self, question: str, principal: Principal, *, session_id: str | None = None,
               filters: Mapping[str, Any] | None = None) -> Any:  # fmt: skip
        """A cited, guarded answer, or an honest "I don't know" (Steps 33-35)."""
        return self._answerer().answer(question, principal, session_id=session_id, filters=filters)

    def stream(self, question: str, principal: Principal, *, session_id: str | None = None,
               filters: Mapping[str, Any] | None = None) -> Iterator[Any]:  # fmt: skip
        """Events: "meta", "delta"s, "done" with the checked answer."""
        events: Iterator[Any] = self._answerer().stream(
            question, principal, session_id=session_id, filters=filters
        )
        return events

    def _answerer(self) -> Any:
        if self._answer_pipeline is None:  # built once: it holds the memory and cache
            from rag_core.answer import AnswerPipeline

            self._answer_pipeline = AnswerPipeline(self.container)
        return self._answer_pipeline

    # ---- quality and fitness -------------------------------------------------------------------

    def check(self) -> list[Any]:
        """Production readiness findings for this profile (Step 37); empty = ready."""
        from rag_core import readiness

        return readiness.check(self.container.config)

    def validate(self) -> list[str]:
        """Every slot names a real component with valid settings (Step 30)."""
        return list(self.container.validate())

    @staticmethod
    def components(kind: str | None = None) -> list[dict[str, Any]]:
        """What can be switched, and to what (Step 30)."""
        return [r for r in describe() if kind is None or r["kind"] == kind]
