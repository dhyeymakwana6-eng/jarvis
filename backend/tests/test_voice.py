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
    assert client.get("/voice/status").json() == {"available": {"jarvis": False, "ultron": False}}


@pytest.mark.skipif(not VoiceService.model_path("jarvis").exists(), reason="voice model not downloaded")
def test_real_piper_synthesis():
    audio = VoiceService.synthesize("Hello, Ridham.", "jarvis")

    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getnframes() / wav.getframerate() > 0.5
