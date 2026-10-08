from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.services.agent_service import Action


# Which persona answers. Same memory and tasks; different voice.
Mode = Literal["jarvis", "ultron"]


class ChatRequest(BaseModel):
    query: str
    mode: Mode = "jarvis"


class ChatResponse(BaseModel):
    response: str
    # Tasks it created or changed, and any waiting for confirmation.
    actions: list[Action] = []


class ActionDecision(BaseModel):
    approve: bool


class ChatTurn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_message: str
    assistant_message: str
    mode: str
    actions: list[Action] | None = None
    created_at: datetime
