from app.models.memory import Memory


class ContextBuilder:

    @staticmethod
    def build(memories: list[Memory]) -> str:

        if not memories:
            return "No relevant memories found."

        context = "Known User Information:\n\n"

        for memory in memories:
            context += f"- {memory.content}\n"

        return context