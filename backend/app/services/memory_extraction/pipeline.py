from sqlalchemy.orm import Session

from app.crud.memory import create_memory, update_memory
from .extractor import MemoryExtractor
from .classifier import MemoryClassifier
from .scorer import MemoryScorer
from .deduplicator import MemoryDeduplicator, DeduplicationDecision


class MemoryPipeline:
    """
    Coordinates memory extraction processing.
    """

    def __init__(self, db: Session):
        self.db = db

        self.extractor = MemoryExtractor()
        self.classifier = MemoryClassifier()
        self.scorer = MemoryScorer()
        self.deduplicator = MemoryDeduplicator()

    def process(self, message: str):
        candidates = self.extractor.extract(message)

        memories = []

        for candidate in candidates:
            memory_type = self.classifier.classify(candidate)
            importance = self.scorer.score(candidate)

            memory_data = {
                "content": candidate,
                "category": memory_type,
                "importance": importance,
            }

            deduplication_result = self.deduplicator.process(
                self.db,
                memory_data
            )

            memory_data["deduplication"] = (
                deduplication_result.model_dump()
            )

            memories.append(memory_data)

        return memories

    def process_and_store(self, message: str):
        memories = self.process(message)

        stored_memories = []

        for memory in memories:
            decision = memory["deduplication"]["decision"]
            importance_scaled = int(memory["importance"] * 100)

            if decision == DeduplicationDecision.NEW:
                stored = create_memory(
                    db=self.db,
                    category=memory["category"],
                    content=memory["content"],
                    importance=importance_scaled
                )
                stored_memories.append(stored)

            elif decision == DeduplicationDecision.UPDATE:
                existing_id = memory["deduplication"]["existing_memory_id"]
                stored = update_memory(
                    db=self.db,
                    memory_id=existing_id,
                    category=memory["category"],
                    content=memory["content"],
                    importance=importance_scaled
                )
                stored_memories.append(stored)

            # DUPLICATE / SIMILAR / CONFLICT: don't store anything new.
            # SIMILAR and CONFLICT aren't produced yet (semantic_match
            # isn't implemented), but skipping storage here keeps the
            # behavior correct once that lands, rather than silently
            # storing duplicates.

        return stored_memories