from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db

from app.schemas.memory import (
    MemoryCreate,
    MemoryResponse
)

from app.crud.memory import (
    create_memory,
    get_memories,
    get_memory,
    delete_memory
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