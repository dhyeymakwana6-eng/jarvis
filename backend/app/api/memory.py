from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db

from app.services.memory_service import MemoryService

from app.services.memory_retriever import MemoryRetriever

from app.schemas.memory import (
    MemoryCreate,
    MemoryResponse
)

from app.crud.memory import (
    create_memory,
    get_memories,
    get_memory,
    delete_memory,
    search_memories
)

router = APIRouter(
    prefix="/memory",
    tags=["Memory"]
)


@router.post(
    "",
    response_model=MemoryResponse
)
def create_memory_endpoint(
    memory: MemoryCreate,
    db: Session = Depends(get_db)
):
    return create_memory(
        db,
        memory.category,
        memory.content,
        memory.importance
    )


@router.get(
    "",
    response_model=list[MemoryResponse]
)
def get_all_memories(
    db: Session = Depends(get_db)
):
    return get_memories(db)

@router.get("/search")
def search_memory_endpoint(
    q: str,
    db: Session = Depends(get_db)
):
    return search_memories(
        db,
        q
    )

@router.get("/test-retrieve")
def test_retrieve(
    query: str,
    db: Session = Depends(get_db)
):
    memories = MemoryRetriever.retrieve(
        db,
        query
    )

    return [
        {
            "id": memory.id,
            "category": memory.category,
            "content": memory.content,
            "importance": memory.importance
        }
        for memory in memories
    ]

@router.get("/context")
def get_memory_context(
    query: str,
    db: Session = Depends(get_db)
):
    context = MemoryService.get_context(
        db,
        query
    )

    return {
        "context": context
    }

@router.get(
    "/{memory_id}",
    response_model=MemoryResponse
)
def get_memory_endpoint(
    memory_id: int,
    db: Session = Depends(get_db)

):
    memory = get_memory(
        db,
        memory_id
    )

    if not memory:
        raise HTTPException(
            status_code=404,
            detail="Memory not found"
        )

    return memory


@router.delete("/{memory_id}")
def delete_memory_endpoint(
    memory_id: int,
    db: Session = Depends(get_db)
):
    memory = delete_memory(
        db,
        memory_id
    )

    if not memory:
        raise HTTPException(
            status_code=404,
            detail="Memory not found"
        )

    return {
        "message": "Memory deleted"
    }

