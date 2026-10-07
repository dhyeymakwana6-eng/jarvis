import os
from typing import TypeVar

from ollama import chat
from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


class LLMUnavailableError(Exception):
    """Ollama couldn't be reached or failed to run the model."""


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
- Use the provided profile and memories as factual information
  about the user, and answer questions about the user from them.
- Never add details about the user that they don't state
  (don't expand abbreviations or guess names, places or dates).
- If asked about the user and the answer isn't in the profile or
  memories, say you don't know.
- Answer general questions (not about the user) normally, without
  mentioning memories.
- Be concise and accurate."""

    def generate_response(
        self,
        user_query: str,
        memory_context: str,
        profile_context: str | None = None,
        tracking_context: str | None = None
    ) -> str:

        system = self.SYSTEM_PROMPT

        if profile_context:
            system += f"\n\nUser Profile:\n{profile_context}"

        if tracking_context:
            system += f"\n\nProjects and Goals:\n{tracking_context}"

        system += f"\n\nRelevant Memories:\n{memory_context}"

        try:
            response = chat(
                model=self.MODEL,
                think=self.THINK,
                messages=[
                    {
                        "role": "system",
                        "content": system
                    },
                    {
                        "role": "user",
                        "content": user_query
                    }
                ]
            )
        except Exception as error:
            raise LLMUnavailableError(
                f"LLM call failed ({self.MODEL}): {error}"
            ) from error

        content = (response.message.content or "").strip()

        return content or self.EMPTY_RESPONSE_FALLBACK


    def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        response_model: type[T]
    ) -> T | None:
        """
        Asks the model for JSON matching response_model's schema
        (Ollama structured outputs). Returns None if the output doesn't
        validate, so callers can skip it. Raises LLMUnavailableError if
        the model can't be reached, so callers can retry later instead
        of losing the work.
        """
        try:
            response = chat(
                model=self.MODEL,
                think=False,
                format=response_model.model_json_schema(),
                options={"temperature": 0},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            )
        except Exception as error:
            raise LLMUnavailableError(
                f"LLM call failed ({self.MODEL}): {error}"
            ) from error

        try:
            return response_model.model_validate_json(response.message.content or "")
        except ValidationError as error:
            print(f"WARNING: structured generation returned invalid output: {error}")
            return None
