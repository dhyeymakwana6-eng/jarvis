from sqlalchemy import Integer, Text, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    user_message: Mapped[str] = mapped_column(Text)

    assistant_message: Mapped[str] = mapped_column(Text)

    # False until memory extraction has run for this turn. Unprocessed
    # rows are picked up again at startup, so a restart mid-extraction
    # doesn't lose memories.
    memories_processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
