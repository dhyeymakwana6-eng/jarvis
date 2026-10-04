from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.core.constants import DEFAULT_USER_ID

from app.schemas.tracking import (
    Status,
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    GoalCreate,
    GoalUpdate,
    GoalResponse
)

from app.crud.tracking import (
    create_project,
    get_projects,
    get_project,
    update_project,
    delete_project,
    create_goal,
    get_goals,
    get_goal,
    update_goal,
    delete_goal
)

projects_router = APIRouter(
    prefix="/projects",
    tags=["Projects"]
)

goals_router = APIRouter(
    prefix="/goals",
    tags=["Goals"]
)


def _not_found(kind: str):
    return HTTPException(
        status_code=404,
        detail=f"{kind} not found"
    )


def _check_project(db: Session, project_id: int | None):
    if project_id is not None and not get_project(db, DEFAULT_USER_ID, project_id):
        raise HTTPException(
            status_code=422,
            detail=f"Project {project_id} not found"
        )


# ---------- Projects ----------

@projects_router.post(
    "",
    response_model=ProjectResponse
)
def create_project_endpoint(
    project: ProjectCreate,
    db: Session = Depends(get_db)
):
    return create_project(
        db,
        DEFAULT_USER_ID,
        **project.model_dump()
    )


@projects_router.get(
    "",
    response_model=list[ProjectResponse]
)
def get_projects_endpoint(
    status: Status | None = None,
    db: Session = Depends(get_db)
):
    return get_projects(db, DEFAULT_USER_ID, status)


@projects_router.get(
    "/{project_id}",
    response_model=ProjectResponse
)
def get_project_endpoint(
    project_id: int,
    db: Session = Depends(get_db)
):
    project = get_project(db, DEFAULT_USER_ID, project_id)

    if not project:
        raise _not_found("Project")

    return project


@projects_router.get(
    "/{project_id}/goals",
    response_model=list[GoalResponse]
)
def get_project_goals_endpoint(
    project_id: int,
    db: Session = Depends(get_db)
):
    if not get_project(db, DEFAULT_USER_ID, project_id):
        raise _not_found("Project")

    return get_goals(db, DEFAULT_USER_ID, project_id=project_id)


@projects_router.patch(
    "/{project_id}",
    response_model=ProjectResponse
)
def update_project_endpoint(
    project_id: int,
    changes: ProjectUpdate,
    db: Session = Depends(get_db)
):
    project = update_project(
        db,
        DEFAULT_USER_ID,
        project_id,
        changes.model_dump(exclude_unset=True)
    )

    if not project:
        raise _not_found("Project")

    return project


@projects_router.delete("/{project_id}")
def delete_project_endpoint(
    project_id: int,
    db: Session = Depends(get_db)
):
    if not delete_project(db, DEFAULT_USER_ID, project_id):
        raise _not_found("Project")

    return {
        "message": "Project deleted"
    }


# ---------- Goals ----------

@goals_router.post(
    "",
    response_model=GoalResponse
)
def create_goal_endpoint(
    goal: GoalCreate,
    db: Session = Depends(get_db)
):
    _check_project(db, goal.project_id)

    return create_goal(
        db,
        DEFAULT_USER_ID,
        **goal.model_dump()
    )


@goals_router.get(
    "",
    response_model=list[GoalResponse]
)
def get_goals_endpoint(
    status: Status | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db)
):
    return get_goals(db, DEFAULT_USER_ID, status, project_id)


@goals_router.get(
    "/{goal_id}",
    response_model=GoalResponse
)
def get_goal_endpoint(
    goal_id: int,
    db: Session = Depends(get_db)
):
    goal = get_goal(db, DEFAULT_USER_ID, goal_id)

    if not goal:
        raise _not_found("Goal")

    return goal


@goals_router.patch(
    "/{goal_id}",
    response_model=GoalResponse
)
def update_goal_endpoint(
    goal_id: int,
    changes: GoalUpdate,
    db: Session = Depends(get_db)
):
    changes_dict = changes.model_dump(exclude_unset=True)

    _check_project(db, changes_dict.get("project_id"))

    goal = update_goal(db, DEFAULT_USER_ID, goal_id, changes_dict)

    if not goal:
        raise _not_found("Goal")

    return goal


@goals_router.delete("/{goal_id}")
def delete_goal_endpoint(
    goal_id: int,
    db: Session = Depends(get_db)
):
    if not delete_goal(db, DEFAULT_USER_ID, goal_id):
        raise _not_found("Goal")

    return {
        "message": "Goal deleted"
    }
