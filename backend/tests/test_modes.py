from app.models.conversation import Conversation
from app.services.llm_service import LLMService
from tests.conftest import TEST_USER_ID


def test_jarvis_prompt_unchanged_and_ultron_shares_the_rules():
    jarvis = LLMService.system_prompt("jarvis")
    ultron = LLMService.system_prompt("ultron")

    assert jarvis.startswith("You are Jarvis, a personal AI assistant.\n\nRules:\n- Never roleplay fictional characters.\n")
    assert ultron.startswith("You are Ultron")
    assert "Never roleplay" not in ultron
    assert ultron.endswith(LLMService.RULES) and jarvis.endswith(LLMService.RULES)
    # Unknown modes fall back to Jarvis.
    assert LLMService.system_prompt("hal") == jarvis


def test_chat_uses_the_requested_persona_and_records_it(client, db, monkeypatch):
    sent = []

    class Reply:
        class message:
            content = "Done. Try to keep up."

    def fake_chat(**kwargs):
        sent.append(kwargs["messages"][0]["content"])
        return Reply

    monkeypatch.setattr("app.api.memory.DEFAULT_USER_ID", TEST_USER_ID)
    monkeypatch.setattr("app.services.llm_service.chat", fake_chat)
    monkeypatch.setattr("app.services.memory_service.EmbeddingService.try_generate_query", lambda q: None)
    # The background extraction opens its own (real) DB session; skip it.
    monkeypatch.setattr("app.api.memory.MemoryPipeline.process_conversation", lambda conversation_id: None)

    assert client.post("/memory/chat", json={"query": "hi", "mode": "ultron"}).status_code == 200
    assert client.post("/memory/chat", json={"query": "hello"}).status_code == 200
    assert client.post("/memory/chat", json={"query": "x", "mode": "hal"}).status_code == 422

    assert sent[0].startswith("You are Ultron") and sent[1].startswith("You are Jarvis")

    turns = db.query(Conversation).filter(Conversation.user_id == TEST_USER_ID).order_by(Conversation.id).all()
    assert [t.mode for t in turns] == ["ultron", "jarvis"]

    history = client.get("/memory/chat/history").json()
    assert [t["mode"] for t in history] == ["ultron", "jarvis"]
