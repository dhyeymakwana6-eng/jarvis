from datetime import datetime

from sqlalchemy import Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(100))

    education: Mapped[str] = mapped_column(String(200))

    skills: Mapped[str] = mapped_column(String(500))

    preferences: Mapped[str] = mapped_column(String(500))

    # Structured profile built from memories by ProfileService
    # (schema: app.schemas.profile.UserProfile).
    profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    profile_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set when memories change; the profile is rebuilt lazily.
    profile_stale: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
