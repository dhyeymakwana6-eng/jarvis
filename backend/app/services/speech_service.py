import io
import os
import threading
from pathlib import Path

from faster_whisper import WhisperModel
from sqlalchemy.orm import Session

from app.crud.tracking import get_projects
from app.models.user import User


class SpeechUnavailableError(Exception):
    """The speech-to-text model couldn't be loaded."""


class SpeechInputError(Exception):
    """The uploaded audio couldn't be decoded."""


class SpeechService:
    """
    Local speech-to-text with faster-whisper. The model downloads into
    MODEL_DIR on first use (base.en is ~140 MB) and is then reused.
    """

    MODEL = os.getenv("WHISPER_MODEL", "base.en")

    MODEL_DIR = Path(os.getenv(
        "WHISPER_MODEL_DIR",
        Path(__file__).resolve().parents[2] / "data" / "whisper"
    ))

    _model: WhisperModel | None = None
    _lock = threading.Lock()

    @classmethod
    def _load(cls) -> WhisperModel:
        with cls._lock:
            if cls._model is None:
                try:
                    cls._model = WhisperModel(
                        cls.MODEL,
                        device="cpu",
                        compute_type="int8",
                        download_root=str(cls.MODEL_DIR)
                    )
                except Exception as error:
                    raise SpeechUnavailableError(
                        f"Speech model {cls.MODEL} couldn't be loaded "
                        f"(first use downloads it into {cls.MODEL_DIR}): {error}"
                    ) from error

            return cls._model

    @staticmethod
    def vocabulary(db: Session, user_id: int) -> str | None:
        """
        Names Whisper wouldn't know, given as a prompt so it spells them
        right ("Ridham", not "Riddham"): the user's name and projects.
        """
        words = ["Jarvis", "Ultron"]

        user = db.get(User, user_id)
        if user and user.name:
            words.insert(0, user.name)

        words.extend(project.name for project in get_projects(db, user_id))

        unique = list(dict.fromkeys(word.strip() for word in words if word.strip()))

        return ", ".join(unique) + "." if unique else None

    @classmethod
    def transcribe(cls, audio: bytes, vocabulary: str | None = None) -> str:
        """Text of the recording (any format the browser records)."""
        model = cls._load()

        try:
            segments, _info = model.transcribe(
                io.BytesIO(audio),
                language="en",
                beam_size=1,
                # Skips silence, so a quiet press returns nothing
                # instead of a hallucinated sentence.
                vad_filter=True,
                initial_prompt=vocabulary
            )
            # Segments are generated lazily; decoding errors surface here.
            return " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as error:
            raise SpeechInputError(f"Couldn't read the recording: {error}") from error
