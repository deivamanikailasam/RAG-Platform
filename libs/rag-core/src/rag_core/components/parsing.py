"""Parsers: bytes of one format in, structured elements out (Step 31).

Structure matters for retrieval: a chunker that knows where headings and tables are can keep a
table whole and label every chunk with its section ("Leave policy > Parental leave"), which makes
both the embedding and the citation better than splitting raw text every N characters.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rag_core.registry import Container, register
from rag_core.types import Document, Element, Source

MIME_BY_EXTENSION = {
    ".txt": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown", ".html": "text/html",
    ".htm": "text/html", ".pdf": "application/pdf", ".csv": "text/csv", ".json": "application/json",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}  # fmt: skip


class ParseError(Exception):
    """The source can't be parsed (corrupt, encrypted, scanned without OCR, unsupported)."""


def detect_mime(uri: str, data: bytes, declared: str = "application/octet-stream") -> str:
    """Trust the content first (magic bytes), then the extension, then what the sender declared."""
    head = data[:512].lstrip()
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04") and b"word/" in data[:4000]:
        return MIME_BY_EXTENSION[".docx"]
    if head[:15].lower().startswith((b"<!doctype html", b"<html")):
        return "text/html"
    ext = PurePosixPath(uri.split("?")[0]).suffix.lower()
    if ext in MIME_BY_EXTENSION:
        return MIME_BY_EXTENSION[ext]
    return declared


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace")  # last resort: never crash on odd bytes


def _title_from(uri: str) -> str:
    stem = PurePosixPath(uri.split("?")[0]).stem
    return re.sub(r"[_-]+", " ", stem).strip().capitalize() or uri


def _doc(source: Source, title: str, elements: list[Element], **meta: Any) -> Document:
    return Document(uri=source.uri, title=title, elements=tuple(e for e in elements if e.text.strip()),
                    sha256=source.sha256, access=source.access,
                    metadata={**source.metadata, **meta, "mime_type": meta.get("mime_type", source.mime_type)})  # fmt: skip


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- plain text and Markdown


class TextParser:
    mime_types = ("text/plain",)

    def parse(self, source: Source) -> Document:
        paras = re.split(r"\n\s*\n", decode(source.data).replace("\r\n", "\n"))
        return _doc(
            source, _title_from(source.uri), [Element("paragraph", p.strip()) for p in paras]
        )


@register("parser", "text", summary="plain text: paragraphs split on blank lines")
def _text(p: BaseModel, c: Container) -> TextParser:
    return TextParser()


class MarkdownParser:
    """Headings, lists, tables and fenced code become their own elements."""

    mime_types = ("text/markdown",)
    _heading = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

    def parse(self, source: Source) -> Document:
        lines = decode(source.data).replace("\r\n", "\n").split("\n")
        elements: list[Element] = []
        buf: list[str] = []
        kind = "paragraph"
        title = ""

        def flush() -> None:
            nonlocal buf, kind
            if buf:
                text = "\n".join(buf).strip()
                if kind == "code":
                    text = "\n".join(
                        ln for ln in text.split("\n") if not ln.strip().startswith("```")
                    )
                else:
                    text = re.sub(
                        r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text
                    )  # [text](url) -> text (url)
                    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)  # **bold** -> bold
                elements.append(Element(kind, text.strip()))  # type: ignore[arg-type]
            buf, kind = [], "paragraph"

        in_code = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_code:
                    buf.append(line)
                    flush()
                    in_code = False
                else:
                    flush()
                    in_code, kind = True, "code"
                    buf.append(line)
                continue
            if in_code:
                buf.append(line)
                continue
            m = self._heading.match(line)
            if m:
                flush()
                level, text = len(m.group(1)), m.group(2)
                title = title or (text if level == 1 else "")
                elements.append(Element("heading", text, level=level))
                continue
            if not line.strip():
                flush()
                continue
            this = ("table" if line.lstrip().startswith("|")
                    else "list" if re.match(r"^\s*([-*+]|\d+[.)])\s+", line) else "paragraph")  # fmt: skip
            if (
                buf
                and this != kind
                and not (kind == "list" and this == "paragraph" and line.startswith("  "))
            ):
                flush()
            kind = this if not buf else kind
            buf.append(line)
        flush()
        return _doc(source, title or _title_from(source.uri), elements)


@register(
    "parser", "markdown", summary="Markdown: headings, lists, tables and code blocks as structure"
)
def _markdown(p: BaseModel, c: Container) -> MarkdownParser:
    return MarkdownParser()


# ---------------------------------------------------------------- HTML


class _HtmlCollector(HTMLParser):
    SKIP: ClassVar[set[str]] = {
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "template",
        "svg",
    }
    BLOCKS: ClassVar[dict[str, str]] = {"p": "paragraph", "li": "list", "pre": "code", "blockquote": "paragraph", "figcaption": "caption",
                "dd": "paragraph", "dt": "paragraph", "td": "_cell", "th": "_cell"}  # fmt: skip

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self.title = ""
        self._skip = 0
        self._stack: list[str] = []
        self._buf: list[str] = []
        self._row: list[str] = []
        self._rows: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCKS or re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self._stack.append(tag)
        elif tag == "br":
            self._buf.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in ("td", "th"):
            self._row.append(" ".join("".join(self._buf).split()))
            self._buf = []
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()
        elif tag == "tr":
            if self._row:
                self._rows.append(" | ".join(self._row))
            self._row = []
        elif tag == "table":
            if self._rows:
                self.elements.append(Element("table", "\n".join(self._rows)))
            self._rows = []
        elif self._stack and self._stack[-1] == tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        self._buf.append(data)

    def _flush(self) -> None:
        text = "".join(self._buf)
        text = "\n".join(" ".join(line.split()) for line in text.split("\n")).strip()
        self._buf = []
        tag = self._stack.pop() if self._stack else "p"
        if not text:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.elements.append(Element("heading", text, level=int(tag[1])))
        else:
            kind = self.BLOCKS.get(tag, "paragraph")
            if kind != "_cell":
                self.elements.append(Element(kind, text))  # type: ignore[arg-type]


class HtmlParser:
    """Readable content only: navigation, scripts, footers and forms are dropped."""

    mime_types = ("text/html",)

    def parse(self, source: Source) -> Document:
        col = _HtmlCollector()
        col.feed(decode(source.data))
        col.close()
        col._flush()
        title = " ".join(col.title.split()) or next(
            (e.text for e in col.elements if e.kind == "heading"), ""
        )
        return _doc(source, title or _title_from(source.uri), col.elements)


@register(
    "parser", "html", summary="HTML: headings, paragraphs, lists, tables; drops nav/footer/scripts"
)
def _html(p: BaseModel, c: Container) -> HtmlParser:
    return HtmlParser()


# ---------------------------------------------------------------- CSV


class CsvParams(_Strict):
    rows_per_element: int = Field(1, ge=1)


class CsvParser:
    """Each row becomes "column: value; …", so a row can be found and cited on its own."""

    mime_types = ("text/csv",)

    def __init__(self, rows_per_element: int = 1) -> None:
        self.n = rows_per_element

    def parse(self, source: Source) -> Document:
        reader = csv.DictReader(io.StringIO(decode(source.data)))
        rows = [
            "; ".join(f"{k}: {v}" for k, v in row.items() if v not in (None, "")) for row in reader
        ]
        groups = ["\n".join(rows[i : i + self.n]) for i in range(0, len(rows), self.n)]
        return _doc(source, _title_from(source.uri), [Element("table", g) for g in groups],
                    columns=list(reader.fieldnames or []))  # fmt: skip


@register(
    "parser",
    "csv",
    params=CsvParams,
    summary="CSV: one element per row (or per N rows), columns named",
)
def _csv(p: CsvParams, c: Container) -> CsvParser:
    return CsvParser(p.rows_per_element)


# ---------------------------------------------------------------- PDF


class PdfParams(_Strict):
    min_chars_per_page: int = Field(20, ge=0)  # below this a page is probably a scanned image


class PdfParser:
    """Text layer per page with page numbers kept (for citations: "p. 12").
    Scanned pages have no text layer: they're reported, not silently indexed as empty (OCR: Docling)."""

    mime_types = ("application/pdf",)

    def __init__(self, min_chars_per_page: int = 20) -> None:
        self.min_chars = min_chars_per_page

    def parse(self, source: Source) -> Document:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        logging.getLogger("pypdf").setLevel(
            logging.ERROR
        )  # its warnings about odd files are noise here

        try:
            reader = PdfReader(io.BytesIO(source.data))
            if reader.is_encrypted:
                raise ParseError("encrypted PDF: ask the owner for an unprotected copy")
            pages = [[ln.strip() for ln in (page.extract_text() or "").split("\n") if ln.strip()]
                    for page in reader.pages]  # fmt: skip
            # Lines repeated on most pages are running headers/footers ("Page 3 of 9" counts as the
            # same line as "Page 4 of 9"): dropped, and a page with nothing else has no text layer.

            def key(ln: str) -> str:
                return re.sub(r"\d+", "#", ln.lower())

            seen = [{key(ln) for ln in p} for p in pages]
            repeated = {
                k
                for k in set().union(*seen)
                if sum(k in s for s in seen) >= max(2, (len(pages) + 1) // 2)
            }
            elements: list[Element] = []
            scanned: list[int] = []
            for n, lines in enumerate(pages, start=1):
                body = [ln for ln in lines if key(ln) not in repeated]
                if len(" ".join(body)) < self.min_chars:
                    scanned.append(n)
                    continue
                elements.append(Element("paragraph", "\n".join(body), page=n))
            info_title = (reader.metadata.title if reader.metadata else None) or ""
        except PdfReadError as e:
            raise ParseError(f"unreadable PDF: {e}") from None
        if not elements:
            raise ParseError(
                f"no text layer on any of {len(reader.pages)} page(s): scanned? use an OCR parser"
            )
        return _doc(source, info_title.strip() or _title_from(source.uri), elements,
                    pages=len(reader.pages), pages_without_text=scanned, repeated_lines_dropped=len(repeated))  # fmt: skip


@register("parser", "pdf", params=PdfParams, requires=("pdf",),
            summary="PDF text layer (pypdf), page numbers kept; flags scanned pages")  # fmt: skip
def _pdf(p: PdfParams, c: Container) -> PdfParser:
    import pypdf  # noqa: F401    (fail at build time, with the extra's name, if missing)

    return PdfParser(p.min_chars_per_page)


# ---------------------------------------------------------------- DOCX


class DocxParser:
    mime_types = (MIME_BY_EXTENSION[".docx"],)

    def parse(self, source: Source) -> Document:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        d = docx.Document(io.BytesIO(source.data))
        elements: list[Element] = []
        for block in d.element.body.iterchildren():
            tag = block.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = Paragraph(block, d)
                style = (para.style.name or "") if para.style is not None else ""
                text = para.text.strip()
                m = re.match(r"Heading (\d)", style)
                if m:
                    elements.append(Element("heading", text, level=int(m.group(1))))
                elif style == "Title":
                    elements.append(Element("title", text, level=0))
                elif "List" in style:
                    elements.append(Element("list", text))
                else:
                    elements.append(Element("paragraph", text))
            elif tag == "tbl":
                table = Table(block, d)
                rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
                elements.append(Element("table", "\n".join(rows)))
        title = (d.core_properties.title or "").strip() or next(
            (e.text for e in elements if e.kind in ("title", "heading")), ""
        )
        return _doc(source, title or _title_from(source.uri), elements)


@register(
    "parser",
    "docx",
    requires=("docx",),
    summary="Word .docx: heading styles, lists and tables (python-docx)",
)
def _docx(p: BaseModel, c: Container) -> DocxParser:
    import docx  # noqa: F401

    return DocxParser()


# ---------------------------------------------------------------- external, layout-aware parsers


class DoclingParser:
    """IBM Docling: layout analysis, tables, reading order, OCR for scanned pages. Heavy (ML models)."""

    mime_types = (
        "application/pdf",
        MIME_BY_EXTENSION[".docx"],
        "text/html",
        "image/png",
        "image/jpeg",
    )

    def parse(self, source: Source) -> Document:  # pragma: no cover - needs docling and its models
        import tempfile
        from pathlib import Path

        from docling.document_converter import DocumentConverter

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / (PurePosixPath(source.uri).name or "input")
            path.write_bytes(source.data)
            markdown = DocumentConverter().convert(str(path)).document.export_to_markdown()
        return MarkdownParser().parse(
            Source(source.uri, markdown.encode(), "text/markdown", source.access, source.metadata)
        )


@register("parser", "docling", status="reference", requires=("docling",),
            summary="layout-aware PDF/DOCX/HTML/images with OCR and table structure (IBM Docling)")  # fmt: skip
def _docling(p: BaseModel, c: Container) -> DoclingParser:  # pragma: no cover
    import docling  # noqa: F401

    return DoclingParser()


class TikaParams(_Strict):
    url: str = "http://tika:9998"


class TikaParser:
    """Apache Tika server: text from ~1,000 formats (Office, email, archives). Plain text only."""

    mime_types = ("application/msword", "application/vnd.ms-excel", "message/rfc822", "application/rtf",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")  # fmt: skip

    def __init__(self, url: str) -> None:
        import httpx

        self._http = httpx.Client(base_url=url, timeout=120)

    def parse(self, source: Source) -> Document:
        r = self._http.put(
            "/tika",
            content=source.data,
            headers={"Accept": "text/plain", "Content-Type": source.mime_type},
        )
        if r.status_code != 200:
            raise ParseError(f"tika: {r.status_code}")
        return TextParser().parse(
            Source(source.uri, r.content, "text/plain", source.access, source.metadata)
        )


@register("parser", "tika", params=TikaParams, status="mocked",
            summary="Apache Tika server for legacy Office, email, RTF, … (text only)")  # fmt: skip
def _tika(p: TikaParams, c: Container) -> TikaParser:
    return TikaParser(p.url)


class ParserRouter:
    """Picks the parser for each source's (detected) type from the profile's `parsers` list."""

    def __init__(self, parsers: list[Any]) -> None:
        self.by_mime: dict[str, Any] = {}
        for p in parsers:
            for m in p.mime_types:
                self.by_mime.setdefault(m, p)  # first one listed wins

    def parse(self, source: Source) -> Document:
        mime = detect_mime(source.uri, source.data, source.mime_type)
        parser = self.by_mime.get(mime)
        if parser is None:
            raise ParseError(
                f"no parser for {mime} ({source.uri}); configured: {', '.join(sorted(self.by_mime))}"
            )
        doc: Document = parser.parse(
            Source(source.uri, source.data, mime, source.access, source.metadata)
        )
        return doc
