from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Goal(Base, TimestampMixin):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(300))

    status: Mapped[str] = mapped_column(String(50))