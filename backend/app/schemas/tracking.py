from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Status = Literal["active", "paused", "completed", "abandoned"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: Status = "active"
    next_action: str | None = Field(None, max_length=500)


class ProjectUpdate(BaseModel):
    # Partial update: only fields that are sent are changed.
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    status: Status | None = None
    next_action: str | None = Field(None, max_length=500)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    status: str
    next_action: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    project_id: int | None = None
    status: Status = "active"
    target_date: date | None = None
    progress: int = Field(0, ge=0, le=100)


class GoalUpdate(BaseModel):
    # Partial update: only fields that are sent are changed.
    title: str | None = Field(None, min_length=1, max_length=300)
    description: str | None = None
    project_id: int | None = None
    status: Status | None = None
    target_date: date | None = None
    progress: int | None = Field(None, ge=0, le=100)


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    project_id: int | None
    status: str
    target_date: date | None
    progress: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
