from sqlalchemy.orm import Session

from app.models.memory import Memory


def create_memory(
    db: Session,
    category: str,
    content: str,
    importance: int
):
    memory = Memory(
        category=category,
        content=content,
        importance=importance
    )

    db.add(memory)
    db.commit()
    db.refresh(memory)

    return memory


def get_memories(db: Session):
    return db.query(Memory).all()


def get_memory(db: Session, memory_id: int):
    return (
        db.query(Memory)
        .filter(Memory.id == memory_id)
        .first()
    )


def delete_memory(db: Session, memory_id: int):
    memory = (
        db.query(Memory)
        .filter(Memory.id == memory_id)
        .first()
    )

    if memory:
        db.delete(memory)
        db.commit()

    return memory


def search_memories(
    db: Session,
    query: str
):
    return (
        db.query(Memory)
        .filter(
            Memory.content.ilike(f"%{query}%")
        )
        .all()
    )