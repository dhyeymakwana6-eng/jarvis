from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database.connection import SessionLocal
from app.models.memory import Memory
from app.models.user import User
from app.schemas.profile import UserProfile
from app.services.llm_service import LLMService, LLMUnavailableError


class ProfileService:
    """
    Builds a structured user profile from memories with the LLM and
    caches it on the User row. Memory changes mark it stale; it is
    rebuilt in the background, never on the request path.
    """

    # Most important memories considered per rebuild, to keep the
    # prompt within a small local model's comfortable context.
    MAX_MEMORIES = 100

    SYSTEM_PROMPT = """You build a profile of a user from facts they told their personal assistant.
Fill every field the facts support:
- name: their name (add a nickname in parentheses if they gave one)
- education: school and/or degree
- work: current employer or job
- location: where they live
- skills, projects, goals, preferences: short phrases
- summary: two or three sentences
Use only what the facts state. Leave a field empty (null or []) if nothing supports it; never guess.
Facts are listed oldest first; if two facts conflict, trust the later one.
In the summary, refer to the user by name or as "they"; never assume gender."""

    @staticmethod
    def get(db: Session, user_id: int) -> User | None:
        return db.get(User, user_id)

    @staticmethod
    def mark_stale(db: Session, user_id: int):
        user = db.get(User, user_id)

        if user and not user.profile_stale:
            user.profile_stale = True
            db.commit()

    @staticmethod
    def rebuild(db: Session, user_id: int) -> UserProfile | None:
        """
        Rebuilds and saves the profile. Returns None (leaving the old
        profile in place) if the user doesn't exist or the LLM output
        is unusable. Raises LLMUnavailableError if the LLM is down.
        """
        user = db.get(User, user_id)

        if user is None:
            return None

        memories = (
            db.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.is_deleted == False
            )
            .order_by(Memory.importance.desc(), Memory.id.desc())
            .limit(ProfileService.MAX_MEMORIES)
            .all()
        )

        # Oldest first, so "trust the later one" holds in the prompt.
        memories.sort(key=lambda memory: memory.id)

        if memories:
            facts = "\n".join(f"- {memory.content}" for memory in memories)
        else:
            facts = "(no facts yet)"

        profile = LLMService().generate_structured(
            ProfileService.SYSTEM_PROMPT,
            f"Facts:\n{facts}",
            UserProfile
        )

        if profile is None:
            return None

        user.profile = profile.model_dump()
        user.profile_updated_at = datetime.now(timezone.utc)
        user.profile_stale = False

        # Keep the legacy columns in sync for anything still reading them.
        # A stated name wins; otherwise keep the name set at signup.
        if profile.name:
            user.name = profile.name[:100]
        user.education = (profile.education or "")[:200]
        user.skills = ", ".join(profile.skills)[:500]
        user.preferences = ", ".join(profile.preferences)[:500]

        db.commit()

        return profile

    @staticmethod
    def refresh_if_stale(user_id: int):
        """
        Background-task entry point. Opens its own session because the
        request's session is closed by the time this runs.
        """
        db = SessionLocal()

        try:
            user = db.get(User, user_id)

            if user and user.profile_stale:
                ProfileService.rebuild(db, user_id)
        except LLMUnavailableError as error:
            # Still marked stale, so the next refresh tries again.
            print(f"WARNING: profile refresh skipped: {error}")
        finally:
            db.close()

    @staticmethod
    def to_context(profile: dict | None) -> str | None:
        """Compact text form of the profile for the chat prompt."""
        if not profile:
            return None

        profile = UserProfile.model_validate(profile)

        lines = []

        for label, value in [
            ("Name", profile.name),
            ("Education", profile.education),
            ("Work", profile.work),
            ("Location", profile.location),
        ]:
            if value:
                lines.append(f"- {label}: {value}")

        for label, values in [
            ("Skills", profile.skills),
            ("Projects", profile.projects),
            ("Goals", profile.goals),
            ("Preferences", profile.preferences),
        ]:
            if values:
                lines.append(f"- {label}: {', '.join(values)}")

        if profile.summary:
            lines.append(f"- Summary: {profile.summary}")

        return "\n".join(lines) or None
