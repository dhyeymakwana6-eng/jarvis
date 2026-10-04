from sqlalchemy.orm import Session

from app.crud.memory import create_memory, update_memory
from app.services.embedding_service import EmbeddingService
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

    def process(self, user_id: int, message: str):
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

            # Embedded once here and reused for dedup and storage.
            embedding = EmbeddingService.try_generate(candidate)

            deduplication_result = self.deduplicator.process(
                self.db,
                user_id,
                memory_data,
                embedding
            )

            memory_data["embedding"] = embedding

            memory_data["deduplication"] = (
                deduplication_result.model_dump()
            )

            memories.append(memory_data)

        return memories

    def process_and_store(self, user_id: int, message: str):
        memories = self.process(user_id, message)

        stored_memories = []

        for memory in memories:
            decision = memory["deduplication"]["decision"]
            importance_scaled = int(memory["importance"] * 100)

            # SIMILAR means "related but possibly a different fact"
            # (e.g. a new employer), so it's stored rather than dropped.
            if decision in (
                DeduplicationDecision.NEW,
                DeduplicationDecision.SIMILAR
            ):
                stored = create_memory(
                    db=self.db,
                    user_id=user_id,
                    category=memory["category"],
                    content=memory["content"],
                    importance=importance_scaled,
                    embedding=memory["embedding"]
                )
                stored_memories.append(stored)

            elif decision == DeduplicationDecision.UPDATE:
                existing_id = memory["deduplication"]["existing_memory_id"]
                stored = update_memory(
                    db=self.db,
                    user_id=user_id,
                    memory_id=existing_id,
                    category=memory["category"],
                    content=memory["content"],
                    importance=importance_scaled,
                    embedding=memory["embedding"]
                )
                stored_memories.append(stored)

            # DUPLICATE / CONFLICT: don't store anything new.
            # CONFLICT isn't produced yet, but skipping storage here
            # keeps the behavior correct once it lands, rather than
            # silently storing contradictory memories.

        return stored_memories