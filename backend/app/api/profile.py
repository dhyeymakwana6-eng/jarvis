from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.core.constants import DEFAULT_USER_ID

from app.services.profile_service import ProfileService
from app.services.llm_service import LLMUnavailableError

from app.schemas.profile import ProfileResponse

router = APIRouter(
    prefix="/profile",
    tags=["Profile"]
)


def _response(user) -> ProfileResponse:
    return ProfileResponse(
        profile=user.profile,
        updated_at=user.profile_updated_at,
        stale=user.profile_stale
    )


@router.get(
    "",
    response_model=ProfileResponse
)
def get_profile(
    db: Session = Depends(get_db)
):
    user = ProfileService.get(db, DEFAULT_USER_ID)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return _response(user)


@router.post(
    "/rebuild",
    response_model=ProfileResponse
)
def rebuild_profile(
    db: Session = Depends(get_db)
):
    user = ProfileService.get(db, DEFAULT_USER_ID)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    try:
        profile = ProfileService.rebuild(db, DEFAULT_USER_ID)
    except LLMUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error)
        )

    if profile is None:
        raise HTTPException(
            status_code=502,
            detail="Profile rebuild failed; the LLM returned invalid output"
        )

    db.refresh(user)

    return _response(user)
