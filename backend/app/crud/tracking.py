from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.goal import Goal


def _apply_status(item, status: str | None):
    """Keeps completed_at (and goal progress) consistent with status."""
    if status is None or status == item.status:
        return

    item.status = status

    if status == "completed":
        item.completed_at = datetime.now(timezone.utc)

        if isinstance(item, Goal):
            item.progress = 100
    else:
        item.completed_at = None


# ---------- Projects ----------

def create_project(
    db: Session,
    user_id: int,
    name: str,
    description: str | None = None,
    status: str = "active",
    next_action: str | None = None
) -> Project:
    project = Project(
        user_id=user_id,
        name=name,
        description=description,
        status="active",
        next_action=next_action
    )
    _apply_status(project, status)

    db.add(project)
    db.commit()
    db.refresh(project)

    return project


def get_projects(
    db: Session,
    user_id: int,
    status: str | None = None
) -> list[Project]:
    query = db.query(Project).filter(
        Project.user_id == user_id,
        Project.is_deleted == False
    )

    if status:
        query = query.filter(Project.status == status)

    return query.order_by(Project.id).all()


def get_project(db: Session, user_id: int, project_id: int) -> Project | None:
    return (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == user_id,
            Project.is_deleted == False
        )
        .first()
    )


def find_project_by_name(db: Session, user_id: int, name: str) -> Project | None:
    """Case-insensitive exact name match among the user's projects."""
    name = name.strip().lower()

    for project in get_projects(db, user_id):
        if project.name.strip().lower() == name:
            return project

    return None


def update_project(
    db: Session,
    user_id: int,
    project_id: int,
    changes: dict
) -> Project | None:
    """changes holds only the fields to set (partial update)."""
    project = get_project(db, user_id, project_id)

    if project is None:
        return None

    for field in ("name", "description", "next_action"):
        if field in changes:
            setattr(project, field, changes[field])

    _apply_status(project, changes.get("status"))

    db.commit()
    db.refresh(project)

    return project


def delete_project(db: Session, user_id: int, project_id: int) -> Project | None:
    """Soft delete. Its goals are kept but unlinked from it."""
    project = get_project(db, user_id, project_id)

    if project is None:
        return None

    project.is_deleted = True

    for goal in get_goals(db, user_id, project_id=project_id):
        goal.project_id = None

    db.commit()

    return project


# ---------- Goals ----------

def create_goal(
    db: Session,
    user_id: int,
    title: str,
    description: str | None = None,
    project_id: int | None = None,
    status: str = "active",
    target_date=None,
    progress: int = 0
) -> Goal:
    goal = Goal(
        user_id=user_id,
        title=title,
        description=description,
        project_id=project_id,
        status="active",
        target_date=target_date,
        progress=progress
    )
    _apply_status(goal, status)

    db.add(goal)
    db.commit()
    db.refresh(goal)

    return goal


def get_goals(
    db: Session,
    user_id: int,
    status: str | None = None,
    project_id: int | None = None
) -> list[Goal]:
    query = db.query(Goal).filter(
        Goal.user_id == user_id,
        Goal.is_deleted == False
    )

    if status:
        query = query.filter(Goal.status == status)

    if project_id is not None:
        query = query.filter(Goal.project_id == project_id)

    # Soonest deadline first; goals without one last.
    return query.order_by(Goal.target_date.asc().nulls_last(), Goal.id).all()


def get_goal(db: Session, user_id: int, goal_id: int) -> Goal | None:
    return (
        db.query(Goal)
        .filter(
            Goal.id == goal_id,
            Goal.user_id == user_id,
            Goal.is_deleted == False
        )
        .first()
    )


def find_goal_by_title(db: Session, user_id: int, title: str) -> Goal | None:
    """Case-insensitive exact title match among the user's goals."""
    title = title.strip().lower()

    for goal in get_goals(db, user_id):
        if goal.title.strip().lower() == title:
            return goal

    return None


def update_goal(
    db: Session,
    user_id: int,
    goal_id: int,
    changes: dict
) -> Goal | None:
    """changes holds only the fields to set (partial update)."""
    goal = get_goal(db, user_id, goal_id)

    if goal is None:
        return None

    for field in ("title", "description", "project_id", "target_date", "progress"):
        if field in changes:
            setattr(goal, field, changes[field])

    _apply_status(goal, changes.get("status"))

    db.commit()
    db.refresh(goal)

    return goal


def delete_goal(db: Session, user_id: int, goal_id: int) -> Goal | None:
    goal = get_goal(db, user_id, goal_id)

    if goal is None:
        return None

    goal.is_deleted = True
    db.commit()

    return goal
