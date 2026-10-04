import re
from typing import List

from .keywords import contains_any


class MemoryExtractor:
    """
    Extract candidate memories from user messages.
    """

    PATTERNS = [
        "i am",
        "i'm",
        "my name is",
        "i study",
        "i work",
        "i like",
        "i love",
        "i prefer",
        "i want",
        "my project is",
    ]

    def extract(self, message: str) -> List[str]:
        """
        Extract memory candidates from a message. Each sentence that
        contains a self-describing pattern becomes its own candidate,
        so questions and unrelated sentences aren't stored.
        """

        sentences = re.split(r"(?<=[.!?])\s+|\n+", message.strip())

        return [
            sentence.strip()
            for sentence in sentences
            if sentence.strip()
            and not sentence.strip().endswith("?")
            and contains_any(sentence, self.PATTERNS)
        ]
