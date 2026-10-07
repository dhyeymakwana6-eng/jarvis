from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.schemas.chat import Mode
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
