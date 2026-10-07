from datetime import datetime, timedelta, timezone

from app.crud.task import create_task, update_task
from app.crud.tracking import create_project
from app.services.task_service import TaskService
from tests.conftest import TEST_USER_ID


IST = timezone(timedelta(hours=5, minutes=30), "IST")
NOW = datetime(2026, 10, 7, 10, 30, tzinfo=IST)  # Wednesday


def at(days=0, hour=0, minute=0):
    return NOW.replace(hour=hour, minute=minute) + timedelta(days=days)


def test_context_groups_tasks_by_urgency(db):
    jarvis = create_project(db, TEST_USER_ID, "Jarvis")
    create_task(db, TEST_USER_ID, "Submit report", due_at=at(-2, 18))
    create_task(db, TEST_USER_ID, "Call mom", due_at=at(0, 17), remind_at=at(0, 16, 30), priority="high")
    create_task(db, TEST_USER_ID, "Earlier today", due_at=at(0, 9))
    create_task(db, TEST_USER_ID, "Add reminders", due_at=at(2, 18), project_id=jarvis.id)
    create_task(db, TEST_USER_ID, "Renew passport", due_at=at(40, 12))
    create_task(db, TEST_USER_ID, "Buy milk", priority="low")
    create_task(db, TEST_USER_ID, "Read paper", priority="high")
    create_task(db, TEST_USER_ID, "Cancelled one", status="cancelled")

    context = TaskService.to_context(db, TEST_USER_ID, NOW)

    assert context == (
        "Now: Wednesday 07 October 2026, 10:30 (IST)\n"
        "\n"
        "OVERDUE:\n"
        "- Submit report (was due Mon 05 Oct 18:00, 1 day ago)\n"
        "- Earlier today (was due 09:00, 1 hour ago)\n"
        "\n"
        "Due today:\n"
        "- [high] Call mom (due 17:00; reminder 16:30)\n"
        "\n"
        "Due in the next 7 days:\n"
        "- Add reminders (due Fri 09 Oct 18:00; project: Jarvis)\n"
        "\n"
        "Due later:\n"
        "- Renew passport (due Mon 16 Nov 12:00)\n"
        "\n"
        "No due date:\n"
        "- [high] Read paper\n"
        "- [low] Buy milk"
    )


def test_times_are_shown_in_local_time(db):
    # Stored in UTC, shown in the user's timezone: 11:30 UTC = 17:00 IST.
    create_task(db, TEST_USER_ID, "Standup", due_at=datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc))

    assert "- Standup (due 17:00)" in TaskService.to_context(db, TEST_USER_ID, NOW)


def test_delivered_and_past_reminders_are_not_listed(db):
    delivered = create_task(db, TEST_USER_ID, "Delivered", remind_at=at(0, 12))
    delivered.reminded_at = NOW
    create_task(db, TEST_USER_ID, "Missed", remind_at=at(0, 9))
    db.commit()

    context = TaskService.to_context(db, TEST_USER_ID, NOW)

    assert "- Delivered\n" in context + "\n"
    assert "- Missed" in context and "reminder" not in context


def test_sections_are_capped(db, monkeypatch):
    monkeypatch.setattr(TaskService, "SECTION_LIMIT", 2)
    for i in range(5):
        create_task(db, TEST_USER_ID, f"Task {i}")

    context = TaskService.to_context(db, TEST_USER_ID, NOW)

    assert "- Task 0\n- Task 1\n- (+3 more)" in context


def test_done_today_is_listed(db):
    task = create_task(db, TEST_USER_ID, "Ship v1")
    update_task(db, TEST_USER_ID, task.id, {"status": "done"})
    task.completed_at = at(0, 9)
    db.commit()

    assert "Done today:\n- Ship v1" in TaskService.to_context(db, TEST_USER_ID, NOW)


def test_no_context_without_tasks(db):
    assert TaskService.to_context(db, TEST_USER_ID, NOW) is None


def test_chat_prompt_includes_tasks(db, monkeypatch):
    from app.services.memory_service import MemoryService

    sent = {}

    class Reply:
        class message:
            content = "Call mom."

    def fake_chat(**kwargs):
        sent.update(kwargs)
        return Reply

    monkeypatch.setattr("app.services.llm_service.chat", fake_chat)
    monkeypatch.setattr("app.services.memory_service.EmbeddingService.try_generate_query", lambda q: None)
    create_task(db, TEST_USER_ID, "Call mom")

    MemoryService.generate_response(db, TEST_USER_ID, "what should I do today")

    system = sent["messages"][0]["content"]
    assert "\n\nTasks:\nNow: " in system
    assert "- Call mom" in system
