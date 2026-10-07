from datetime import datetime, timedelta, timezone

from app.crud.task import create_task, get_tasks, update_task
from app.crud.tracking import create_project
from tests.conftest import TEST_USER_ID


AT_5PM = datetime(2026, 10, 7, 17, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_tasks_sort_by_due_then_priority_with_undated_last(db):
    create_task(db, TEST_USER_ID, "undated")
    create_task(db, TEST_USER_ID, "later", due_at=AT_5PM + timedelta(days=1))
    create_task(db, TEST_USER_ID, "now normal", due_at=AT_5PM)
    create_task(db, TEST_USER_ID, "now high", due_at=AT_5PM, priority="high")

    assert [t.title for t in get_tasks(db, TEST_USER_ID)] == [
        "now high", "now normal", "later", "undated"
    ]


def test_done_sets_completed_at_and_reopening_clears_it(db):
    task = create_task(db, TEST_USER_ID, "Buy milk")

    update_task(db, TEST_USER_ID, task.id, {"status": "done"})
    assert task.completed_at is not None

    update_task(db, TEST_USER_ID, task.id, {"status": "todo"})
    assert task.completed_at is None


def test_rescheduling_a_reminder_rearms_it(db):
    task = create_task(db, TEST_USER_ID, "Call mom", remind_at=AT_5PM)
    task.reminded_at = AT_5PM
    db.commit()

    update_task(db, TEST_USER_ID, task.id, {"title": "Call mom back"})
    assert task.reminded_at is not None  # unrelated edit: still delivered

    update_task(db, TEST_USER_ID, task.id, {"remind_at": AT_5PM + timedelta(hours=1)})
    assert task.reminded_at is None


def test_tasks_api(client):
    project = client.post("/projects", json={"name": "Jarvis"}).json()

    task = client.post("/tasks", json={
        "title": "Add reminders",
        "project_id": project["id"],
        "priority": "high",
        "due_at": "2026-10-10T18:00:00+05:30",
        "remind_at": "2026-10-10T17:00:00+05:30",
    }).json()
    assert task["status"] == "todo"
    # Same instant, whatever timezone the DB session reports it in.
    assert datetime.fromisoformat(task["remind_at"]) == datetime(2026, 10, 10, 11, 30, tzinfo=timezone.utc)

    assert client.get("/tasks?due_before=2026-10-11T00:00:00Z").json()[0]["id"] == task["id"]
    assert client.get("/tasks?due_before=2026-10-09T00:00:00Z").json() == []

    done = client.patch(f"/tasks/{task['id']}", json={"status": "done"}).json()
    assert done["completed_at"]
    assert client.get("/tasks?status=done").json()[0]["id"] == task["id"]

    # Validation: unknown project, bad status, naive datetime, missing task.
    assert client.post("/tasks", json={"title": "x", "project_id": 424242}).status_code == 422
    assert client.post("/tasks", json={"title": "x", "status": "finished"}).status_code == 422
    assert client.post("/tasks", json={"title": "x", "due_at": "2026-10-10T18:00:00"}).status_code == 422
    assert client.patch("/tasks/424242", json={"status": "done"}).status_code == 404

    # Deleting the project keeps the task but unlinks it.
    client.delete(f"/projects/{project['id']}")
    assert client.get(f"/tasks/{task['id']}").json()["project_id"] is None

    assert client.delete(f"/tasks/{task['id']}").status_code == 200
    assert client.get("/tasks").json() == []


def test_reminders_api_due_dismiss_snooze_and_done(client, db):
    from app.models.task import Task

    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=5)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()

    due = client.post("/tasks", json={"title": "Call mom", "remind_at": past}).json()
    later = client.post("/tasks", json={"title": "Later", "remind_at": future}).json()
    client.post("/tasks", json={"title": "No reminder"})
    done = client.post("/tasks", json={"title": "Done already", "remind_at": past, "status": "done"}).json()

    assert [t["id"] for t in client.get("/reminders/due").json()] == [due["id"]]

    # Dismiss: handled, not shown again.
    dismissed = client.post(f"/reminders/{due['id']}/dismiss").json()
    assert dismissed["reminded_at"]
    assert client.get("/reminders/due").json() == []

    # Snooze: rescheduled from now and re-armed.
    snoozed = client.post(f"/reminders/{due['id']}/snooze", json={"minutes": 10}).json()
    assert snoozed["reminded_at"] is None
    assert datetime.fromisoformat(snoozed["remind_at"]) > now + timedelta(minutes=9)

    # Done via the tasks API also stops it from being due.
    task = db.get(Task, due["id"])
    task.remind_at = now - timedelta(minutes=1)
    db.commit()
    assert len(client.get("/reminders/due").json()) == 1
    client.patch(f"/tasks/{due['id']}", json={"status": "done"})
    assert client.get("/reminders/due").json() == []

    assert client.post("/reminders/424242/dismiss").status_code == 404
    assert client.post(f"/reminders/{later['id']}/snooze", json={"minutes": 0}).status_code == 422
    assert done["status"] == "done"
