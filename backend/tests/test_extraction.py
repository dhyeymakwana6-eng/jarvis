import pytest

from app.services.memory_extraction.extractor import MemoryExtractor
from app.services.memory_extraction.classifier import MemoryClassifier
from app.services.memory_extraction.scorer import MemoryScorer
from app.services.memory_extraction.keywords import contains_any


@pytest.fixture
def extractor():
    return MemoryExtractor()


def test_extracts_each_fact_sentence_separately(extractor):
    message = "I am building Jarvis. I live in Ahmedabad. Call me Ridz."

    assert extractor.extract(message) == [
        "I am building Jarvis.",
        "I live in Ahmedabad.",
        "Call me Ridz.",
    ]


def test_skips_questions_and_unrelated_sentences(extractor):
    message = "Where do I live? The weather is nice. I work at Google."

    assert extractor.extract(message) == ["I work at Google."]


@pytest.mark.parametrize("message", [
    "I am tired.",
    "I'm not sure.",
    "I am so bored today.",
    "I'm going to the gym.",
])
def test_skips_transient_states(extractor, message):
    assert extractor.extract(message) == []


@pytest.mark.parametrize("message", [
    "I'm tired but I work at Google.",
    "I am a mechanical engineering student.",
    "I'm learning Rust.",
])
def test_keeps_lasting_facts(extractor, message):
    assert extractor.extract(message) == [message]


def test_contains_any_matches_whole_words_only():
    assert contains_any("I like tea", ["like"])
    assert not contains_any("It is likely to rain", ["like"])
    assert contains_any("I WANT TO travel", ["want to"])


@pytest.mark.parametrize("memory, category", [
    ("I am building Jarvis", "project"),
    ("I study at PDEU", "education"),
    ("I plan to learn Rust", "goal"),
    ("I like tea", "preference"),
    ("I work at Google", "work"),
    ("It is likely done", "other"),
])
def test_classifier(memory, category):
    assert MemoryClassifier().classify(memory) == category


def test_scorer_ranks_projects_above_preferences_and_stays_in_range():
    scorer = MemoryScorer()

    project = scorer.score("I am building Jarvis")
    preference = scorer.score("I like tea")
    everything = scorer.score(
        "I am building a project and want to study at university"
    )

    assert project > preference
    assert 0.0 <= preference <= 1.0
    assert everything == 1.0
