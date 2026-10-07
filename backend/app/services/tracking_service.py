import re
from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.clock import local_now
from app.crud.tracking import (
    create_project,
    get_projects,
    get_project,
    find_project_by_name,
    update_project,
    create_goal,
    get_goals,
    get_goal,
    find_goal_by_title,
    update_goal
)
from app.models.goal import Goal
from app.schemas.tracking import Status
from app.services.llm_service import LLMService
from app.services.task_service import TaskService, NewTask, TaskChange


# ---------- LLM output schema ----------
# Separate typed lists (rather than one generic "action" list) make
# required fields like a new project's name enforceable by the schema.

class NewProject(BaseModel):
    name: str
    description: str | None = None
    next_action: str | None = None


class NewGoal(BaseModel):
    title: str
    project_id: int | None = Field(None, description="id of a listed project this goal belongs to")
    project_name: str | None = Field(None, description="name of a project in new_projects this goal belongs to")
    target_date: str | None = Field(None, description="YYYY-MM-DD")


class ProjectChange(BaseModel):
    id: int
    status: Status | None = None
    next_action: str | None = None


class GoalChange(BaseModel):
    id: int
    status: Status | None = None
    progress: int | None = Field(None, ge=0, le=100)
    target_date: str | None = Field(None, description="YYYY-MM-DD")


class TrackingChanges(BaseModel):
    reasoning: str = Field(description="one sentence: what the message changes, if anything")
    new_projects: list[NewProject]
    new_goals: list[NewGoal]
    project_updates: list[ProjectChange]
    goal_updates: list[GoalChange]
    new_tasks: list[NewTask]
    task_updates: list[TaskChange]


class TrackingService:
    """
    Keeps projects and goals in sync with what the user says in chat,
    and renders them as context for the chat prompt.
    """

    SYSTEM_PROMPT = """You track a user's projects, goals and tasks for their personal assistant.
Given the user's message and their current projects, goals and tasks, record only the changes the message clearly states. Leave every list empty if it states none; questions and small talk change nothing.
- new_projects: a new, named piece of work the user started that is not already listed.
- new_goals: a new objective or target. It is new if its objective differs from every listed goal, even within the same project. Set project_id when it belongs to a listed project, or project_name when it belongs to a project in new_projects.
  Example: with goal "Deploy Jarvis on a Raspberry Pi" listed, "I want to finish the Jarvis voice system by Friday" is a NEW goal (a different objective in the same project), not an update.
  Projects have no deadlines: a target or deadline about a project ("I want to deploy Jarvis by November") is a NEW goal linked to that project.
- project_updates / goal_updates: changes to a LISTED item, by its id. Set only the fields the message changes (status, next_action, progress, target_date). Update a goal only when the message is about that goal's own objective; sharing a project name is not enough ("finish the Jarvis tests" is not the goal "Deploy Jarvis on a Raspberry Pi").
  progress is a percentage the message states or implies ("halfway" = 50, "almost done" = 90, "just started" = 10); leave it null otherwise, never 0 by default.
  next_action is the next step the user says they need to take on a project ("Next for Jarvis I need to add reminders" -> next_action "Add reminders").
- new_tasks: a single concrete action the user must do or asks to be reminded about ("remind me to call mom at 5", "I need to submit the report by Friday"). A goal is a larger outcome worked towards over weeks or months; a task is one action, and anything due within a few days is a task. title is the action without the time ("Call mom").
  A project step WITH a deadline is a task linked to the project ("For Jarvis I need to write the reminder UI by Friday" -> new task "Write the reminder UI" with project_id of Jarvis and due_at = that Friday's date); without a deadline it is only next_action.
  "Remind me ..." sets remind_at. Whenever the message states a deadline ("by Friday", "before tomorrow evening", "due Monday"), always set due_at. Set priority only if the user says it is urgent/important (high) or unimportant (low).
- task_updates: changes to a LISTED task by its id. Done/finished/called/sent it -> status done; cancel/never mind/no longer needed -> status cancelled; a new time -> remind_at or due_at.
Statuses: completed = finished or done; abandoned = gave up, dropped, cancelled or stopped for good; paused = on hold or postponed; active = started again or in progress. Task statuses are only todo, done and cancelled.
Never re-create a listed item.
Convert relative dates to YYYY-MM-DD from Now. "By <month>" or "this month/year" means the last day of that period. Leave target_date null if no time is stated.
Task times (due_at, remind_at) are local times "YYYY-MM-DD HH:MM" computed from Now: "in 20 minutes" adds to Now; "at 5" is the next 5 o'clock still ahead, read as daytime (17:00); "tonight" is 20:00, "this evening" 18:00, "tomorrow morning" 09:00; a day with no time is that date only ("YYYY-MM-DD")."""

    # ---------- Prompt state ----------

    @staticmethod
    def _goal_line(goal: Goal, today: date) -> str:
        details = [goal.status]

        if goal.project_id:
            details.append(f"project {goal.project_id}")

        if goal.progress:
            details.append(f"{goal.progress}%")

        if goal.target_date:
            details.append(f"due {goal.target_date.isoformat()}")

        return f"- [{goal.id}] {goal.title} ({', '.join(details)})"

    @staticmethod
    def state_text(db: Session, user_id: int, now: datetime) -> str:
        """Everything the tracker LLM needs: the local time and all open items with ids."""
        today = now.date()
        lines = [f"Now: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')})", "Projects:"]

        projects = get_projects(db, user_id)
        for project in projects:
            line = f"- [{project.id}] {project.name} ({project.status})"
            if project.next_action:
                line += f" next: {project.next_action}"
            lines.append(line)
        if not projects:
            lines.append("(none)")

        lines.append("Goals:")
        goals = get_goals(db, user_id)
        for goal in goals:
            lines.append(TrackingService._goal_line(goal, today))
        if not goals:
            lines.append("(none)")

        lines.extend(TaskService.state_lines(db, user_id, now))

        return "\n".join(lines)

    # ---------- Applying changes ----------

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None

        try:
            # Keep the date of a full timestamp ("2026-10-08 20:00").
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None

    @staticmethod
    def apply(
        db: Session,
        user_id: int,
        changes: TrackingChanges,
        now: datetime | None = None
    ) -> list[str]:
        """
        Applies LLM-proposed changes after validating them: ids must
        belong to the user, names already in use aren't re-created,
        and bad dates are dropped. Returns a log of what changed.
        """
        log = []
        created_projects = {}

        for new in changes.new_projects:
            name = new.name.strip()

            if not name or find_project_by_name(db, user_id, name):
                continue

            project = create_project(
                db,
                user_id,
                name[:200],
                description=new.description,
                next_action=(new.next_action or None) and new.next_action[:500]
            )
            created_projects[name.lower()] = project
            log.append(f"created project {project.id}: {project.name}")

        for new in changes.new_goals:
            title = new.title.strip()

            if not title or find_goal_by_title(db, user_id, title):
                continue

            project_id = None

            if new.project_id is not None and get_project(db, user_id, new.project_id):
                project_id = new.project_id
            elif new.project_name:
                project = (
                    created_projects.get(new.project_name.strip().lower())
                    or find_project_by_name(db, user_id, new.project_name)
                )
                project_id = project.id if project else None

            goal = create_goal(
                db,
                user_id,
                title[:300],
                project_id=project_id,
                target_date=TrackingService._parse_date(new.target_date)
            )
            log.append(f"created goal {goal.id}: {goal.title}")

        for change in changes.project_updates:
            fields = {}

            if change.status:
                fields["status"] = change.status
            if change.next_action:
                fields["next_action"] = change.next_action[:500]

            if fields and update_project(db, user_id, change.id, fields):
                log.append(f"updated project {change.id}: {fields}")

        for change in changes.goal_updates:
            fields = {}

            if change.status:
                fields["status"] = change.status
            if change.progress is not None:
                fields["progress"] = change.progress
            target_date = TrackingService._parse_date(change.target_date)
            if target_date:
                fields["target_date"] = target_date

            if fields and update_goal(db, user_id, change.id, fields):
                log.append(f"updated goal {change.id}: {fields}")

        log.extend(TaskService.apply_changes(
            db,
            user_id,
            changes.new_tasks,
            changes.task_updates,
            created_projects,
            now or local_now()
        ))

        return log

    # Phrased as a question but asking for something to be done.
    REQUEST = re.compile(
        r"^\s*(?:can|could|will|would)\s+you\b|^\s*please\b|\bremind me\b",
        re.IGNORECASE
    )

    @staticmethod
    def is_question(message: str) -> bool:
        """
        Plain questions change nothing, so they skip the LLM call.
        "Can you remind me to call mom at 5?" is a request, not a question.
        """
        message = message.strip()

        return message.endswith("?") and not TrackingService.REQUEST.search(message)

    @staticmethod
    def process_message(
        db: Session,
        user_id: int,
        message: str,
        now: datetime | None = None
    ) -> list[str]:
        """Asks the LLM what the message changes and applies it."""
        if TrackingService.is_question(message):
            return []

        now = now or local_now()

        changes = LLMService().generate_structured(
            TrackingService.SYSTEM_PROMPT,
            f"{TrackingService.state_text(db, user_id, now)}\n\nUser message: {message}",
            TrackingChanges
        )

        if changes is None:
            return []

        return TrackingService.apply(db, user_id, changes, now)

    # ---------- Chat context ----------

    @staticmethod
    def to_context(db: Session, user_id: int, today: date | None = None) -> str | None:
        """Active/paused projects and open goals, for the chat prompt."""
        today = today or local_now().date()

        projects = get_projects(db, user_id)
        project_names = {project.id: project.name for project in projects}

        sections = []

        for status in ("active", "paused"):
            lines = []

            for project in projects:
                if project.status != status:
                    continue

                line = f"- {project.name}"
                if project.next_action:
                    line += f" (next step: {project.next_action})"
                lines.append(line)

            if lines:
                sections.append(f"{status.capitalize()} projects:\n" + "\n".join(lines))

        goal_lines = []

        for goal in get_goals(db, user_id):
            if goal.status not in ("active", "paused"):
                continue

            details = []
            if goal.project_id in project_names:
                details.append(f"project: {project_names[goal.project_id]}")
            if goal.status == "paused":
                details.append("paused")
            if goal.progress:
                details.append(f"{goal.progress}% done")
            if goal.target_date:
                days = (goal.target_date - today).days
                if days < 0:
                    details.append(f"OVERDUE, was due {goal.target_date.isoformat()}")
                else:
                    details.append(f"due {goal.target_date.isoformat()}, in {days} days")
            else:
                details.append("no deadline")

            goal_lines.append(f"- {goal.title} ({'; '.join(details)})")

        if goal_lines:
            sections.append("Open goals:\n" + "\n".join(goal_lines))

        if not sections:
            return None

        return f"Today: {today.isoformat()}\n\n" + "\n\n".join(sections)
