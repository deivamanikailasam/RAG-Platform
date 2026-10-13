"""Parsers, normalisers and PII redaction (Step 31)."""

from __future__ import annotations

import pytest

from rag_core.components.cleaning import (
    BoilerplateRemover,
    RegexPiiRedactor,
    UnicodeNormalizer,
    redact_document,
)
from rag_core.components.parsing import (
    CsvParser,
    DocxParser,
    HtmlParser,
    MarkdownParser,
    ParseError,
    ParserRouter,
    PdfParser,
    TextParser,
    decode,
    detect_mime,
)
from rag_core.types import Document, Element, Source


def kinds(doc: Document) -> list[tuple[str, str]]:
    return [(e.kind, e.text) for e in doc.elements]


def test_markdown_keeps_structure(sources: dict[str, Source]) -> None:
    doc = MarkdownParser().parse(sources["md"])
    assert doc.title == "Leave policy"
    got = kinds(doc)
    assert ("heading", "Annual leave") in got
    assert (
        "paragraph",
        "Full-time staff get 20 days of annual leave per year.\nLeave must be approved by your manager.",
    ) in got
    assert any(k == "list" and t.startswith("- Book leave") for k, t in got)
    assert any(k == "table" and "Primary carer" in t for k, t in got)
    assert ("code", "POLICY-ID: POL-117") in got  # fences gone, content kept
    assert doc.access == sources["md"].access  # access travels with the content


def test_html_keeps_content_and_drops_chrome(sources: dict[str, Source]) -> None:
    doc = HtmlParser().parse(sources["html"])
    text = doc.text
    assert doc.title == "Remote work"
    assert "three days" in text
    assert "Item | Budget\nChair | $400" in text  # tables as rows
    for chrome in ("track()", "Home", "Copyright"):  # scripts, navigation, footers
        assert chrome not in text
    assert ("heading", "Equipment") in kinds(doc)


def test_pdf_pages_footers_and_scanned_pages(sources: dict[str, Source]) -> None:
    doc = PdfParser().parse(sources["pdf"])
    assert doc.title == "Travel policy"
    assert [e.page for e in doc.elements] == [1, 2]  # page numbers kept for citations
    assert "confidential - page" not in doc.text  # the running footer is gone
    assert doc.metadata["pages_without_text"] == [3]  # reported, not silently indexed as empty


def test_pdf_without_any_text_fails_loudly() -> None:
    import io

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()
    with pytest.raises(ParseError, match="no text layer"):
        PdfParser().parse(Source("x.pdf", buf.getvalue()))
    with pytest.raises(ParseError, match="unreadable PDF"):
        PdfParser().parse(Source("x.pdf", b"%PDF-1.4 not really"))


def test_docx_headings_lists_tables(sources: dict[str, Source]) -> None:
    doc = DocxParser().parse(sources["docx"])
    assert doc.title == "Security policy"
    got = kinds(doc)
    assert ("heading", "Passwords") in got
    assert ("list", "Lock your screen when you leave your desk.") in got
    assert ("table", "Device | Encryption\nLaptop | FileVault") in got


def test_csv_rows_are_findable_on_their_own(sources: dict[str, Source]) -> None:
    doc = CsvParser().parse(sources["csv"])
    assert kinds(doc) == [
        ("table", "city: Melbourne; phone: 03 9000 0000; open: 8am"),
        ("table", "city: Sydney; open: 9am"),
    ]
    assert doc.metadata["columns"] == ["city", "phone", "open"]


@pytest.mark.parametrize(
    ("uri", "data", "expected"),
    [("a.bin", b"%PDF-1.7 ...", "application/pdf"),
    ("report", b"<!DOCTYPE html><html>", "text/html"),
    ("notes.md", b"# hi", "text/markdown"),
    ("x.txt?version=3", b"hi", "text/plain"),
    ("mystery", b"\x00\x01", "application/octet-stream")],
)  # fmt: skip
def test_type_detection_trusts_content_first(uri: str, data: bytes, expected: str) -> None:
    assert detect_mime(uri, data) == expected


def test_router_picks_by_type_and_explains_gaps(sources: dict[str, Source]) -> None:
    router = ParserRouter([MarkdownParser(), HtmlParser(), TextParser()])
    assert router.parse(sources["html"]).title == "Remote work"
    with pytest.raises(ParseError, match="no parser for application/pdf"):
        router.parse(sources["pdf"])


def test_decoding_never_crashes() -> None:
    assert decode("café".encode()) == "café"
    assert decode("\ufeffBOM".encode()) == "BOM"  # a byte-order mark is dropped
    assert decode("café".encode("cp1252")) == "café"


def test_unicode_normaliser() -> None:
    doc = Document("u", "t", (Element("paragraph", "The ﬁnal infor-\nmation\x07 is \u00a0  here\nnow"),
                            Element("table", "a | b\nc | d")), "sha")  # fmt: skip
    out = UnicodeNormalizer().normalize(doc)
    assert out.elements[0].text == "The final information is here now"
    assert out.elements[1].text == "a | b\nc | d"  # tables keep their rows


def test_boilerplate_remover() -> None:
    els = [Element("paragraph", f"Page {i} of 9") for i in range(1, 5)] + [
        Element("heading", "Intro"), Element("paragraph", "A real paragraph that is long enough to keep around."),
        Element("paragraph", "A real paragraph that is long enough to keep around.")]  # fmt: skip
    out = BoilerplateRemover().normalize(Document("u", "t", tuple(els), "sha"))
    assert [e.text for e in out.elements] == [
        "Intro",
        "A real paragraph that is long enough to keep around.",
    ]


@pytest.mark.parametrize(
    ("text", "kind"),
    [("mail jane.doe+x@example.com.au now", "email"),
    ("card 4111 1111 1111 1111 ok", "credit_card"),
    ("TFN 123 456 782 here", "au_tfn"),
    ("ABN 51 824 753 556", "au_abn"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "iban"),
    ("call 0412 345 678 today", "phone"),
    ("call +61 3 9000 0000", "phone"),
    ("from 192.168.10.1", "ipv4")],
)  # fmt: skip
def test_pii_is_found(text: str, kind: str) -> None:
    out, found = RegexPiiRedactor().redact(text)
    assert kind in found, (out, found)
    assert f"[{kind.upper()}]" in out


@pytest.mark.parametrize(
    "text", ["order 4111 1111 1111 1112", "ref 123 456 789", "version 1.2.3.4.5 build"]
)
def test_checksums_prevent_false_positives(text: str) -> None:
    out, found = RegexPiiRedactor(["credit_card", "au_tfn"]).redact(text)
    assert found == []
    assert out == text


def test_pii_strategies() -> None:
    text = "Ask jane@example.com or jane@example.com"
    assert RegexPiiRedactor(["email"], "remove").redact(text)[0] == "Ask  or "
    pseudo, _ = RegexPiiRedactor(["email"], "pseudonymise", key=b"k").redact(text)
    a, b = pseudo.split(" or ")
    assert a.endswith(b)  # same person -> same token: still joinable
    assert b.startswith("[EMAIL:")
    assert (
        RegexPiiRedactor(["email"], "pseudonymise", key=b"other").redact(text)[0] != pseudo
    )  # keyed
    with pytest.raises(ValueError, match="needs a key"):
        RegexPiiRedactor(["email"], "pseudonymise")
    with pytest.raises(ValueError, match="unknown PII kinds"):
        RegexPiiRedactor(["passport"])


def test_redact_document_covers_title_and_elements(sources: dict[str, Source]) -> None:
    doc = MarkdownParser().parse(sources["md"])
    out, found = redact_document(doc, RegexPiiRedactor())
    assert sorted(set(found)) == ["email", "phone"]
    assert "hr@example.com" not in out.text
    assert "0412 345 678" not in out.text
