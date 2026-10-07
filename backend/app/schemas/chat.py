from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


# Which persona answers. Same memory and tasks; different voice.
Mode = Literal["jarvis", "ultron"]


class ChatRequest(BaseModel):
    query: str
    mode: Mode = "jarvis"


class ChatResponse(BaseModel):
    response: str


class ChatTurn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_message: str
    assistant_message: str
    mode: str
    created_at: datetime
