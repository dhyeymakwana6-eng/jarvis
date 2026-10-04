import re


def contains_any(text: str, keywords: list[str]) -> bool:
    """
    True if any keyword/phrase appears in text as whole words,
    case-insensitively. "like" matches "I like tea" but not "likely".
    """
    pattern = r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b"
    return re.search(pattern, text, re.IGNORECASE) is not None
