from sqlalchemy.orm import Session

from app.crud.memory import create_memory
from .extractor import MemoryExtractor
from .classifier import MemoryClassifier
from .scorer import MemoryScorer
from .deduplicator import MemoryDeduplicator


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
            created_memory = create_memory(
                db=self.db,
                category=memory["category"],
                content=memory["content"],
                importance=int(memory["importance"] * 100)
            )

            stored_memories.append(created_memory)

        return stored_memories