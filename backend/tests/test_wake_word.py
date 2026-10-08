import io
import wave

import numpy as np
import pytest

from app.services.voice_service import VoiceService
from app.services.wake_word_service import WakeWordService

WINDOW = 40_000  # 2.5s at 16 kHz, what the browser sends


def test_wake_endpoint_scores_the_window(client, monkeypatch):
    received = []

    def fake_score(cls, pcm):
        received.append(len(pcm))
        return 0.93

    monkeypatch.setattr(WakeWordService, "score", classmethod(fake_score))

    response = client.post("/voice/wake", content=b"\x00\x00" * WINDOW)

    assert response.status_code == 200
    assert response.json() == {"score": 0.93, "detected": True}
    assert received == [WINDOW * 2]


def test_wake_endpoint_rejects_bad_windows(client, monkeypatch):
    monkeypatch.setattr(WakeWordService, "_sessions", ("loaded",) * 3)

    short = client.post("/voice/wake", content=b"\x00\x00" * 1000)
    assert short.status_code == 422 and "at least 2s" in short.json()["detail"]

    assert client.post("/voice/wake", content=b"\x00" * 40_001).status_code == 422
    assert client.post("/voice/wake", content=b"\x00\x00" * 64_001).status_code == 413


def test_missing_wake_models_are_a_503_with_a_download_hint(client, monkeypatch, tmp_path):
    monkeypatch.setattr(WakeWordService, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(WakeWordService, "_sessions", None)

    response = client.post("/voice/wake", content=b"\x00\x00" * WINDOW)

    assert response.status_code == 503
    assert "download_wake_word" in response.json()["detail"]
    assert client.get("/voice/status").json()["wake_word"] is False


def spoken(text: str, mode: str = "jarvis") -> np.ndarray:
    """Piper speech resampled to 16 kHz, after 2.5s of silence."""
    with wave.open(io.BytesIO(VoiceService.synthesize(text, mode))) as wav:
        rate = wav.getframerate()
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32)

    times = np.arange(0, len(audio) / rate, 1 / 16_000)
    audio = np.interp(times, np.arange(len(audio)) / rate, audio)

    return np.concatenate([np.zeros(WINDOW), audio, np.zeros(16_000)]).astype("<i2")


def peak_while_streaming(audio: np.ndarray) -> float:
    # Like the browser: every 500 ms, the latest 2.5s.
    return max(
        WakeWordService.score(audio[end - WINDOW:end].tobytes())
        for end in range(WINDOW, len(audio) + 1, 8_000)
    )


@pytest.mark.skipif(
    not (WakeWordService.available() and VoiceService.model_path("jarvis").exists()),
    reason="wake word or voice model not downloaded",
)
@pytest.mark.parametrize("text, wakes", [
    ("Hey Jarvis.", True),
    ("Hey Jarvis, what's on my list today?", True),
    ("I told my friend about the movie yesterday.", False),
    ("Remind me to buy milk.", False),
])
def test_real_wake_word_detection(text, wakes):
    assert (peak_while_streaming(spoken(text)) >= WakeWordService.THRESHOLD) is wakes
