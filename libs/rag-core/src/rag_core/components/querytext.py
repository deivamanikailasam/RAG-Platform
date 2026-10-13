"""Question clean-up and translation before search (extension 04).

    query_transformer: {use: normalize, spelling: true}            # "anual leev" -> "annual leave"
    query_transformer: {use: translate, mode: glossary, glossary: {urlaub: leave}}
    query_transformer: {use: chain, steps: [normalize, {use: expand-terms, file: glossary.yaml}]}

`normalize` repairs what people type: Unicode look-alikes, stray whitespace and punctuation runs,
and (with `spelling`) words that aren't in the corpus but are one or two letters away from a word
that is. The vocabulary is the keyword index's own words, limited to the chunks the person may
read, or a list you give it. Codes, numbers, short words and anything in `protected` are never
touched; the original question is still searched too (`include_original`), so a wrong
"correction" can't lose the right document.

`translate` makes cross-lingual search work when the corpus is in one language (`target`) and
people ask in others: it detects the question's language and adds a translation. Offline it is
a passthrough (multilingual embedders such as BGE-M3 or multilingual-e5 already match across
languages) or a glossary lookup; with `mode: llm` a model translates, falling back to the
passthrough if the call fails.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core.components.basics import words
from rag_core.registry import Container, register
from rag_core.text import _LANG_WORDS
from rag_core.types import Query

log = logging.getLogger("rag_core.querytext")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def edit_distance(a: str, b: str, limit: int = 3) -> int:
    """Damerau-Levenshtein distance (adjacent swaps count once), stopping early above `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


# ================================================================ normalize + spelling


class NormalizeParams(_Strict):
    spelling: bool = True
    vocabulary: list[str] = Field(default_factory=list)  # extra known words (product names, …)
    vocabulary_file: str | None = None  # one word per line
    from_index: bool = True  # learn words from the keyword index (only what the person may read)
    protected: list[str] = Field(default_factory=list)  # never "correct" these
    min_length: int = Field(4, ge=3)  # shorter words are left alone ("vpn", "hr")
    max_edits: int = Field(2, ge=1, le=3)  # 1 for words up to 7 letters, this for longer ones
    include_original: bool = True  # search the question as typed as well


_PUNCT_RUN = re.compile(r"([!?.,;:])\1+")
_SPACE = re.compile(r"\s+")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "})


class QueryNormalizer:
    """Clean up a question and fix its misspellings against the corpus vocabulary. No model."""

    def __init__(self, p: NormalizeParams, index: Any = None) -> None:
        self.p, self.index = p, index
        known = [w.lower() for w in p.vocabulary]
        if p.vocabulary_file:
            known += [
                w.strip().lower()
                for w in Path(p.vocabulary_file).read_text().splitlines()
                if w.strip()
            ]
        self.static = Counter(known)
        self.protected = {w.lower() for w in p.protected}
        self._cache: dict[str, tuple[int, Counter[str]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def clean(text: str) -> str:
        t = unicodedata.normalize("NFKC", text).translate(_QUOTES)
        t = "".join(ch for ch in t if unicodedata.category(ch)[0] != "C" or ch in "\n\t")
        return _SPACE.sub(" ", _PUNCT_RUN.sub(r"\1", t)).strip()

    def vocabulary(self, query: Query) -> Counter[str]:
        vocab = Counter(self.static)
        if self.p.from_index and self.index is not None and hasattr(self.index, "vocabulary"):
            key = query.principal.fingerprint
            size = len(getattr(self.index, "_docs", ())) if hasattr(self.index, "_docs") else -1
            with self._lock:
                hit = self._cache.get(key)
            if hit is None or hit[0] != size or size < 0:
                hit = (size, self.index.vocabulary(query.principal))
                with self._lock:
                    self._cache[key] = hit
            vocab.update(hit[1])
        return vocab

    def correct_word(self, word: str, vocab: Counter[str]) -> str:
        low = word.lower()
        if (len(low) < self.p.min_length or low in vocab or low in self.protected
                or any(ch.isdigit() for ch in low) or not vocab):  # fmt: skip
            return word
        limit = 1 if len(low) <= 7 else self.p.max_edits
        best: tuple[int, int, str] | None = None
        for cand, freq in vocab.items():
            if abs(len(cand) - len(low)) > limit or (cand[0] != low[0] and len(low) <= 5):
                continue
            d = edit_distance(low, cand, limit)
            if d <= limit and (best is None or (d, -freq) < (best[0], best[1])):
                best = (d, -freq, cand)
        if best is None:
            return word
        fixed = best[2]
        return fixed.capitalize() if word[:1].isupper() and word[1:].islower() else fixed

    def correct(self, text: str, query: Query) -> str:
        if not self.p.spelling:
            return text
        vocab = self.vocabulary(query)
        return re.sub(
            r"[^\W\d_]+(?:'[^\W\d_]+)?", lambda m: self.correct_word(m.group(0), vocab), text
        )

    def transform(self, query: Query) -> list[str]:
        clean = self.clean(query.text)
        fixed = self.correct(clean, query)
        out = [fixed]
        if self.p.include_original and query.text.strip() not in out:
            out.append(query.text.strip())
        return list(dict.fromkeys(t for t in out if t))


@register("query_transformer", "normalize", params=NormalizeParams,
          summary="clean up Unicode, spacing and punctuation; fix misspellings against the corpus words (no LLM)")  # fmt: skip
def _normalize(p: NormalizeParams, c: Container) -> QueryNormalizer:
    index = c.get("keyword_index") if p.from_index and c.has("keyword_index") else None
    return QueryNormalizer(p, index)


# ================================================================ translate


def detect_query_language(text: str, languages: Sequence[str] | None = None) -> str:
    """The language of a short question, from function words ("und" when unsure)."""
    ws = words(text)
    scores = {lang: sum(w in set(v) for w in ws) for lang, v in _LANG_WORDS.items()
              if languages is None or lang in languages}  # fmt: skip
    if not scores:
        return "und"
    best = max(scores, key=lambda k: scores[k])
    ranked = sorted(scores.values(), reverse=True)
    if scores[best] == 0 or (len(ranked) > 1 and ranked[0] == ranked[1]):
        return "und"
    return best


class TranslateParams(_Strict):
    target: str = "en"  # the corpus language
    mode: Literal["passthrough", "glossary", "llm"] = "passthrough"
    glossary: dict[str, str] = Field(default_factory=dict)  # word or phrase -> target language
    glossary_file: str | None = None  # the same map in YAML
    llm_slot: Literal["llm", "judge_llm"] = "llm"
    include_original: bool = True  # search the question as asked too (multilingual embedders)
    max_tokens: int = Field(200, ge=20)


class QueryTranslator:
    """Cross-lingual search: add the question in the corpus language. `passthrough` changes
    nothing (rely on a multilingual embedder; the trace still shows the detected language),
    `glossary` replaces known words and phrases, `llm` asks a model (and falls back)."""

    def __init__(self, p: TranslateParams, llm: Any = None) -> None:
        self.p, self.llm = p, llm
        table = dict(p.glossary)
        if p.glossary_file:
            import yaml

            table |= {
                str(k): str(v)
                for k, v in (yaml.safe_load(Path(p.glossary_file).read_text()) or {}).items()
            }
        self.glossary = {" ".join(words(k)): v for k, v in table.items()}
        self.last_language = "und"

    def by_glossary(self, text: str) -> str:
        out = f" {' '.join(words(text))} "
        for key in sorted(self.glossary, key=len, reverse=True):
            out = out.replace(f" {key} ", f" {self.glossary[key]} ")
        return out.strip()

    def by_llm(self, text: str, lang: str) -> str | None:
        try:
            reply = str(self.llm.complete(
                f"Translate the user's question into the language with ISO code '{self.p.target}'. "
                "Reply with the translation only. Keep codes, names and numbers unchanged.",
                text, max_tokens=self.p.max_tokens)).strip()  # fmt: skip
        except Exception as e:  # a helper must never take search down
            log.warning("query translation failed, searching the question as asked: %s", e)
            return None
        return reply.splitlines()[0].strip() if reply else None

    def transform(self, query: Query) -> list[str]:
        lang = detect_query_language(query.text)
        self.last_language = lang
        if lang in ("und", self.p.target) or self.p.mode == "passthrough":
            return [query.text]
        made = (
            self.by_glossary(query.text)
            if self.p.mode == "glossary"
            else self.by_llm(query.text, lang)
        )
        texts = [made] if made else []
        if self.p.include_original or not texts:
            texts.append(query.text)
        return list(dict.fromkeys(texts))


@register("query_transformer", "translate", params=TranslateParams,
          summary="cross-lingual search: add the question in the corpus language (passthrough, glossary or LLM)")  # fmt: skip
def _translate(p: TranslateParams, c: Container) -> QueryTranslator:
    return QueryTranslator(
        p, c.get(p.llm_slot if c.has(p.llm_slot) else "llm") if p.mode == "llm" else None
    )


__all__ = ["QueryNormalizer", "QueryTranslator", "detect_query_language", "edit_distance"]
