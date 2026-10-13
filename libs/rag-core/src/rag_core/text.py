"""Small, dependency-free text helpers shared by chunkers, enrichers and compressors (extension 02).

Everything here is deterministic and offline: it is what the components fall back to when no
model is configured (CI, a laptop), and what checks a model's output before it is trusted
(`grounded`: is an LLM's summary or extraction actually made of the source's words?).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from datetime import date

from rag_core.components.basics import words

SENTENCE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9\"'(\[])|\n{2,}")

STOPWORDS = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "to", "in", "on", "at", "by", "for", "with", "from", "into", "onto", "over", "under", "about", "as", "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did", "done", "have", "has", "had", "having", "i", "me", "my", "we", "our", "you", "your", "he", "him", "his", "she", "her", "it", "its", "they", "them", "their", "this", "that", "these", "those", "there", "here", "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "should", "would", "could", "may", "might", "must", "shall", "also", "per", "via", "up", "down", "out", "off", "again", "further", "once", "s", "t", "don", "doesn", "isn", "aren", "wasn", "weren", "hasn", "haven"]
)  # fmt: skip


def sentences(text: str) -> list[str]:
    """Sentences, cut at . ! ? followed by a capital (or at a blank line)."""
    return [s.strip() for s in SENTENCE.split(text) if s and s.strip()]


def content_words(text: str) -> list[str]:
    """The words that carry meaning: no stop words, no single letters."""
    return [w for w in words(text) if w not in STOPWORDS and len(w) > 1]


def overlap(candidate: str, source: str) -> float:
    """Share of the candidate's content words that also occur in the source (0..1)."""
    cand = set(content_words(candidate))
    if not cand:
        return 0.0
    return len(cand & set(content_words(source))) / len(cand)


def grounded(candidate: str, source: str, min_overlap: float = 0.5) -> bool:
    """Is a model's output (a summary, a proposition, an extract) made of the source's words?
    A cheap check that catches "I don't know.", refusals and invented facts before they are
    indexed or shown; it can't prove a paraphrase is faithful, only reject an obvious stranger."""
    return bool(candidate.strip()) and overlap(candidate, source) >= min_overlap


def extractive_summary(texts: Sequence[str], max_sentences: int = 3) -> str:
    """The most central sentences, in their original order: each sentence scores the average
    frequency (across all the texts) of its content words, so sentences about what the texts are
    MOSTLY about win. No model; the offline fallback for every summariser here."""
    sents = [s for t in texts for s in (sentences(t) or [t]) if s.strip()]
    if not sents:
        return ""
    freq = Counter(w for s in sents for w in set(content_words(s)))
    scored = []
    for i, s in enumerate(sents):
        ws = set(content_words(s))
        score = sum(freq[w] for w in ws) / (len(ws) + 2) if ws else 0.0
        scored.append((score, -i, s))
    best = sorted(scored, reverse=True)[:max_sentences]
    keep = sorted(best, key=lambda x: -x[1])
    return " ".join(s for _, _, s in keep)


# ---------------------------------------------------------------- keywords


def tfidf_keywords(texts: Sequence[str], k: int = 5) -> list[list[str]]:
    """Top-k terms of each text by TF-IDF, the IDF taken over the texts given (e.g. the chunks of
    one document): words that make a chunk different from its neighbours."""
    tfs = [Counter(content_words(t)) for t in texts]
    df: Counter[str] = Counter(w for tf in tfs for w in tf)
    n = len(texts)
    out = []
    for tf in tfs:
        total = sum(tf.values()) or 1
        scored = sorted(
            ((tf[w] / total) * (math.log((1 + n) / (1 + df[w])) + 1), w) for w in tf if len(w) > 2
        )
        out.append([w for _, w in sorted(scored, key=lambda x: (-x[0], x[1]))[:k]])
    return out


def yake_keywords(text: str, k: int = 5) -> list[str]:
    """A simplified YAKE (Campos et al., 2020): a single document, no corpus, no model. Each
    candidate word is scored by its casing (capitalised mid-sentence = a name), its position
    (early = important), its frequency, and how many sentences it appears in; LOWER is better."""
    sents = sentences(text) or [text]
    tf: Counter[str] = Counter()
    upper: Counter[str] = Counter()
    positions: dict[str, list[int]] = {}
    spread: dict[str, set[int]] = {}
    for i, s in enumerate(sents):
        raw = re.findall(r"[\w][\w'\-]*", s)
        for j, tok in enumerate(raw):
            w = tok.lower()
            if w in STOPWORDS or len(w) < 3 or w.isdigit():
                continue
            tf[w] += 1
            if (j > 0 and tok[0].isupper()) or (len(tok) > 1 and tok.isupper()):
                upper[w] += 1
            positions.setdefault(w, []).append(i)
            spread.setdefault(w, set()).add(i)
    if not tf:
        return []
    mean = sum(tf.values()) / len(tf)
    std = math.sqrt(sum((v - mean) ** 2 for v in tf.values()) / len(tf))
    scores = {}
    for w, f in tf.items():
        t_case = upper[w] / (1 + math.log(f))
        pos = sorted(positions[w])[len(positions[w]) // 2]
        t_pos = math.log(math.log(3 + pos))
        t_freq = f / (mean + std)
        t_diff = len(spread[w]) / len(sents)
        scores[w] = t_pos / (t_case + t_freq + t_diff)
    return [w for w, _ in sorted(scores.items(), key=lambda x: (x[1], x[0]))[:k]]


# ---------------------------------------------------------------- language

_LANG_WORDS = {
    "en": ["the", "and", "of", "to", "is", "in", "that", "for", "it", "with", "as", "on", "are", "be", "this", "by", "not", "or", "have", "from"],
    "de": ["der", "die", "und", "das", "ist", "nicht", "ein", "eine", "zu", "den", "mit", "von", "für", "auf", "sich", "des", "dem", "im", "auch"],
    "fr": ["le", "la", "les", "et", "des", "est", "une", "un", "pour", "dans", "que", "qui", "sur", "pas", "du", "au", "avec", "par", "sont"],
    "es": ["el", "la", "los", "las", "y", "de", "que", "en", "un", "una", "es", "por", "para", "con", "no", "del", "se", "al", "como"],
    "nl": ["de", "het", "een", "en", "van", "is", "dat", "niet", "op", "te", "zijn", "voor", "met", "die", "er", "aan", "ook"],
    "it": ["il", "lo", "la", "gli", "le", "e", "di", "che", "un", "una", "per", "non", "con", "del", "della", "sono", "si", "nel"],
    "pt": ["o", "a", "os", "as", "e", "de", "que", "um", "uma", "para", "com", "não", "do", "da", "em", "no", "na", "por", "são"],
}  # fmt: skip


def detect_language(text: str) -> tuple[str, float]:
    """(ISO 639-1 code, confidence 0..1) from stop-word frequencies. Good enough to route and
    filter by language for the languages listed; "und" (undetermined) when unsure."""
    ws = words(text)[:2000]
    if len(ws) < 5:
        return "und", 0.0
    counts = Counter(ws)
    scores = {lang: sum(counts[w] for w in set(vocab)) for lang, vocab in _LANG_WORDS.items()}
    best = max(scores, key=lambda lang: scores[lang])
    total = sum(scores.values())
    if not scores[best] or scores[best] / len(ws) < 0.05:
        return "und", 0.0
    return best, round(scores[best] / total, 3)


# ---------------------------------------------------------------- dates and entities

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}  # fmt: skip
_MONTHS |= {m[:3]: i for m, i in list(_MONTHS.items())}
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
DATE_DMY = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
DATE_TEXT = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\.?,?\s+(\d{{4}})\b", re.I)
DATE_TEXT_US = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def extract_dates(text: str, day_first: bool = True) -> list[str]:
    """Dates written in the text, as sorted unique ISO strings (2025-03-01): 2025-03-01,
    1/3/2025 (day first unless day_first=False), 1 March 2025, March 1, 2025."""
    found: set[str] = set()
    for y, m, d in DATE_ISO.findall(text):
        found.add(_iso(int(y), int(m), int(d)) or "")
    for a, b, y in DATE_DMY.findall(text):
        d, m = (int(a), int(b)) if day_first else (int(b), int(a))
        found.add(_iso(int(y), m, d) or "")
    for d, mon, y in DATE_TEXT.findall(text):
        found.add(_iso(int(y), _MONTHS[mon.lower()[:3]], int(d)) or "")
    for mon, d, y in DATE_TEXT_US.findall(text):
        found.add(_iso(int(y), _MONTHS[mon.lower()[:3]], int(d)) or "")
    return sorted(f for f in found if f)


ENTITY_PATTERNS: dict[str, re.Pattern[str]] = {
    # document and ticket identifiers: POL-117, ISO-27001, JIRA-4521
    "code": re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b"),
    "money": re.compile(r"(?:[$€£¥]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|bn|million|billion))?"
                        r"|\b\d[\d,]*(?:\.\d+)?\s?(?:dollars|euros|pounds|AUD|USD|EUR|GBP)\b)", re.I),
    "percent": re.compile(r"\b\d+(?:\.\d+)?\s?%"),
    "url": re.compile(r"\bhttps?://[^\s<>\"')]+"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    # organisations by their legal suffix: "Example Pty Ltd", "Acme Inc."
    "org": re.compile(r"\b(?:[A-Z][\w&]+\s){1,4}(?:Pty Ltd|Ltd|Inc|LLC|GmbH|AG|SA|BV|PLC|Corp|Corporation)\b\.?"),
    # Capitalised multi-word names not at a sentence start: "Fair Work Commission"
    "name": re.compile(r"(?<![.!?]\s)(?<!^)\b(?:[A-Z][a-z]+(?:\s(?:of|and|for|the)\s|\s)){1,4}[A-Z][a-z]+\b"),
}  # fmt: skip


def extract_entities(text: str, kinds: Sequence[str]) -> dict[str, list[str]]:
    """Entities found by pattern, per kind, unique, in order of first appearance."""
    out: dict[str, list[str]] = {}
    for kind in kinds:
        pat = ENTITY_PATTERNS.get(kind)
        if pat is None:
            continue
        found = list(dict.fromkeys(m.group(0).strip().rstrip(".,") for m in pat.finditer(text)))
        if found:
            out[kind] = found[:20]
    return out


DOC_TYPES: dict[str, list[str]] = {
    "policy": ["policy", "policies", "code of conduct", "standard"],
    "procedure": ["procedure", "process", "how to", "how-to", "step-by-step", "runbook", "playbook"],
    "contract": ["agreement", "contract", "terms and conditions", "hereinafter", "party"],
    "invoice": ["invoice", "amount due", "bill to", "remittance"],
    "minutes": ["minutes", "meeting notes", "attendees", "action items"],
    "faq": ["faq", "frequently asked", "questions and answers"],
    "guide": ["guide", "manual", "handbook", "tutorial", "getting started"],
    "report": ["report", "findings", "executive summary", "analysis"],
    "specification": ["specification", "requirements", "rfc", "design doc", "architecture"],
    "release-notes": ["release notes", "changelog", "what's new"],
}  # fmt: skip
CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rs", ".rb", ".cs",
                   ".cpp", ".c", ".h", ".kt", ".swift", ".php", ".scala", ".sh", ".sql"}  # fmt: skip


def guess_doc_type(
    uri: str, title: str, text: str, rules: dict[str, list[str]] | None = None
) -> str:
    """The kind of document, from its file extension, title and opening: policy, procedure,
    contract, invoice, minutes, faq, guide, report, specification, release-notes, code, table, or
    "document". The title counts three times as much as the opening text."""
    lower = uri.lower()
    if any(lower.endswith(ext) for ext in CODE_EXTENSIONS):
        return "code"
    if lower.endswith((".csv", ".tsv", ".xlsx")):
        return "table"
    head, name = " " + " ".join(words(text[:1500])) + " ", " " + " ".join(words(title)) + " "
    best, best_score = "document", 0
    for kind, cues in (rules or DOC_TYPES).items():
        score = 0
        for cue in cues:
            c = " " + " ".join(words(cue)) + " "
            score += 3 * (c in name) + (c in head)
        if score > best_score:
            best, best_score = kind, score
    return best
