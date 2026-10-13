#!/usr/bin/env python3
"""Is there a document for everything? Fails CI when something has no documentation.

    doc_coverage.py [--json]

Checks, all offline and from the repository itself:

1. every registered component (the catalogue) is named in the decision guide
   (docs/concepts/decision-guide.md) AND in at least one step or extension write-up
   (docs/steps/, docs/extensions/), as `name` in backticks;
2. every `just` recipe appears in docs/reference.md (as `just <recipe>`);
3. every ADR file is linked from docs/adr/README.md;
4. every step write-up is linked from docs/steps/README.md and every extension page from
   docs/extensions/README.md;
5. every relative markdown link in docs/ (and the root README) points at a file that exists and,
   when it names a heading (`file.md#heading`), at a heading that exists.

A component name shared by several kinds (`memory`, `llm`, `gateway`, …) counts as mentioned once
its name appears; the catalogue is the per-kind source of truth.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
GUIDE = DOCS / "concepts/decision-guide.md"
REFERENCE = DOCS / "reference.md"

_RECIPE = re.compile(r"^@?([A-Za-z_][\w-]*)(?:\s[^:]*?)?:(?!=)")
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ANCHOR_TAG = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"")


def components() -> list[tuple[str, str]]:
    from rag_core.registry import describe

    return sorted({(r["kind"], r["name"]) for r in describe()})


def recipes(justfile: Path = ROOT / "justfile") -> list[str]:
    """Public recipe names, parsed from the justfile (same list as `just --summary`)."""
    out = []
    for line in justfile.read_text().splitlines():
        if (
            not line
            or line[0] in " \t#["
            or line.startswith(("set ", "export ", "alias ", "import ", "mod "))
        ):
            continue
        m = _RECIPE.match(line)
        if m and not m.group(1).startswith("_"):
            out.append(m.group(1))
    return sorted(set(out))


def _named_spans(text: str) -> str:
    """The parts of a page that name things: code spans, fenced code (YAML snippets) and bold text."""
    spans: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            spans.append(line)
        else:
            spans += re.findall(r"`([^`\n]+)`", line) + re.findall(r"\*\*([^*\n]+)\*\*", line)
    return "\n".join(spans)


def _mentions(named: str, name: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", named) is not None


def _read(paths: Iterable[Path]) -> str:
    return "\n".join(p.read_text() for p in paths)


def check_components() -> list[str]:
    problems = []
    guide = GUIDE.read_text() if GUIDE.is_file() else ""
    if not guide:
        problems.append(f"{GUIDE.relative_to(ROOT)} is missing")
    write_ups = _named_spans(
        _read(sorted((DOCS / "steps").glob("*.md")) + sorted((DOCS / "extensions").glob("*.md")))
    )
    for kind, name in components():
        if guide and f"`{name}`" not in guide:
            problems.append(f"component {kind}/{name}: not in docs/concepts/decision-guide.md")
        if not _mentions(write_ups, name):
            problems.append(
                f"component {kind}/{name}: not in any docs/steps or docs/extensions page"
            )
    return problems


def check_recipes() -> list[str]:
    """Every recipe documented in the reference; every `just <name>` there still exists."""
    ref = REFERENCE.read_text()
    have = recipes()
    problems = [
        f"just recipe {r!r}: not in docs/reference.md"
        for r in have
        if not re.search(rf"just {re.escape(r)}(?![\w-])", ref) and f"`{r}`" not in ref
    ]
    builtin = {"--list", "--summary", "--check", "--fmt"}
    for name in sorted(set(re.findall(r"`just ([A-Za-z_][\w-]*)", ref)) - set(have) - builtin):
        problems.append(
            f"docs/reference.md names `just {name}`, which is not a recipe in the justfile"
        )
    return problems


def check_indexes() -> list[str]:
    problems = []
    for folder, pattern in (
        ("adr", "[0-9][0-9][0-9][1-9]-*.md"),
        ("steps", "step-*.md"),
        ("extensions", "[0-9][0-9]-*.md"),
    ):
        index = DOCS / folder / "README.md"
        text = index.read_text() if index.is_file() else ""
        for page in sorted((DOCS / folder).glob(pattern)):
            if f"({page.name}" not in text and f"/{page.name}" not in text:
                problems.append(
                    f"docs/{folder}/{page.name}: not linked from docs/{folder}/README.md"
                )
    return problems


def slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their text
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    out = []
    for ch in text:
        if ch in " -":
            out.append("-")
        elif ch == "_" or ch.isalnum() or unicodedata.category(ch).startswith(("L", "N")):
            out.append(ch)
    return "".join(out)


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    found: set[str] = set()
    in_fence = False
    for line in path.read_text().splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        found.update(_ANCHOR_TAG.findall(line))
        m = _HEADING.match(line)
        if m:
            base = slug(m.group(2))
            n = seen.get(base, 0)
            seen[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
    return found


def links(path: Path) -> Iterable[tuple[int, str]]:
    in_fence = False
    for no, line in enumerate(path.read_text().splitlines(), 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = re.sub(r"`[^`]*`", "", line)  # code spans are not links
        for m in _LINK.finditer(line):
            yield no, m.group(1) or m.group(2)


def check_links(files: Iterable[Path]) -> list[str]:
    problems = []
    cache: dict[Path, set[str]] = {}
    for f in files:
        for no, target in links(f):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("//"):
                continue  # http:, https:, mailto:, …
            path_part, _, anchor = target.partition("#")
            dest = f if not path_part else (f.parent / path_part).resolve()
            where = f"{f.relative_to(ROOT)}:{no}"
            if not dest.exists():
                problems.append(f"{where}: broken link {target!r}")
                continue
            if anchor and dest.is_file() and dest.suffix == ".md":
                if dest not in cache:
                    cache[dest] = anchors(dest)
                if anchor not in cache[dest]:
                    problems.append(f"{where}: no heading #{anchor} in {dest.relative_to(ROOT)}")
    return problems


def run() -> dict[str, list[str]]:
    md = [*sorted(DOCS.rglob("*.md")), ROOT / "README.md"]
    return {
        "components": check_components(),
        "recipes": check_recipes(),
        "indexes": check_indexes(),
        "links": check_links(md),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="doc_coverage.py")
    ap.add_argument("--json", action="store_true", help="print the gaps as JSON")
    a = ap.parse_args(argv)
    result = run()
    gaps = sum(len(v) for v in result.values())
    if a.json:
        print(json.dumps(result, indent=2))
    else:
        for group, items in result.items():
            for item in items:
                print(f"ERROR [{group}] {item}", file=sys.stderr)
        n_comp = len(components())
        print(
            f"documentation coverage: {n_comp} components, {len(recipes())} recipes, ADRs, indexes and "
            f"links checked; {gaps} gap(s)"
        )
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
