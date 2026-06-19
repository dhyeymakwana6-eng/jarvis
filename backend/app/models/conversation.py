from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_message: Mapped[str] = mapped_column(Text)

    assistant_message: Mapped[str] = mapped_column(Text)