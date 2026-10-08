import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core import recurrence
from app.core.clock import local_now
from app.crud.task import create_task, delete_task, find_task_by_title, get_task, get_tasks, update_task
from app.crud.tracking import (
    create_goal,
    create_project,
    delete_goal,
    delete_project,
    find_goal_by_title,
    find_project_by_name,
    get_goal,
    get_project,
    update_goal,
    update_project
)
from app.schemas.task import Priority
from app.schemas.tracking import Status
from app.services.task_service import TaskService


# ---------- Tool arguments (their JSON schemas are what the LLM sees) ----------

LocalTime = "local time, YYYY-MM-DD HH:MM (or YYYY-MM-DD for a day)"


class CreateTaskArgs(BaseModel):
    title: str = Field(description='the action, without the time ("Call mom")')
    due_at: str | None = Field(None, description=f"a deadline the user states (\"by Friday\"), {LocalTime}; not for reminders")
    remind_at: str | None = Field(None, description=f"when to remind the user; always set for \"remind me\", {LocalTime}")
    priority: Priority | None = Field(None, description="only if the user says it's urgent/important or not")
    project: str | None = Field(None, description="name of one of the user's projects it belongs to")
    repeat: str | None = Field(None, description=f"only if it repeats: {recurrence.FORMATS}")


class UpdateTaskArgs(BaseModel):
    id: int = Field(description="N from the task's [task N]")
    status: Literal["todo", "done", "cancelled"] | None = Field(
        None, description="done when finished, cancelled when no longer needed, todo to reopen"
    )
    title: str | None = None
    due_at: str | None = Field(None, description=f"new deadline, {LocalTime}")
    remind_at: str | None = Field(None, description=f"new reminder time, {LocalTime}")
    priority: Priority | None = None
    repeat: str | None = Field(None, description=f"new repeat rule ({recurrence.FORMATS}), or none to stop repeating")


class TaskIdArgs(BaseModel):
    id: int = Field(description="N from the task's [task N]")


class ListTasksArgs(BaseModel):
    status: Literal["todo", "done", "cancelled"] = "todo"


StatusHelp = "completed when finished, paused when on hold, abandoned when dropped for good, active when resumed"
Day = 'YYYY-MM-DD; "by <month>" or "this month/year" means the last day of that period'


class CreateProjectArgs(BaseModel):
    name: str = Field(description="the project's short name")
    description: str | None = None
    next_action: str | None = Field(None, description="the next step, if the user says one")


class UpdateProjectArgs(BaseModel):
    id: int = Field(description="N from the project's [project N]")
    status: Status | None = Field(None, description=StatusHelp)
    name: str | None = None
    next_action: str | None = Field(None, description="the next step the user says they need to take")
    description: str | None = None


class ProjectIdArgs(BaseModel):
    id: int = Field(description="N from the project's [project N]")


class CreateGoalArgs(BaseModel):
    title: str = Field(description='the objective, without the deadline ("Deploy Jarvis on a Raspberry Pi")')
    project: str | None = Field(None, description="name of one of the user's projects it belongs to")
    target_date: str | None = Field(None, description=f"deadline the user states, {Day}")
    progress: int | None = Field(None, ge=0, le=100, description="percent done, if the user says")


class UpdateGoalArgs(BaseModel):
    id: int = Field(description="N from the goal's [goal N]")
    status: Status | None = Field(None, description=StatusHelp)
    progress: int | None = Field(
        None, ge=0, le=100,
        description='percent done the user states or implies ("halfway" 50, "almost done" 90)'
    )
    target_date: str | None = Field(None, description=f"new deadline, {Day}")
    title: str | None = None


class GoalIdArgs(BaseModel):
    id: int = Field(description="N from the goal's [goal N]")


# ---------- Tools ----------

@dataclass
class ToolContext:
    db: Session
    user_id: int
    now: datetime


class ToolError(Exception):
    """A tool couldn't run with these arguments; the message goes to the LLM."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    # Returns a one-line summary of what was done, shown to the user
    # and given to the LLM as the tool's result.
    run: Callable[[ToolContext, BaseModel], str]
    # Destructive: held until the user confirms. Returns what would happen.
    confirm: Callable[[ToolContext, BaseModel], str] | None = None

    def schema(self) -> dict:
        parameters = self.args.model_json_schema()
        parameters.pop("title", None)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters
            }
        }


def _when(moment: datetime | None, now: datetime) -> str:
    return TaskService._time(moment, now) if moment else ""


def _describe(task, now: datetime) -> str:
    details = []
    if task.due_at:
        details.append(f"due {_when(task.due_at, now)}")
    if task.remind_at and task.reminded_at is None:
        details.append(f"reminder {_when(task.remind_at, now)}")
    if task.recurrence:
        details.append(f"repeats {recurrence.describe(task.recurrence)}")

    return f"“{task.title}”" + (f" ({', '.join(details)})" if details else "")


def _task(ctx: ToolContext, task_id: int):
    task = get_task(ctx.db, ctx.user_id, task_id)
    if task is None:
        raise ToolError(f"no task with id {task_id}")
    return task


def _time_arg(value: str | None, ctx: ToolContext, *, reminder: bool) -> datetime | None:
    if not value:
        return None

    moment = TaskService.parse_local(value, ctx.now)
    if moment is None:
        raise ToolError(f"can't read the time {value!r}; use YYYY-MM-DD HH:MM")

    if reminder:
        moment = TaskService._future_reminder(moment, ctx.now)
        if moment is None:
            raise ToolError(f"the reminder time {value!r} is in the past")

    return moment


def _repeat_arg(value: str | None) -> str | None:
    """A normalized rule; None for no repeat ("none", "never", "")."""
    if not value or value.strip().lower() in ("none", "never", "no", "stop", "once"):
        return None
    try:
        return recurrence.normalize(value)
    except recurrence.RecurrenceError as error:
        raise ToolError(str(error))


def _create_task(ctx: ToolContext, args: CreateTaskArgs) -> str:
    title = args.title.strip()[:300]
    if not title:
        raise ToolError("the title is empty")

    existing = find_task_by_title(ctx.db, ctx.user_id, title)
    if existing:
        return f"Already on the list: {_describe(existing, ctx.now)}"

    project = find_project_by_name(ctx.db, ctx.user_id, args.project) if args.project else None

    task = create_task(
        ctx.db,
        ctx.user_id,
        title,
        project_id=project.id if project else None,
        priority=args.priority or "normal",
        due_at=_time_arg(args.due_at, ctx, reminder=False),
        remind_at=_time_arg(args.remind_at, ctx, reminder=True),
        recurrence=_repeat_arg(args.repeat)
    )

    return f"Added {_describe(task, ctx.now)}"


def _update_task(ctx: ToolContext, args: UpdateTaskArgs) -> str:
    task = _task(ctx, args.id)

    fields = {}
    if args.status:
        fields["status"] = args.status
    if args.title and args.title.strip():
        fields["title"] = args.title.strip()[:300]
    if args.priority:
        fields["priority"] = args.priority
    if args.due_at:
        fields["due_at"] = _time_arg(args.due_at, ctx, reminder=False)
    if args.remind_at:
        fields["remind_at"] = _time_arg(args.remind_at, ctx, reminder=True)
    if args.repeat:
        fields["recurrence"] = _repeat_arg(args.repeat)

    if not fields:
        raise ToolError("nothing to change")

    task = update_task(ctx.db, ctx.user_id, task.id, fields)

    if fields.keys() == {"recurrence"} and task.recurrence is None:
        return f"Stopped repeating “{task.title}”"

    if fields.keys() == {"status"}:
        verb = {"done": "Completed", "cancelled": "Cancelled", "todo": "Reopened"}[args.status]
        summary = f"{verb} “{task.title}”"

        # Completing a repeating task created its next occurrence.
        upcoming = find_task_by_title(ctx.db, ctx.user_id, task.title) if args.status == "done" and task.recurrence else None
        if upcoming:
            summary += f"; next one {_when(upcoming.due_at or upcoming.remind_at, ctx.now)}"

        return summary

    return f"Updated {_describe(task, ctx.now)}" + (f", now {task.status}" if args.status else "")


def _delete_task(ctx: ToolContext, args: TaskIdArgs) -> str:
    task = _task(ctx, args.id)
    delete_task(ctx.db, ctx.user_id, task.id)
    return f"Deleted “{task.title}”"


def _confirm_delete(ctx: ToolContext, args: TaskIdArgs) -> str:
    return f"Delete “{_task(ctx, args.id).title}”"


def _project(ctx: ToolContext, project_id: int):
    project = get_project(ctx.db, ctx.user_id, project_id)
    if project is None:
        raise ToolError(f"no project with id {project_id}")
    return project


def _goal(ctx: ToolContext, goal_id: int):
    goal = get_goal(ctx.db, ctx.user_id, goal_id)
    if goal is None:
        raise ToolError(f"no goal with id {goal_id}")
    return goal


def _project_by_name(ctx: ToolContext, name: str | None):
    if not name:
        return None
    project = find_project_by_name(ctx.db, ctx.user_id, name)
    if project is None:
        raise ToolError(f"no project named {name!r}; create it first or leave project empty")
    return project


def _date_arg(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise ToolError(f"can't read the date {value!r}; use YYYY-MM-DD")


STATUS_VERB = {"completed": "Completed", "paused": "Paused", "abandoned": "Dropped", "active": "Resumed"}


def _create_project(ctx: ToolContext, args: CreateProjectArgs) -> str:
    name = args.name.strip()[:200]
    if not name:
        raise ToolError("the name is empty")

    if find_project_by_name(ctx.db, ctx.user_id, name):
        return f"Already a project: “{name}”"

    project = create_project(
        ctx.db,
        ctx.user_id,
        name,
        description=args.description,
        next_action=(args.next_action or None) and args.next_action[:500]
    )
    return f"Started project “{project.name}”" + (f" (next: {project.next_action})" if project.next_action else "")


def _update_project(ctx: ToolContext, args: UpdateProjectArgs) -> str:
    project = _project(ctx, args.id)

    fields = {}
    if args.status:
        fields["status"] = args.status
    if args.name and args.name.strip():
        fields["name"] = args.name.strip()[:200]
    if args.next_action and args.next_action.strip():
        fields["next_action"] = args.next_action.strip()[:500]
    if args.description:
        fields["description"] = args.description

    if not fields:
        raise ToolError("nothing to change")

    project = update_project(ctx.db, ctx.user_id, project.id, fields)

    if fields.keys() == {"status"}:
        return f"{STATUS_VERB[args.status]} project “{project.name}”"

    changes = [f"next: {project.next_action}"] if "next_action" in fields else []
    if args.status:
        changes.append(project.status)
    return f"Updated project “{project.name}”" + (f" ({', '.join(changes)})" if changes else "")


def _delete_project(ctx: ToolContext, args: ProjectIdArgs) -> str:
    project = _project(ctx, args.id)
    delete_project(ctx.db, ctx.user_id, project.id)
    return f"Deleted project “{project.name}”"


def _confirm_delete_project(ctx: ToolContext, args: ProjectIdArgs) -> str:
    return f"Delete project “{_project(ctx, args.id).name}” (its goals and tasks stay)"


def _describe_goal(goal) -> str:
    details = []
    if goal.progress:
        details.append(f"{goal.progress}%")
    if goal.target_date:
        details.append(f"by {goal.target_date.isoformat()}")
    return f"“{goal.title}”" + (f" ({', '.join(details)})" if details else "")


def _create_goal(ctx: ToolContext, args: CreateGoalArgs) -> str:
    title = args.title.strip()[:300]
    if not title:
        raise ToolError("the title is empty")

    existing = find_goal_by_title(ctx.db, ctx.user_id, title)
    if existing:
        return f"Already a goal: {_describe_goal(existing)}"

    project = _project_by_name(ctx, args.project)

    goal = create_goal(
        ctx.db,
        ctx.user_id,
        title,
        project_id=project.id if project else None,
        target_date=_date_arg(args.target_date),
        progress=args.progress or 0
    )
    return f"New goal {_describe_goal(goal)}"


def _update_goal(ctx: ToolContext, args: UpdateGoalArgs) -> str:
    goal = _goal(ctx, args.id)

    fields = {}
    if args.status:
        fields["status"] = args.status
    if args.progress is not None:
        fields["progress"] = args.progress
    if args.target_date:
        fields["target_date"] = _date_arg(args.target_date)
    if args.title and args.title.strip():
        fields["title"] = args.title.strip()[:300]

    if not fields:
        raise ToolError("nothing to change")

    goal = update_goal(ctx.db, ctx.user_id, goal.id, fields)

    if fields.keys() == {"status"}:
        return f"{STATUS_VERB[args.status]} goal “{goal.title}”"

    return f"Updated goal {_describe_goal(goal)}" + (f", {goal.status}" if args.status else "")


def _delete_goal(ctx: ToolContext, args: GoalIdArgs) -> str:
    goal = _goal(ctx, args.id)
    delete_goal(ctx.db, ctx.user_id, goal.id)
    return f"Deleted goal “{goal.title}”"


def _confirm_delete_goal(ctx: ToolContext, args: GoalIdArgs) -> str:
    return f"Delete goal “{_goal(ctx, args.id).title}”"


def _list_tasks(ctx: ToolContext, args: ListTasksArgs) -> str:
    tasks = get_tasks(ctx.db, ctx.user_id, status=args.status)[-30:]
    if not tasks:
        return f"No {args.status} tasks"
    lines = "; ".join(f"[{task.id}] {_describe(task, ctx.now)}" for task in tasks)
    return f"{args.status} tasks: {lines}"


TOOLS = {tool.name: tool for tool in [
    Tool(
        "create_task",
        "Add a task or reminder for the user.",
        CreateTaskArgs,
        _create_task
    ),
    Tool(
        "update_task",
        "Change one of the user's listed tasks: mark it done or cancelled, rename it, or move its deadline or reminder.",
        UpdateTaskArgs,
        _update_task
    ),
    Tool(
        "delete_task",
        "Permanently remove a task (only when the user asks to delete it; to drop a task use update_task with status cancelled).",
        TaskIdArgs,
        _delete_task,
        confirm=_confirm_delete
    ),
    Tool(
        "list_tasks",
        "List the user's tasks by status, e.g. finished ones (open tasks are already in the prompt).",
        ListTasksArgs,
        _list_tasks
    ),
    Tool(
        "create_project",
        "Start tracking a new, named piece of work the user has begun (not one already listed).",
        CreateProjectArgs,
        _create_project
    ),
    Tool(
        "update_project",
        "Change a listed project: finish, pause, drop or resume it, rename it, or set its next step.",
        UpdateProjectArgs,
        _update_project
    ),
    Tool(
        "delete_project",
        "Permanently remove a project (only when the user asks to delete it; to drop it use update_project with status abandoned).",
        ProjectIdArgs,
        _delete_project,
        confirm=_confirm_delete_project
    ),
    Tool(
        "create_goal",
        "Add a goal: an outcome the user works towards over weeks or months (a single action due soon is a task).",
        CreateGoalArgs,
        _create_goal
    ),
    Tool(
        "update_goal",
        "Change a listed goal: its progress, deadline or status (completed, paused, abandoned, active), or rename it.",
        UpdateGoalArgs,
        _update_goal
    ),
    Tool(
        "delete_goal",
        "Permanently remove a goal (only when the user asks to delete it; to drop it use update_goal with status abandoned).",
        GoalIdArgs,
        _delete_goal,
        confirm=_confirm_delete_goal
    ),
]}

# What each changing tool acts on. When the chat agent acted on a kind of
# item in a turn, the background tracker doesn't create that kind for it
# (they'd be duplicates) and leaves the items it touched alone.
KIND_OF_TOOL = {
    "create_task": "task", "update_task": "task", "delete_task": "task",
    "create_project": "project", "update_project": "project", "delete_project": "project",
    "create_goal": "goal", "update_goal": "goal", "delete_goal": "goal",
}


def agent_edits(actions: list[dict]) -> dict[str, set[int]]:
    """
    From a turn's logged actions: each kind the agent acted on, with the
    ids of existing items it changed. Older rows logged task_id.
    """
    edits: dict[str, set[int]] = {}

    for action in actions or []:
        kind = KIND_OF_TOOL.get(action.get("tool"))
        if kind is None:
            continue
        ids = edits.setdefault(kind, set())
        target = action.get("target_id") or action.get("task_id")
        if target:
            ids.add(target)

    return edits


# ---------- Actions ----------

ActionStatus = Literal["done", "failed", "pending", "declined", "expired"]


class Action(BaseModel):
    tool: str
    summary: str
    status: ActionStatus
    # Set while it waits for the user's confirmation.
    pending_id: str | None = None
    # The existing item it changed or deletes (update/delete).
    target_id: int | None = None


@dataclass
class PendingAction:
    user_id: int
    tool: str
    args: dict
    conversation_id: int | None = None
    created: float = field(default_factory=time.monotonic)


class PendingActions:
    """
    Destructive actions waiting for the user's OK. Kept in memory: a
    restart forgets them, and they expire, so a stale button can't act.
    """

    TTL_SECONDS = 10 * 60

    _items: dict[str, PendingAction] = {}
    _lock = threading.Lock()

    @classmethod
    def add(cls, user_id: int, tool: str, args: dict) -> str:
        pending_id = secrets.token_urlsafe(9)
        with cls._lock:
            cls._expire()
            cls._items[pending_id] = PendingAction(user_id, tool, args)
        return pending_id

    @classmethod
    def attach(cls, pending_ids: list[str], conversation_id: int):
        with cls._lock:
            for pending_id in pending_ids:
                if pending_id in cls._items:
                    cls._items[pending_id].conversation_id = conversation_id

    @classmethod
    def take(cls, pending_id: str, user_id: int) -> PendingAction | None:
        with cls._lock:
            cls._expire()
            item = cls._items.get(pending_id)
            if item is None or item.user_id != user_id:
                return None
            return cls._items.pop(pending_id)

    @classmethod
    def _expire(cls):
        cutoff = time.monotonic() - cls.TTL_SECONDS
        for pending_id in [k for k, v in cls._items.items() if v.created < cutoff]:
            del cls._items[pending_id]


class AgentService:
    """
    Runs the chat model's tool calls on the user's tasks, projects and
    goals, holding destructive ones for confirmation.
    """

    @staticmethod
    def tool_schemas() -> list[dict]:
        return [tool.schema() for tool in TOOLS.values()]

    @staticmethod
    def run_tool(
        db: Session,
        user_id: int,
        name: str,
        arguments: dict,
        now: datetime | None = None
    ) -> tuple[Action, str]:
        """
        Executes (or, for destructive tools, holds) one tool call.
        Returns the action for the user and the result text for the LLM.
        """
        tool = TOOLS.get(name)
        if tool is None:
            return Action(tool=name, summary=f"Unknown action {name}", status="failed"), f"error: no tool named {name}"

        ctx = ToolContext(db, user_id, now or local_now())

        try:
            args = tool.args.model_validate(arguments or {})
            target_id = getattr(args, "id", None)

            if tool.confirm:
                summary = tool.confirm(ctx, args)
                pending_id = PendingActions.add(user_id, name, args.model_dump())
                return (
                    Action(tool=name, summary=summary, status="pending", pending_id=pending_id, target_id=target_id),
                    f"Not done yet: “{summary}” needs the user's confirmation, and they have "
                    "a Confirm button for it. Ask them to confirm; don't say it's done."
                )

            summary = tool.run(ctx, args)
            return Action(tool=name, summary=summary, status="done", target_id=target_id), summary

        except (ToolError, ValidationError) as error:
            db.rollback()
            reason = str(error).splitlines()[0]
            return (
                Action(tool=name, summary=f"Couldn't {name.replace('_', ' ')}: {reason}", status="failed"),
                f"error: {reason}. Nothing was saved. Call the tool again with corrected "
                "arguments, or tell the user it failed."
            )

    @staticmethod
    def resolve(
        db: Session,
        user_id: int,
        pending_id: str,
        approve: bool,
        now: datetime | None = None
    ) -> tuple[Action, int | None]:
        """
        Confirms or declines a held action. Returns the outcome and the
        conversation it came from (to update its log).
        """
        item = PendingActions.take(pending_id, user_id)
        if item is None:
            return Action(tool="", summary="This request expired; ask again.", status="expired"), None

        tool = TOOLS[item.tool]
        ctx = ToolContext(db, user_id, now or local_now())
        args = tool.args.model_validate(item.args)

        if not approve:
            try:
                summary = tool.confirm(ctx, args)
            except ToolError:
                summary = item.tool.replace("_", " ")
            return Action(tool=item.tool, summary=f"Not done: {summary}", status="declined", target_id=args.id), item.conversation_id

        try:
            return Action(tool=item.tool, summary=tool.run(ctx, args), status="done", target_id=args.id), item.conversation_id
        except ToolError as error:
            db.rollback()
            return Action(tool=item.tool, summary=f"Couldn't do it: {error}", status="failed"), item.conversation_id
