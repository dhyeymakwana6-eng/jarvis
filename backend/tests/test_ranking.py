from datetime import datetime, timedelta, timezone

from app.models.memory import Memory
from app.services.memory_ranker import MemoryRanker
from app.services.query_terms import query_terms


def make_memory(id, content, importance=50, days_old=0):
    timestamp = datetime.now(timezone.utc) - timedelta(days=days_old)

    return Memory(
        id=id,
        content=content,
        importance=importance,
        created_at=timestamp,
        last_accessed_at=timestamp,
    )


def test_query_terms_drop_stopwords_and_short_words():
    assert query_terms("What is the capital of France?") == ["capital", "france"]


def test_decay_halves_importance_after_half_life():
    memory = make_memory(1, "x", importance=80, days_old=MemoryRanker.DECAY_HALF_LIFE_DAYS)

    assert abs(MemoryRanker._decayed_importance(memory) - 40) < 0.5


def test_keyword_rank_uses_whole_words_and_drops_non_matches():
    memories = [
        make_memory(1, "I like to start projects"),
        make_memory(2, "I make art"),
    ]

    ranked = MemoryRanker.rank(memories, "tell me about art")

    assert [memory.id for memory in ranked] == [2]


def test_rank_hybrid_prefers_semantic_match_and_respects_top_k():
    close = make_memory(1, "I work at Google")
    keyword_only = make_memory(2, "Google Maps is useful")
    far = make_memory(3, "I like hiking")

    ranked = MemoryRanker.rank_hybrid(
        semantic_matches=[(close, 0.30), (far, 0.47)],
        keyword_matches=[keyword_only],
        query="where do I work?",
        top_k=2,
    )

    assert [memory.id for memory in ranked] == [1, 3]


def test_rank_hybrid_includes_keyword_only_candidates():
    keyword_only = make_memory(2, "Google Maps is useful")

    ranked = MemoryRanker.rank_hybrid([], [keyword_only], "google maps")

    assert ranked == [keyword_only]
