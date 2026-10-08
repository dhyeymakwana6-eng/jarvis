from datetime import date, datetime, timedelta, timezone

import pytest

from app.crud.task import create_task, update_task
from app.crud.tracking import create_goal
from app.models.conversation import Conversation
from app.models.routine import RoutineRun
from app.services.llm_service import LLMService, LLMUnavailableError
from app.services.routine_service import RoutineService
from tests.conftest import TEST_USER_ID


IST = timezone(timedelta(hours=5, minutes=30), "IST")
MORNING = datetime(2026, 10, 8, 8, 5, tzinfo=IST)  # Thursday


def at(days=0, hour=0, minute=0):
    return MORNING.replace(hour=hour, minute=minute) + timedelta(days=days)


@pytest.fixture
def llm(monkeypatch):
    """Records what the LLM is asked and answers with a fixed text."""
    calls = []

    def fake(self, system, user):
        calls.append((system, user))
        return "Good morning. Two things today."

    monkeypatch.setattr(LLMService, "generate_text", fake)
    return calls


# ---------- Schedule ----------

def test_routines_are_due_from_their_time_for_a_few_hours(monkeypatch):
    monkeypatch.setenv("JARVIS_MORNING_BRIEFING", "07:30")

    assert not RoutineService.is_due("morning", at(0, 7, 29))
    assert RoutineService.is_due("morning", at(0, 7, 30))
    assert RoutineService.is_due("morning", at(0, 11, 29))
    assert not RoutineService.is_due("morning", at(0, 11, 30))
    assert not RoutineService.is_due("evening", at(0, 20, 59))
    assert RoutineService.is_due("evening", at(0, 23, 59))


def test_routines_can_be_turned_off_or_misconfigured(monkeypatch):
    monkeypatch.setenv("JARVIS_EVENING_REVIEW", "off")
    monkeypatch.setenv("JARVIS_MORNING_BRIEFING", "25:00")

    assert RoutineService.scheduled_time("evening") is None
    assert not RoutineService.is_due("evening", at(0, 21, 30))
    assert RoutineService.scheduled_time("morning").strftime("%H:%M") == "08:00"


# ---------- Content ----------

def test_morning_facts(db):
    create_task(db, TEST_USER_ID, "Submit report", due_at=at(-1, 18))
    create_task(db, TEST_USER_ID, "Call mom", remind_at=at(0, 18), priority="high")
    create_task(db, TEST_USER_ID, "Stretch", remind_at=at(0, 16), recurrence="daily")
    create_task(db, TEST_USER_ID, "Next week", due_at=at(6, 12))
    create_goal(db, TEST_USER_ID, "Deploy to Pi", target_date=date(2026, 10, 10), progress=40)
    create_goal(db, TEST_USER_ID, "Far goal", target_date=date(2026, 12, 1))

    facts = RoutineService.facts(db, TEST_USER_ID, "morning", MORNING)

    assert facts == (
        "Now: Thursday 08 October, 08:05\n\n"
        "Overdue:\n- Submit report (was due yesterday 18:00)\n\n"
        "Today:\n- Stretch (reminder 16:00, repeats every day)\n- Call mom (high priority) (reminder 18:00)\n\n"
        "Goal deadlines:\n- Deploy to Pi (40% done, due Saturday 10 October)"
    )


def test_evening_facts(db):
    done = create_task(db, TEST_USER_ID, "Ship v1", due_at=at(0, 12))
    update_task(db, TEST_USER_ID, done.id, {"status": "done"})
    done.completed_at = at(0, 15)
    db.commit()
    create_task(db, TEST_USER_ID, "Email Raj", due_at=at(0, 17))
    create_task(db, TEST_USER_ID, "Dentist", remind_at=at(1, 9, 30))

    facts = RoutineService.facts(db, TEST_USER_ID, "evening", at(0, 21))

    assert "Finished today:\n- Ship v1" in facts
    assert "Still open from today:\n- Email Raj (was due 17:00)" in facts
    assert "Tomorrow:\n- Dentist (reminder tomorrow 09:30)" in facts


def test_empty_days_say_so(db):
    assert "Today: nothing scheduled" in RoutineService.facts(db, TEST_USER_ID, "morning", MORNING)
    evening = RoutineService.facts(db, TEST_USER_ID, "evening", at(0, 21))
    assert "Finished today: nothing marked done" in evening and "Tomorrow: nothing scheduled" in evening


def test_compose_uses_the_persona_and_falls_back_to_facts(llm, monkeypatch):
    assert RoutineService.compose("morning", "Today: nothing scheduled", "ultron") == "Good morning. Two things today."
    system, user = llm[0]
    assert system.startswith("You are Ultron") and "morning briefing" in system and user == "Today: nothing scheduled"

    def down(self, system, user):
        raise LLMUnavailableError("ollama down")

    monkeypatch.setattr(LLMService, "generate_text", down)
    assert RoutineService.compose("evening", "Tomorrow: nothing scheduled", "jarvis") == (
        "Evening review.\n\nTomorrow: nothing scheduled"
    )


# ---------- Running ----------

def test_run_due_writes_each_routine_once_a_day(db, llm, monkeypatch):
    monkeypatch.setenv("JARVIS_MORNING_BRIEFING", "08:00")
    db.add(Conversation(user_id=TEST_USER_ID, user_message="hi", assistant_message="hi", mode="ultron"))
    db.commit()

    assert RoutineService.run_due(db, TEST_USER_ID, at(0, 7, 59)) == []

    (run,) = RoutineService.run_due(db, TEST_USER_ID, MORNING)
    assert (run.kind, run.run_date, run.mode, run.text) == ("morning", date(2026, 10, 8), "ultron", "Good morning. Two things today.")

    assert RoutineService.run_due(db, TEST_USER_ID, MORNING + timedelta(minutes=5)) == []
    assert len(llm) == 1

    # Tomorrow is a new day.
    assert len(RoutineService.run_due(db, TEST_USER_ID, MORNING + timedelta(days=1))) == 1


def test_dismissed_routines_leave_the_due_list_until_run_again(db, llm):
    run = RoutineService.run(db, TEST_USER_ID, "evening", at(0, 21))
    assert RoutineService.pending(db, TEST_USER_ID, at(0, 21, 5)) == [run]

    RoutineService.dismiss(db, TEST_USER_ID, run.id)
    assert RoutineService.pending(db, TEST_USER_ID, at(0, 21, 5)) == []

    again = RoutineService.run(db, TEST_USER_ID, "evening", at(0, 22))
    assert again.id == run.id and again.dismissed_at is None
    assert db.query(RoutineRun).filter_by(user_id=TEST_USER_ID).count() == 1


def test_routines_api(client, db, llm, monkeypatch):
    monkeypatch.setattr("app.api.routine.DEFAULT_USER_ID", TEST_USER_ID)
    monkeypatch.setenv("JARVIS_EVENING_REVIEW", "off")

    settings = client.get("/routines").json()
    assert {s["kind"]: s["time"] for s in settings} == {"morning": "08:00", "evening": None}

    run = client.post("/routines/morning/run").json()
    assert run["kind"] == "morning" and run["text"] == "Good morning. Two things today."

    assert [r["id"] for r in client.get("/routines/due").json()] == [run["id"]]
    assert client.post(f"/routines/runs/{run['id']}/dismiss").status_code == 200
    assert client.get("/routines/due").json() == []

    assert client.post("/routines/runs/987654321/dismiss").status_code == 404
    assert client.post("/routines/lunch/run").status_code == 422
