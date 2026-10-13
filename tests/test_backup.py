"""Backups and restore drills (Step 36), against a real Postgres with pgvector."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backup", ROOT / "scripts/backup.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["backup"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def source_db() -> tuple[str, str]:
    admin = os.environ.get("RAG_TEST_PGVECTOR_DSN")
    if not admin or not shutil.which("pg_dump"):
        pytest.skip("needs RAG_TEST_PGVECTOR_DSN and pg_dump/pg_restore on PATH")
    import psycopg
    from psycopg.conninfo import make_conninfo

    from rag_core import config
    from rag_core import evaluate as ev
    from rag_core.testing.postgres import apply_migrations, pgvector_version

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS rag_backup_src WITH (FORCE)")
        conn.execute("CREATE DATABASE rag_backup_src")
    dsn = make_conninfo(admin, dbname="rag_backup_src")
    apply_migrations(dsn, 64, ROOT / "infra/db/rag/migrations")
    os.environ["RAG_BACKUP_TEST_DSN"] = dsn
    store = {
        "dsn_env": "RAG_BACKUP_TEST_DSN",
        "collection": "handbook",
        "dimensions": 64,
        # halfvec needs pgvector >= 0.7 (apply_migrations falls back to vector the same way)
        "vector_type": "halfvec" if pgvector_version(dsn) >= (0, 7) else "vector",
    }
    c = config.load(ROOT / "rag.yaml", "offline", env={})
    c = type(c)({**dict(c.config), "embedder": {"use": "hashing", "dimensions": 64},
                 "vector_store": {"use": "pgvector", **store}, "keyword_index": {"use": "postgres-fts", **store},
                 "manifest": {"use": "postgres", **store}}, "backup-test")  # fmt: skip
    ds = ROOT / "examples/eval/handbook.yaml"
    ev.ingest_corpus(c, ev.load_dataset(ds), ds.parent)
    return admin, dsn


def test_backup_and_restore_drill(source_db: tuple[str, str], tmp_path: Path) -> None:
    admin, dsn = source_db
    b = load()
    receipt = b.backup(dsn, tmp_path / "rag.dump")
    assert receipt["counts"]["rag.documents"] == 17
    assert receipt["counts"]["rag.chunks"] > 17
    assert receipt["counts"]["rag.ingest_manifest"] == 17
    result = b.restore_test(tmp_path / "rag.dump", admin)
    assert result["ok"], result["problems"]
    assert result["counts"] == receipt["counts"]


def test_restore_drill_catches_a_damaged_backup(source_db: tuple[str, str], tmp_path: Path) -> None:
    admin, dsn = source_db
    b = load()
    b.backup(dsn, tmp_path / "rag.dump")
    with (tmp_path / "rag.dump").open("ab") as f:
        f.write(b"\x00")  # one byte appended
    result = b.restore_test(tmp_path / "rag.dump", admin)
    assert not result["ok"]
    assert "checksum differs" in result["problems"][0]


def test_backup_uploads_dump_and_receipt(source_db: tuple[str, str], tmp_path: Path) -> None:
    _, dsn = source_db
    uploads: list[tuple[str, str, str]] = []

    class S3:
        def upload_file(self, path: str, bucket: str, key: str) -> None:
            uploads.append((Path(path).name, bucket, key))

    s3: Any = S3()
    r = load().backup(dsn, tmp_path / "rag.dump", "s3://rag-backups/daily/", s3_client=s3)
    assert uploads == [
        ("rag.dump", "rag-backups", "daily/rag.dump"),
        ("rag.dump.json", "rag-backups", "daily/rag.dump.json"),
    ]
    assert r["uploaded"] == "s3://rag-backups/daily/rag.dump"
