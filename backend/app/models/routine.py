from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class RoutineRun(Base, TimestampMixin):
    """
    One delivery of a scheduled routine (the morning briefing or evening
    review): at most one per kind per day, which the HUD shows until
    dismissed.
    """
    __tablename__ = "routine_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "run_date", name="uq_routine_runs_user_kind_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # "morning" or "evening" (app.services.routine_service.ROUTINES).
    kind: Mapped[str] = mapped_column(String(20))

    # The user's local date it belongs to.
    run_date: Mapped[date] = mapped_column(Date)

    text: Mapped[str] = mapped_column(Text)

    # Persona it was written in.
    mode: Mapped[str] = mapped_column(String(20), default="jarvis", server_default="jarvis")

    # Set when the user dismisses it on any device.
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
