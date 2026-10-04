import re
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.memory import Memory
from app.crud.memory import semantic_search_memories
from app.services.query_terms import query_terms


class MemoryRetriever:

    # Upper bound on candidates pulled from the DB before ranking.
    MAX_CANDIDATES = 100

    # Cosine distance cutoff for semantic matches (nomic-embed-text
    # with search prefixes). Calibrated on a small sample: relevant
    # memories landed at ~0.30-0.45, unrelated ones at ~0.49+. Revisit
    # as real memories accumulate.
    MAX_SEMANTIC_DISTANCE = 0.48

    @staticmethod
    def retrieve(
        db: Session,
        user_id: int,
        query: str,
        record_access: bool = True
    ):

        conditions = []

        for word in query_terms(query):

            # Postgres regex word boundaries (\m start, \M end), so
            # "art" doesn't match "start".
            conditions.append(
                Memory.content.op("~*")(
                    rf"\m{re.escape(word)}\M"
                )
            )

        if not conditions:
            return []

        memories = (
            db.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.is_deleted == False,
                or_(*conditions)
            )
            .order_by(Memory.importance.desc())
            .limit(MemoryRetriever.MAX_CANDIDATES)
            .all()
        )

        if record_access:
            MemoryRetriever.record_access(db, memories)

        return memories

    @staticmethod
    def retrieve_semantic(
        db: Session,
        user_id: int,
        query_embedding: list[float],
        limit: int = 20
    ) -> list[tuple[Memory, float]]:
        """
        Nearest memories by embedding, as (memory, distance) pairs.
        Anything farther than MAX_SEMANTIC_DISTANCE is treated as
        unrelated and dropped.
        """
        return semantic_search_memories(
            db,
            user_id,
            query_embedding,
            limit=limit,
            max_distance=MemoryRetriever.MAX_SEMANTIC_DISTANCE
        )

    @staticmethod
    def record_access(db: Session, memories: list[Memory]):
        """
        Bumps access_count and last_accessed_at for the given
        memories, so importance decay (in MemoryRanker) has real
        access data to work with.
        """
        if not memories:
            return

        now = datetime.now(timezone.utc)

        for memory in memories:
            memory.access_count += 1
            memory.last_accessed_at = now

        db.commit()
