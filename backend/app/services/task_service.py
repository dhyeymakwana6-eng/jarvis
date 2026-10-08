import re
from datetime import datetime, time, timedelta

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.clock import local_now
from app.core.recurrence import describe as describe_recurrence
from app.crud.task import create_task, get_task, get_tasks, find_task_by_title, update_task
from app.crud.tracking import get_projects, get_project, find_project_by_name
from app.models.project import Project
from app.models.task import Task
from app.schemas.task import TaskStatus, Priority


# ---------- LLM output schema (part of TrackingChanges) ----------

LocalTime = Field(None, description="local time, YYYY-MM-DD HH:MM")


class NewTask(BaseModel):
    # Field order matters to the LLM: with the time fields last it
    # fills them after settling the project, instead of skipping them.
    title: str = Field(description="the action, without the time (\"Call mom\")")
    project_id: int | None = Field(None, description="id of a listed project this task belongs to")
    project_name: str | None = Field(None, description="name of a project in new_projects this task belongs to")
    due_at: str | None = Field(None, description="the deadline the message states, local YYYY-MM-DD HH:MM or YYYY-MM-DD")
    remind_at: str | None = Field(None, description="when to remind, local YYYY-MM-DD HH:MM")
    priority: Priority | None = None


class TaskChange(BaseModel):
    id: int
    status: TaskStatus | None = None
    due_at: str | None = LocalTime
    remind_at: str | None = LocalTime
    priority: Priority | None = None


class TaskService:
    """
    Applies task changes the tracker LLM proposes, and renders a user's
    tasks as context for the chat prompt.
    """

    # Reminder time when the user gives a day but no time.
    DEFAULT_REMINDER_TIME = time(9, 0)

    # ---------- Applying changes ----------

    @staticmethod
    def parse_local(value: str | None, now: datetime) -> datetime | None:
        """
        "YYYY-MM-DD HH:MM" (or a bare date, meaning DEFAULT_REMINDER_TIME)
        in the user's timezone. None if missing or malformed.
        """
        if not value:
            return None

        value = value.strip()

        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                moment = datetime.combine(
                    datetime.fromisoformat(value).date(),
                    TaskService.DEFAULT_REMINDER_TIME
                )
            else:
                moment = datetime.fromisoformat(value.replace(" ", "T", 1))
        except ValueError:
            return None

        # The LLM is asked for local times; an offset, if it adds one
        # anyway, is respected.
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=now.tzinfo)

        return moment

    @staticmethod
    def _future_reminder(moment: datetime | None, now: datetime) -> datetime | None:
        """
        Reminders must be in the future. "At 5" said at 18:00 resolved to
        today 17:00 means tomorrow; anything older is dropped.
        """
        if moment is None or moment > now - timedelta(minutes=1):
            return moment

        if moment > now - timedelta(days=1):
            return moment + timedelta(days=1)

        return None

    @staticmethod
    def apply_changes(
        db: Session,
        user_id: int,
        new_tasks: list[NewTask],
        task_updates: list[TaskChange],
        created_projects: dict[str, Project],
        now: datetime
    ) -> list[str]:
        """
        Validates and applies LLM-proposed task changes: ids must belong
        to the user, open tasks aren't duplicated, bad times are dropped.
        Returns a log of what changed.
        """
        log = []

        for new in new_tasks:
            title = new.title.strip()

            if not title or find_task_by_title(db, user_id, title):
                continue

            project_id = None

            if new.project_id is not None and get_project(db, user_id, new.project_id):
                project_id = new.project_id
            elif new.project_name:
                project = (
                    created_projects.get(new.project_name.strip().lower())
                    or find_project_by_name(db, user_id, new.project_name)
                )
                project_id = project.id if project else None

            task = create_task(
                db,
                user_id,
                title[:300],
                project_id=project_id,
                priority=new.priority or "normal",
                due_at=TaskService.parse_local(new.due_at, now),
                remind_at=TaskService._future_reminder(
                    TaskService.parse_local(new.remind_at, now), now
                )
            )
            log.append(f"created task {task.id}: {task.title}")

        for change in task_updates:
            if get_task(db, user_id, change.id) is None:
                continue

            fields = {}

            if change.status:
                fields["status"] = change.status
            if change.priority:
                fields["priority"] = change.priority

            due_at = TaskService.parse_local(change.due_at, now)
            if due_at:
                fields["due_at"] = due_at

            remind_at = TaskService._future_reminder(
                TaskService.parse_local(change.remind_at, now), now
            )
            if remind_at:
                fields["remind_at"] = remind_at

            if fields and update_task(db, user_id, change.id, fields):
                log.append(f"updated task {change.id}: {fields}")

        return log

    @staticmethod
    def state_lines(db: Session, user_id: int, now: datetime) -> list[str]:
        """Open tasks with ids and local times, for the tracker LLM."""
        lines = ["Tasks:"]

        def fmt(moment: datetime) -> str:
            return moment.astimezone(now.tzinfo).strftime("%Y-%m-%d %H:%M")

        tasks = get_tasks(db, user_id, status="todo")

        for task in tasks:
            details = []
            if task.due_at:
                details.append(f"due {fmt(task.due_at)}")
            if task.remind_at:
                details.append(f"reminder {fmt(task.remind_at)}")
            if task.project_id:
                details.append(f"project {task.project_id}")

            suffix = f" ({', '.join(details)})" if details else ""
            lines.append(f"- [{task.id}] {task.title}{suffix}")

        if not tasks:
            lines.append("(none)")

        return lines

    # ---------- Chat context ----------

    # Tasks listed per section; the rest are summarised as "+N more".
    SECTION_LIMIT = 8

    # "Upcoming" covers tasks due within this many days after today.
    UPCOMING_DAYS = 7

    @staticmethod
    def _time(moment: datetime, now: datetime) -> str:
        """Local time, with the day only when it isn't today."""
        moment = moment.astimezone(now.tzinfo)

        if moment.date() == now.date():
            return moment.strftime("%H:%M")

        if moment.year == now.year:
            return moment.strftime("%a %d %b %H:%M")

        return moment.strftime("%a %d %b %Y %H:%M")

    @staticmethod
    def _ago(moment: datetime, now: datetime) -> str:
        """How long ago, computed here because small LLMs get date maths wrong."""
        minutes = int((now - moment).total_seconds() // 60)

        if minutes < 60:
            return f"{minutes} min ago"
        if minutes < 24 * 60:
            hours = minutes // 60
            return f"{hours} hour{'s' if hours != 1 else ''} ago"

        days = minutes // (24 * 60)
        return f"{days} day{'s' if days != 1 else ''} ago"

    @staticmethod
    def _line(task: Task, now: datetime, project_names: dict[int, str]) -> str:
        details = []

        if task.due_at:
            if task.due_at < now:
                details.append(
                    f"was due {TaskService._time(task.due_at, now)}, {TaskService._ago(task.due_at, now)}"
                )
            else:
                details.append(f"due {TaskService._time(task.due_at, now)}")

        if task.remind_at and task.reminded_at is None and task.remind_at > now:
            details.append(f"reminder {TaskService._time(task.remind_at, now)}")

        if task.recurrence:
            details.append(f"repeats {describe_recurrence(task.recurrence)}")

        if task.project_id in project_names:
            details.append(f"project: {project_names[task.project_id]}")

        priority = f"[{task.priority}] " if task.priority != "normal" else ""
        suffix = f" ({'; '.join(details)})" if details else ""

        # The id lets the chat model's tools refer to the task.
        return f"- [task {task.id}] {priority}{task.title}{suffix}"

    @staticmethod
    def _section(title: str, tasks: list[Task], now: datetime, project_names: dict[int, str]) -> str | None:
        if not tasks:
            return None

        shown = tasks[:TaskService.SECTION_LIMIT]
        lines = [TaskService._line(task, now, project_names) for task in shown]

        if len(tasks) > len(shown):
            lines.append(f"- (+{len(tasks) - len(shown)} more)")

        return f"{title}:\n" + "\n".join(lines)

    @staticmethod
    def to_context(db: Session, user_id: int, now: datetime | None = None) -> str | None:
        """
        Open tasks grouped by urgency, plus what was finished today, for
        the chat prompt. None when there's nothing to show.
        """
        now = now or local_now()

        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_today = start_of_today + timedelta(days=1)
        end_of_upcoming = end_of_today + timedelta(days=TaskService.UPCOMING_DAYS)

        project_names = {project.id: project.name for project in get_projects(db, user_id)}

        overdue, today, upcoming, later, undated = [], [], [], [], []

        # Sorted by due time, then priority (see get_tasks).
        for task in get_tasks(db, user_id, status="todo"):
            if task.due_at is None:
                undated.append(task)
            elif task.due_at < now:
                overdue.append(task)
            elif task.due_at < end_of_today:
                today.append(task)
            elif task.due_at < end_of_upcoming:
                upcoming.append(task)
            else:
                later.append(task)

        # Undated tasks: high priority first.
        undated.sort(key=lambda task: {"high": 0, "normal": 1, "low": 2}.get(task.priority, 1))

        done_today = [
            task
            for task in get_tasks(db, user_id, status="done")
            if task.completed_at and task.completed_at >= start_of_today
        ]

        sections = [
            TaskService._section("OVERDUE", overdue, now, project_names),
            TaskService._section("Due today", today, now, project_names),
            TaskService._section(f"Due in the next {TaskService.UPCOMING_DAYS} days", upcoming, now, project_names),
            TaskService._section("Due later", later, now, project_names),
            TaskService._section("No due date", undated, now, project_names),
            TaskService._section("Done today", done_today, now, project_names),
        ]
        sections = [section for section in sections if section]

        if not sections:
            return None

        # The current time is in the prompt already (clock_context).
        return "\n\n".join(sections)
