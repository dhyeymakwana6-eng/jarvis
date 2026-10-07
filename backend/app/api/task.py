from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.core.constants import DEFAULT_USER_ID

from app.schemas.task import (
    TaskStatus,
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    SnoozeRequest
)

from app.crud.task import (
    create_task,
    get_tasks,
    get_task,
    update_task,
    delete_task,
    get_due_reminders,
    acknowledge_reminder,
    snooze_reminder
)
from app.crud.tracking import get_project

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"]
)

reminders_router = APIRouter(
    prefix="/reminders",
    tags=["Reminders"]
)


def _not_found():
    return HTTPException(
        status_code=404,
        detail="Task not found"
    )


def _check_project(db: Session, project_id: int | None):
    if project_id is not None and not get_project(db, DEFAULT_USER_ID, project_id):
        raise HTTPException(
            status_code=422,
            detail=f"Project {project_id} not found"
        )


@router.post(
    "",
    response_model=TaskResponse
)
def create_task_endpoint(
    task: TaskCreate,
    db: Session = Depends(get_db)
):
    _check_project(db, task.project_id)

    return create_task(
        db,
        DEFAULT_USER_ID,
        **task.model_dump()
    )


@router.get(
    "",
    response_model=list[TaskResponse]
)
def get_tasks_endpoint(
    status: TaskStatus | None = None,
    project_id: int | None = None,
    due_before: AwareDatetime | None = None,
    db: Session = Depends(get_db)
):
    return get_tasks(db, DEFAULT_USER_ID, status, project_id, due_before)


@router.get(
    "/{task_id}",
    response_model=TaskResponse
)
def get_task_endpoint(
    task_id: int,
    db: Session = Depends(get_db)
):
    task = get_task(db, DEFAULT_USER_ID, task_id)

    if not task:
        raise _not_found()

    return task


@router.patch(
    "/{task_id}",
    response_model=TaskResponse
)
def update_task_endpoint(
    task_id: int,
    changes: TaskUpdate,
    db: Session = Depends(get_db)
):
    changes_dict = changes.model_dump(exclude_unset=True)

    _check_project(db, changes_dict.get("project_id"))

    task = update_task(db, DEFAULT_USER_ID, task_id, changes_dict)

    if not task:
        raise _not_found()

    return task


@router.delete("/{task_id}")
def delete_task_endpoint(
    task_id: int,
    db: Session = Depends(get_db)
):
    if not delete_task(db, DEFAULT_USER_ID, task_id):
        raise _not_found()

    return {
        "message": "Task deleted"
    }


# ---------- Reminders ----------
# Clients poll /reminders/due and then dismiss, snooze or complete each
# one (PATCH /tasks/{id} with status "done"). The first device to act
# handles it; others drop it on their next poll.

@reminders_router.get(
    "/due",
    response_model=list[TaskResponse]
)
def due_reminders_endpoint(
    db: Session = Depends(get_db)
):
    return get_due_reminders(db, DEFAULT_USER_ID, datetime.now(timezone.utc))


@reminders_router.post(
    "/{task_id}/dismiss",
    response_model=TaskResponse
)
def dismiss_reminder_endpoint(
    task_id: int,
    db: Session = Depends(get_db)
):
    task = acknowledge_reminder(db, DEFAULT_USER_ID, task_id, datetime.now(timezone.utc))

    if not task:
        raise _not_found()

    return task


@reminders_router.post(
    "/{task_id}/snooze",
    response_model=TaskResponse
)
def snooze_reminder_endpoint(
    task_id: int,
    snooze: SnoozeRequest,
    db: Session = Depends(get_db)
):
    until = datetime.now(timezone.utc) + timedelta(minutes=snooze.minutes)

    task = snooze_reminder(db, DEFAULT_USER_ID, task_id, until)

    if not task:
        raise _not_found()

    return task
