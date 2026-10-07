from dotenv import load_dotenv

load_dotenv()

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.memory import router as memory_router
from app.api.profile import router as profile_router
from app.api.tracking import projects_router, goals_router
from app.api.task import router as task_router, reminders_router
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

    yield

app = FastAPI(
    title="Jarvis",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(memory_router)
app.include_router(profile_router)
app.include_router(projects_router)
app.include_router(goals_router)
app.include_router(task_router)
app.include_router(reminders_router)


@app.get("/")
def root():
    return {
        "status": "online",
        "assistant": "Jarvis"
    }