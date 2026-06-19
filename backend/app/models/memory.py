from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    category: Mapped[str] = mapped_column(String(100))

    content: Mapped[str] = mapped_column(Text)

    importance: Mapped[int] = mapped_column(Integer)