class MemoryScorer:
    """
    Assign importance scores to memories.
    """

    def score(self, memory: str) -> float:
        memory_lower = memory.lower()

        score = 0.5

        # Critical project information
        if any(keyword in memory_lower for keyword in [
            "project",
            "building",
            "developing",
            "creating"
        ]):
            score += 0.4

        # Education information
        if any(keyword in memory_lower for keyword in [
            "study",
            "student",
            "college",
            "university",
            "engineering"
        ]):
            score += 0.3

        # Goals and ambitions
        if any(keyword in memory_lower for keyword in [
            "goal",
            "want to",
            "plan to",
            "aim to"
        ]):
            score += 0.2

        # Preferences are useful but less critical
        if any(keyword in memory_lower for keyword in [
            "like",
            "love",
            "prefer",
            "favorite"
        ]):
            score -= 0.1

        # Clamp between 0 and 1
        score = max(0.0, min(score, 1.0))

        return round(score, 2)