from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_USER_ID
from app.database.connection import get_db
from app.services.routine_service import ROUTINES, RoutineService

router = APIRouter(
    prefix="/routines",
    tags=["Routines"]
)

RoutineKind = Literal["morning", "evening"]


class RoutineRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    run_date: date
    text: str
    mode: str
    created_at: datetime
    # Changes when it's rewritten (run on demand), so clients show it again.
    updated_at: datetime


@router.get("")
def routines_endpoint():
    # Each routine and its local time ("HH:MM"), or null when off.
    return [
        {
            "kind": kind,
            "title": routine.title,
            "time": (at := RoutineService.scheduled_time(kind)) and at.strftime("%H:%M")
        }
        for kind, routine in ROUTINES.items()
    ]


@router.get(
    "/due",
    response_model=list[RoutineRunResponse]
)
def due_routines_endpoint(
    db: Session = Depends(get_db)
):
    # Today's briefings not yet dismissed; clients poll this like
    # /reminders/due and dismiss what they've shown.
    return RoutineService.pending(db, DEFAULT_USER_ID)


@router.post(
    "/{kind}/run",
    response_model=RoutineRunResponse
)
async def run_routine_endpoint(
    kind: RoutineKind,
    db: Session = Depends(get_db)
):
    # On demand ("brief me now"): writes today's run again. Takes a few
    # seconds (LLM), so it's kept off the event loop.
    return await run_in_threadpool(RoutineService.run, db, DEFAULT_USER_ID, kind)


@router.post(
    "/runs/{run_id}/dismiss",
    response_model=RoutineRunResponse
)
def dismiss_routine_endpoint(
    run_id: int,
    db: Session = Depends(get_db)
):
    run = RoutineService.dismiss(db, DEFAULT_USER_ID, run_id)

    if run is None:
        raise HTTPException(status_code=404, detail="Routine run not found")

    return run
