from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatRequest(BaseModel):
    query: str


class ChatResponse(BaseModel):
    response: str


class ChatTurn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_message: str
    assistant_message: str
    created_at: datetime
