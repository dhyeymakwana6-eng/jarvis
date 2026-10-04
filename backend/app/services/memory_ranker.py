import re
import math
from datetime import datetime, timezone

from app.models.memory import Memory
from app.services.query_terms import query_terms


class MemoryRanker:

    # Importance halves every DECAY_HALF_LIFE_DAYS since last access.
    DECAY_HALF_LIFE_DAYS = 30

    @staticmethod
    def _decayed_importance(memory: Memory) -> float:
        reference_time = memory.last_accessed_at or memory.created_at

        if reference_time is None:
            return float(memory.importance)

        now = datetime.now(timezone.utc)

        days_elapsed = (now - reference_time).total_seconds() / 86400

        decay_factor = 0.5 ** (days_elapsed / MemoryRanker.DECAY_HALF_LIFE_DAYS)

        return memory.importance * decay_factor

    @staticmethod
    def rank(memories: list[Memory], query: str, top_k: int | None = None):

        query_words = query_terms(query)

        scored_memories = []

        for memory in memories:

            score = 0

            memory_words = set(
                re.findall(r"\w+", memory.content.lower())
            )

            for word in query_words:

                if word in memory_words:
                    score += 1

            decayed_importance = MemoryRanker._decayed_importance(memory)

            scored_memories.append(
                (score, decayed_importance, memory)
            )

        scored_memories.sort(
            key=lambda x: (x[0], x[1]),
            reverse=True
        )

        ranked = [
            memory
            for score, decayed_importance, memory
            in scored_memories
            if score > 0
        ]

        return ranked[:top_k] if top_k is not None else ranked

    # Weights for rank_hybrid. Semantic similarity dominates; keyword
    # hits and (decayed) importance break ties and rescue memories
    # that have no embedding yet.
    SEMANTIC_WEIGHT = 0.6
    KEYWORD_WEIGHT = 0.25
    IMPORTANCE_WEIGHT = 0.15

    @staticmethod
    def _keyword_score(memory: Memory, query_words: list[str]) -> float:
        """Fraction of meaningful query words found in the memory (0-1)."""
        if not query_words:
            return 0.0

        memory_words = set(re.findall(r"\w+", memory.content.lower()))

        matches = sum(1 for word in query_words if word in memory_words)

        return matches / len(query_words)

    @staticmethod
    def rank_hybrid(
        semantic_matches: list[tuple[Memory, float]],
        keyword_matches: list[Memory],
        query: str,
        top_k: int | None = None
    ) -> list[Memory]:
        """
        Merges semantic (memory, cosine distance) results with keyword
        results into one ranking. A memory found by either path is a
        candidate; its score combines all three signals.
        """
        query_words = query_terms(query)

        distances = {memory.id: distance for memory, distance in semantic_matches}

        candidates = {memory.id: memory for memory, _ in semantic_matches}
        for memory in keyword_matches:
            candidates.setdefault(memory.id, memory)

        scored = []

        for memory_id, memory in candidates.items():
            semantic = (
                1 - distances[memory_id]
                if memory_id in distances
                else 0.0
            )

            keyword = MemoryRanker._keyword_score(memory, query_words)

            # Importance is stored on a 0-100 scale.
            importance = min(MemoryRanker._decayed_importance(memory) / 100, 1.0)

            score = (
                MemoryRanker.SEMANTIC_WEIGHT * semantic
                + MemoryRanker.KEYWORD_WEIGHT * keyword
                + MemoryRanker.IMPORTANCE_WEIGHT * importance
            )

            scored.append((score, memory))

        scored.sort(key=lambda x: x[0], reverse=True)

        ranked = [memory for score, memory in scored]

        return ranked[:top_k] if top_k is not None else ranked
