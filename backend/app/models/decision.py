from sqlalchemy import Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    decision: Mapped[str] = mapped_column(Text)

    reason: Mapped[str] = mapped_column(Text)