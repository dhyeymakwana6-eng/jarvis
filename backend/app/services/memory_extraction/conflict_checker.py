from typing import Literal

from pydantic import BaseModel

from app.services.llm_service import LLMService


class ConflictVerdict(BaseModel):
    # Reason comes first so the model justifies before deciding;
    # measured more accurate than verdict-first.
    reason: str
    relation: Literal["same", "contradicts", "compatible"]


class ConflictChecker:
    """
    Uses the LLM to decide whether a new statement contradicts an
    existing memory. Only "contradicts" is acted on; "same" vs
    "compatible" mix-ups are harmless (the memory is just stored).
    """

    SYSTEM_PROMPT = """You compare two facts a user told their personal assistant at different times: an EXISTING memory and a NEW statement.
First give a one-sentence reason, then one relation:
- "same": both say the same thing, possibly in different words or with minor extra detail.
- "contradicts": both cannot be true now, so the NEW statement replaces the EXISTING one (e.g. a different employer, city, school, or a reversed preference).
- "compatible": both can be true at the same time (different topics, an added fact, or a nickname/alias alongside a name).
Only judge what is stated; do not assume."""

    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    def check(self, existing: str, new: str) -> ConflictVerdict | None:
        """None if the LLM is unavailable; callers treat that as no conflict."""
        return self.llm.generate_structured(
            self.SYSTEM_PROMPT,
            f"EXISTING: {existing}\nNEW: {new}",
            ConflictVerdict
        )
