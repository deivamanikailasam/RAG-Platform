"""A throwaway Postgres with the REAL migrations, for tests that need one (Steps 31 and 36).

    from rag_core.testing.postgres import apply_migrations
    apply_migrations("postgres://postgres:…@127.0.0.1:55432/rag_test")

Creates the pgvector extension and the rag schema, then applies every `-- migrate:up` section of
infra/db/rag/migrations in order (what dbmate does in the real platform). The vector size is
shrunk to `dimensions` so tests can use a small offline embedder, and halfvec falls back to
vector on pgvector older than 0.7.
"""

from __future__ import annotations

import os
from pathlib import Path

# libs/rag-core/src/rag_core/testing/postgres.py -> the repository root
REPO = Path(__file__).resolve().parents[5]
MIGRATIONS = REPO / "infra/db/rag/migrations"


def pgvector_version(dsn: str) -> tuple[int, int]:
    import psycopg

    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    if row is None:
        raise RuntimeError("the vector extension isn't installed in this database")
    major, minor = (int(x) for x in str(row[0]).split(".")[:2])
    return major, minor


def apply_migrations(dsn: str, dimensions: int = 64, directory: Path | None = None) -> None:
    """Apply every migration's up section to an EMPTY database (as its owner)."""
    import psycopg

    folder = directory or Path(os.environ.get("RAG_MIGRATIONS_DIR", str(MIGRATIONS)))
    files = sorted(folder.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"no migrations in {folder}")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE SCHEMA IF NOT EXISTS rag")
    halfvec = pgvector_version(dsn) >= (0, 7)  # halfvec arrived in pgvector 0.7
    with psycopg.connect(dsn, autocommit=True) as conn:
        for f in files:  # Step 11's tables, then Step 31's changes, then Step 36's, …
            up = f.read_text().split("-- migrate:down")[0]
            if halfvec:
                up = up.replace("halfvec(1024)", f"halfvec({dimensions})")
            else:
                up = up.replace("halfvec_cosine_ops", "vector_cosine_ops").replace(
                    "halfvec(1024)", f"vector({dimensions})"
                )
            conn.execute(up)
