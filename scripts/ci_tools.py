#!/usr/bin/env python3
"""Install pinned, checksum-verified tool binaries (Step 27).

    just tools                  everything in ci/tools.yaml, into .tools/bin
    just tools opa trivy        only these

Nothing is unpacked or made executable until its SHA-256 matches ci/tools.yaml. The same file is
used on your Mac and in CI, so both run byte-identical tools.
"""

from __future__ import annotations

import hashlib
import io
import platform
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ToolError(Exception):
    pass


def current_platform() -> str:
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine, machine
    )
    return f"{system}-{arch}"


def fetch(url: str) -> bytes:
    if not url.startswith(
        ("https://", "file://")
    ):  # never plain http: it can be altered in transit
        raise ToolError(f"refusing non-https URL: {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 - scheme checked above
        data: bytes = resp.read()
    return data


def install(name: str, spec: dict[str, Any], dest: Path, plat: str) -> Path:
    entry = spec.get(plat)
    if entry is None:
        raise ToolError(f"{name}: no build listed for {plat}")
    data = fetch(entry["url"])
    actual = hashlib.sha256(data).hexdigest()
    if actual != entry["sha256"]:
        raise ToolError(
            f"{name}: SHA-256 mismatch (expected {entry['sha256'][:12]}…, got {actual[:12]}…): "
            "refusing to install"
        )
    if member := spec.get("member"):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            try:
                info = tar.getmember(member)
            except KeyError:
                raise ToolError(f"{name}: '{member}' not found in the archive") from None
            if not info.isfile():
                raise ToolError(f"{name}: '{member}' is not a regular file")
            extracted = tar.extractfile(info)
            if extracted is None:
                raise ToolError(f"{name}: '{member}' could not be read")
            data = extracted.read()
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / name
    with tempfile.NamedTemporaryFile(
        dir=dest, delete=False
    ) as tmp:  # write, then rename: no half files
        tmp.write(data)
    Path(tmp.name).chmod(0o755)
    Path(tmp.name).replace(target)
    return target


def main(argv: list[str]) -> int:
    manifest = yaml.safe_load((ROOT / "ci/tools.yaml").read_text())["tools"]
    names = argv or sorted(manifest)
    dest, plat = ROOT / ".tools/bin", current_platform()
    try:
        for name in names:
            if name not in manifest:
                raise ToolError(f"unknown tool '{name}' (known: {', '.join(sorted(manifest))})")
            path = install(name, manifest[name], dest, plat)
            print(f"{name:11} {manifest[name]['version']:8} verified -> {path.relative_to(ROOT)}")
    except ToolError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
