import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.clock import local_now
from app.crud.task import create_task, delete_task, find_task_by_title, get_task, get_tasks, update_task
from app.crud.tracking import find_project_by_name
from app.schemas.task import Priority
from app.services.task_service import TaskService


# ---------- Tool arguments (their JSON schemas are what the LLM sees) ----------

LocalTime = "local time, YYYY-MM-DD HH:MM (or YYYY-MM-DD for a day)"


class CreateTaskArgs(BaseModel):
    title: str = Field(description='the action, without the time ("Call mom")')
    due_at: str | None = Field(None, description=f"a deadline the user states (\"by Friday\"), {LocalTime}; not for reminders")
    remind_at: str | None = Field(None, description=f"when to remind the user; always set for \"remind me\", {LocalTime}")
    priority: Priority | None = Field(None, description="only if the user says it's urgent/important or not")
    project: str | None = Field(None, description="name of one of the user's projects it belongs to")


class UpdateTaskArgs(BaseModel):
    id: int = Field(description="the task's id from the task list")
    status: Literal["todo", "done", "cancelled"] | None = Field(
        None, description="done when finished, cancelled when no longer needed, todo to reopen"
    )
    title: str | None = None
    due_at: str | None = Field(None, description=f"new deadline, {LocalTime}")
    remind_at: str | None = Field(None, description=f"new reminder time, {LocalTime}")
    priority: Priority | None = None


class TaskIdArgs(BaseModel):
    id: int = Field(description="the task's id from the task list")


class ListTasksArgs(BaseModel):
    status: Literal["todo", "done", "cancelled"] = "todo"


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
        remind_at=_time_arg(args.remind_at, ctx, reminder=True)
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

    if not fields:
        raise ToolError("nothing to change")

    task = update_task(ctx.db, ctx.user_id, task.id, fields)

    if fields.keys() == {"status"}:
        verb = {"done": "Completed", "cancelled": "Cancelled", "todo": "Reopened"}[args.status]
        return f"{verb} “{task.title}”"

    return f"Updated {_describe(task, ctx.now)}" + (f", now {task.status}" if args.status else "")


def _delete_task(ctx: ToolContext, args: TaskIdArgs) -> str:
    task = _task(ctx, args.id)
    delete_task(ctx.db, ctx.user_id, task.id)
    return f"Deleted “{task.title}”"


def _confirm_delete(ctx: ToolContext, args: TaskIdArgs) -> str:
    return f"Delete “{_task(ctx, args.id).title}”"


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
]}

# Tools that change tasks. When the chat used them in a turn, the
# background tracker doesn't add tasks for it (they'd be duplicates)
# and leaves the tasks they touched alone.
TASK_TOOLS = {"create_task", "update_task", "delete_task"}


# ---------- Actions ----------

ActionStatus = Literal["done", "failed", "pending", "declined", "expired"]


class Action(BaseModel):
    tool: str
    summary: str
    status: ActionStatus
    # Set while it waits for the user's confirmation.
    pending_id: str | None = None
    # The existing task it changed or deletes (update/delete).
    task_id: int | None = None


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
    """Runs the chat model's tool calls, holding destructive ones for confirmation."""

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
            task_id = getattr(args, "id", None)

            if tool.confirm:
                summary = tool.confirm(ctx, args)
                pending_id = PendingActions.add(user_id, name, args.model_dump())
                return (
                    Action(tool=name, summary=summary, status="pending", pending_id=pending_id, task_id=task_id),
                    f"Not done yet: “{summary}” needs the user's confirmation, and they have "
                    "a Confirm button for it. Ask them to confirm; don't say it's done."
                )

            summary = tool.run(ctx, args)
            return Action(tool=name, summary=summary, status="done", task_id=task_id), summary

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
            return Action(tool=item.tool, summary=f"Not done: {summary}", status="declined", task_id=args.id), item.conversation_id

        try:
            return Action(tool=item.tool, summary=tool.run(ctx, args), status="done", task_id=args.id), item.conversation_id
        except ToolError as error:
            db.rollback()
            return Action(tool=item.tool, summary=f"Couldn't do it: {error}", status="failed"), item.conversation_id
