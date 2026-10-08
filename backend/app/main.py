from dotenv import load_dotenv

load_dotenv()

import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from app.api.memory import router as memory_router
from app.api.profile import router as profile_router
from app.api.tracking import projects_router, goals_router
from app.api.task import router as task_router, reminders_router
from app.api.voice import router as voice_router
from app.api.routine import router as routine_router
from app.api.auth import router as auth_router, require_auth
from app.services.auth_service import AuthService
from app.core.constants import DEFAULT_USER_ID
from app.services.routine_service import RoutineScheduler
from app.services.memory_extraction.pipeline import MemoryPipeline
from app.database.connection import SessionLocal
from app.database.seed import ensure_default_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with SessionLocal() as db:
            ensure_default_user(db)
    except Exception as error:
        # Don't block startup; requests will report the DB problem.
        print(f"WARNING: could not ensure default user: {error}")

    # Finish memory extraction interrupted by a previous shutdown.
    # A daemon thread, so startup isn't blocked on LLM calls.
    threading.Thread(
        target=MemoryPipeline.process_pending,
        daemon=True
    ).start()

    if not AuthService.required():
        print("WARNING: JARVIS_PASSCODE is not set; the API is open to anyone who can reach it.")

    # Morning briefing / evening review at their times.
    scheduler = RoutineScheduler(DEFAULT_USER_ID)
    scheduler.start()

    yield

    scheduler.stop()

app = FastAPI(
    title="Jarvis",
    version="1.0.0",
    lifespan=lifespan
)

# Everything but /auth and the health check needs a session once a
# passcode is set (see AuthService).
protected = [Depends(require_auth)]

app.include_router(auth_router)
app.include_router(memory_router, dependencies=protected)
app.include_router(profile_router, dependencies=protected)
app.include_router(projects_router, dependencies=protected)
app.include_router(goals_router, dependencies=protected)
app.include_router(task_router, dependencies=protected)
app.include_router(reminders_router, dependencies=protected)
app.include_router(voice_router, dependencies=protected)
app.include_router(routine_router, dependencies=protected)


@app.get("/")
def root():
    return {
        "status": "online",
        "assistant": "Jarvis"
    }