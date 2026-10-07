from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_USER_ID
from app.database.connection import get_db
from app.schemas.chat import Mode
from app.services.speech_service import SpeechService, SpeechUnavailableError, SpeechInputError
from app.services.voice_service import VoiceService, VoiceUnavailableError

router = APIRouter(
    prefix="/voice",
    tags=["Voice"]
)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    mode: Mode = "jarvis"


@router.get("/status")
def voice_status():
    # Which modes have a voice model installed.
    return {"available": VoiceService.available()}


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
