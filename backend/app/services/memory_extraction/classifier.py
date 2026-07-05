class MemoryClassifier:
    """
    Classify memories into categories.
    """

    def classify(self, memory: str) -> str:
        memory_lower = memory.lower()

        if any(keyword in memory_lower for keyword in [
            "building",
            "project",
            "developing",
            "creating"
        ]):
            return "project"

        if any(keyword in memory_lower for keyword in [
            "study",
            "student",
            "college",
            "university",
            "engineering",
            "school"
        ]):
            return "education"

        if any(keyword in memory_lower for keyword in [
            "goal",
            "want to",
            "plan to",
            "aim to"
        ]):
            return "goal"

        if any(keyword in memory_lower for keyword in [
            "like",
            "love",
            "prefer",
            "favorite"
        ]):
            return "preference"

        if any(keyword in memory_lower for keyword in [
            "work",
            "job",
            "company",
            "employee"
        ]):
            return "work"

        return "other"