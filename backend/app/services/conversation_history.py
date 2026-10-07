from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.conversation import Conversation


class ConversationHistory:
    """
    Recent chat turns, so follow-ups ("and the second one?") make sense.

    Turns come from the conversations log. A session is the run of
    turns since the last IDLE_GAP of silence; older turns are left to
    long-term memory instead of being replayed to the LLM.
    """

    IDLE_GAP = timedelta(minutes=30)

    # Most recent turns sent to the LLM.
    MAX_TURNS = 6

    # Ollama often runs models with a small context window by default,
    # so history is also capped by size (~1.5k tokens), dropping the
    # oldest turns first.
    MAX_CHARS = 6000

    @staticmethod
    def current_session(
        db: Session,
        user_id: int,
        limit: int = MAX_TURNS,
        now: datetime | None = None
    ) -> list[Conversation]:
        """Up to `limit` turns of the current session, oldest first."""
        now = now or datetime.now(timezone.utc)

        recent = (
            db.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
            .all()
        )

        session = []
        newer = now

        for turn in recent:
            if newer - turn.created_at > ConversationHistory.IDLE_GAP:
                break

            session.append(turn)
            newer = turn.created_at

        session.reverse()

        return session

    @staticmethod
    def for_prompt(
        db: Session,
        user_id: int,
        now: datetime | None = None
    ) -> list[tuple[str, str]]:
        """(user, assistant) pairs for the LLM, oldest first, within MAX_CHARS."""
        turns = ConversationHistory.current_session(db, user_id, now=now)

        pairs = []
        total = 0

        for turn in reversed(turns):
            size = len(turn.user_message) + len(turn.assistant_message)

            if total + size > ConversationHistory.MAX_CHARS:
                break

            pairs.append((turn.user_message, turn.assistant_message))
            total += size

        pairs.reverse()

        return pairs
