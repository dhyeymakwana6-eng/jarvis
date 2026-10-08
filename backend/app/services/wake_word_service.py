import os
import threading
from pathlib import Path

import numpy as np
import onnxruntime as ort


class WakeWordUnavailableError(Exception):
    """The wake word models aren't installed."""


class WakeWordInputError(Exception):
    """The audio window is too short or malformed."""


class WakeWordService:
    """
    Local "Hey Jarvis" detection with openWakeWord's pretrained ONNX models,
    run directly with onnxruntime (the openwakeword package would pull in
    scikit-learn and tflite for nothing):

        16 kHz audio -> melspectrogram -> speech embedding (76 mel frames
        each, every 8 frames = 80 ms) -> classifier over 16 embeddings.

    It's stateless: each call scores a short rolling window of audio, so
    the browser sends the last ~2.5s every half second. The models live in
    MODEL_DIR (download with `python -m scripts.download_wake_word`).
    """

    MODEL_DIR = Path(os.getenv(
        "WAKE_WORD_DIR",
        Path(__file__).resolve().parents[2] / "data" / "wakeword"
    ))

    WAKE_MODEL = os.getenv("WAKE_WORD_MODEL", "hey_jarvis_v0.1")
    THRESHOLD = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))

    SAMPLE_RATE = 16_000
    MEL_WINDOW = 76
    MEL_STEP = 8
    EMBEDDINGS = 16

    # The shortest window that yields one prediction (16 embeddings).
    MIN_SAMPLES = 32_000
    # Longer windows are trimmed to their end; this bounds the work per call.
    MAX_SAMPLES = 4 * SAMPLE_RATE

    _sessions: tuple[ort.InferenceSession, ...] | None = None
    _lock = threading.Lock()

    @classmethod
    def model_paths(cls) -> list[Path]:
        return [
            cls.MODEL_DIR / "melspectrogram.onnx",
            cls.MODEL_DIR / "embedding_model.onnx",
            cls.MODEL_DIR / f"{cls.WAKE_MODEL}.onnx",
        ]

    @classmethod
    def available(cls) -> bool:
        return all(path.exists() for path in cls.model_paths())

    @classmethod
    def _load(cls) -> tuple[ort.InferenceSession, ...]:
        with cls._lock:
            if cls._sessions is None:
                if not cls.available():
                    raise WakeWordUnavailableError(
                        f"Wake word models not found in {cls.MODEL_DIR} "
                        "(run `python -m scripts.download_wake_word`)"
                    )

                options = ort.SessionOptions()
                options.intra_op_num_threads = 1
                options.inter_op_num_threads = 1

                cls._sessions = tuple(
                    ort.InferenceSession(
                        str(path),
                        sess_options=options,
                        providers=["CPUExecutionProvider"]
                    )
                    for path in cls.model_paths()
                )

            return cls._sessions

    @classmethod
    def score(cls, pcm: bytes) -> float:
        """
        Highest wake word probability (0..1) over the latest half second or
        so of the window. `pcm` is 16-bit little-endian mono at 16 kHz.
        """
        if len(pcm) % 2:
            raise WakeWordInputError("PCM must be 16-bit samples")

        samples = np.frombuffer(pcm, dtype="<i2")[-cls.MAX_SAMPLES:]

        if samples.size < cls.MIN_SAMPLES:
            raise WakeWordInputError(
                f"Need at least {cls.MIN_SAMPLES / cls.SAMPLE_RATE:g}s of audio"
            )

        melspec, embedding, classifier = cls._load()

        mel = melspec.run(None, {"input": samples.astype(np.float32)[None]})[0]
        # Same rescaling openWakeWord applies to match Google's original model.
        mel = np.squeeze(mel) / 10 + 2

        # Embedding windows aligned to the end, so the newest audio is in one.
        starts = range(mel.shape[0] - cls.MEL_WINDOW, -1, -cls.MEL_STEP)
        windows = np.stack([mel[start:start + cls.MEL_WINDOW] for start in reversed(starts)])
        features = embedding.run(None, {"input_1": windows[..., None].astype(np.float32)})[0]
        features = features.reshape(len(windows), -1)

        # Score every 16-embedding run that ends in the newest 8 positions
        # (640 ms): enough to overlap the browser's 500 ms hop.
        name = classifier.get_inputs()[0].name
        last = len(features)
        first = max(cls.EMBEDDINGS, last - 7)

        scores = [
            classifier.run(None, {name: features[end - cls.EMBEDDINGS:end][None]})[0].item()
            for end in range(first, last + 1)
        ]

        return float(max(scores))

    @classmethod
    def detect(cls, pcm: bytes) -> dict:
        score = cls.score(pcm)
        return {"score": round(score, 4), "detected": score >= cls.THRESHOLD}
