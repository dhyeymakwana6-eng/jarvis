from typing import List


class MemoryExtractor:
    """
    Extract candidate memories from user messages.
    """

    def extract(self, message: str) -> List[str]:
        """
        Extract memory candidates from a message.
        """

        candidates = []

        message_lower = message.lower()

        patterns = [
            "i am",
            "i'm",
            "my name is",
            "i study",
            "i work",
            "i like",
            "i love",
            "i prefer",
            "i want",
            "i am building",
            "i'm building",
            "my project is",
        ]

        for pattern in patterns:
            if pattern in message_lower:
                candidates.append(message.strip())
                break

        return candidates