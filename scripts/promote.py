#!/usr/bin/env python3
"""Promote a released rag-api image to an environment (Step 29): change ONE line in git.

    just promote local sha256:3f1c…     verify the signature and provenance (just image-verify), then
                                        set the digest in deploy/envs/local/kustomization.yaml,
                                        commit on a branch and open a pull request

Merging the pull request is the deployment: Argo CD sees the new digest on main and rolls it out.
Rolling back is `git revert` of that commit, through the same pull request flow.
This script only edits the file; the recipe does the verifying and the git work.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENVS = ROOT / "deploy" / "envs"
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
IMAGE = "rag-api"


class PromoteError(Exception):
    pass


def promote(env: str, digest: str, envs: Path = ENVS) -> str | None:
    """Set the rag-api digest for one environment. Returns the previous digest (None if unset)."""
    if not DIGEST.match(digest):
        raise PromoteError(f"not an image digest: {digest!r} (expected sha256:<64 hex>)")
    path = envs / env / "kustomization.yaml"
    if not path.is_file():
        known = sorted(p.name for p in envs.iterdir() if (p / "kustomization.yaml").is_file())
        raise PromoteError(f"unknown environment {env!r} (known: {', '.join(known)})")
    text = path.read_text()
    entries = [i for i in (yaml.safe_load(text) or {}).get("images", []) if i.get("name") == IMAGE]
    if len(entries) != 1:
        raise PromoteError(f"{path}: expected exactly one images entry named {IMAGE!r}")
    previous = str(entries[0].get("digest", "")) or None
    if previous == digest:
        return previous
    # Edit the one line as text, so every comment and all formatting stay exactly as they are
    lines = text.splitlines(keepends=True)
    head = next(
        n for n, line in enumerate(lines) if re.match(rf"^(\s*)- name: {IMAGE}\s*(#.*)?$", line)
    )
    indent = len(lines[head]) - len(lines[head].lstrip()) + 2
    for n in range(head + 1, len(lines)):
        line = lines[n]
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            lines.insert(n, " " * indent + f"digest: {digest}\n")
            break
        if re.match(r"^\s*digest:", line):
            lines[n] = re.sub(r"(digest:\s*)\S+", lambda m: m.group(1) + digest, line, count=1)
            break
    else:
        lines.append(" " * indent + f"digest: {digest}\n")
    new = "".join(lines)
    check = [i for i in yaml.safe_load(new)["images"] if i.get("name") == IMAGE]
    if check[0].get("digest") != digest:  # pragma: no cover - a guard, not a branch we expect
        raise PromoteError(f"{path}: could not set the digest safely; edit it by hand")
    path.write_text(new)
    return None if previous is None or "<digest>" in previous else previous


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="promote")
    ap.add_argument("env")
    ap.add_argument("digest")
    a = ap.parse_args(argv)
    try:
        previous = promote(a.env, a.digest)
    except PromoteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if previous == a.digest:
        print(f"{a.env} already runs {a.digest}")
    else:
        print(f"{a.env}: rag-api {previous or '(none)'} -> {a.digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
