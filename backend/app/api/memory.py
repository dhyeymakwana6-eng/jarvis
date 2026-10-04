from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.conversation import Conversation
from app.core.constants import DEFAULT_USER_ID

from app.services.memory_service import MemoryService

from app.services.memory_retriever import MemoryRetriever

from app.services.embedding_service import EmbeddingService, EmbeddingError

from app.services.memory_extraction.pipeline import MemoryPipeline

from app.schemas.memory import (
    MemoryCreate,
    MemoryUpdate,
    MemoryResponse,
    MemorySearchResult
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
    search_memories,
    semantic_search_memories
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
        DEFAULT_USER_ID,
        category,
        min_importance,
        limit,
        offset,
        include_deleted
    )

@router.get(
    "/search",
    response_model=list[MemoryResponse]
)
def search_memory_endpoint(
    q: str,
    db: Session = Depends(get_db)
):
    return search_memories(
        db,
        DEFAULT_USER_ID,
        q
    )

@router.get(
    "/semantic-search",
    response_model=list[MemorySearchResult]
)
def semantic_search_endpoint(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    try:
        query_embedding = EmbeddingService.generate_query(q)
    except EmbeddingError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error)
        )

    matches = semantic_search_memories(
        db,
        DEFAULT_USER_ID,
        query_embedding,
        limit
    )

    return [
        MemorySearchResult(
            id=memory.id,
            category=memory.category,
            content=memory.content,
            importance=memory.importance,
            distance=round(distance, 4)
        )
        for memory, distance in matches
    ]

@router.get(
    "/test-retrieve",
    response_model=list[MemoryResponse]
)
def test_retrieve(
    query: str,
    db: Session = Depends(get_db)
):
    # Debug endpoint: don't count these lookups as real accesses,
    # otherwise testing skews importance decay.
    return MemoryRetriever.retrieve(
        db,
        DEFAULT_USER_ID,
        query,
        record_access=False
    )

@router.get("/context")
def get_memory_context(
    query: str,
    db: Session = Depends(get_db)
):
    context = MemoryService.get_context(
        db,
        DEFAULT_USER_ID,
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Retrieve context before storing this message, so the user's
    # own message isn't fed back to the LLM as a "known fact".
    response = MemoryService.generate_response(
        db,
        DEFAULT_USER_ID,
        request.query
    )

    # Log the turn first, then extract/store memories and refresh the
    # profile after the response is sent (conflict checks take a few
    # seconds). The log row makes extraction survive a restart.
    conversation = Conversation(
        user_id=DEFAULT_USER_ID,
        user_message=request.query,
        assistant_message=response
    )
    db.add(conversation)
    db.commit()

    background_tasks.add_task(
        MemoryPipeline.process_conversation,
        conversation.id
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
        DEFAULT_USER_ID,
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
        DEFAULT_USER_ID,
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
        DEFAULT_USER_ID,
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
    memory = restore_memory(db, DEFAULT_USER_ID, memory_id)

    if not memory:
        raise HTTPException(
            status_code=404,
            detail="Memory not found or not deleted"
        )

    return memory
