"""
Brings an existing database up to date with the current models.

create_tables.py only creates missing tables; it never adds columns
to tables that already exist. This script does both: it creates
missing tables, then adds missing columns. Every statement here is idempotent, so
this is safe to re-run. Run from backend/:

    python -m app.models.migrate            # schema + embed missing
    python -m app.models.migrate --reembed  # also redo all embeddings

Use --reembed after changing the embedding model or prefixes.

Replace with Alembic once the schema starts changing more often.
"""
import sys

from sqlalchemy import text

from app.database.base import Base
from app.database.connection import engine, SessionLocal
import app.models  # noqa: F401  (registers every model on Base)
from app.database.seed import ensure_default_user
from app.services.embedding_service import EmbeddingService


STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(768)",
    "CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw "
    "ON memories USING hnsw (embedding vector_cosine_ops)",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_by_id INTEGER REFERENCES memories(id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile JSONB",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_updated_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_stale BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS memories_processed BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT",
    "ALTER TABLE projects ALTER COLUMN status SET DEFAULT 'active'",
    "ALTER TABLE projects ALTER COLUMN next_action DROP NOT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE goals ADD COLUMN IF NOT EXISTS description TEXT",
    "ALTER TABLE goals ALTER COLUMN status SET DEFAULT 'active'",
    "ALTER TABLE goals ADD COLUMN IF NOT EXISTS target_date DATE",
    "ALTER TABLE goals ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE goals ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
    "ALTER TABLE goals ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false",
]


def backfill_embeddings(conn, reembed: bool = False):
    where = "" if reembed else " WHERE embedding IS NULL"

    rows = conn.execute(
        text(f"SELECT id, content FROM memories{where}")
    ).all()

    filled = 0

    for memory_id, content in rows:
        embedding = EmbeddingService.try_generate(content)

        if embedding is None:
            continue

        conn.execute(
            text("UPDATE memories SET embedding = :embedding WHERE id = :id"),
            {"embedding": str(embedding), "id": memory_id}
        )
        filled += 1

    print(f"Embedded {filled}/{len(rows)} memories.")


if __name__ == "__main__":
    # New tables (e.g. tasks); existing ones are left alone.
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        for statement in STATEMENTS:
            conn.execute(text(statement))

    with SessionLocal() as db:
        ensure_default_user(db)

    print("Schema up to date.")

    with engine.begin() as conn:
        backfill_embeddings(conn, reembed="--reembed" in sys.argv)
