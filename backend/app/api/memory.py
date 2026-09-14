from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.core.constants import DEFAULT_USER_ID

from app.services.memory_service import MemoryService

from app.services.memory_retriever import MemoryRetriever

from app.services.memory_extraction.pipeline import MemoryPipeline

from app.schemas.memory import (
    MemoryCreate,
    MemoryUpdate,
    MemoryResponse
)
from app.schemas.chat import (
    ChatRequest,
    ChatResponse
)

from app.crud.memory import (
    create_memory,
    get_memories,
    get_memory,
    update_memory,
    delete_memory,
    restore_memory,
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
        DEFAULT_USER_ID,
        memory.category,
        memory.content,
        memory.importance
    )


@router.get(
    "",
    response_model=list[MemoryResponse]
)
def get_all_memories(
    category: str = None,
    min_importance: int = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
    db: Session = Depends(get_db)
):
    return get_memories(
        db,
        category,
        min_importance,
        limit,
        offset,
        include_deleted
    )

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

@router.post(
    "/chat",
    response_model=ChatResponse
)
def chat_endpoint(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    # Automatically extract and store memories
    pipeline = MemoryPipeline(db)
    pipeline.process_and_store(DEFAULT_USER_ID, request.query)

    # Generate response using stored memories
    response = MemoryService.generate_response(
        db,
        request.query
    )

    return ChatResponse(
        response=response
    )

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

@router.put(
    "/{memory_id}",
    response_model=MemoryResponse
)
def update_memory_endpoint(
    memory_id: int,
    memory: MemoryUpdate,
    db: Session = Depends(get_db)
):
    updated = update_memory(
        db,
        memory_id,
        memory.category,
        memory.content,
        memory.importance
    )

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Memory not found"
        )

    return updated

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

@router.post("/{memory_id}/restore", response_model=MemoryResponse)
def restore_memory_endpoint(
    memory_id: int,
    db: Session = Depends(get_db)
):
    memory = restore_memory(db, memory_id)

    if not memory:
        raise HTTPException(
            status_code=404,
            detail="Memory not found or not deleted"
        )

    return memory