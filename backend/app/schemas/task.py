from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


TaskStatus = Literal["todo", "done", "cancelled"]

Priority = Literal["low", "normal", "high"]


# Times must carry a UTC offset ("2026-10-07T17:00:00+05:30"), so a
# reminder fires at the moment the user meant, whatever the server's
# timezone.

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str | None = None
    project_id: int | None = None
    status: TaskStatus = "todo"
    priority: Priority = "normal"
    due_at: AwareDatetime | None = None
    remind_at: AwareDatetime | None = None


class TaskUpdate(BaseModel):
    # Partial update: only fields that are sent are changed.
    title: str | None = Field(None, min_length=1, max_length=300)
    notes: str | None = None
    project_id: int | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    due_at: AwareDatetime | None = None
    remind_at: AwareDatetime | None = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    notes: str | None
    project_id: int | None
    status: str
    priority: str
    due_at: datetime | None
    remind_at: datetime | None
    reminded_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SnoozeRequest(BaseModel):
    minutes: int = Field(10, ge=1, le=24 * 60)
