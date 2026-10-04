from datetime import date

from app.crud.tracking import create_project, create_goal, get_projects, get_goals, update_goal
from app.services.tracking_service import (
    TrackingService,
    TrackingChanges,
    NewProject,
    NewGoal,
    ProjectChange,
    GoalChange,
)
from tests.conftest import TEST_USER_ID

TODAY = date(2026, 10, 4)


def changes(**lists):
    return TrackingChanges(
        reasoning="test",
        new_projects=lists.get("new_projects", []),
        new_goals=lists.get("new_goals", []),
        project_updates=lists.get("project_updates", []),
        goal_updates=lists.get("goal_updates", []),
    )


def test_apply_creates_project_and_links_goal_by_new_project_name(db):
    TrackingService.apply(db, TEST_USER_ID, changes(
        new_projects=[NewProject(name="Guitar")],
        new_goals=[NewGoal(title="Play a full song", project_name="guitar", target_date="2026-12-31")],
    ))

    [project] = get_projects(db, TEST_USER_ID)
    [goal] = get_goals(db, TEST_USER_ID)

    assert goal.project_id == project.id
    assert goal.target_date == date(2026, 12, 31)


def test_apply_skips_existing_names_unknown_ids_and_bad_dates(db):
    project = create_project(db, TEST_USER_ID, "Jarvis")
    create_goal(db, TEST_USER_ID, "Learn Rust")

    log = TrackingService.apply(db, TEST_USER_ID, changes(
        new_projects=[NewProject(name="jarvis")],
        new_goals=[
            NewGoal(title="learn rust"),
            NewGoal(title="Ship v1", project_id=424242, target_date="end of month"),
        ],
        project_updates=[ProjectChange(id=424242, status="completed")],
    ))

    assert len(get_projects(db, TEST_USER_ID)) == 1
    ship = [goal for goal in get_goals(db, TEST_USER_ID) if goal.title == "Ship v1"][0]
    assert ship.project_id is None
    assert ship.target_date is None
    assert log == [f"created goal {ship.id}: Ship v1"]
    assert project.status == "active"


def test_completing_goal_sets_progress_and_completed_at_and_reopening_clears_it(db):
    goal = create_goal(db, TEST_USER_ID, "Deploy to Pi", progress=50)

    TrackingService.apply(db, TEST_USER_ID, changes(
        goal_updates=[GoalChange(id=goal.id, status="completed")],
    ))
    assert goal.progress == 100
    assert goal.completed_at is not None

    update_goal(db, TEST_USER_ID, goal.id, {"status": "active"})
    assert goal.completed_at is None


def test_questions_skip_the_llm(db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LLM should not be called for questions")

    monkeypatch.setattr("app.services.tracking_service.LLMService.generate_structured", fail)

    assert TrackingService.process_message(db, TEST_USER_ID, "What am I working on?") == []


def test_context_shows_open_items_with_deadlines_and_hides_closed_ones(db):
    jarvis = create_project(db, TEST_USER_ID, "Jarvis", next_action="Add reminders")
    create_project(db, TEST_USER_ID, "Portfolio", status="abandoned")
    create_goal(db, TEST_USER_ID, "Deploy to Pi", project_id=jarvis.id, target_date=date(2026, 10, 9), progress=50)
    create_goal(db, TEST_USER_ID, "Fix login bug", target_date=date(2026, 10, 1))
    create_goal(db, TEST_USER_ID, "Old goal", status="completed")

    context = TrackingService.to_context(db, TEST_USER_ID, TODAY)

    assert "- Jarvis (next step: Add reminders)" in context
    assert "Portfolio" not in context
    assert "Old goal" not in context
    assert "- Deploy to Pi (project: Jarvis; 50% done; due 2026-10-09, in 5 days)" in context
    assert "- Fix login bug (OVERDUE, was due 2026-10-01)" in context


def test_context_is_none_without_open_items(db):
    assert TrackingService.to_context(db, TEST_USER_ID, TODAY) is None


def test_projects_and_goals_api(client):
    project = client.post("/projects", json={"name": "Jarvis"}).json()
    goal = client.post("/goals", json={
        "title": "Deploy to Pi",
        "project_id": project["id"],
        "target_date": "2026-11-30",
    }).json()

    assert client.get(f"/projects/{project['id']}/goals").json()[0]["id"] == goal["id"]

    done = client.patch(f"/goals/{goal['id']}", json={"status": "completed"}).json()
    assert done["progress"] == 100 and done["completed_at"]

    assert client.get("/goals?status=completed").json()[0]["id"] == goal["id"]
    assert client.post("/goals", json={"title": "x", "project_id": 424242}).status_code == 422
    assert client.patch("/projects/424242", json={"status": "paused"}).status_code == 404
    assert client.post("/projects", json={"name": "x", "status": "finished"}).status_code == 422

    assert client.delete(f"/projects/{project['id']}").status_code == 200
    assert client.get(f"/goals/{goal['id']}").json()["project_id"] is None
    assert client.get("/projects").json() == []
