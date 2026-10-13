"""Cleaning before chunking (Step 31): normalisers, boilerplate removal, and PII redaction.

Garbage in the index is garbage in every answer: page footers matched by keyword search, hyphenated
words that never match, a customer's phone number embedded for ever. This is where they go.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_core.registry import Container, register
from rag_core.types import Document, Element


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- normalisers


class UnicodeNormalizer:
    """NFKC (ﬁ→fi, full-width→ASCII), no control characters, words re-joined across line-break
    hyphens ("infor-\\nmation"→"information"), whitespace collapsed (newlines in tables/code kept)."""

    def normalize(self, document: Document) -> Document:
        out = []
        for e in document.elements:
            text = unicodedata.normalize("NFKC", e.text)
            text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
            if e.kind not in ("code", "table"):
                text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
                text = re.sub(r"[ \t]*\n[ \t]*", " " if e.kind == "paragraph" else "\n", text)
                text = re.sub(r"[ \t\u00a0]+", " ", text)  # \u00a0 = no-break space
            out.append(replace(e, text=text.strip()))
        return replace(document, elements=tuple(x for x in out if x.text))


@register(
    "normalizer",
    "unicode",
    summary="NFKC, control characters out, line-break hyphens joined, whitespace collapsed",
)
def _unicode(p: BaseModel, c: Container) -> UnicodeNormalizer:
    return UnicodeNormalizer()


class BoilerplateParams(_Strict):
    min_repeats: int = Field(3, ge=2)  # the same short line on this many pages = a header/footer
    max_chars: int = Field(120, ge=10)


class BoilerplateRemover:
    """Drops short elements that repeat across a document (running headers, footers, "Page 3 of 9",
    cookie banners) and exact duplicate paragraphs."""

    def __init__(self, min_repeats: int = 3, max_chars: int = 120) -> None:
        self.min_repeats, self.max_chars = min_repeats, max_chars

    @staticmethod
    def _key(text: str) -> str:
        return re.sub(r"\d+", "#", text.lower()).strip()  # "Page 3 of 9" == "Page 4 of 9"

    def normalize(self, document: Document) -> Document:
        counts = Counter(
            self._key(e.text) for e in document.elements if len(e.text) <= self.max_chars
        )
        seen: set[str] = set()
        kept = []
        for e in document.elements:
            k = self._key(e.text)
            if (
                e.kind != "heading"
                and len(e.text) <= self.max_chars
                and counts[k] >= self.min_repeats
            ):
                continue
            if e.kind == "paragraph" and len(e.text) > 40:
                if e.text in seen:
                    continue
                seen.add(e.text)
            kept.append(e)
        return replace(document, elements=tuple(kept))


@register("normalizer", "boilerplate", params=BoilerplateParams,
            summary="drops repeated headers/footers/banners and duplicate paragraphs")  # fmt: skip
def _boilerplate(p: BoilerplateParams, c: Container) -> BoilerplateRemover:
    return BoilerplateRemover(p.min_repeats, p.max_chars)


# ---------------------------------------------------------------- PII


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        total, alt = total + n, not alt
    return total % 10 == 0


def _tfn(digits: str) -> bool:
    """Australian Tax File Number checksum (9 digits)."""
    w = (1, 4, 3, 7, 5, 8, 6, 9, 10)
    return len(digits) == 9 and sum(int(d) * x for d, x in zip(digits, w, strict=True)) % 11 == 0


def _abn(digits: str) -> bool:
    """Australian Business Number checksum (11 digits)."""
    if len(digits) != 11:
        return False
    w = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
    nums = [int(d) for d in digits]
    nums[0] -= 1
    return sum(n * x for n, x in zip(nums, w, strict=True)) % 89 == 0


def _iban(text: str) -> bool:
    s = text.replace(" ", "").upper()
    s = s[4:] + s[:4]
    return int("".join(str(int(ch, 36)) for ch in s)) % 97 == 1


# kind -> (pattern, validator on the digits/text or None). Validators cut false positives sharply.
DETECTORS: dict[str, tuple[re.Pattern[str], object]] = {
    "email": (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), None),
    "credit_card": (re.compile(r"\b(?:\d[ -]?){13,19}\b"), lambda m: _luhn(re.sub(r"\D", "", m))),
    "au_tfn": (re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"), lambda m: _tfn(re.sub(r"\D", "", m))),
    "au_abn": (
        re.compile(r"\b\d{2}[ ]?\d{3}[ ]?\d{3}[ ]?\d{3}\b"),
        lambda m: _abn(re.sub(r"\D", "", m)),
    ),
    "iban": (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"), _iban),
    "phone": (
        re.compile(
            r"(?<![\w+])(?:\+?61[ -]?|0)[2-478](?:[ -]?\d){8}\b|\+\d{1,3}(?:[ -]?\d{2,4}){2,4}\b"
        ),
        None,
    ),
    "ipv4": (
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
        None,
    ),
}


class RegexPiiParams(_Strict):
    kinds: list[str] = Field(default_factory=lambda: list(DETECTORS))
    strategy: Literal["mask", "pseudonymise", "remove"] = "mask"
    # pseudonymise: a keyed hash, so the same email always becomes the same token (joins still work)
    # but nobody without the key can reverse it. The key comes from an env var (OpenBao, Step 28).
    key_env: str = "RAG_PII_HMAC_KEY"
    # Step 32: or a file OpenBao Agent writes (/run/bao/pii_hmac_key); the file wins when both are set
    key_file: str | None = None


class RegexPiiRedactor:
    """Pattern + checksum detectors: emails, cards (Luhn), Australian TFN/ABN (checksums), IBAN
    (mod 97), phone numbers, IP addresses. Fast and predictable; names and addresses need NER
    (Presidio). Precision over recall: a validator must agree before anything is changed."""

    def __init__(
        self, kinds: list[str] | None = None, strategy: str = "mask", key: bytes = b""
    ) -> None:
        unknown = set(kinds or []) - set(DETECTORS)
        if unknown:
            raise ValueError(f"unknown PII kinds: {sorted(unknown)}")
        self.kinds = kinds or list(DETECTORS)
        self.strategy = strategy
        self._key = key
        if strategy == "pseudonymise" and not key:
            raise ValueError("pseudonymise needs a key (set key_file or the key_env variable)")

    def _replace(self, kind: str, value: str) -> str:
        if self.strategy == "remove":
            return ""
        if self.strategy == "pseudonymise":
            tag = hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()[:10]
            return f"[{kind.upper()}:{tag}]"
        return f"[{kind.upper()}]"

    def redact(self, text: str) -> tuple[str, list[str]]:
        found: list[str] = []
        for kind in self.kinds:
            pattern, valid = DETECTORS[kind]

            def sub(m: re.Match[str], kind: str = kind, valid: object = valid) -> str:
                if valid is not None and not valid(m.group(0)):  # type: ignore[operator]
                    return m.group(0)
                found.append(kind)
                return self._replace(kind, m.group(0))

            text = pattern.sub(sub, text)
        return text, found


@register("pii", "regex", params=RegexPiiParams,
            summary="emails, cards, AU TFN/ABN, IBAN, phones, IPs with checksums; mask, pseudonymise or remove")  # fmt: skip
def _regex_pii(p: RegexPiiParams, c: Container) -> RegexPiiRedactor:
    key = (
        Path(p.key_file).read_text().strip().encode()
        if p.key_file
        else os.environ.get(p.key_env, "").encode()
    )
    return RegexPiiRedactor(p.kinds, p.strategy, key)


class PresidioParams(_Strict):
    language: str = "en"
    entities: list[str] = Field(default_factory=lambda: ["PERSON", "LOCATION", "EMAIL_ADDRESS", "PHONE_NUMBER",
                                            "CREDIT_CARD", "AU_TFN", "AU_ABN", "AU_MEDICARE"])  # fmt: skip
    score_threshold: float = 0.5


class PresidioRedactor:  # pragma: no cover - needs presidio and a spaCy model
    """Microsoft Presidio: NER (names, places) plus rule-based recognisers, including Australian IDs."""

    def __init__(self, p: PresidioParams) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        self.p, self.analyzer, self.anonymizer = p, AnalyzerEngine(), AnonymizerEngine()

    def redact(self, text: str) -> tuple[str, list[str]]:
        results = self.analyzer.analyze(text=text, language=self.p.language, entities=self.p.entities,
                                score_threshold=self.p.score_threshold)  # fmt: skip
        return self.anonymizer.anonymize(text=text, analyzer_results=results).text, [
            r.entity_type for r in results
        ]


@register("pii", "presidio", params=PresidioParams, status="reference", requires=("presidio",),
            summary="Microsoft Presidio: names and places (NER) plus AU/US/EU identifiers")  # fmt: skip
def _presidio(p: PresidioParams, c: Container) -> PresidioRedactor:  # pragma: no cover
    return PresidioRedactor(p)


def redact_document(document: Document, redactor: object) -> tuple[Document, list[str]]:
    found: list[str] = []
    elements: list[Element] = []
    for e in document.elements:
        text, kinds = redactor.redact(e.text)  # type: ignore[attr-defined]
        found += kinds
        elements.append(replace(e, text=text))
    title, kinds = redactor.redact(document.title)  # type: ignore[attr-defined]
    return replace(document, title=title, elements=tuple(elements)), found + kinds
