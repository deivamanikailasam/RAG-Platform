"""More chunkers (extension 02): propositions and source code.

What the Step 31 chunkers already cover, so nothing is duplicated here:
    Markdown headers   `structure` (the Markdown/HTML/DOCX parsers turn headers into heading elements)
    tables             `structure` keeps a table whole, or splits it by rows repeating the header
    code blocks        `structure` keeps a fenced block whole, or cuts it between lines
    token windows      `fixed` (N tokens with overlap, counted by the token_counter: exact with
                       `hf-tokenizer`)
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field

from rag_core.components.chunking import (
    SECTION_KEYS,
    SizeParams,
    StructureChunker,
    StructureParams,
    _Base,
    _Strict,
)
from rag_core.registry import Container, register
from rag_core.text import grounded, sentences
from rag_core.types import Chunk, Document

# ================================================================ propositions

PROPOSITION_SYSTEM = "You split text into atomic, self-contained facts. You never add information."
PROPOSITION_PROMPT = """Decompose the passage into propositions: short, simple sentences that each
state ONE fact and can be understood on their own. Replace pronouns ("it", "they", "this") with
what they refer to, and add the subject the passage is about when a fact needs it. Keep numbers,
names and terms exactly as written. One proposition per line, nothing else.

Document: {title}
Section: {section}
Passage:
{passage}"""

PRONOUN = re.compile(
    r"^(it|its|this|that|these|those|they|their|them|he|she|his|her|such|both)\b", re.I
)
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


class PropositionParams(_Strict):
    passage_tokens: int = Field(300, ge=32, le=4096)  # the text one LLM call decomposes
    use_llm: bool = True  # False: the rule-based split, always (offline, free)
    llm_slot: Literal["llm", "judge_llm", "answer_llm"] = "llm"
    min_overlap: float = Field(0.5, ge=0, le=1)  # an LLM proposition must reuse this share of words
    max_propositions: int = Field(40, ge=1, le=200)  # per passage


class PropositionChunker(_Base):
    """Dense X Retrieval (Chen et al., 2023): index atomic facts ("Parental leave is 18 weeks at
    full pay.") instead of passages. Each proposition keeps its passage in metadata["window"],
    so `window-expand` gives the model the full passage. An LLM decomposes the text when one is
    configured and its output is grounded in the passage; otherwise (offline, or the model
    refused or invented), a rule-based split: sentences, then clauses at ";", with a leading
    pronoun replaced by the section's subject."""

    def __init__(self, counter: Any, p: PropositionParams, llm: Any = None) -> None:
        super().__init__(counter)
        self.p, self.llm = p, llm
        self.passages = StructureChunker(counter, StructureParams(max_tokens=p.passage_tokens,
                                         overlap_tokens=0, min_tokens=0))  # fmt: skip

    @staticmethod
    def rules(text: str, subject: str) -> list[str]:
        subject = re.sub(
            r"^\d+(?:\.\d+)*[.)]?\s+", "", subject
        )  # "4.2 Parental leave" -> "Parental leave"
        out: list[str] = []
        for block in re.split(r"\n{2,}", text):
            lines = [ln for ln in block.split("\n") if ln.strip()]
            if lines and sum(ln.lstrip().startswith("|") for ln in lines) * 2 >= len(lines):
                out.append(block.strip())  # a table is one fact sheet: kept whole
                continue
            for s in sentences(block) or [block]:
                for part in (x.strip() for x in re.split(r";\s+|\n+", s)):
                    part = BULLET.sub("", part).strip()
                    if len(part.split()) < 3:
                        continue
                    if subject and PRONOUN.match(part):
                        part = f"{subject}: {part}"
                    if part[-1] not in ".!?":
                        part += "."
                    out.append(part[0].upper() + part[1:])
        return out

    def _llm(self, passage: str, title: str, section: str) -> list[str]:
        try:
            reply = self.llm.complete(PROPOSITION_SYSTEM, PROPOSITION_PROMPT.format(
                title=title, section=section or "-", passage=passage), max_tokens=800)  # fmt: skip
        except (RuntimeError, OSError, ValueError):
            return []
        reply = reply.strip()
        lines: list[str] = []
        if reply.startswith("["):
            try:
                lines = [str(x) for x in json.loads(reply)]
            except ValueError:
                lines = []
        lines = lines or reply.splitlines()
        source = f"{title}\n{section}\n{passage}"
        props = [BULLET.sub("", ln).strip() for ln in lines]
        return [p for p in props if len(p.split()) >= 3 and grounded(p, source, self.p.min_overlap)]

    def chunk(self, document: Document) -> list[Chunk]:
        pieces: list[tuple[str, dict[str, Any]]] = []
        for passage in self.passages.chunk(document):
            section = str(passage.metadata.get("section") or "")
            subject = str(passage.metadata.get("heading") or document.title)
            props, by = [], "rules"
            if self.p.use_llm and self.llm is not None:
                props, by = self._llm(passage.text, document.title, section), "llm"
            if not props:
                props, by = self.rules(passage.text, subject), "rules"
            meta = {k: v for k, v in passage.metadata.items() if k in SECTION_KEYS}
            for prop in props[: self.p.max_propositions] or [passage.text]:
                pieces.append((prop, {**meta, "window": passage.text, "passage_id": passage.id,
                                      "proposition_by": by}))  # fmt: skip
        return self._make(document, pieces)


@register("chunker", "proposition", params=PropositionParams,
          summary="atomic self-contained facts (LLM, grounded-checked; rule-based offline); passage kept for window-expand")  # fmt: skip
def _proposition(p: PropositionParams, c: Container) -> PropositionChunker:
    llm = c.get(p.llm_slot) if p.use_llm and c.has(p.llm_slot) else None
    return PropositionChunker(c.get("token_counter"), p, llm)


# ================================================================ source code

LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".go": "go", ".rs": "rust", ".rb": "ruby", ".java": "java",
    ".kt": "kotlin", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp", ".php": "php",
    ".sh": "shell", ".sql": "sql", ".scala": "scala", ".swift": "swift",
}  # fmt: skip
_BRACES = r"^(?:(?:public|private|protected|internal|static|final|abstract|override|sealed|export|default|async|inline|virtual)\s+)*"
BOUNDARY = {
    "python": re.compile(r"^(?:@|def\s|async\s+def\s|class\s)"),
    "javascript": re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\b|class\b|(?:const|let|var)\s+\w+\s*=)"),
    "typescript": re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\b|class\b|interface\b|type\s+\w+|enum\b|(?:const|let)\s+\w+\s*[:=])"),
    "go": re.compile(r"^(?:func|type|var|const)\b"),
    "rust": re.compile(r"^(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+)?(?:fn|struct|enum|impl|trait|mod)\b"),
    "ruby": re.compile(r"^(?:def|class|module)\b"),
    "sql": re.compile(r"^(?:create|alter|drop|insert|update|delete|select|with|grant)\b", re.I),
    "shell": re.compile(r"^(?:function\s+)?\w[\w-]*\s*\(\)\s*\{?"),
    **{lang: re.compile(_BRACES + r"(?:class|interface|enum|record|struct|fun|def|func|void|[\w<>\[\],]+\s+\w+\s*\()")
       for lang in ("java", "kotlin", "csharp", "c", "cpp", "php", "scala", "swift")},
}  # fmt: skip
COMMENT = re.compile(r"^\s*(?:#|//|/\*|\*|--|\"\"\"|''')")
SYMBOL = re.compile(
    r"\b(?:def|class|function|func|fn|struct|interface|type|enum|trait|impl|module|record)\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"
    r"|^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*="
    r"|^\s{0,4}(?:(?:public|private|protected|internal|static|final|abstract|override|virtual)\s+)+[\w<>\[\],]+\s+([A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)  # fmt: skip


class CodeParams(SizeParams):
    language: str | None = None  # python, go, …; None: from the file extension


class CodeChunker(_Base):
    """Source files cut at top-level definitions (functions, classes, types), with the comments
    and decorators above a definition kept with it; small definitions are packed together, a big
    one is cut between lines. Each chunk records its language, symbols and line numbers, so a
    question naming a function finds it and a citation points at the lines."""

    def __init__(self, counter: Any, p: CodeParams) -> None:
        super().__init__(counter)
        self.p = p

    def language(self, document: Document) -> str:
        if self.p.language:
            return self.p.language
        ext = PurePosixPath(document.uri.split("?")[0]).suffix.lower()
        return LANGUAGES.get(ext, "text")

    def blocks(self, text: str, lang: str) -> list[tuple[int, list[str]]]:
        """(first line number, lines) per top-level block."""
        pat = BOUNDARY.get(lang)
        blocks: list[tuple[int, list[str]]] = [(1, [])]
        prev = ""
        for n, line in enumerate(text.split("\n"), 1):
            starts = (pat.match(line) if pat else (line[:1].strip() and not prev.strip())) and not (
                lang == "python" and prev.startswith("@")
            )
            if starts and blocks[-1][1]:
                # comments right above a definition belong to it
                cur = blocks[-1][1]
                moved: list[str] = []
                while cur and cur[-1].strip() and COMMENT.match(cur[-1]):
                    moved.insert(0, cur.pop())
                blocks.append((n - len(moved), [*moved, line]))
            else:
                blocks[-1][1].append(line)
            prev = line
        return [(s, ls) for s, ls in blocks if any(x.strip() for x in ls)]

    @staticmethod
    def symbols(text: str) -> list[str]:
        out = []
        for m in SYMBOL.finditer(text):
            name = next((g for g in m.groups() if g), None)
            if name:
                out.append(name)
        return list(dict.fromkeys(out))[:10]

    def chunk(self, document: Document) -> list[Chunk]:
        lang = self.language(document)
        text = document.text  # line numbers are those of the parsed text (blank-line runs folded)
        pieces: list[tuple[str, dict[str, Any]]] = []
        group: list[tuple[int, list[str]]] = []

        def flush() -> None:
            if not group:
                return
            body = "\n".join(ln for _, ls in group for ln in ls).strip("\n")
            start = group[0][0]
            end = start + sum(len(ls) for _, ls in group) - 1
            syms = self.symbols(body)
            pieces.append((body, {"code_language": lang, "symbols": syms, "line_start": start,
                                  "line_end": end, "section": syms[0] if syms else ""}))  # fmt: skip
            group.clear()

        for start, lines in self.blocks(text, lang):
            body = "\n".join(lines)
            n = self.counter.count(body)
            if n > self.p.max_tokens:  # one big definition: cut between lines
                flush()
                line = start
                for part in self._windows(lines, self.p.max_tokens, 0, "\n"):
                    count = part.count("\n") + 1
                    group.append((line, part.split("\n")))
                    flush()
                    line += count
                continue
            size = sum(self.counter.count("\n".join(ls)) for _, ls in group)
            if group and size + n > self.p.max_tokens:
                flush()
            group.append((start, lines))
        flush()
        return self._make(document, pieces)


@register("chunker", "code", params=CodeParams,
          summary="source code cut at top-level definitions (language from the extension); symbols and line numbers recorded")  # fmt: skip
def _code(p: CodeParams, c: Container) -> CodeChunker:
    return CodeChunker(c.get("token_counter"), p)
