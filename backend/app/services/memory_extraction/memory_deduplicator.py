from enum import Enum
from uuid import UUID
from typing import Optional

from pydantic import BaseModel


class DeduplicationDecision(str, Enum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    UPDATE = "UPDATE"
    SIMILAR = "SIMILAR"
    CONFLICT = "CONFLICT"


class DeduplicationResult(BaseModel):
    decision: DeduplicationDecision
    existing_memory_id: Optional[UUID] = None
    confidence: float
    reason: str


class MemoryDeduplicator:
    def __init__(self):
        pass

    async def exact_match(
        self,
        user_id: UUID,
        memory
    ):
        """
        Task 2 implementation.
        """
        return None

    async def semantic_match(
        self,
        user_id: UUID,
        memory
    ):
        """
        Task 3 implementation.
        """
        return None

    async def determine_action(
        self,
        user_id: UUID,
        memory
    ) -> DeduplicationResult:
        """
        Task 4 implementation.
        """

        return DeduplicationResult(
            decision=DeduplicationDecision.NEW,
            existing_memory_id=None,
            confidence=1.0,
            reason="Deduplication not implemented yet."
        )

    async def process(
        self,
        user_id: UUID,
        memory
    ) -> DeduplicationResult:
        return await self.determine_action(
            user_id=user_id,
            memory=memory
        )