import re


# Words that carry no topic on their own. Without this, "what is the
# capital of France?" keyword-matches any memory containing "the".
STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "you", "your", "yours",
    "what", "whats", "where", "when", "who", "whom", "why", "how",
    "which", "does", "did", "have", "has", "had", "can", "could",
    "would", "should", "will", "about", "with", "this", "that", "these",
    "those", "there", "then", "than", "from", "into", "mine", "tell",
    "know", "like", "any", "some", "all", "not", "but", "too", "very",
    "just", "also", "its", "our", "out", "get", "got", "much", "many",
}


def query_terms(text: str) -> list[str]:
    """Meaningful lowercase words from a query, for keyword matching."""
    return [
        word
        for word in re.findall(r"\w+", text.lower())
        if len(word) > 2 and word not in STOPWORDS
    ]
