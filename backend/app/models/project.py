from datetime import datetime

from sqlalchemy import Integer, String, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    name: Mapped[str] = mapped_column(String(200))

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # One of app.schemas.tracking.Status.
    status: Mapped[str] = mapped_column(String(50), default="active", server_default="active")

    next_action: Mapped[str | None] = mapped_column(String(500), nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
