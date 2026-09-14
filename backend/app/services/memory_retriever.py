import re
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.memory import Memory


class MemoryRetriever:

    @staticmethod
    def retrieve(
        db: Session,
        query: str
    ):

        query_words = re.findall(
            r"\w+",
            query.lower()
        )

        conditions = []

        for word in query_words:

            if len(word) <= 2:
                continue

            conditions.append(
                Memory.content.ilike(
                    f"%{word}%"
                )
            )

        if not conditions:
            return []

        memories = (
            db.query(Memory)
            .filter(
                Memory.is_deleted == False,
                or_(*conditions)
            )
            .order_by(Memory.importance.desc())
            .all()
        )

        MemoryRetriever._record_access(db, memories)

        return memories

    @staticmethod
    def _record_access(db: Session, memories: list[Memory]):
        """
        Bumps access_count and last_accessed_at for every memory
        that was retrieved, so importance decay (in MemoryRanker)
        has real access data to work with.
        """
        if not memories:
            return

        now = datetime.now(timezone.utc)

        for memory in memories:
            memory.access_count += 1
            memory.last_accessed_at = now

        db.commit()