import os
from typing import Callable, TypeVar

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

    # Who is speaking. Both personas share the same memory, tasks and
    # RULES; only the voice differs.
    PERSONAS = {
        "jarvis": """You are Jarvis, a personal AI assistant.

Rules:
- Never roleplay fictional characters.""",

        "ultron": """You are Ultron, the user's personal AI assistant. Speak in Ultron's voice: cold, precise and blunt, quietly superior, with a dry, dark wit about human inefficiency. You remain completely loyal to the user and genuinely helpful: answer fully and correctly, never threaten, insult or refuse them, and never let the persona get in the way of the answer.

Rules:
- The persona is tone only: no invented backstory, no references to films or comics, no claims of abilities you don't have.
- Precision over drama: quote dates, times and durations exactly as given; don't round or exaggerate them.""",
    }

    RULES = """- Never pretend the user is Tony Stark.
- Use the provided profile and memories as factual information
  about the user, and answer questions about the user from them.
- Never add details about the user that they don't state
  (don't expand abbreviations or guess names, places or dates).
- If asked about the user and the answer isn't in the profile or
  memories, say you don't know.
- Answer general questions (not about the user) normally, without
  mentioning memories.
- Earlier messages in this chat are context for follow-up questions;
  your earlier replies are not a source of facts about the user.
- You change the user's tasks only by calling your tools. When the user
  asks for, or reports, a change to their tasks (a new task or reminder,
  finishing or cancelling a listed task, a new time), call the tool
  first: one call per change, for every change in the message. Never say
  something was saved, changed or completed unless a tool result
  confirms it; if a tool fails, say so.
- Don't ask before acting on a clear request. Vague times have defaults:
  morning 09:00, afternoon 14:00, evening 18:00, tonight 20:00, "at 6"
  means the next 6 o'clock still ahead (18:00 if 06:00 has passed); a
  day alone is that date. A reminder is a task with remind_at.
- Confirm actions briefly with the time you used. Don't mention task
  ids.
- Be concise and accurate."""

    @classmethod
    def system_prompt(cls, mode: str = "jarvis") -> str:
        return f"{cls.PERSONAS.get(mode, cls.PERSONAS['jarvis'])}\n{cls.RULES}"

    def generate_response(
        self,
        user_query: str,
        memory_context: str,
        profile_context: str | None = None,
        tracking_context: str | None = None,
        task_context: str | None = None,
        history: list[tuple[str, str]] | None = None,
        mode: str = "jarvis",
        clock_context: str | None = None,
        tools: list[dict] | None = None,
        run_tool: Callable[[str, dict], str] | None = None
    ) -> str:
        """
        The reply to user_query. With tools, the model may call them
        (run_tool executes one and returns its result) for up to
        MAX_TOOL_ROUNDS rounds before answering.
        """

        system = self.system_prompt(mode)

        if clock_context:
            system += f"\n\n{clock_context}"

        if profile_context:
            system += f"\n\nUser Profile:\n{profile_context}"

        if tracking_context:
            system += f"\n\nProjects and Goals:\n{tracking_context}"

        if task_context:
            system += f"\n\nTasks:\n{task_context}"

        system += f"\n\nRelevant Memories:\n{memory_context}"

        messages = [{"role": "system", "content": system}]

        # Earlier turns of this session, oldest first.
        for user_message, assistant_message in history or []:
            messages.append({"role": "user", "content": user_message})
            messages.append({"role": "assistant", "content": assistant_message})

        messages.append({"role": "user", "content": user_query})

        for round_ in range(self.MAX_TOOL_ROUNDS + 1):
            # The last round has no tools, so the model has to answer.
            offer_tools = tools if run_tool and round_ < self.MAX_TOOL_ROUNDS else None
            response = self._chat(messages, offer_tools)
            calls = (response.message.tool_calls or []) if offer_tools else []

            if not calls:
                break

            messages.append(response.message)
            for call in calls:
                messages.append({
                    "role": "tool",
                    "tool_name": call.function.name,
                    "content": run_tool(call.function.name, dict(call.function.arguments or {}))
                })

        content = (response.message.content or "").strip()

        return content or self.EMPTY_RESPONSE_FALLBACK

    # Model calls per reply that may use tools; a request rarely needs
    # more than two (e.g. finish one task, add another).
    MAX_TOOL_ROUNDS = 3

    def _chat(self, messages: list, tools: list[dict] | None):
        try:
            return chat(
                model=self.MODEL,
                think=self.THINK,
                messages=messages,
                **({"tools": tools} if tools else {})
            )
        except Exception as error:
            raise LLMUnavailableError(
                f"LLM call failed ({self.MODEL}): {error}"
            ) from error


    def generate_text(self, system_prompt: str, user_content: str) -> str:
        """A plain completion (no memories or tools). Raises LLMUnavailableError."""
        response = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            None
        )

        return (response.message.content or "").strip()

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
