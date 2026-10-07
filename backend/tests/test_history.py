from datetime import datetime, timedelta, timezone

from app.models.conversation import Conversation
from app.services.conversation_history import ConversationHistory
from app.services.llm_service import LLMService

from tests.conftest import TEST_USER_ID


NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def add_turn(db, minutes_ago, user, assistant="ok"):
    turn = Conversation(
        user_id=TEST_USER_ID,
        user_message=user,
        assistant_message=assistant,
        created_at=NOW - timedelta(minutes=minutes_ago)
    )
    db.add(turn)
    db.commit()
    return turn


def test_session_stops_at_idle_gap(db):
    add_turn(db, 120, "old session")
    add_turn(db, 20, "first")
    add_turn(db, 5, "second")

    session = ConversationHistory.current_session(db, TEST_USER_ID, now=NOW)

    assert [t.user_message for t in session] == ["first", "second"]


def test_no_session_after_long_silence(db):
    add_turn(db, 45, "an hour ago")

    assert ConversationHistory.current_session(db, TEST_USER_ID, now=NOW) == []


def test_session_keeps_only_latest_turns(db):
    for minute in range(10, 0, -1):
        add_turn(db, minute, f"turn {minute}")

    session = ConversationHistory.current_session(db, TEST_USER_ID, limit=3, now=NOW)

    assert [t.user_message for t in session] == ["turn 3", "turn 2", "turn 1"]


def test_prompt_history_drops_oldest_over_size_cap(db, monkeypatch):
    monkeypatch.setattr(ConversationHistory, "MAX_CHARS", 25)
    add_turn(db, 3, "aaaaaaaaaa", "aaaaaaaaaa")
    add_turn(db, 2, "bbbbbbbbbb", "bb")
    add_turn(db, 1, "cc", "cc")

    assert ConversationHistory.for_prompt(db, TEST_USER_ID, now=NOW) == [
        ("bbbbbbbbbb", "bb"),
        ("cc", "cc"),
    ]


def test_llm_receives_history_between_system_and_query(monkeypatch):
    sent = {}

    class Reply:
        class message:
            content = "The second one is Rust."

    def fake_chat(**kwargs):
        sent.update(kwargs)
        return Reply

    monkeypatch.setattr("app.services.llm_service.chat", fake_chat)

    LLMService().generate_response(
        "and the second one?",
        "none",
        history=[("Name two languages", "Python and Rust.")]
    )

    assert [(m["role"], m["content"]) for m in sent["messages"][1:]] == [
        ("user", "Name two languages"),
        ("assistant", "Python and Rust."),
        ("user", "and the second one?"),
    ]
    assert sent["messages"][0]["role"] == "system"


def test_history_endpoint_returns_current_session(client, db, monkeypatch):
    monkeypatch.setattr("app.api.memory.DEFAULT_USER_ID", TEST_USER_ID)
    # Server time, not NOW: the endpoint compares against the real clock.
    real_now = datetime.now(timezone.utc)
    db.add(Conversation(user_id=TEST_USER_ID, user_message="hi", assistant_message="hello",
                        created_at=real_now - timedelta(minutes=2)))
    db.commit()

    body = client.get("/memory/chat/history").json()

    assert [(t["user_message"], t["assistant_message"]) for t in body] == [("hi", "hello")]


def test_chat_response_includes_session_history(db, monkeypatch):
    from app.services.memory_service import MemoryService

    sent = {}

    class Reply:
        class message:
            content = "Rust."

    def fake_chat(**kwargs):
        sent.update(kwargs)
        return Reply

    monkeypatch.setattr("app.services.llm_service.chat", fake_chat)
    monkeypatch.setattr("app.services.memory_service.EmbeddingService.try_generate_query", lambda q: None)
    db.add(Conversation(user_id=TEST_USER_ID, user_message="Name two languages",
                        assistant_message="Python and Rust.",
                        created_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    db.commit()

    MemoryService.generate_response(db, TEST_USER_ID, "and the second one?")

    assert [m["content"] for m in sent["messages"][1:]] == [
        "Name two languages", "Python and Rust.", "and the second one?"
    ]
