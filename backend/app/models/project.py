from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    name: Mapped[str] = mapped_column(String(200))

    status: Mapped[str] = mapped_column(String(50))

    next_action: Mapped[str] = mapped_column(String(500))