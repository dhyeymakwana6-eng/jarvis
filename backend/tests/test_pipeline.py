from app.models.conversation import Conversation
from app.services.llm_service import LLMUnavailableError
from app.services.memory_extraction.pipeline import MemoryPipeline

from tests.conftest import TEST_USER_ID


def test_llm_outage_leaves_conversation_for_retry(db, monkeypatch):
    def down(*args, **kwargs):
        raise LLMUnavailableError("Ollama is down")

    # Run the background task on the rolled-back test session.
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr("app.services.memory_extraction.pipeline.SessionLocal", lambda: db)
    monkeypatch.setattr("app.services.memory_extraction.pipeline.EmbeddingService.try_generate", lambda text: None)
    monkeypatch.setattr("app.services.tracking_service.LLMService.generate_structured", down)

    conversation = Conversation(
        user_id=TEST_USER_ID,
        user_message="I'm going to learn Rust.",
        assistant_message="Nice."
    )
    db.add(conversation)
    db.commit()

    MemoryPipeline.process_conversation(conversation.id)

    db.refresh(conversation)
    assert conversation.memories_processed is False
