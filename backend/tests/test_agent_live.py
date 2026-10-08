"""
The real local model choosing tools. Slow (a few seconds per case) and
needs Ollama, so it's opt-in:

    JARVIS_LIVE_LLM=1 python -m pytest tests/test_agent_live.py
"""
import os

import pytest

from app.crud.task import create_task, get_tasks
from app.services.memory_service import MemoryService
from app.services.tracking_service import TrackingService
from tests.conftest import TEST_USER_ID

pytestmark = pytest.mark.skipif(
    os.getenv("JARVIS_LIVE_LLM") != "1",
    reason="set JARVIS_LIVE_LLM=1 to run against the real model"
)


@pytest.fixture
def chat(db, monkeypatch):
    # No memories or history: only the tasks matter here.
    monkeypatch.setattr("app.services.memory_service.EmbeddingService.try_generate_query", lambda q: None)
    monkeypatch.setattr("app.services.memory_service.ConversationHistory.for_prompt", lambda db, user_id: [])

    def send(query, mode="jarvis"):
        actions = []
        reply = MemoryService.generate_response(db, TEST_USER_ID, query, mode, actions=actions)
        print(f"\n{query!r} -> {[(a.tool, a.status, a.summary) for a in actions]}\n  {reply!r}")
        return reply, actions

    return send


def titles(db, status="todo"):
    return {task.title.lower() for task in get_tasks(db, TEST_USER_ID, status=status)}


@pytest.mark.parametrize("mode", ["jarvis", "ultron"])
def test_creates_a_reminder(db, chat, mode):
    _, actions = chat("Remind me to call mom at 6 pm", mode)

    assert [a.tool for a in actions] == ["create_task"]
    task = get_tasks(db, TEST_USER_ID, status="todo")[0]
    assert "mom" in task.title.lower() and task.remind_at.astimezone().hour == 18


def test_completes_a_listed_task(db, chat):
    create_task(db, TEST_USER_ID, "Submit report")

    chat("I submitted the report")

    assert "submit report" in titles(db, "done")


def test_two_changes_in_one_message(db, chat):
    create_task(db, TEST_USER_ID, "Submit report")
    message = "I sent the report. Also remind me to email Raj tomorrow morning"

    _, actions = chat(message)
    # Then the background tracker, as after every chat turn: it catches
    # what the agent missed without duplicating what it did.
    TrackingService.process_message(
        db, TEST_USER_ID, message,
        agent_task_ids={a.task_id for a in actions if a.task_id} if actions else None
    )

    assert "submit report" in titles(db, "done")
    assert len([title for title in titles(db) if "raj" in title]) == 1


def test_delete_asks_first(db, chat):
    create_task(db, TEST_USER_ID, "Old idea")

    _, actions = chat("Delete the old idea task")

    assert [(a.tool, a.status) for a in actions] == [("delete_task", "pending")]
    assert "old idea" in titles(db)


@pytest.mark.parametrize("query", ["What's the capital of France?", "How are you today?"])
def test_questions_dont_act(db, chat, query):
    create_task(db, TEST_USER_ID, "Buy milk")

    _, actions = chat(query)

    assert actions == []
