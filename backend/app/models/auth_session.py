from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class AuthSession(Base, TimestampMixin):
    """A signed-in browser. Only a hash of its token is stored."""
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # SHA-256 of the session token (the cookie holds the token itself).
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Which browser, to recognise sessions later (e.g. to revoke one).
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
