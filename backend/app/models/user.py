from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(100))

    education: Mapped[str] = mapped_column(String(200))

    skills: Mapped[str] = mapped_column(String(500))

    preferences: Mapped[str] = mapped_column(String(500))