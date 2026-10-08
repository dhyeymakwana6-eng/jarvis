"""
Downloads openWakeWord's ONNX models (~3.6 MB) into data/wakeword:

    python -m scripts.download_wake_word
"""
import urllib.request

from app.services.wake_word_service import WakeWordService

RELEASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"


def main():
    WakeWordService.MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for path in WakeWordService.model_paths():
        if path.exists():
            print(f"have {path.name}")
            continue

        print(f"downloading {path.name}")
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(f"{RELEASE}/{path.name}", partial)
        partial.rename(path)


if __name__ == "__main__":
    main()
