from datetime import datetime, timedelta, timezone

import pytest

from app.crud.task import create_task, get_tasks
from app.crud.tracking import create_project
from app.services.task_service import NewTask, TaskChange, TaskService
from app.services.tracking_service import TrackingChanges, TrackingService, NewProject
from tests.conftest import TEST_USER_ID


IST = timezone(timedelta(hours=5, minutes=30), "IST")
NOW = datetime(2026, 10, 7, 18, 0, tzinfo=IST)  # Wednesday evening


def changes(**lists):
    return TrackingChanges(
        reasoning="test",
        new_projects=lists.get("new_projects", []),
        new_goals=[],
        project_updates=[],
        goal_updates=[],
        new_tasks=lists.get("new_tasks", []),
        task_updates=lists.get("task_updates", []),
    )


def local(text):
    return TaskService.parse_local(text, NOW)


@pytest.mark.parametrize("text, expected", [
    ("2026-10-08 17:00", datetime(2026, 10, 8, 17, 0, tzinfo=IST)),
    ("2026-10-08T17:00", datetime(2026, 10, 8, 17, 0, tzinfo=IST)),
    ("2026-10-09", datetime(2026, 10, 9, 9, 0, tzinfo=IST)),  # day only -> 09:00
    ("2026-10-08T11:30:00+00:00", datetime(2026, 10, 8, 17, 0, tzinfo=IST)),  # offset respected
    ("tomorrow at 5", None),
    ("", None),
    (None, None),
])
def test_parse_local(text, expected):
    assert local(text) == expected


def test_reminder_already_passed_today_moves_to_tomorrow_and_stale_ones_drop(db):
    log = TrackingService.apply(db, TEST_USER_ID, changes(new_tasks=[
        NewTask(title="Call mom", remind_at="2026-10-07 17:00"),     # 1h ago -> tomorrow
        NewTask(title="Pay rent", remind_at="2026-09-01 10:00"),     # weeks ago -> dropped
        NewTask(title="Take pills", remind_at="2026-10-07 18:20"),   # ahead -> kept
    ]), NOW)

    tasks = {t.title: t for t in get_tasks(db, TEST_USER_ID)}
    assert tasks["Call mom"].remind_at == datetime(2026, 10, 8, 17, 0, tzinfo=IST)
    assert tasks["Pay rent"].remind_at is None
    assert tasks["Take pills"].remind_at == datetime(2026, 10, 7, 18, 20, tzinfo=IST)
    assert len(log) == 3


def test_new_tasks_link_projects_and_skip_duplicates(db):
    jarvis = create_project(db, TEST_USER_ID, "Jarvis")
    create_task(db, TEST_USER_ID, "Buy milk")

    TrackingService.apply(db, TEST_USER_ID, changes(
        new_projects=[NewProject(name="Garden")],
        new_tasks=[
            NewTask(title="buy milk"),                                   # duplicate
            NewTask(title="Add voice", project_id=jarvis.id, priority="high"),
            NewTask(title="Water plants", project_name="garden", due_at="2026-10-08"),
            NewTask(title="Ghost", project_id=424242),                   # unknown project
        ],
    ), NOW)

    tasks = {t.title: t for t in get_tasks(db, TEST_USER_ID)}
    assert set(tasks) == {"Buy milk", "Add voice", "Water plants", "Ghost"}
    assert tasks["Add voice"].project_id == jarvis.id and tasks["Add voice"].priority == "high"
    assert tasks["Water plants"].project_id is not None
    assert tasks["Water plants"].due_at == datetime(2026, 10, 8, 9, 0, tzinfo=IST)
    assert tasks["Ghost"].project_id is None


def test_task_updates_complete_cancel_and_reschedule(db):
    report = create_task(db, TEST_USER_ID, "Submit report")
    dentist = create_task(db, TEST_USER_ID, "Dentist")
    call = create_task(db, TEST_USER_ID, "Call mom", remind_at=NOW + timedelta(minutes=30))

    log = TrackingService.apply(db, TEST_USER_ID, changes(task_updates=[
        TaskChange(id=report.id, status="done"),
        TaskChange(id=dentist.id, status="cancelled"),
        TaskChange(id=call.id, remind_at="2026-10-07 20:00"),
        TaskChange(id=424242, status="done"),                            # not the user's
        TaskChange(id=call.id, due_at="soon"),                           # bad time: no-op
    ]), NOW)

    assert report.status == "done" and report.completed_at is not None
    assert dentist.status == "cancelled"
    assert call.remind_at == datetime(2026, 10, 7, 20, 0, tzinfo=IST)
    assert len(log) == 3


@pytest.mark.parametrize("message, question", [
    ("What am I working on?", True),
    ("Did I call mom?", True),
    ("Can you remind me to call mom at 5?", False),
    ("could you add buy milk to my list?", False),
    ("Please remind me tomorrow?", False),
    ("Remind me to call mom at 5", False),
    ("I finished the report.", False),
])
def test_requests_phrased_as_questions_still_reach_the_llm(message, question):
    assert TrackingService.is_question(message) is question


def test_state_text_lists_open_tasks_in_local_time(db):
    create_task(db, TEST_USER_ID, "Call mom", remind_at=datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc))
    create_task(db, TEST_USER_ID, "Old", status="done")

    state = TrackingService.state_text(db, TEST_USER_ID, NOW)

    assert state.startswith("Now: 2026-10-07 18:00 (Wednesday)")
    assert "Tasks:\n- [" in state and "] Call mom (reminder 2026-10-07 17:00)" in state
    assert "Old" not in state


def test_reminder_request_goes_through_llm_end_to_end(db, monkeypatch):
    seen = {}

    def fake_structured(self, system_prompt, user_content, response_model):
        seen["content"] = user_content
        return changes(new_tasks=[NewTask(title="Call mom", remind_at="2026-10-07 19:00")])

    monkeypatch.setattr("app.services.tracking_service.LLMService.generate_structured", fake_structured)

    log = TrackingService.process_message(db, TEST_USER_ID, "Can you remind me to call mom at 7?", NOW)

    assert seen["content"].endswith("User message: Can you remind me to call mom at 7?")
    assert log and get_tasks(db, TEST_USER_ID)[0].remind_at == datetime(2026, 10, 7, 19, 0, tzinfo=IST)
