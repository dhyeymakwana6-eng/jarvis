from datetime import date, datetime

from sqlalchemy import Integer, String, Text, ForeignKey, Boolean, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Goal(Base, TimestampMixin):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(300))

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # One of app.schemas.tracking.Status.
    status: Mapped[str] = mapped_column(String(50), default="active", server_default="active")

    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 0-100.
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
