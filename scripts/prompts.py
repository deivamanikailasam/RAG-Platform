#!/usr/bin/env python3
"""The prompt registry's command line (Step 24).

just prompts list                          every prompt, its versions and labels
just prompts lint [--against OLD_LOCK]     validate everything (pre-commit and CI run this)
just prompts new rag-answer                start v<N+1> as a copy of the latest version
just prompts lock                          release new versions: record their SHA-256
just prompts promote rag-answer 2 production
just prompts render rag-answer --label staging --var question="…" --var context="…"
just prompts diff rag-answer 1 2           what changed between two versions
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from rag_common.prompts import (
    LABEL,
    LABELS_FILE,
    VERSION_FILE,
    PromptError,
    Registry,
    file_sha256,
    load_version,
    lock_only_grew,
    read_lock,
    write_lock,
)

LABELS_HEADER = (
    "# Which version each environment uses. Promote or roll back = change a number here, in a PR.\n"
    "# Edit with `just prompts promote <name> <version> <label>` (it re-checks everything).\n"
)


def cmd_list(root: Path) -> int:
    reg = Registry.load(root)
    for name in reg.names():
        labels = ", ".join(f"{k}={v}" for k, v in sorted(reg.labels_of(name).items()))
        print(f"{name:20} versions {reg.versions_of(name)!s:10} labels: {labels or '-'}")
    return 0


def cmd_lint(root: Path, against: Path | None) -> int:
    Registry.load(root)  # raises PromptError with the exact problem
    if against is not None:  # CI: compare with the lock file on main
        old = json.loads(against.read_text()) if against.stat().st_size else {}
        if problems := lock_only_grew(old, read_lock(root)):
            raise PromptError("; ".join(problems))
    print("prompts OK")
    return 0


def cmd_new(root: Path, name: str) -> int:
    folder = root / name
    versions = sorted(
        int(m.group(1)) for p in folder.glob("v*.yaml") if (m := VERSION_FILE.match(p.name))
    )
    if not versions:
        raise PromptError(f"no prompt named '{name}' (create {folder}/v1.yaml by hand)")
    latest, nxt = folder / f"v{versions[-1]}.yaml", versions[-1] + 1
    text = re.sub(r"(?m)^version: \d+$", f"version: {nxt}", latest.read_text(), count=1)
    text = re.sub(
        r"(?m)^changelog: .*$", "changelog: TODO describe what changed and why", text, count=1
    )
    target = folder / f"v{nxt}.yaml"
    target.write_text(text)
    print(f"created {target}: edit it, then `just prompts lock` when it's ready for review")
    return 0


def cmd_lock(root: Path) -> int:
    Registry.load(root, require_lock=False)  # only valid files can be released
    lock, added = read_lock(root), []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(folder.glob("v*.yaml")):
            v = str(load_version(path).version)
            sha = file_sha256(path)
            known = lock.get(folder.name, {}).get(v)
            if known is None:
                lock.setdefault(folder.name, {})[v] = sha
                added.append(f"{folder.name}@{v}")
            elif known != sha:
                raise PromptError(f"{folder.name}@{v} was released and has been edited: revert it "
                                  "(git checkout) and use `just prompts new`")  # fmt: skip
    write_lock(root, lock)
    print("released:", ", ".join(added) if added else "nothing new")
    return 0


def cmd_promote(root: Path, name: str, version: int, label: str) -> int:
    if not LABEL.match(label):
        raise PromptError(f"bad label name '{label}'")
    reg = Registry.load(root)
    reg.get(name, version=version)  # must exist and be released
    path = root / LABELS_FILE
    labels = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}
    before = labels.get(name, {}).get(label)
    labels.setdefault(name, {})[label] = version
    path.write_text(LABELS_HEADER + yaml.safe_dump(labels, sort_keys=True))
    Registry.load(root)  # re-check the result
    print(f"{name}.{label}: {before} -> {version}   (commit labels.yaml and open a PR)")
    return 0


def cmd_render(
    root: Path, name: str, label: str | None, version: int | None, pairs: list[str]
) -> int:
    if bad := [p for p in pairs if "=" not in p]:
        raise PromptError(f"--var needs NAME=VALUE, got {bad}")
    values = dict(p.split("=", 1) for p in pairs)
    r = Registry.load(root).render(name, values, label=label, version=version)
    out: dict[str, Any] = {
        "ref": r.ref,
        "sha256": r.sha256[:12],
        "model": r.model,
        "params": dict(r.params),
    }
    out |= {"messages": list(r.messages)} if r.messages else {"text": r.text}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_diff(root: Path, name: str, a: int, b: int) -> int:
    reg = Registry.load(root)
    reg.get(name, version=a)
    reg.get(name, version=b)
    old, new = (root / name / f"v{a}.yaml").read_text(), (root / name / f"v{b}.yaml").read_text()
    sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                               f"{name}@{a}", f"{name}@{b}"))  # fmt: skip
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="prompts")
    ap.add_argument("--root", type=Path, default=Path("prompts"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("lint")
    p.add_argument("--against", type=Path, help="lock file from main (CI)")
    p = sub.add_parser("new")
    p.add_argument("name")
    sub.add_parser("lock")
    p = sub.add_parser("promote")
    p.add_argument("name")
    p.add_argument("version", type=int)
    p.add_argument("label")
    p = sub.add_parser("render")
    p.add_argument("name")
    p.add_argument("--label")
    p.add_argument("--version", type=int)
    p.add_argument("--var", action="append", default=[], metavar="NAME=VALUE")
    p = sub.add_parser("diff")
    p.add_argument("name")
    p.add_argument("a", type=int)
    p.add_argument("b", type=int)
    a = ap.parse_args(argv)
    try:
        match a.cmd:
            case "list":
                return cmd_list(a.root)
            case "lint":
                return cmd_lint(a.root, a.against)
            case "new":
                return cmd_new(a.root, a.name)
            case "lock":
                return cmd_lock(a.root)
            case "promote":
                return cmd_promote(a.root, a.name, a.version, a.label)
            case "render":
                return cmd_render(a.root, a.name, a.label, a.version, a.var)
            case _:
                return cmd_diff(a.root, a.name, a.a, a.b)
    except PromptError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
