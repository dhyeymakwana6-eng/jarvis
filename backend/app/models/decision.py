from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    decision: Mapped[str] = mapped_column(Text)

    reason: Mapped[str] = mapped_column(Text)
    