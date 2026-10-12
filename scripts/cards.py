#!/usr/bin/env python3
"""Model, dataset and system cards: check them, publish them, and ask "what depends on this?" (Step 25).

just cards lint [--strict]          every rule; --strict turns warnings into failures (weekly CI)
just cards docs [--check]           write docs/cards/*.md from the YAML (--check: fail if stale)
just cards impact model:embedder    what is affected if this changes
just cards lineage system:rag-api   what this was built from
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from rag_common.cards import CardError, Catalogue, documents
from rag_common.prompts import PromptError

ROOT = Path(__file__).resolve().parents[1]


def load(root: Path) -> Catalogue:
    return Catalogue.load(
        root / "cards",
        inventory=root / "infra/model-serving/models.yaml",
        gateway=root / "infra/config/litellm/config.yaml",
        prompts=root / "prompts",
    )


def cmd_lint(cat: Catalogue, today: dt.date, strict: bool) -> int:
    findings = cat.check(today)
    for f in findings:
        print(f)
    warnings = sum(f.level == "warning" for f in findings)
    errors = sum(f.level == "error" for f in findings)
    kinds = {k: sum(n.startswith(k) for n in cat.cards) for k in ("model", "dataset", "system")}
    print(f"{len(cat.cards)} cards ({kinds['model']} models, {kinds['dataset']} datasets, "
          f"{kinds['system']} system(s)): {errors} errors, {warnings} warnings"
          + (" (strict: warnings fail too)" if strict else ""))  # fmt: skip
    return 1 if errors or (strict and warnings) else 0


def cmd_docs(cat: Catalogue, out: Path, check: bool) -> int:
    docs = documents(cat)
    if check:
        stale = sorted(n for n, text in docs.items()
                       if not (out / n).exists() or (out / n).read_text() != text)  # fmt: skip
        extra = (
            sorted(p.name for p in out.glob("*.md") if p.name not in docs) if out.exists() else []
        )
        if stale or extra:
            print(f"out of date (run `just cards docs`): {', '.join(stale + extra)}")
            return 1
        print("card docs up to date")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.md"):
        if old.name not in docs:
            old.unlink()  # a removed card loses its page too
    for name, text in docs.items():
        (out / name).write_text(text)
    print(f"wrote {len(docs)} files to {out}")
    return 0


def cmd_impact(cat: Catalogue, node: str) -> int:
    if node not in cat.nodes():
        print(f"unknown: {node} (try one of: {', '.join(sorted(cat.nodes()))})", file=sys.stderr)
        return 1
    affected = cat.downstream(node)
    print(f"If {node} changes, re-check:")
    for depth, n, how in affected:
        card = cat.cards.get(n)
        owner = f"   [owner: {card.owner}]" if card else ""
        print(f"{'  ' * depth}- {n} ({how}){owner}")
    if not affected:
        print("  (nothing depends on it)")
    return 0


def cmd_lineage(cat: Catalogue, node: str) -> int:
    if node not in cat.nodes():
        print(f"unknown: {node} (try one of: {', '.join(sorted(cat.nodes()))})", file=sys.stderr)
        return 1
    print(f"{node} is built from:")
    for n in cat.upstream(node):
        print(f"  - {n}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cards")
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    p = sub.add_parser("docs")
    p.add_argument("--check", action="store_true")
    sub.add_parser("impact").add_argument("node")
    sub.add_parser("lineage").add_argument("node")
    a = ap.parse_args(argv)
    try:
        cat = load(a.root)
    except (CardError, PromptError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    match a.cmd:
        case "lint":
            return cmd_lint(cat, a.today, a.strict)
        case "docs":
            return cmd_docs(cat, a.root / "docs/cards", a.check)
        case "impact":
            return cmd_impact(cat, a.node)
        case _:
            return cmd_lineage(cat, a.node)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
