from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import func
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

    # Trigram similarity thresholds for semantic_match.
    UPDATE_THRESHOLD = 0.85
    SIMILAR_THRESHOLD = 0.6

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
                Memory.is_deleted == False,
                Memory.content.ilike(memory_data["content"].strip())
            )
            .first()
        )

    def semantic_match(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> Optional[tuple[Memory, float]]:
        """
        Task 3: find memories that are *similar* (not identical) using
        Postgres trigram similarity (pg_trgm). This is a lexical
        approximation, not true semantic/embedding-based matching --
        it catches reworded or partially overlapping text, but won't
        catch paraphrases with entirely different wording. True
        embedding-based semantic search is planned for a later phase.
        """
        content = memory_data["content"].strip()

        similarity_expr = func.similarity(Memory.content, content)

        result = (
            db.query(Memory, similarity_expr.label("sim"))
            .filter(
                Memory.user_id == user_id,
                Memory.category == memory_data["category"],
                Memory.is_deleted == False,
                similarity_expr >= self.SIMILAR_THRESHOLD
            )
            .order_by(similarity_expr.desc())
            .first()
        )

        if result is None:
            return None

        memory, score = result
        return memory, float(score)

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

        match = self.semantic_match(db, user_id, memory_data)

        if match:
            memory, score = match

            if score >= self.UPDATE_THRESHOLD:
                return DeduplicationResult(
                    decision=DeduplicationDecision.UPDATE,
                    existing_memory_id=memory.id,
                    confidence=score,
                    reason=(
                        f"Highly similar memory found (similarity={score:.2f}); "
                        "treating as an update to the existing memory."
                    )
                )

            return DeduplicationResult(
                decision=DeduplicationDecision.SIMILAR,
                existing_memory_id=memory.id,
                confidence=score,
                reason=(
                    f"Similar memory found (similarity={score:.2f}) but below "
                    "the update threshold; not auto-merging."
                )
            )

        # CONFLICT detection (e.g. contradictory facts) requires actual
        # meaning comparison, not just text similarity -- not
        # implemented yet. Planned for a later phase alongside
        # embeddings/semantic search.
        return DeduplicationResult(
            decision=DeduplicationDecision.NEW,
            existing_memory_id=None,
            confidence=1.0,
            reason="No exact or similar match found."
        )

    def process(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> DeduplicationResult:
        return self.determine_action(db, user_id, memory_data)