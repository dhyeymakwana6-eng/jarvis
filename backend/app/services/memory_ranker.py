import re
import math
from datetime import datetime, timezone

from app.models.memory import Memory


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
    def rank(memories: list[Memory], query: str):

        query_words = re.findall(
            r"\w+",
            query.lower()
        )

        scored_memories = []

        for memory in memories:

            score = 0

            memory_text = memory.content.lower()

            for word in query_words:

                if len(word) <= 2:
                    continue

                if word in memory_text:
                    score += 1

            decayed_importance = MemoryRanker._decayed_importance(memory)

            scored_memories.append(
                (score, decayed_importance, memory)
            )

        scored_memories.sort(
            key=lambda x: (x[0], x[1]),
            reverse=True
        )

        return [
            memory
            for score, decayed_importance, memory
            in scored_memories
            if score > 0
        ]