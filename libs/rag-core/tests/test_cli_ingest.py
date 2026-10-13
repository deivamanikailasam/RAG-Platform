"""The `rag ingest | delete | enqueue | worker` commands (Step 31), on the repository's sample corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_core.cli import main as rag_cli

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "examples" / "corpus"
RAG_YAML = str(ROOT / "rag.yaml")


def test_the_sample_corpus_is_what_make_corpus_writes() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_corpus", ROOT / "scripts/make_corpus.py")
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, data in mod.files().items():
        assert _content((CORPUS / name).read_bytes()) == _content(data), (
            f"{name}: run scripts/make_corpus.py"
        )


def _content(data: bytes) -> object:
    """A .docx is a zip: compare what's inside (compressed bytes may differ between zlib builds)."""
    import io
    import zipfile

    if not data.startswith(b"PK"):
        return data
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


def test_ingest_the_corpus_offline(capsys: pytest.CaptureFixture[str]) -> None:
    files = sorted(str(p) for p in CORPUS.iterdir())
    # a failed source makes the exit code 1, so scripts and CI notice
    assert (
        rag_cli(["ingest", "--file", RAG_YAML, "--profile", "offline", "--group", "hr", *files])
        == 1
    )
    out = {line.split()[-1] if "pii" not in line and "PDF" not in line else line.split()[4]: line
           for line in capsys.readouterr().out.splitlines()}  # fmt: skip
    by_name = {Path(k).name: v for k, v in out.items()}
    assert by_name["broken.pdf"].startswith("failed")
    assert "unreadable PDF" in by_name["broken.pdf"]
    assert by_name["leave-policy.md"].split()[:2] == ["indexed", "2"]
    assert by_name["leave-policy.md"].endswith("pii: email, phone")
    assert by_name["offices.csv"].endswith("pii: phone")
    for name in ("remote-work.html", "security-policy.docx", "travel-policy.pdf"):
        assert by_name[name].split()[:2] == ["indexed", "1"], by_name[name]
    assert all(k.startswith("file:///") for k in out)  # local paths became file:// URIs


def test_delete_enqueue_and_worker(capsys: pytest.CaptureFixture[str]) -> None:
    md = str(CORPUS / "leave-policy.md")
    assert rag_cli(["delete", "--file", RAG_YAML, "--profile", "offline", md]) == 0
    assert capsys.readouterr().out.startswith("deleted")
    # the offline profile's queue lives in this process: enqueue prints the job id and the URI
    assert (
        rag_cli(["enqueue", "--file", RAG_YAML, "--profile", "offline", "--group", "hr", md]) == 0
    )
    assert capsys.readouterr().out.split() == ["1", (CORPUS / "leave-policy.md").as_uri()]
    # a fresh process has an empty in-memory queue: the worker finds nothing and stops
    assert rag_cli(["worker", "--file", RAG_YAML, "--profile", "offline"]) == 0
    assert capsys.readouterr().out == ""
