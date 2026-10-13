"""Sample documents in every supported format, generated in the test (no binary files in git)."""

from __future__ import annotations

import io

import pytest

from rag_core.types import Access, Source

MARKDOWN = b"""# Leave policy

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

HTML = b"""<!doctype html>
<html>
<head>
  <title>Remote work</title>
  <script>track()</script>
  <style>body { font-family: sans-serif; }</style>
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


def make_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
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


def make_docx() -> bytes:
    import docx

    d = docx.Document()
    d.core_properties.title = "Security policy"
    d.add_heading("Passwords", level=1)
    d.add_paragraph("Use a password manager. Minimum length is 14 characters.")
    d.add_heading("Devices", level=1)
    d.add_paragraph("Lock your screen when you leave your desk.", style="List Bullet")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Device", "Encryption"
    t.cell(1, 0).text, t.cell(1, 1).text = "Laptop", "FileVault"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


HR = Access("internal", ("hr",))


@pytest.fixture
def sources() -> dict[str, Source]:
    return {
        "md": Source("file:///docs/leave-policy.md", MARKDOWN, access=HR),
        "html": Source("file:///docs/remote.html", HTML, access=Access("public")),
        "pdf": Source("file:///docs/travel.pdf", make_pdf(), access=HR),
        "docx": Source(
            "file:///docs/security.docx", make_docx(), access=Access("internal", ("eng", "hr"))
        ),
        "csv": Source(
            "file:///docs/offices.csv",
            b"city,phone,open\nMelbourne,03 9000 0000,8am\nSydney,,9am\n",
        ),
        "txt": Source("file:///docs/notes.txt", b"First paragraph.\n\nSecond paragraph."),
    }
