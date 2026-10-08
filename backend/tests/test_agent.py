from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.crud.task import create_task, get_task, get_tasks
from app.crud.tracking import create_project
from app.models.conversation import Conversation
from app.services.agent_service import AgentService, PendingActions
from app.services.llm_service import LLMService
from app.services.tracking_service import TrackingChanges, TrackingService
from app.services.task_service import NewTask, TaskChange
from tests.conftest import TEST_USER_ID


IST = timezone(timedelta(hours=5, minutes=30), "IST")
NOW = datetime(2026, 10, 8, 10, 0, tzinfo=IST)  # Thursday


def run(db, name, **arguments):
    return AgentService.run_tool(db, TEST_USER_ID, name, arguments, NOW)


# ---------- Tools ----------

def test_create_task_with_reminder_and_project(db):
    create_project(db, TEST_USER_ID, "Jarvis")

    action, result = run(db, "create_task", title="Call mom", remind_at="2026-10-08 18:00", project="jarvis")

    assert action.status == "done" and result == action.summary
    assert action.summary == "Added “Call mom” (reminder 18:00)"
    task = get_tasks(db, TEST_USER_ID, status="todo")[-1]
    assert task.remind_at == datetime(2026, 10, 8, 18, 0, tzinfo=IST)
    assert task.project_id is not None


def test_create_task_doesnt_duplicate_an_open_task(db):
    run(db, "create_task", title="Buy milk")

    action, _ = run(db, "create_task", title="buy milk")

    assert action.summary == "Already on the list: “Buy milk”"
    assert len([t for t in get_tasks(db, TEST_USER_ID, status="todo") if t.title == "Buy milk"]) == 1


def test_bad_arguments_fail_without_changing_anything(db):
    past, result = run(db, "create_task", title="Call mom", remind_at="2026-10-01 09:00")
    unreadable, _ = run(db, "create_task", title="Call mom", due_at="next blursday")
    missing, _ = run(db, "update_task", id=987654321, status="done")
    invalid, _ = run(db, "update_task", status="done")
    unknown, _ = run(db, "launch_rockets")

    assert [a.status for a in (past, unreadable, missing, invalid, unknown)] == ["failed"] * 5
    assert result.startswith("error: the reminder time '2026-10-01 09:00' is in the past. Nothing was saved.")
    assert "blursday" in unreadable.summary
    assert "no task with id 987654321" in missing.summary
    assert get_tasks(db, TEST_USER_ID) == []


def test_update_task_completes_and_reschedules(db):
    task = create_task(db, TEST_USER_ID, "Submit report")

    done, _ = run(db, "update_task", id=task.id, status="done")
    assert done.summary == "Completed “Submit report”"
    assert get_task(db, TEST_USER_ID, task.id).status == "done"

    moved, _ = run(db, "update_task", id=task.id, status="todo", due_at="2026-10-09")
    assert moved.summary == "Updated “Submit report” (due Fri 09 Oct 09:00), now todo"


def test_delete_waits_for_confirmation(db):
    task = create_task(db, TEST_USER_ID, "Old idea")

    action, result = run(db, "delete_task", id=task.id)

    assert action.status == "pending" and action.summary == "Delete “Old idea”"
    assert "needs the user's confirmation" in result
    assert get_task(db, TEST_USER_ID, task.id) is not None

    outcome, _ = AgentService.resolve(db, TEST_USER_ID, action.pending_id, approve=True, now=NOW)
    assert outcome.status == "done" and outcome.summary == "Deleted “Old idea”"
    assert get_task(db, TEST_USER_ID, task.id) is None

    # A button can't act twice.
    again, _ = AgentService.resolve(db, TEST_USER_ID, action.pending_id, approve=True, now=NOW)
    assert again.status == "expired"


def test_declined_and_expired_deletes_keep_the_task(db, monkeypatch):
    task = create_task(db, TEST_USER_ID, "Keep me")

    declined, _ = run(db, "delete_task", id=task.id)
    outcome, _ = AgentService.resolve(db, TEST_USER_ID, declined.pending_id, approve=False, now=NOW)
    assert outcome.status == "declined" and outcome.summary == "Not done: Delete “Keep me”"

    stale, _ = run(db, "delete_task", id=task.id)
    monkeypatch.setattr(PendingActions, "TTL_SECONDS", -1)
    expired, _ = AgentService.resolve(db, TEST_USER_ID, stale.pending_id, approve=True, now=NOW)
    assert expired.status == "expired"

    # Another user's pending action can't be resolved.
    monkeypatch.setattr(PendingActions, "TTL_SECONDS", 600)
    other, _ = run(db, "delete_task", id=task.id)
    assert AgentService.resolve(db, TEST_USER_ID + 1, other.pending_id, approve=True)[0].status == "expired"

    assert get_task(db, TEST_USER_ID, task.id) is not None


def test_tool_schemas_describe_arguments():
    schemas = {s["function"]["name"]: s["function"] for s in AgentService.tool_schemas()}

    assert set(schemas) == {"create_task", "update_task", "delete_task", "list_tasks"}
    assert schemas["create_task"]["parameters"]["required"] == ["title"]
    assert "remind_at" in schemas["create_task"]["parameters"]["properties"]


# ---------- The tool loop ----------

def reply(content="", calls=()):
    tool_calls = [
        SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))
        for name, arguments in calls
    ]
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or None, role="assistant"))


def test_loop_runs_tools_then_answers(monkeypatch):
    replies = iter([
        reply(calls=[("update_task", {"id": 7, "status": "done"})]),
        reply(calls=[("create_task", {"title": "Email Raj"})]),
        reply("Done, and I'll remind you."),
    ])
    requests = []

    def fake_chat(**kwargs):
        requests.append(kwargs)
        return next(replies)

    monkeypatch.setattr("app.services.llm_service.chat", fake_chat)
    ran = []

    answer = LLMService().generate_response(
        "I sent the report, remind me to email Raj",
        "none",
        tools=[{"type": "function"}],
        run_tool=lambda name, args: ran.append((name, args)) or f"ok {name}"
    )

    assert answer == "Done, and I'll remind you."
    assert ran == [("update_task", {"id": 7, "status": "done"}), ("create_task", {"title": "Email Raj"})]
    # Each tool result is sent back before the next call.
    assert requests[2]["messages"][-1] == {"role": "tool", "tool_name": "create_task", "content": "ok create_task"}


def test_loop_stops_offering_tools_after_the_limit(monkeypatch):
    requests = []

    def fake_chat(**kwargs):
        requests.append(kwargs)
        return reply("still going", calls=[("list_tasks", {})])

    monkeypatch.setattr("app.services.llm_service.chat", fake_chat)
    ran = []

    answer = LLMService().generate_response("loop", "none", tools=[{}], run_tool=lambda n, a: ran.append(n) or "ok")

    assert answer == "still going"
    assert len(ran) == LLMService.MAX_TOOL_ROUNDS
    assert "tools" not in requests[-1]


def test_no_tools_without_a_runner(monkeypatch):
    requests = []
    monkeypatch.setattr("app.services.llm_service.chat", lambda **kw: requests.append(kw) or reply("hi"))

    assert LLMService().generate_response("hi", "none") == "hi"
    assert "tools" not in requests[0]


# ---------- Chat endpoint ----------

def test_chat_returns_and_logs_actions(client, db, monkeypatch):
    task = create_task(db, TEST_USER_ID, "Old idea")
    replies = iter([
        reply(calls=[("create_task", {"title": "Call mom", "remind_at": "2099-01-01 18:00"}),
                     ("delete_task", {"id": task.id})]),
        reply("Added. Confirm the delete?"),
    ])

    monkeypatch.setattr("app.api.memory.DEFAULT_USER_ID", TEST_USER_ID)
    monkeypatch.setattr("app.services.llm_service.chat", lambda **kw: next(replies))
    monkeypatch.setattr("app.services.memory_service.EmbeddingService.try_generate_query", lambda q: None)
    monkeypatch.setattr("app.api.memory.MemoryPipeline.process_conversation", lambda conversation_id: None)

    body = client.post("/memory/chat", json={"query": "remind me to call mom, and delete the old idea"}).json()

    assert body["response"] == "Added. Confirm the delete?"
    created, pending = body["actions"]
    assert created["status"] == "done" and created["summary"].startswith("Added “Call mom”")
    assert pending["status"] == "pending" and pending["pending_id"]

    confirmed = client.post(f"/memory/chat/actions/{pending['pending_id']}", json={"approve": True}).json()
    assert confirmed == {
        "tool": "delete_task", "summary": "Deleted “Old idea”", "status": "done", "pending_id": None, "task_id": task.id
    }

    # The turn's log shows the outcome, also in history.
    turn = db.query(Conversation).filter(Conversation.user_id == TEST_USER_ID).one()
    assert [a["status"] for a in turn.actions] == ["done", "done"]
    assert client.get("/memory/chat/history").json()[-1]["actions"][1]["summary"] == "Deleted “Old idea”"

    assert client.post("/memory/chat/actions/nope", json={"approve": True}).json()["status"] == "expired"


def test_tracker_backs_up_the_agent_without_duplicating_it(db):
    report = create_task(db, TEST_USER_ID, "Submit report")
    agents = create_task(db, TEST_USER_ID, "Agent's task")
    changes = TrackingChanges(
        reasoning="",
        new_projects=[], new_goals=[], project_updates=[], goal_updates=[],
        new_tasks=[NewTask(title="Email Raj")],
        task_updates=[TaskChange(id=report.id, status="done"), TaskChange(id=agents.id, status="cancelled")]
    )

    # The agent created "Email Raj" (worded its own way) and changed its
    # task: only the update it missed is applied.
    log = TrackingService.apply(db, TEST_USER_ID, changes, NOW, agent_task_ids={agents.id})

    assert log == [f"updated task {report.id}: {{'status': 'done'}}"]
    assert get_task(db, TEST_USER_ID, agents.id).status == "todo"
    assert "Email Raj" not in {t.title for t in get_tasks(db, TEST_USER_ID)}

    # Without agent actions it handles tasks fully, as before.
    TrackingService.apply(db, TEST_USER_ID, changes, NOW)
    assert "Email Raj" in {t.title for t in get_tasks(db, TEST_USER_ID)}
