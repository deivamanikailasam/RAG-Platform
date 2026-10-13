#!/usr/bin/env python3
"""Write the small sample corpus in examples/corpus/ (Step 31).

    uv run python scripts/make_corpus.py          # (re)writes every file
    uv run rag ingest --profile offline --group hr examples/corpus/*

One file per format the built-in parsers read: Markdown, HTML, CSV, a digital PDF (with a running
footer and a page without a text layer, like a scanned one), a Word file, and a corrupt PDF that
must be reported as failed, not crash the run. The PDF and Word files are written with fixed
dates, so running this again produces the same bytes and the ingestion manifest sees no change.
The same documents are the test fixtures in libs/rag-core/tests/conftest.py.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples" / "corpus"

LEAVE_POLICY = """# Leave policy

All staff accrue leave from their first day.

## Annual leave

Full-time staff get **20 days** of annual leave per year.
Leave must be approved by your manager.

- Book leave in the HR portal
- At least two weeks' notice for more than five days

## Parental leave

Parental leave is 18 weeks at full pay. Contact hr@example.com or call 0412 345 678.

| Type | Weeks | Paid |
|------|-------|------|
| Primary carer | 18 | yes |
| Secondary carer | 4 | yes |

```text
POLICY-ID: POL-117
```
"""

REMOTE_WORK = """<!doctype html>
<html>
<head>
  <title>Remote work</title>
  <script>track()</script>
</head>
<body>
  <nav><a href="/">Home</a> | <a href="/hr">HR</a></nav>
  <main>
    <h1>Remote work policy</h1>
    <p>You may work from home up to <b>three days</b> a week.</p>
    <h2>Equipment</h2>
    <ul>
      <li>A laptop is provided.</li>
      <li>Monitors on request.</li>
    </ul>
    <table>
      <tr><th>Item</th><th>Budget</th></tr>
      <tr><td>Chair</td><td>$400</td></tr>
    </table>
  </main>
  <footer>Copyright 2026 Example Pty Ltd</footer>
</body>
</html>
"""

OFFICES = "city,phone,open\nMelbourne,03 9000 0000,8am\nSydney,,9am\n"

FIXED = dt.datetime(2026, 10, 13, 9, 0, 0)


def travel_policy_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=True)  # invariant: no timestamps, same bytes
    c.setTitle("Travel policy")
    pages = [
        [
            "Travel policy",
            "",
            "Economy class for flights under six hours.",
            "Business class needs approval (POL-117).",
        ],
        ["Meals", "", "Meal allowance is 90 dollars a day in Australia."],
        [],  # a scanned page: no text layer
    ]
    for n, lines in enumerate(pages, start=1):
        y = 780
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.drawString(72, 40, f"Example Pty Ltd - confidential - page {n}")
        c.showPage()
    c.save()
    return buf.getvalue()


def security_policy_docx() -> bytes:
    import docx

    d = docx.Document()
    d.core_properties.title = "Security policy"
    d.core_properties.created = d.core_properties.modified = FIXED
    d.add_heading("Passwords", level=1)
    d.add_paragraph("Use a password manager. Minimum length is 14 characters.")
    d.add_heading("Devices", level=1)
    d.add_paragraph("Lock your screen when you leave your desk.", style="List Bullet")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Device", "Encryption"
    t.cell(1, 0).text, t.cell(1, 1).text = "Laptop", "FileVault"
    buf = io.BytesIO()
    d.save(buf)
    return _repack(buf.getvalue())


def _repack(docx_bytes: bytes) -> bytes:
    """A .docx is a zip whose entries carry the time it was saved: set one fixed time instead."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(docx_bytes)) as src,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for info in src.infolist():
            fixed = zipfile.ZipInfo(info.filename, date_time=FIXED.timetuple()[:6])
            fixed.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(fixed, src.read(info.filename))
    return out.getvalue()


def files() -> dict[str, bytes]:
    return {
        "leave-policy.md": LEAVE_POLICY.encode(),
        "remote-work.html": REMOTE_WORK.encode(),
        "offices.csv": OFFICES.encode(),
        "travel-policy.pdf": travel_policy_pdf(),
        "security-policy.docx": security_policy_docx(),
        "broken.pdf": b"%PDF-1.4 broken",  # a corrupt upload: reported as failed, never indexed
    }


def main() -> int:
    CORPUS.mkdir(parents=True, exist_ok=True)
    for name, data in files().items():
        (CORPUS / name).write_bytes(data)
        print(f"wrote {CORPUS.relative_to(ROOT) / name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
