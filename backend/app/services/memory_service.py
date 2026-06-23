from sqlalchemy.orm import Session

from app.services.memory_retriever import MemoryRetriever
from app.services.memory_ranker import MemoryRanker
from app.services.context_builder import ContextBuilder


class MemoryService:

    @staticmethod
    def get_relevant_memories(
        db: Session,
        query: str
    ):

        memories = MemoryRetriever.retrieve(
            db,
            query
        )

        ranked_memories = MemoryRanker.rank(
            memories,
            query
        )

        return ranked_memories

    @staticmethod
    def get_context(
        db: Session,
        query: str
    ):

        memories = MemoryRetriever.retrieve(
            db,
            query
        )

        ranked_memories = MemoryRanker.rank(
            memories,
            query
        )

        context = ContextBuilder.build(
            ranked_memories
        )

        return context