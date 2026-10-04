"""
Brings an existing database up to date with the current models.

create_tables.py only creates missing tables; it never adds columns
to tables that already exist. Every statement here is idempotent, so
this is safe to re-run. Run from backend/:

    python -m app.models.migrate            # schema + embed missing
    python -m app.models.migrate --reembed  # also redo all embeddings

Use --reembed after changing the embedding model or prefixes.

Replace with Alembic once the schema starts changing more often.
"""
import sys

from sqlalchemy import text

from app.database.connection import engine
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
    with engine.begin() as conn:
        for statement in STATEMENTS:
            conn.execute(text(statement))

    print("Schema up to date.")

    with engine.begin() as conn:
        backfill_embeddings(conn, reembed="--reembed" in sys.argv)
