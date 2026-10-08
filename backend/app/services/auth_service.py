import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.auth_session import AuthSession


class AuthService:
    """
    Single-user access control.

    JARVIS_PASSCODE: when set, every API route needs a session (a cookie
    from POST /auth/login) or the API token. When unset, the API is open
    (as before) and the HUD warns about it.

    JARVIS_API_TOKEN: optional bearer token for scripts and devices
    (`Authorization: Bearer <token>`); only accepted when it's set.
    """

    COOKIE = "jarvis_session"
    SESSION_DAYS = 30

    # Failed logins: after MAX_FAILURES within FAILURE_WINDOW, logins are
    # refused until the window passes (a single user, so one global limit).
    MAX_FAILURES = 5
    FAILURE_WINDOW = 5 * 60

    # Valid tokens are remembered briefly so the wake word's 2 requests a
    # second don't each hit the database. Logout clears it.
    CACHE_SECONDS = 60

    _failures: list[float] = []
    _cache: dict[str, tuple[int, float]] = {}
    _lock = threading.Lock()

    # ---------- Settings ----------

    @staticmethod
    def passcode() -> str | None:
        return os.getenv("JARVIS_PASSCODE") or None

    @staticmethod
    def api_token() -> str | None:
        return os.getenv("JARVIS_API_TOKEN") or None

    @classmethod
    def required(cls) -> bool:
        return cls.passcode() is not None

    @staticmethod
    def cookie_secure() -> bool:
        # Secure cookies are only sent over HTTPS; set this when serving it.
        return os.getenv("JARVIS_COOKIE_SECURE", "").lower() in ("1", "true", "yes")

    # ---------- Login ----------

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def locked_out(cls) -> int:
        """Seconds until logins are accepted again (0 if they are)."""
        now = time.monotonic()
        with cls._lock:
            cls._failures = [t for t in cls._failures if now - t < cls.FAILURE_WINDOW]
            if len(cls._failures) < cls.MAX_FAILURES:
                return 0
            return int(cls.FAILURE_WINDOW - (now - cls._failures[0])) + 1

    @classmethod
    def check_passcode(cls, attempt: str) -> bool:
        passcode = cls.passcode()
        ok = passcode is not None and hmac.compare_digest(attempt.encode(), passcode.encode())

        if not ok:
            with cls._lock:
                cls._failures.append(time.monotonic())

        return ok

    @classmethod
    def create_session(cls, db: Session, user_id: int, user_agent: str | None) -> str:
        """A new session; returns its token (for the cookie)."""
        token = secrets.token_urlsafe(32)

        # Tidy up while we're here.
        db.query(AuthSession).filter(AuthSession.expires_at <= datetime.now(timezone.utc)).delete()

        db.add(AuthSession(
            user_id=user_id,
            token_hash=cls._hash(token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=cls.SESSION_DAYS),
            user_agent=(user_agent or "")[:300] or None
        ))
        db.commit()

        return token

    @classmethod
    def end_session(cls, db: Session, token: str | None):
        if not token:
            return

        token_hash = cls._hash(token)
        db.query(AuthSession).filter(AuthSession.token_hash == token_hash).delete()
        db.commit()

        with cls._lock:
            cls._cache.pop(token_hash, None)

    # ---------- Checking requests ----------

    @classmethod
    def session_user(cls, db: Session, token: str | None) -> int | None:
        """The user a session token belongs to, or None if it's invalid or expired."""
        if not token:
            return None

        token_hash = cls._hash(token)
        now = time.monotonic()

        with cls._lock:
            cached = cls._cache.get(token_hash)
            if cached and now - cached[1] < cls.CACHE_SECONDS:
                return cached[0]

        session = (
            db.query(AuthSession)
            .filter(
                AuthSession.token_hash == token_hash,
                AuthSession.expires_at > datetime.now(timezone.utc)
            )
            .first()
        )

        if session is None:
            return None

        with cls._lock:
            cls._cache[token_hash] = (session.user_id, now)

        return session.user_id

    @classmethod
    def valid_api_token(cls, authorization: str | None) -> bool:
        token = cls.api_token()

        if not token or not authorization:
            return False

        scheme, _, value = authorization.partition(" ")

        return scheme.lower() == "bearer" and hmac.compare_digest(value.strip().encode(), token.encode())
