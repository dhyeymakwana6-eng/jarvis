from fastapi import FastAPI

from app.api.memory import router as memory_router

app = FastAPI(
    title="Jarvis",
    version="1.0.0"
)

app.include_router(memory_router)


@app.get("/")
def root():
    return {
        "status": "online",
        "assistant": "Jarvis"
    }