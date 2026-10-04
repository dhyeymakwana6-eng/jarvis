from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.memory import Memory
from app.crud.memory import semantic_search_memories


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

    # Trigram similarity thresholds for lexical_match (fallback when
    # no embedding is available).
    UPDATE_THRESHOLD = 0.85
    SIMILAR_THRESHOLD = 0.6

    # Cosine distance thresholds for semantic_match (nomic-embed-text,
    # document prefix). Measured: paraphrases ("I work at X" / "I am
    # employed by X") ~0.03; related-but-different facts ("I work at
    # X" / "I work at Y", "I like hiking" / "I enjoy hiking in the
    # mountains") ~0.08-0.18.
    UPDATE_DISTANCE = 0.05
    SIMILAR_DISTANCE = 0.20

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
                # Case-insensitive equality. Not ilike(): % and _ in the
                # content would act as wildcards and match other memories.
                func.lower(Memory.content)
                == memory_data["content"].strip().lower()
            )
            .first()
        )

    def semantic_match(
        self,
        db: Session,
        user_id: int,
        embedding: list[float]
    ) -> Optional[tuple[Memory, float]]:
        """
        Nearest existing memory by embedding, as (memory, cosine
        distance), or None if nothing is within SIMILAR_DISTANCE.
        Searches across categories: the keyword classifier can put
        the same fact in different categories.
        """
        matches = semantic_search_memories(
            db,
            user_id,
            embedding,
            limit=1,
            max_distance=self.SIMILAR_DISTANCE
        )

        return matches[0] if matches else None

    def lexical_match(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> Optional[tuple[Memory, float]]:
        """
        Fallback for when no embedding is available: find similar
        memories using Postgres trigram similarity (pg_trgm). Catches
        reworded or partially overlapping text, but not paraphrases
        with entirely different wording.
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
        memory_data: dict,
        embedding: Optional[list[float]] = None
    ) -> DeduplicationResult:
        """
        Decide what to do with this memory candidate. Uses embeddings
        when available, trigram similarity otherwise.
        """
        existing = self.exact_match(db, user_id, memory_data)

        if existing:
            return DeduplicationResult(
                decision=DeduplicationDecision.DUPLICATE,
                existing_memory_id=existing.id,
                confidence=1.0,
                reason="Identical content already stored in this category."
            )

        if embedding is not None:
            return self._decide_semantic(db, user_id, embedding)

        return self._decide_lexical(db, user_id, memory_data)

    def _decide_semantic(
        self,
        db: Session,
        user_id: int,
        embedding: list[float]
    ) -> DeduplicationResult:
        match = self.semantic_match(db, user_id, embedding)

        if match is None:
            return self._new("No semantically similar memory found.")

        memory, distance = match
        confidence = round(1 - distance, 3)

        if distance <= self.UPDATE_DISTANCE:
            return DeduplicationResult(
                decision=DeduplicationDecision.UPDATE,
                existing_memory_id=memory.id,
                confidence=confidence,
                reason=(
                    f"Same fact already stored (distance={distance:.3f}); "
                    "updating it with the newer wording."
                )
            )

        return DeduplicationResult(
            decision=DeduplicationDecision.SIMILAR,
            existing_memory_id=memory.id,
            confidence=confidence,
            reason=(
                f"Related memory found (distance={distance:.3f}) but it "
                "may be a different fact; not merging."
            )
        )

    def _decide_lexical(
        self,
        db: Session,
        user_id: int,
        memory_data: dict
    ) -> DeduplicationResult:
        match = self.lexical_match(db, user_id, memory_data)

        if match is None:
            return self._new("No exact or similar match found.")

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

    @staticmethod
    def _new(reason: str) -> DeduplicationResult:
        # CONFLICT detection (e.g. "I work at X" vs "I work at Y")
        # needs meaning comparison beyond distance -- such pairs land
        # in the SIMILAR band. Planned with an LLM-based check later.
        return DeduplicationResult(
            decision=DeduplicationDecision.NEW,
            existing_memory_id=None,
            confidence=1.0,
            reason=reason
        )

    def process(
        self,
        db: Session,
        user_id: int,
        memory_data: dict,
        embedding: Optional[list[float]] = None
    ) -> DeduplicationResult:
        return self.determine_action(db, user_id, memory_data, embedding)