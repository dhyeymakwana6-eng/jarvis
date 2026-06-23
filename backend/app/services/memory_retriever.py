from sqlalchemy.orm import Session

from app.models.memory import Memory


class MemoryRetriever:

    @staticmethod
    def retrieve(db: Session, query: str):
        memories = (
            db.query(Memory)
            .filter(Memory.content.ilike(f"%{query}%"))
            .order_by(Memory.importance.desc())
            .all()
        )

        return memories