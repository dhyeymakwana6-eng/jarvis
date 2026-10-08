from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.recurrence import RecurrenceError, describe, next_occurrence, normalize, pin
from app.crud.task import acknowledge_reminder, create_task, get_task, get_tasks, update_task
from app.services.agent_service import AgentService
from tests.conftest import TEST_USER_ID

LONDON = ZoneInfo("Europe/London")


@pytest.fixture(autouse=True)
def london(monkeypatch):
    # A timezone with DST, so wall-clock handling is exercised.
    monkeypatch.setenv("JARVIS_TIMEZONE", "Europe/London")


def at(*args):
    return datetime(*args, tzinfo=LONDON)


# ---------- Rules ----------

@pytest.mark.parametrize("rule, normal", [
    ("Daily", "daily"),
    ("days:1", "daily"),
    ("days: 3", "days:3"),
    ("weekly: Thu, mon, monday", "weekly:mon,thu"),
    ("monthly:07", "monthly:7"),
])
def test_normalize(rule, normal):
    assert normalize(rule) == normal


@pytest.mark.parametrize("rule", ["hourly", "weekly:xyz", "days:0", "monthly:32", ""])
def test_normalize_rejects_unknown_rules(rule):
    with pytest.raises(RecurrenceError, match="use daily, weekdays"):
        normalize(rule)


@pytest.mark.parametrize("rule, after, expected", [
    ("daily", at(2026, 10, 8, 16), at(2026, 10, 9, 16)),
    ("daily", at(2026, 10, 12, 9), at(2026, 10, 12, 16)),            # missed days skipped
    ("weekdays", at(2026, 10, 9, 16), at(2026, 10, 12, 16)),         # Fri -> Mon
    ("weekly:mon,thu", at(2026, 10, 8, 16), at(2026, 10, 12, 16)),
    ("weekly:thu", at(2026, 10, 8, 16), at(2026, 10, 15, 16)),
    ("days:3", at(2026, 10, 8, 16), at(2026, 10, 11, 16)),
    ("days:3", at(2026, 10, 20, 0), at(2026, 10, 20, 16)),
    ("daily", at(2026, 10, 24, 16), at(2026, 10, 25, 16)),           # clocks go back, still 16:00
])
def test_next_occurrence(rule, after, expected):
    anchor = at(2026, 10, 8, 16) if after < at(2026, 10, 24) else at(2026, 10, 24, 16)

    assert next_occurrence(rule, anchor, after) == expected


def test_monthly_keeps_its_day_through_short_months():
    first = at(2026, 1, 31, 9)
    rule = pin("monthly", first)

    february = next_occurrence(rule, first, first)
    march = next_occurrence(rule, february, february)

    assert rule == "monthly:31"
    assert (february.date(), march.date()) == (at(2026, 2, 28).date(), at(2026, 3, 31).date())


def test_describe():
    assert [describe(r) for r in ["daily", "weekdays", "weekly:mon,wed,fri", "days:2", "monthly:1"]] == [
        "every day", "every weekday", "every Mon, Wed and Fri", "every 2 days", "every month on the 1st"
    ]


# ---------- Tasks ----------

def soon(hours=1):
    """A whole-minute time ahead of now, in London."""
    return (datetime.now(LONDON) + timedelta(hours=hours)).replace(second=0, microsecond=0)


def test_completing_a_repeating_task_creates_the_next_one(db):
    due = soon()
    task = create_task(db, TEST_USER_ID, "Water plants", due_at=due, remind_at=due - timedelta(minutes=30), recurrence="days:2")

    update_task(db, TEST_USER_ID, task.id, {"status": "done"})

    assert get_task(db, TEST_USER_ID, task.id).status == "done"
    (upcoming,) = get_tasks(db, TEST_USER_ID, status="todo")
    assert upcoming.title == "Water plants" and upcoming.recurrence == "days:2"
    assert upcoming.due_at == due + timedelta(days=2)
    assert upcoming.remind_at == upcoming.due_at - timedelta(minutes=30)


def test_cancelling_stops_the_repeat(db):
    task = create_task(db, TEST_USER_ID, "Gym", remind_at=soon(), recurrence="weekdays")

    update_task(db, TEST_USER_ID, task.id, {"status": "cancelled"})

    assert get_tasks(db, TEST_USER_ID, status="todo") == []


def test_dismissing_a_repeating_reminder_moves_it_on(db):
    fired = soon(-2)
    task = create_task(db, TEST_USER_ID, "Stretch", remind_at=fired, recurrence="daily")

    acknowledge_reminder(db, TEST_USER_ID, task.id, datetime.now(timezone.utc))

    task = get_task(db, TEST_USER_ID, task.id)
    assert task.status == "todo" and task.reminded_at is None
    assert task.remind_at == fired + timedelta(days=1)


def test_dismissing_a_repeating_task_with_a_deadline_just_acknowledges(db):
    task = create_task(db, TEST_USER_ID, "Rent", due_at=soon(48), remind_at=soon(-1), recurrence="monthly")

    acknowledge_reminder(db, TEST_USER_ID, task.id, datetime.now(timezone.utc))

    assert get_task(db, TEST_USER_ID, task.id).reminded_at is not None


def test_a_repeating_task_without_a_time_gets_a_morning_reminder(db):
    task = create_task(db, TEST_USER_ID, "Journal", recurrence="daily")

    local = task.remind_at.astimezone(LONDON)
    assert (local.hour, local.minute) == (9, 0)
    assert timedelta(0) < task.remind_at - datetime.now(timezone.utc) <= timedelta(days=1)


def test_weekly_and_monthly_are_pinned(db):
    due = at(2026, 12, 31, 18)
    task = create_task(db, TEST_USER_ID, "Review", due_at=due, recurrence="monthly")
    weekly = create_task(db, TEST_USER_ID, "Plan week", due_at=at(2026, 12, 27, 18), recurrence="weekly")

    assert task.recurrence == "monthly:31" and weekly.recurrence == "weekly:sun"


def test_api_validates_and_returns_recurrence(client):
    bad = client.post("/tasks", json={"title": "x", "recurrence": "hourly"})
    assert bad.status_code == 422

    created = client.post("/tasks", json={
        "title": "Stand-up", "remind_at": soon().isoformat(), "recurrence": "Weekdays"
    }).json()
    assert created["recurrence"] == "weekdays"

    stopped = client.patch(f"/tasks/{created['id']}", json={"recurrence": None}).json()
    assert stopped["recurrence"] is None


def test_agent_creates_and_completes_repeating_tasks(db):
    now = datetime.now(LONDON)
    remind = soon(2)

    action, _ = AgentService.run_tool(db, TEST_USER_ID, "create_task", {
        "title": "Stretch", "remind_at": remind.strftime("%Y-%m-%d %H:%M"), "repeat": "daily"
    }, now)
    assert action.status == "done" and "repeats every day" in action.summary

    bad, result = AgentService.run_tool(db, TEST_USER_ID, "create_task", {"title": "Nap", "repeat": "hourly"}, now)
    assert bad.status == "failed" and "use daily, weekdays" in result

    task = get_tasks(db, TEST_USER_ID, status="todo")[0]
    done, _ = AgentService.run_tool(db, TEST_USER_ID, "update_task", {"id": task.id, "status": "done"}, now)
    assert done.summary.startswith("Completed “Stretch”; next one ")

    upcoming = get_tasks(db, TEST_USER_ID, status="todo")[0]
    stop, _ = AgentService.run_tool(db, TEST_USER_ID, "update_task", {"id": upcoming.id, "repeat": "none"}, now)
    assert stop.summary == "Stopped repeating “Stretch”"
    assert get_task(db, TEST_USER_ID, upcoming.id).recurrence is None


def test_a_weekday_rule_starts_on_its_first_allowed_day(db):
    # "Every Mon and Thu" with a time put on some other day: moved to the
    # first allowed day from now, same time.
    now = datetime.now(LONDON)
    off_day = next(
        (now + timedelta(days=d)).replace(hour=20, minute=0, second=0, microsecond=0)
        for d in range(1, 8)
        if (now + timedelta(days=d)).weekday() not in (0, 3)
    )

    task = create_task(db, TEST_USER_ID, "Trash", remind_at=off_day, recurrence="weekly:mon,thu")

    local = task.remind_at.astimezone(LONDON)
    assert local.weekday() in (0, 3) and (local.hour, local.minute) == (20, 0)
    assert datetime.now(timezone.utc) < task.remind_at <= datetime.now(timezone.utc) + timedelta(days=7)


def test_an_explicit_later_start_is_kept(db):
    start = (datetime.now(LONDON) + timedelta(days=30)).replace(hour=9, minute=0, second=0, microsecond=0)
    while start.weekday() != 0:
        start += timedelta(days=1)

    task = create_task(db, TEST_USER_ID, "Course", remind_at=start, recurrence="weekly:mon")

    assert task.remind_at == start
