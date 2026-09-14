from datetime import datetime

from sqlalchemy import Integer, String, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    category: Mapped[str] = mapped_column(String(100))

    content: Mapped[str] = mapped_column(Text)

    importance: Mapped[int] = mapped_column(Integer)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")