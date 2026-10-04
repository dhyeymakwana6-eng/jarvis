from sqlalchemy.orm import Session

from app.services.memory_retriever import MemoryRetriever
from app.services.memory_ranker import MemoryRanker
from app.services.context_builder import ContextBuilder
from app.services.llm_service import LLMService
from app.services.embedding_service import EmbeddingService

class MemoryService:

    # Max memories injected into the LLM prompt.
    CONTEXT_LIMIT = 10

    @staticmethod
    def get_relevant_memories(
        db: Session,
        user_id: int,
        query: str
    ):

        keyword_matches = MemoryRetriever.retrieve(
            db,
            user_id,
            query,
            record_access=False
        )

        query_embedding = EmbeddingService.try_generate_query(query)

        if query_embedding is not None:
            semantic_matches = MemoryRetriever.retrieve_semantic(
                db,
                user_id,
                query_embedding
            )

            ranked_memories = MemoryRanker.rank_hybrid(
                semantic_matches,
                keyword_matches,
                query,
                top_k=MemoryService.CONTEXT_LIMIT
            )
        else:
            # Ollama unavailable: fall back to keyword-only ranking.
            ranked_memories = MemoryRanker.rank(
                keyword_matches,
                query,
                top_k=MemoryService.CONTEXT_LIMIT
            )

        # Only memories that actually make it into the context count
        # as accessed, not every candidate the retriever returned.
        MemoryRetriever.record_access(db, ranked_memories)

        return ranked_memories

    @staticmethod
    def get_context(
        db: Session,
        user_id: int,
        query: str
    ):

        ranked_memories = MemoryService.get_relevant_memories(
            db,
            user_id,
            query
        )

        return ContextBuilder.build(
            ranked_memories
        )

    @staticmethod
    def generate_response(
        db: Session,
        user_id: int,
        query: str
    ):

        context = MemoryService.get_context(
            db,
            user_id,
            query
        )

        llm = LLMService()

        return llm.generate_response(
            user_query=query,
            memory_context=context
        )
