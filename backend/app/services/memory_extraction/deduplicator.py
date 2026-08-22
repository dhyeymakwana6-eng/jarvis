from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.memory import Memory


class DeduplicationDecision(str, Enum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    UPDATE = "UPDATE"
    SIMILAR = "SIMILAR"
    CONFLICT = "CONFLICT"


class DeduplicationResult(BaseModel):
    decision: DeduplicationDecision
    existing_memory_id: Optional[int] = None
    confidence: float
    reason: str


class MemoryDeduplicator:
    """
    Decides whether a newly extracted memory candidate is new,
    a duplicate, an update to an existing memory, or a conflict.

    NOTE: This runs against plain SQLAlchemy Sessions (sync), matching
    the rest of the codebase, so these methods are intentionally sync
    rather than async.

    NOTE: Matching is scoped per-user via user_id, so one user's
    memories never dedupe against another user's.
    """

    def __init__(self):
        pass

    def exact_match(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> Optional[Memory]:
        """
        Task 2: look for an existing memory with identical content
        in the same category, scoped to this user.
        """
        return (
            db.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.category == memory_data["category"],
                Memory.content.ilike(memory_data["content"].strip())
            )
            .first()
        )

    def semantic_match(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> Optional[Memory]:
        """
        Task 3: find memories that are *similar* (not identical) using
        embeddings/semantic similarity. Not implemented yet -- requires
        an embedding model and vector similarity search, planned for
        a later phase.
        """
        return None

    def determine_action(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> DeduplicationResult:
        """
        Task 4: decide what to do with this memory candidate.
        """
        existing = self.exact_match(db, user_id, memory_data)

        if existing:
            return DeduplicationResult(
                decision=DeduplicationDecision.DUPLICATE,
                existing_memory_id=existing.id,
                confidence=1.0,
                reason="Identical content already stored in this category."
            )

        # Semantic matching not implemented yet, so anything that
        # isn't an exact match is treated as new for now.
        return DeduplicationResult(
            decision=DeduplicationDecision.NEW,
            existing_memory_id=None,
            confidence=1.0,
            reason="No exact match found."
        )

    def process(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> DeduplicationResult:
        return self.determine_action(db, user_id, memory_data)