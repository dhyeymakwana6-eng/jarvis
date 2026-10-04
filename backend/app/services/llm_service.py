import os

from ollama import chat


class LLMService:

    MODEL = os.getenv("LLM_MODEL", "qwen3.5:9b")

    # qwen3.5 is a reasoning model. With thinking on it spent ~3.6k
    # tokens (minutes) per reply and sometimes returned empty content;
    # off, replies take ~1-2s. Set LLM_THINK=true to re-enable.
    THINK = os.getenv("LLM_THINK", "false").lower() == "true"

    EMPTY_RESPONSE_FALLBACK = "Sorry, I couldn't generate a response. Please try again."

    SYSTEM_PROMPT = """You are Jarvis, a personal AI assistant.

Rules:
- Never roleplay fictional characters.
- Never pretend the user is Tony Stark.
- Use the provided memories as factual information.
- If relevant memories exist, answer using them.
- Never add details about the user that the memories don't state
  (don't expand abbreviations or guess names, places or dates).
- Be concise and accurate.
- If no memory is relevant, say you do not know."""

    def generate_response(
        self,
        user_query: str,
        memory_context: str
    ) -> str:

        response = chat(
            model=self.MODEL,
            think=self.THINK,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{self.SYSTEM_PROMPT}\n\n"
                        f"Relevant Memories:\n{memory_context}"
                    )
                },
                {
                    "role": "user",
                    "content": user_query
                }
            ]
        )

        content = (response.message.content or "").strip()

        return content or self.EMPTY_RESPONSE_FALLBACK
