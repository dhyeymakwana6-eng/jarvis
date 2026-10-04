from app.models.memory import Memory
from app.services.memory_extraction.conflict_checker import ConflictVerdict
from app.services.memory_extraction.deduplicator import (
    DeduplicationDecision,
    MemoryDeduplicator,
)
from app.services.profile_service import ProfileService
from app.services.llm_service import LLMService


class FakeChecker:
    def __init__(self, relations):
        self.relations = relations
        self.calls = []

    def check(self, existing, new):
        self.calls.append(existing)
        relation = self.relations.get(existing)
        return ConflictVerdict(reason="test", relation=relation) if relation else None


def memory(id, content):
    return Memory(id=id, content=content)


def test_find_conflict_returns_first_contradiction():
    checker = FakeChecker({
        "I like hiking": "compatible",
        "I work at Anthropic": "contradicts",
    })
    dedup = MemoryDeduplicator(checker)

    result = dedup._find_conflict(
        "I work at Google now",
        [(memory(1, "I like hiking"), 0.25), (memory(2, "I work at Anthropic"), 0.20)],
    )

    assert result.decision == DeduplicationDecision.CONFLICT
    assert result.existing_memory_id == 2


def test_find_conflict_ignores_unavailable_llm_and_disabled_checker():
    candidates = [(memory(1, "I work at Anthropic"), 0.2)]

    assert MemoryDeduplicator(FakeChecker({}))._find_conflict("x", candidates) is None
    assert MemoryDeduplicator(None)._find_conflict("x", candidates) is None


def test_profile_to_context_lists_only_filled_fields():
    context = ProfileService.to_context({
        "name": "Ridham",
        "education": None,
        "work": "Google",
        "location": None,
        "skills": [],
        "projects": ["Jarvis"],
        "goals": [],
        "preferences": ["light mode", "hiking"],
        "summary": "Ridham builds Jarvis.",
    })

    assert context == (
        "- Name: Ridham\n"
        "- Work: Google\n"
        "- Projects: Jarvis\n"
        "- Preferences: light mode, hiking\n"
        "- Summary: Ridham builds Jarvis."
    )


def test_profile_to_context_handles_missing_profile():
    assert ProfileService.to_context(None) is None


def test_llm_empty_reply_falls_back(monkeypatch):
    class Reply:
        class message:
            content = "   "

    monkeypatch.setattr("app.services.llm_service.chat", lambda **kwargs: Reply)

    assert LLMService().generate_response("hi", "none") == LLMService.EMPTY_RESPONSE_FALLBACK


def test_llm_structured_returns_none_on_bad_json(monkeypatch):
    class Reply:
        class message:
            content = "not json"

    monkeypatch.setattr("app.services.llm_service.chat", lambda **kwargs: Reply)

    assert LLMService().generate_structured("s", "u", ConflictVerdict) is None
