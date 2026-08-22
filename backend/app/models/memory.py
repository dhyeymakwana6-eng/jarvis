from sqlalchemy import Integer, String, Text, ForeignKey
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