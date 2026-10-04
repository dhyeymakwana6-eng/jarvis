from sqlalchemy.orm import Session

from app.models.memory import Memory
from app.models.user import User
from app.services.embedding_service import EmbeddingService


def _mark_profile_stale(db: Session, user_id: int):
    # Committed by the caller together with the memory change.
    user = db.get(User, user_id)

    if user is not None:
        user.profile_stale = True


def create_memory(
    db: Session,
    user_id: int,
    category: str,
    content: str,
    importance: int,
    embedding: list[float] | None = None
):
    # Callers that already embedded the content (e.g. the extraction
    # pipeline, for deduplication) pass it in to avoid a second call.
    if embedding is None:
        embedding = EmbeddingService.try_generate(content)

    memory = Memory(
        user_id=user_id,
        category=category,
        content=content,
        importance=importance,
        embedding=embedding
    )

    db.add(memory)
    _mark_profile_stale(db, user_id)
    db.commit()
    db.refresh(memory)

    return memory


def get_memories(
    db: Session,
    user_id: int,
    category: str = None,
    min_importance: int = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False
):
    query = db.query(Memory).filter(Memory.user_id == user_id)

    if not include_deleted:
        query = query.filter(Memory.is_deleted == False)

    if category:
        query = query.filter(Memory.category == category)

    if min_importance is not None:
        query = query.filter(Memory.importance >= min_importance)

    return (
        query
        .order_by(Memory.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_memory(
    db: Session,
    user_id: int,
    memory_id: int,
    include_deleted: bool = False
):
    query = db.query(Memory).filter(
        Memory.id == memory_id,
        Memory.user_id == user_id
    )

    if not include_deleted:
        query = query.filter(Memory.is_deleted == False)

    return query.first()


def update_memory(
    db: Session,
    user_id: int,
    memory_id: int,
    category: str,
    content: str,
    importance: int,
    embedding: list[float] | None = None
):
    memory = get_memory(db, user_id, memory_id)

    if memory:
        if embedding is not None:
            memory.embedding = embedding
        elif content != memory.content or memory.embedding is None:
            memory.embedding = EmbeddingService.try_generate(content)

        memory.category = category
        memory.content = content
        memory.importance = importance
        _mark_profile_stale(db, user_id)
        db.commit()
        db.refresh(memory)

    return memory


def delete_memory(db: Session, user_id: int, memory_id: int):
    memory = get_memory(db, user_id, memory_id)

    if memory:
        memory.is_deleted = True
        _mark_profile_stale(db, user_id)
        db.commit()
        db.refresh(memory)

    return memory


def supersede_memory(
    db: Session,
    user_id: int,
    memory_id: int,
    superseded_by_id: int
):
    """
    Retires a memory that a newer one contradicts. It's soft-deleted
    (so retrieval skips it) and linked to its replacement; restoring
    it clears the link.
    """
    memory = get_memory(db, user_id, memory_id)

    if memory:
        memory.is_deleted = True
        memory.superseded_by_id = superseded_by_id
        _mark_profile_stale(db, user_id)
        db.commit()
        db.refresh(memory)

    return memory


def restore_memory(db: Session, user_id: int, memory_id: int):
    memory = (
        db.query(Memory)
        .filter(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.is_deleted == True
        )
        .first()
    )

    if memory:
        memory.is_deleted = False
        memory.superseded_by_id = None
        _mark_profile_stale(db, user_id)
        db.commit()
        db.refresh(memory)

    return memory


def _escape_like(text: str) -> str:
    # Treat % and _ in user input literally instead of as wildcards.
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def search_memories(
    db: Session,
    user_id: int,
    query: str
):
    return (
        db.query(Memory)
        .filter(
            Memory.user_id == user_id,
            Memory.content.ilike(f"%{_escape_like(query)}%", escape="\\"),
            Memory.is_deleted == False
        )
        .all()
    )


def semantic_search_memories(
    db: Session,
    user_id: int,
    query_embedding: list[float],
    limit: int = 10,
    max_distance: float | None = None
) -> list[tuple[Memory, float]]:
    """
    Finds memories nearest to the query embedding using pgvector's
    cosine distance operator (<=>). Returns (memory, distance) pairs,
    nearest first. Lower distance = more similar (0 = identical,
    1 = unrelated, 2 = opposite).
    """
    distance = Memory.embedding.cosine_distance(query_embedding)

    query = (
        db.query(Memory, distance.label("distance"))
        .filter(
            Memory.user_id == user_id,
            Memory.is_deleted == False,
            Memory.embedding.isnot(None)
        )
    )

    if max_distance is not None:
        query = query.filter(distance <= max_distance)

    return [
        (memory, float(memory_distance))
        for memory, memory_distance
        in query.order_by(distance).limit(limit).all()
    ]
