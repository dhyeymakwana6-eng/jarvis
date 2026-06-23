from ollama import chat


class LLMService:

    def generate_response(
        self,
        user_query: str,
        memory_context: str
    ) -> str:

        prompt = f"""
You are Jarvis, a personal AI assistant.

Rules:
- Never roleplay fictional characters.
- Never pretend the user is Tony Stark.
- Use the provided memories as factual information.
- If relevant memories exist, answer using them.
- Be concise and accurate.
- If no memory is relevant, say you do not know.

Relevant Memories:
{memory_context}

User Question:
{user_query}
"""

        response = chat(
            model="llama3:8b",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        print(response)

        return response.message.content