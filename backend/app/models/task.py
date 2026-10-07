from datetime import datetime

from sqlalchemy import Integer, String, Text, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Task(Base, TimestampMixin):
    """
    A to-do item. A plain reminder ("remind me to call mom at 5") is a
    task with remind_at set.
    """
    __tablename__ = "tasks"
    __table_args__ = (
        # Reminder delivery looks up a user's tasks by remind_at.
        Index("ix_tasks_user_remind_at", "user_id", "remind_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(300))

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # One of app.schemas.task.TaskStatus.
    status: Mapped[str] = mapped_column(String(20), default="todo", server_default="todo")

    # One of app.schemas.task.Priority.
    priority: Mapped[str] = mapped_column(String(20), default="normal", server_default="normal")

    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set when the reminder has been delivered; cleared when remind_at
    # changes, so a rescheduled reminder fires again.
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
