from datetime import datetime, time, timedelta, timezone

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.core import recurrence as rules
from app.core.clock import local_timezone
from app.models.task import Task

# When a repeating task is given no time, its reminder goes off at this hour.
DEFAULT_REPEAT_TIME = time(9, 0)


def _apply_status(task: Task, status: str | None):
    """Keeps completed_at consistent with status."""
    if status is None or status == task.status:
        return

    task.status = status
    task.completed_at = datetime.now(timezone.utc) if status == "done" else None


def create_task(
    db: Session,
    user_id: int,
    title: str,
    notes: str | None = None,
    project_id: int | None = None,
    status: str = "todo",
    priority: str = "normal",
    due_at: datetime | None = None,
    remind_at: datetime | None = None,
    recurrence: str | None = None
) -> Task:
    """recurrence: a rule (app.core.recurrence); raises RecurrenceError if invalid."""
    task = Task(
        user_id=user_id,
        title=title,
        notes=notes,
        project_id=project_id,
        status="todo",
        priority=priority,
        due_at=due_at,
        remind_at=remind_at
    )
    _apply_status(task, status)
    _set_recurrence(task, recurrence)

    db.add(task)
    db.commit()
    db.refresh(task)

    return task


# High priority first within the same due time.
_PRIORITY_ORDER = case(
    {"high": 0, "normal": 1, "low": 2},
    value=Task.priority,
    else_=1
)


def get_tasks(
    db: Session,
    user_id: int,
    status: str | None = None,
    project_id: int | None = None,
    due_before: datetime | None = None
) -> list[Task]:
    query = db.query(Task).filter(
        Task.user_id == user_id,
        Task.is_deleted == False
    )

    if status:
        query = query.filter(Task.status == status)

    if project_id is not None:
        query = query.filter(Task.project_id == project_id)

    if due_before is not None:
        query = query.filter(Task.due_at <= due_before)

    # Soonest due first; undated tasks last.
    return query.order_by(Task.due_at.asc().nulls_last(), _PRIORITY_ORDER, Task.id).all()


def get_task(db: Session, user_id: int, task_id: int) -> Task | None:
    return (
        db.query(Task)
        .filter(
            Task.id == task_id,
            Task.user_id == user_id,
            Task.is_deleted == False
        )
        .first()
    )


def find_task_by_title(db: Session, user_id: int, title: str) -> Task | None:
    """Case-insensitive exact title match among the user's open tasks."""
    title = title.strip().lower()

    for task in get_tasks(db, user_id, status="todo"):
        if task.title.strip().lower() == title:
            return task

    return None


def update_task(
    db: Session,
    user_id: int,
    task_id: int,
    changes: dict
) -> Task | None:
    """changes holds only the fields to set (partial update)."""
    task = get_task(db, user_id, task_id)

    if task is None:
        return None

    for field in ("title", "notes", "project_id", "priority", "due_at"):
        if field in changes:
            setattr(task, field, changes[field])

    if "remind_at" in changes and changes["remind_at"] != task.remind_at:
        task.remind_at = changes["remind_at"]
        # Rescheduled (or cleared): the new reminder hasn't fired yet.
        task.reminded_at = None

    if "recurrence" in changes:
        _set_recurrence(task, changes["recurrence"])

    completing = changes.get("status") == "done" and task.status != "done"
    _apply_status(task, changes.get("status"))

    if completing and task.recurrence:
        db.add(_next_occurrence(task))

    db.commit()
    db.refresh(task)

    return task


# ---------- Repeating tasks ----------

def _set_recurrence(task: Task, rule: str | None):
    """
    Sets (or with None/"" clears) the repeat rule. A repeating task needs
    a time to repeat from: without one, its reminder is set to the next
    DEFAULT_REPEAT_TIME on a day the rule allows.
    """
    if not rule:
        task.recurrence = None
        return

    rule = rules.normalize(rule)
    now = datetime.now(timezone.utc)
    tz = local_timezone()
    tied_to_days = rule == "weekdays" or rule.startswith("weekly:")

    if task.due_at is None and task.remind_at is None:
        yesterday = datetime.combine(now.astimezone(tz).date() - timedelta(days=1), DEFAULT_REPEAT_TIME, tz)
        # The first slot still ahead (today's, if so): on an allowed day
        # for rules tied to weekdays; any day for the rest, which then
        # repeat from it.
        task.remind_at = rules.next_occurrence(rule if tied_to_days else "daily", yesterday, now)
        task.reminded_at = None

    elif tied_to_days:
        # The given time may fall on a day the rule skips (the LLM picks
        # a date for "every Mon and Thu at 8pm"): start at the first
        # allowed day at that time, from now, or from the given day when
        # it's an explicit start more than a week out.
        anchor = task.due_at or task.remind_at
        wall = anchor.astimezone(tz).timetz().replace(tzinfo=None)
        start = anchor if anchor - now > timedelta(days=7) else now
        day_before = datetime.combine(start.astimezone(tz).date() - timedelta(days=1), wall, tz)
        first = rules.next_occurrence(rule, day_before, start - timedelta(seconds=1))
        if first != anchor:
            task.due_at = _shift(task.due_at, anchor, first)
            task.remind_at = _shift(task.remind_at, anchor, first)
            task.reminded_at = None

    task.recurrence = rules.pin(rule, task.due_at or task.remind_at)


def _shift(moment: datetime | None, anchor: datetime, target: datetime) -> datetime | None:
    """Moves `moment` by as many calendar days as anchor -> target, same wall time."""
    if moment is None:
        return None
    tz = local_timezone()
    days = (target.astimezone(tz).date() - anchor.astimezone(tz).date()).days
    local = moment.astimezone(tz)
    return datetime.combine(local.date() + timedelta(days=days), local.timetz().replace(tzinfo=None), tz)


def _next_occurrence(task: Task) -> Task:
    """The task's next occurrence after now (missed ones are skipped)."""
    anchor = task.due_at or task.remind_at
    target = rules.next_occurrence(task.recurrence, anchor, datetime.now(timezone.utc))

    return Task(
        user_id=task.user_id,
        title=task.title,
        notes=task.notes,
        project_id=task.project_id,
        status="todo",
        priority=task.priority,
        due_at=_shift(task.due_at, anchor, target),
        remind_at=_shift(task.remind_at, anchor, target),
        recurrence=task.recurrence
    )


def delete_task(db: Session, user_id: int, task_id: int) -> Task | None:
    task = get_task(db, user_id, task_id)

    if task is None:
        return None

    task.is_deleted = True
    db.commit()

    return task


# ---------- Reminders ----------

def get_due_reminders(db: Session, user_id: int, now: datetime) -> list[Task]:
    """Open tasks whose reminder time has passed and hasn't been handled."""
    return (
        db.query(Task)
        .filter(
            Task.user_id == user_id,
            Task.is_deleted == False,
            Task.status == "todo",
            Task.remind_at.isnot(None),
            Task.remind_at <= now,
            Task.reminded_at.is_(None)
        )
        .order_by(Task.remind_at, Task.id)
        .all()
    )


def acknowledge_reminder(db: Session, user_id: int, task_id: int, now: datetime) -> Task | None:
    """
    Marks a delivered reminder as handled, so it isn't shown again. A
    repeating reminder without a deadline ("stretch every day at 4") moves
    on to its next time instead.
    """
    task = get_task(db, user_id, task_id)

    if task is None or task.remind_at is None:
        return None

    if task.recurrence and task.due_at is None:
        task.remind_at = rules.next_occurrence(task.recurrence, task.remind_at, now)
        task.reminded_at = None
    else:
        task.reminded_at = now
    db.commit()
    db.refresh(task)

    return task


def snooze_reminder(db: Session, user_id: int, task_id: int, until: datetime) -> Task | None:
    task = get_task(db, user_id, task_id)

    if task is None:
        return None

    task.remind_at = until
    task.reminded_at = None
    db.commit()
    db.refresh(task)

    return task
