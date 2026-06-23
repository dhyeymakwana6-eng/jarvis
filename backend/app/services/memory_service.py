from sqlalchemy.orm import Session

from app.services.memory_retriever import MemoryRetriever
from app.services.memory_ranker import MemoryRanker
from app.services.context_builder import ContextBuilder
from app.services.llm_service import LLMService

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
        
    @staticmethod
    def generate_response(
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

        llm = LLMService()

        response = llm.generate_response(
            user_query=query,
            memory_context=context
        )

        return response
    

