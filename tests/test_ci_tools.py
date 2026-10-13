"""The tool installer: nothing runs unless its checksum matches (Step 27)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_tools", ROOT / "scripts/ci_tools.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_tools"] = module
    spec.loader.exec_module(module)
    return module


ct = _load()
BINARY = b"#!/bin/sh\necho hello from a pinned tool\n"


def tarball(name: str, data: bytes, *, symlink: bool = False) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        if symlink:
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
        else:
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        readme = tarfile.TarInfo("README.md")
        readme.size = 2
        tar.addfile(readme, io.BytesIO(b"hi"))
    return buf.getvalue()


def spec(
    tmp_path: Path, payload: bytes, *, sha: str | None = None, member: str | None = None
) -> dict[str, Any]:
    src = tmp_path / "download.bin"
    src.write_bytes(payload)
    entry = {"url": src.as_uri(), "sha256": sha or hashlib.sha256(payload).hexdigest()}
    return {"version": "1.0.0", "linux-amd64": entry, **({"member": member} if member else {})}


def test_plain_binary_is_installed_executable(tmp_path: Path) -> None:
    path = ct.install("tool", spec(tmp_path, BINARY), tmp_path / "bin", "linux-amd64")
    assert path.read_bytes() == BINARY
    assert path.stat().st_mode & 0o111


def test_member_is_extracted_from_an_archive(tmp_path: Path) -> None:
    s = spec(tmp_path, tarball("trivy", BINARY), member="trivy")
    assert ct.install("trivy", s, tmp_path / "bin", "linux-amd64").read_bytes() == BINARY


def test_checksum_mismatch_installs_nothing(tmp_path: Path) -> None:
    s = spec(tmp_path, BINARY, sha="0" * 64)
    with pytest.raises(ct.ToolError, match=r"SHA-256 mismatch .* refusing to install"):
        ct.install("tool", s, tmp_path / "bin", "linux-amd64")
    assert not (tmp_path / "bin").exists()  # not even a partial file


def test_archive_tricks_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ct.ToolError, match="not a regular file"):
        ct.install(
            "x",
            spec(tmp_path, tarball("x", b"", symlink=True), member="x"),
            tmp_path / "b",
            "linux-amd64",
        )
    with pytest.raises(ct.ToolError, match="'y' not found"):
        ct.install(
            "y", spec(tmp_path, tarball("x", BINARY), member="y"), tmp_path / "b", "linux-amd64"
        )


def test_unsafe_url_and_unknown_platform(tmp_path: Path) -> None:
    with pytest.raises(ct.ToolError, match="refusing non-https URL"):
        ct.fetch("http://example.com/tool")
    with pytest.raises(ct.ToolError, match="no build listed for windows-amd64"):
        ct.install("tool", spec(tmp_path, BINARY), tmp_path / "bin", "windows-amd64")


def test_manifest_is_complete_and_strict() -> None:
    """Every tool: a version, https URLs that contain that version, and a 64-hex SHA-256, for both platforms."""
    tools = yaml.safe_load((ROOT / "ci/tools.yaml").read_text())["tools"]
    assert set(tools) == {
        "opa",
        "regal",
        "dbmate",
        "actionlint",
        "gitleaks",
        "trivy",
        "syft",
        "cosign",
    }
    for name, t in tools.items():
        for plat in ("linux-amd64", "darwin-arm64"):
            entry = t[plat]
            assert entry["url"].startswith("https://github.com/"), name
            assert t["version"] in entry["url"], f"{name}: URL doesn't match the pinned version"
            assert len(entry["sha256"]) == 64, name
            assert int(entry["sha256"], 16) >= 0, name
