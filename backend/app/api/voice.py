from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_USER_ID
from app.database.connection import get_db
from app.schemas.chat import Mode
from app.services.speech_service import SpeechService, SpeechUnavailableError, SpeechInputError
from app.services.voice_service import VoiceService, VoiceUnavailableError
from app.services.wake_word_service import (
    WakeWordInputError,
    WakeWordService,
    WakeWordUnavailableError
)

router = APIRouter(
    prefix="/voice",
    tags=["Voice"]
)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    mode: Mode = "jarvis"


@router.get("/status")
def voice_status():
    # Which modes have a voice model installed, and whether the wake
    # word can be used.
    return {
        "available": VoiceService.available(),
        "wake_word": WakeWordService.available()
    }


@router.post(
    "/speak",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}}
)
async def speak_endpoint(request: SpeakRequest):
    if not VoiceService.speakable(request.text):
        raise HTTPException(status_code=422, detail="Nothing to say")

    try:
        # Synthesis is CPU-bound; keep it off the event loop.
        audio = await run_in_threadpool(VoiceService.synthesize, request.text, request.mode)
    except VoiceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return Response(content=audio, media_type="audio/wav")


# A minute of browser-recorded Opus is well under 1 MB.
MAX_RECORDING_BYTES = 15 * 1024 * 1024


@router.post("/transcribe")
async def transcribe_endpoint(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Speech to text. The body is the raw recording (whatever the browser's
    MediaRecorder produced, e.g. audio/webm or audio/mp4).
    """
    audio = await request.body()

    if not audio:
        raise HTTPException(status_code=422, detail="Empty recording")

    if len(audio) > MAX_RECORDING_BYTES:
        raise HTTPException(status_code=413, detail="Recording too long")

    vocabulary = SpeechService.vocabulary(db, DEFAULT_USER_ID)

    try:
        text = await run_in_threadpool(SpeechService.transcribe, audio, vocabulary)
    except SpeechUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error))
    except SpeechInputError as error:
        raise HTTPException(status_code=422, detail=str(error))

    return {"text": text}


# 4s of 16-bit 16 kHz audio; the browser sends 2.5s.
MAX_WAKE_WINDOW_BYTES = 4 * 16_000 * 2


@router.post("/wake")
async def wake_endpoint(request: Request):
    """
    Wake word check. The body is the latest ~2.5s of mic audio as raw
    16-bit little-endian mono PCM at 16 kHz; the browser posts it every
    half second while the wake word is on.
    """
    pcm = await request.body()

    if len(pcm) > MAX_WAKE_WINDOW_BYTES:
        raise HTTPException(status_code=413, detail="Audio window too long")

    try:
        return await run_in_threadpool(WakeWordService.detect, pcm)
    except WakeWordUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error))
    except WakeWordInputError as error:
        raise HTTPException(status_code=422, detail=str(error))
