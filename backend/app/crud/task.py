from datetime import datetime, timezone

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.models.task import Task


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
    remind_at: datetime | None = None
) -> Task:
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

    _apply_status(task, changes.get("status"))

    db.commit()
    db.refresh(task)

    return task


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
    """Marks a delivered reminder as handled, so it isn't shown again."""
    task = get_task(db, user_id, task_id)

    if task is None or task.remind_at is None:
        return None

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
