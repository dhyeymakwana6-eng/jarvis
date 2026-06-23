import re

from app.models.memory import Memory


class MemoryRanker:

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

            scored_memories.append(
                (score, memory)
            )

        scored_memories.sort(
            key=lambda x: (
                x[0],
                x[1].importance
            ),
            reverse=True
        )

        return [
            memory
            for score, memory
            in scored_memories
            if score > 0
        ]