from .keywords import contains_any


class MemoryScorer:
    """
    Assign importance scores to memories.
    """

    def score(self, memory: str) -> float:
        score = 0.5

        # Critical project information
        if contains_any(memory, [
            "project",
            "projects",
            "building",
            "developing",
            "creating"
        ]):
            score += 0.4

        # Education information
        if contains_any(memory, [
            "study",
            "studying",
            "student",
            "college",
            "university",
            "engineering"
        ]):
            score += 0.3

        # Goals and ambitions
        if contains_any(memory, [
            "goal",
            "want to",
            "plan to",
            "aim to"
        ]):
            score += 0.2

        # Preferences are useful but less critical
        if contains_any(memory, [
            "like",
            "likes",
            "love",
            "loves",
            "prefer",
            "favorite"
        ]):
            score -= 0.1

        # Clamp between 0 and 1
        score = max(0.0, min(score, 1.0))

        return round(score, 2)