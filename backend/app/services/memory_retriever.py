import re

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
            .filter(or_(*conditions))
            .order_by(Memory.importance.desc())
            .all()
        )

        return memories