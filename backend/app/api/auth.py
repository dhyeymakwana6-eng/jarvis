from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_USER_ID
from app.database.connection import get_db
from app.services.auth_service import AuthService

router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)


def require_auth(request: Request, db: Session = Depends(get_db)):
    """
    Guards every API route except /auth and the health check: a session
    cookie or the API token, when JARVIS_PASSCODE is set.
    """
    if not AuthService.required():
        return

    if AuthService.valid_api_token(request.headers.get("authorization")):
        return

    if AuthService.session_user(db, request.cookies.get(AuthService.COOKIE)) is not None:
        return

    raise HTTPException(status_code=401, detail="Not signed in")


class LoginRequest(BaseModel):
    passcode: str = Field(min_length=1, max_length=200)


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    # required: a passcode is set. authenticated: this request may use the API.
    required = AuthService.required()

    authenticated = not required or (
        AuthService.valid_api_token(request.headers.get("authorization"))
        or AuthService.session_user(db, request.cookies.get(AuthService.COOKIE)) is not None
    )

    return {"required": required, "authenticated": bool(authenticated)}


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    if not AuthService.required():
        raise HTTPException(status_code=400, detail="No passcode is set (JARVIS_PASSCODE)")

    wait = AuthService.locked_out()
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts; try again in {wait} seconds",
            headers={"Retry-After": str(wait)}
        )

    if not AuthService.check_passcode(body.passcode):
        raise HTTPException(status_code=401, detail="Wrong passcode")

    token = AuthService.create_session(db, DEFAULT_USER_ID, request.headers.get("user-agent"))

    response.set_cookie(
        AuthService.COOKIE,
        token,
        max_age=AuthService.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="strict",
        secure=AuthService.cookie_secure(),
        path="/"
    )

    return {"authenticated": True}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    AuthService.end_session(db, request.cookies.get(AuthService.COOKIE))
    response.delete_cookie(AuthService.COOKIE, path="/")
    return {"authenticated": False}
