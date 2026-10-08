from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.conversation import Conversation
from app.core.constants import DEFAULT_USER_ID

from app.services.memory_service import MemoryService

from app.services.memory_retriever import MemoryRetriever

from app.services.embedding_service import EmbeddingService, EmbeddingError

from app.services.llm_service import LLMUnavailableError

from app.services.conversation_history import ConversationHistory

from app.services.memory_extraction.pipeline import MemoryPipeline

from app.services.agent_service import Action, AgentService, PendingActions

from app.schemas.memory import (
    MemoryCreate,
    MemoryUpdate,
    MemoryResponse,
    MemorySearchResult
)
from app.schemas.chat import (
    ActionDecision,
    ChatRequest,
    ChatResponse,
    ChatTurn
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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
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
    limit: int = Query(10, ge=1, le=50),
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
    # Debug endpoint, like /test-retrieve: don't record accesses.
    context = MemoryService.get_context(
        db,
        DEFAULT_USER_ID,
        query,
        record_access=False
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
    actions: list[Action] = []

    try:
        response = MemoryService.generate_response(
            db,
            DEFAULT_USER_ID,
            request.query,
            request.mode,
            actions=actions
        )
    except LLMUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error)
        )

    # Log the turn first, then extract/store memories and refresh the
    # profile after the response is sent (conflict checks take a few
    # seconds). The log row makes extraction survive a restart.
    conversation = Conversation(
        user_id=DEFAULT_USER_ID,
        user_message=request.query,
        assistant_message=response,
        mode=request.mode,
        actions=[action.model_dump() for action in actions] or None
    )
    db.add(conversation)
    db.commit()

    PendingActions.attach(
        [action.pending_id for action in actions if action.pending_id],
        conversation.id
    )

    background_tasks.add_task(
        MemoryPipeline.process_conversation,
        conversation.id
    )

    return ChatResponse(
        response=response,
        actions=actions
    )

@router.post(
    "/chat/actions/{pending_id}",
    response_model=Action
)
def resolve_action_endpoint(
    pending_id: str,
    decision: ActionDecision,
    db: Session = Depends(get_db)
):
    # The user's answer to an action that needed confirmation (e.g.
    # deleting a task). Expired or unknown ids change nothing.
    action, conversation_id = AgentService.resolve(
        db,
        DEFAULT_USER_ID,
        pending_id,
        decision.approve
    )

    # Keep the turn's log in step, so reloaded history shows the outcome.
    conversation = db.get(Conversation, conversation_id) if conversation_id else None

    if conversation and conversation.actions:
        conversation.actions = [
            action.model_dump() if logged.get("pending_id") == pending_id else logged
            for logged in conversation.actions
        ]
        db.commit()

    return action

@router.get(
    "/chat/history",
    response_model=list[ChatTurn]
)
def chat_history_endpoint(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    # The current session (turns since the last 30 min of silence),
    # oldest first. The LLM sees the last few of these.
    return ConversationHistory.current_session(
        db,
        DEFAULT_USER_ID,
        limit=limit
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
