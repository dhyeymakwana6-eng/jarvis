from pydantic import BaseModel


class MemoryCreate(BaseModel):
    category: str
    content: str
    importance: int


class MemoryResponse(BaseModel):
    id: int
    category: str
    content: str
    importance: int

    class Config:
        from_attributes = True