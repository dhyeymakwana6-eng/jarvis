from .keywords import contains_any


class MemoryClassifier:
    """
    Classify memories into categories.
    """

    def classify(self, memory: str) -> str:
        if contains_any(memory, [
            "building",
            "project",
            "projects",
            "developing",
            "creating"
        ]):
            return "project"

        if contains_any(memory, [
            "study",
            "studying",
            "student",
            "college",
            "university",
            "engineering",
            "school"
        ]):
            return "education"

        if contains_any(memory, [
            "goal",
            "want to",
            "plan to",
            "aim to"
        ]):
            return "goal"

        if contains_any(memory, [
            "like",
            "likes",
            "love",
            "loves",
            "prefer",
            "favorite"
        ]):
            return "preference"

        if contains_any(memory, [
            "work",
            "working",
            "job",
            "company",
            "employee"
        ]):
            return "work"

        return "other"