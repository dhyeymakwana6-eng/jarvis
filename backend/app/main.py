from dotenv import load_dotenv

load_dotenv()

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.memory import router as memory_router
from app.api.profile import router as profile_router
from app.api.tracking import projects_router, goals_router
from app.services.memory_extraction.pipeline import MemoryPipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/")
def root():
    return {
        "status": "online",
        "assistant": "Jarvis"
    }