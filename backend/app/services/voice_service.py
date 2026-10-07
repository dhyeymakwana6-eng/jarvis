import io
import os
import re
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

from piper import PiperVoice, SynthesisConfig


class VoiceUnavailableError(Exception):
    """The voice model for a mode isn't installed."""


@dataclass(frozen=True)
class VoiceProfile:
    model: str
    # >1 speaks slower, <1 faster. ULTRON is rendered a little fast
    # because the browser pitches it down, which also slows it.
    length_scale: float = 1.0


class VoiceService:
    """
    Local text-to-speech with Piper. Each mode has its own voice; the
    models live in VOICE_DIR (download with `python -m piper.download_voices`).
    """

    VOICE_DIR = Path(os.getenv(
        "PIPER_VOICE_DIR",
        Path(__file__).resolve().parents[2] / "data" / "voices"
    ))

    PROFILES = {
        "jarvis": VoiceProfile(os.getenv("JARVIS_VOICE", "en_GB-alan-medium")),
        "ultron": VoiceProfile(os.getenv("ULTRON_VOICE", "en_US-ryan-medium"), length_scale=0.9),
    }

    # Longer replies are cut at a sentence boundary: a spoken wall of
    # text is worse than reading it, and synthesis time grows with length.
    MAX_CHARS = 1200

    _voices: dict[str, PiperVoice] = {}
    _lock = threading.Lock()

    @classmethod
    def model_path(cls, mode: str) -> Path:
        profile = cls.PROFILES.get(mode, cls.PROFILES["jarvis"])
        return cls.VOICE_DIR / f"{profile.model}.onnx"

    @classmethod
    def available(cls) -> dict[str, bool]:
        return {mode: cls.model_path(mode).exists() for mode in cls.PROFILES}

    @classmethod
    def _voice(cls, mode: str) -> PiperVoice:
        """Loaded once per mode (~0.4s), then reused."""
        with cls._lock:
            if mode not in cls._voices:
                path = cls.model_path(mode)

                if not path.exists():
                    raise VoiceUnavailableError(
                        f"Voice model missing: {path}. Download it with "
                        f"`python -m piper.download_voices --download-dir {cls.VOICE_DIR} "
                        f"{cls.PROFILES[mode].model}`"
                    )

                cls._voices[mode] = PiperVoice.load(path)

            return cls._voices[mode]

    @staticmethod
    def speakable(text: str, limit: int = MAX_CHARS) -> str:
        """Markdown and symbols removed, so they aren't read aloud."""
        text = re.sub(r"```.*?```", " ", text, flags=re.S)       # code blocks
        text = re.sub(r"`([^`]*)`", r"\1", text)                 # inline code
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)     # links -> label
        text = re.sub(r"(\*\*|\*)(\S.*?\S|\S)\1", r"\2", text)  # *bold*/*italic*
        # _italic_ only at word edges, so snake_case_names survive.
        text = re.sub(r"(?<!\w)(__|_)(\S.*?\S|\S)\1(?!\w)", r"\2", text)
        text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)        # headings
        text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", text, flags=re.M)  # list markers
        text = re.sub(r"(?<!\w)[*_#~>]+(?!\w)", " ", text)       # stray markup
        text = re.sub(r"\s*\n+\s*", ". ", text.strip())          # lines -> sentences
        text = re.sub(r"([.!?:;])\.\s", r"\1 ", text)            # no doubled stops
        text = re.sub(r"\s{2,}", " ", text).strip()

        if len(text) <= limit:
            return text

        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))

        return cut[:end + 1] if end > 0 else cut

    @classmethod
    def synthesize(cls, text: str, mode: str) -> bytes:
        """WAV audio of `text` in the mode's voice."""
        mode = mode if mode in cls.PROFILES else "jarvis"
        voice = cls._voice(mode)
        config = SynthesisConfig(length_scale=cls.PROFILES[mode].length_scale)

        buffer = io.BytesIO()

        with wave.open(buffer, "wb") as wav:
            voice.synthesize_wav(cls.speakable(text), wav, syn_config=config)

        return buffer.getvalue()
