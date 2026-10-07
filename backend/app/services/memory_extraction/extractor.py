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
        "i plan",
        "i enjoy",
        "i hate",
        "i dislike",
        "i don't like",
        "i live",
        "i moved",
        "i switched",
        "i use",
        "call me",
        "my favorite",
        "my favourite",
        "my goal",
        "my project is",
    ]

    # "I am ..." / "I'm ..." followed by one of these describes a
    # passing state, not a lasting fact ("I'm tired", "I am not sure").
    # going/trying/thinking are only transient when no plan follows:
    # "I'm going to the gym" is, "I'm going to learn Rust" isn't.
    TRANSIENT_STATE = re.compile(
        r"\b(?:i am|i'm)\s+(?:so\s+|very\s+|really\s+|just\s+|a bit\s+|kind of\s+)?"
        r"(?:not sure|tired|sleepy|hungry|thirsty|bored|busy|sick|fine|ok|okay|"
        r"good|great|sorry|sure|back|here|done|ready|confused|stressed|"
        r"excited|happy|sad|angry|late|wondering|"
        r"going(?!\s+to\s+(?!(?:the|a|an|my|bed|sleep)\b)\w)|"
        r"trying(?!\s+to\s+\w)|"
        r"thinking(?!\s+(?:about|of)\s+\w)|"
        r"curious|lost|stuck|free|available|away|home)\b",
        re.IGNORECASE
    )

    def _is_transient(self, sentence: str) -> bool:
        """
        True if the sentence's only self-description is a passing
        state. "I'm tired but I work at X" still counts as a fact.
        """
        if not self.TRANSIENT_STATE.search(sentence):
            return False

        remainder = self.TRANSIENT_STATE.sub("", sentence)

        return not contains_any(remainder, self.PATTERNS)

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
            and not self._is_transient(sentence)
        ]
