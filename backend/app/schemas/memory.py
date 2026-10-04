from pydantic import BaseModel, ConfigDict, Field


# Importance is stored on a 0-100 scale (the extraction pipeline
# scales its 0.0-1.0 scores by 100).
Importance = Field(ge=0, le=100)


class MemoryCreate(BaseModel):
    category: str
    content: str
    importance: int = Importance

class MemoryUpdate(BaseModel):
    category: str
    content: str
    importance: int = Importance

class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    content: str
    importance: int
    is_deleted: bool = False
    # Set when a newer, contradicting memory replaced this one;
    # POST /memory/{id}/restore undoes it.
    superseded_by_id: int | None = None


class MemorySearchResult(MemoryResponse):
    # Cosine distance to the query: 0 = identical, ~1 = unrelated.
    distance: float
