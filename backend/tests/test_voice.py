import io
import wave

import pytest

from app.services.voice_service import VoiceService, VoiceUnavailableError


@pytest.mark.parametrize("text, spoken", [
    ("**Call mom.** Due at 20:00.", "Call mom. Due at 20:00."),
    ("Plan:\n1. Submit the report\n2. Call mom", "Plan: Submit the report. Call mom"),
    ("- [high] Buy milk\n- Read `paper.pdf`", "[high] Buy milk. Read paper.pdf"),
    ("## Status\nAll *systems* nominal.", "Status. All systems nominal."),
    ("See [the docs](http://x.y) now.", "See the docs now."),
    ("Run this:\n```\nrm -rf /\n```\nDone.", "Run this: Done."),
    ("snake_case_name stays", "snake_case_name stays"),
])
def test_speakable_strips_markdown(text, spoken):
    assert VoiceService.speakable(text) == spoken


def test_speakable_cuts_long_text_at_a_sentence():
    text = "One sentence here. " * 100

    spoken = VoiceService.speakable(text, limit=50)

    assert spoken == "One sentence here. One sentence here."


class FakeVoice:
    def __init__(self):
        self.calls = []

    def synthesize_wav(self, text, wav, syn_config=None):
        self.calls.append((text, syn_config.length_scale))
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x00" * 2205)


def test_speak_endpoint_returns_wav_in_the_modes_voice(client, monkeypatch):
    voice = FakeVoice()
    monkeypatch.setattr(VoiceService, "_voice", classmethod(lambda cls, mode: voice))

    response = client.post("/voice/speak", json={"text": "**Acknowledged.**", "mode": "ultron"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content)) as wav:
        assert wav.getframerate() == 22050 and wav.getnframes() == 2205
    assert voice.calls == [("Acknowledged.", 0.9)]

    assert client.post("/voice/speak", json={"text": "**", "mode": "jarvis"}).status_code == 422
    assert client.post("/voice/speak", json={"text": "hi", "mode": "hal"}).status_code == 422


def test_missing_voice_model_is_a_503_with_a_download_hint(client, monkeypatch, tmp_path):
    monkeypatch.setattr(VoiceService, "VOICE_DIR", tmp_path)
    monkeypatch.setattr(VoiceService, "_voices", {})

    response = client.post("/voice/speak", json={"text": "hello"})

    assert response.status_code == 503
    assert "piper.download_voices" in response.json()["detail"]
    assert client.get("/voice/status").json()["available"] == {"jarvis": False, "ultron": False}


@pytest.mark.skipif(not VoiceService.model_path("jarvis").exists(), reason="voice model not downloaded")
def test_real_piper_synthesis():
    audio = VoiceService.synthesize("Hello, Ridham.", "jarvis")

    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getnframes() / wav.getframerate() > 0.5


# ---------- Speech to text ----------

from app.services.speech_service import SpeechService, SpeechInputError


class FakeWhisper:
    def __init__(self, text="Remind me to call mom"):
        self.text = text
        self.calls = []

    def transcribe(self, audio, **options):
        self.calls.append((audio.read(), options))
        segment = type("Segment", (), {"text": f" {self.text} "})
        return iter([segment]), None


def test_transcribe_endpoint_returns_text_and_passes_vocabulary(client, db, monkeypatch):
    from app.crud.tracking import create_project
    from app.models.user import User
    from tests.conftest import TEST_USER_ID

    whisper = FakeWhisper()
    monkeypatch.setattr(SpeechService, "_load", classmethod(lambda cls: whisper))
    monkeypatch.setattr("app.api.voice.DEFAULT_USER_ID", TEST_USER_ID)
    db.get(User, TEST_USER_ID).name = "Ridham"
    create_project(db, TEST_USER_ID, "Jarvis")
    create_project(db, TEST_USER_ID, "Tag-it")

    response = client.post("/voice/transcribe", content=b"OggS-fake", headers={"Content-Type": "audio/webm"})

    assert response.json() == {"text": "Remind me to call mom"}
    audio, options = whisper.calls[0]
    assert audio == b"OggS-fake"
    assert options["initial_prompt"] == "Ridham, Jarvis, Ultron, Tag-it."
    assert options["language"] == "en" and options["vad_filter"] is True


def test_transcribe_rejects_empty_oversized_and_unreadable_audio(client, monkeypatch):
    def broken(cls):
        class Model:
            def transcribe(self, audio, **options):
                raise ValueError("Invalid data found when processing input")
        return Model()

    monkeypatch.setattr(SpeechService, "_load", classmethod(broken))
    monkeypatch.setattr("app.api.voice.MAX_RECORDING_BYTES", 10)

    assert client.post("/voice/transcribe", content=b"").status_code == 422
    assert client.post("/voice/transcribe", content=b"x" * 11).status_code == 413
    unreadable = client.post("/voice/transcribe", content=b"garbage")
    assert unreadable.status_code == 422 and "Couldn't read" in unreadable.json()["detail"]


@pytest.mark.skipif(
    not (VoiceService.model_path("jarvis").exists() and (SpeechService.MODEL_DIR).exists()),
    reason="voice or speech model not downloaded",
)
def test_real_round_trip_speech_to_text():
    audio = VoiceService.synthesize("Remind me to call mom at five.", "jarvis")

    text = SpeechService.transcribe(audio, "Ridham, Jarvis.").lower()

    # The British voice says "mum"; either spelling is a correct hearing.
    assert ("call mom" in text or "call mum" in text) and "five" in text.replace("5", "five")
