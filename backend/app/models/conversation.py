from sqlalchemy import Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    user_message: Mapped[str] = mapped_column(Text)

    assistant_message: Mapped[str] = mapped_column(Text)

    # Persona that replied (app.schemas.chat.Mode).
    mode: Mapped[str] = mapped_column(String(20), default="jarvis", server_default="jarvis")

    # False until memory extraction has run for this turn. Unprocessed
    # rows are picked up again at startup, so a restart mid-extraction
    # doesn't lose memories.
    memories_processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # What the assistant did this turn (app.services.agent_service.Action
    # dicts), e.g. tasks it created. None when it took no action.
    actions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
