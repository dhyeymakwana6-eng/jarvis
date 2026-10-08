import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import local_now
from app.core.recurrence import describe as describe_recurrence
from app.crud.task import get_tasks
from app.crud.tracking import get_goals
from app.database.connection import SessionLocal
from app.models.conversation import Conversation
from app.models.routine import RoutineRun
from app.services.llm_service import LLMService, LLMUnavailableError


@dataclass(frozen=True)
class Routine:
    kind: str
    title: str
    env: str
    default_time: str
    # What the LLM is asked to write from the facts.
    brief: str


ROUTINES = {
    "morning": Routine(
        "morning", "Morning briefing", "JARVIS_MORNING_BRIEFING", "08:00",
        "a short morning briefing: greet the user, then what's overdue, what's due and "
        "which reminders are set for today, and any goal deadline coming up"
    ),
    "evening": Routine(
        "evening", "Evening review", "JARVIS_EVENING_REVIEW", "21:00",
        "a short evening review: what the user finished today, what's still open from "
        "today, and what tomorrow holds"
    ),
}


class RoutineService:
    """
    Scheduled routines. At each routine's local time a short spoken-style
    text is written from the user's tasks and goals and stored; clients
    poll /routines/due, show it, speak it, and dismiss it.

    Times come from JARVIS_MORNING_BRIEFING / JARVIS_EVENING_REVIEW
    ("HH:MM", or "off"). A routine missed while the backend was down is
    still delivered within LATE_WINDOW.
    """

    LATE_WINDOW = timedelta(hours=4)

    GOAL_HORIZON_DAYS = 7

    # ---------- Schedule ----------

    @staticmethod
    def scheduled_time(kind: str) -> time | None:
        routine = ROUTINES[kind]
        value = os.getenv(routine.env, routine.default_time).strip().lower()

        if value in ("off", "none", "no", ""):
            return None

        match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            print(f"WARNING: {routine.env}={value!r} isn't HH:MM; using {routine.default_time}")
            match = re.fullmatch(r"(\d{1,2}):(\d{2})", routine.default_time)

        return time(int(match.group(1)), int(match.group(2)))

    @staticmethod
    def is_due(kind: str, now: datetime) -> bool:
        """Its time today has passed, within LATE_WINDOW (and before midnight)."""
        at = RoutineService.scheduled_time(kind)
        if at is None:
            return False

        start = datetime.combine(now.date(), at, now.tzinfo)
        return start <= now < start + RoutineService.LATE_WINDOW

    # ---------- Content ----------

    @staticmethod
    def _when(moment: datetime, now: datetime) -> str:
        """The time, with the day when it isn't today (spelled out, for the LLM)."""
        local = moment.astimezone(now.tzinfo)
        days = (local.date() - now.date()).days
        day = {0: "", -1: "yesterday ", 1: "tomorrow "}.get(days, local.strftime("%A %d %B "))
        return f"{day}{local.strftime('%H:%M')}"

    @staticmethod
    def _task(task, now: datetime) -> str:
        details = []
        if task.due_at:
            was = "was due" if task.due_at < now else "due"
            details.append(f"{was} {RoutineService._when(task.due_at, now)}")
        if task.remind_at and task.reminded_at is None:
            details.append(f"reminder {RoutineService._when(task.remind_at, now)}")
        if task.recurrence:
            details.append(f"repeats {describe_recurrence(task.recurrence)}")
        priority = " (high priority)" if task.priority == "high" else ""
        return f"- {task.title}{priority}" + (f" ({', '.join(details)})" if details else "")

    @staticmethod
    def facts(db: Session, user_id: int, kind: str, now: datetime) -> str:
        """What the routine is about, as plain lines (also the LLM-free fallback)."""
        today = now.date()
        start = datetime.combine(today, time(0), now.tzinfo)
        tomorrow = start + timedelta(days=1)
        after_tomorrow = tomorrow + timedelta(days=1)

        open_tasks = get_tasks(db, user_id, status="todo")

        def on(task, day_start: datetime, day_end: datetime) -> bool:
            when = [t for t in (task.due_at, task.remind_at) if t]
            return any(day_start <= t < day_end for t in when)

        def by_time(tasks: list) -> list:
            # In the order they happen, as a day is told.
            return sorted(tasks, key=lambda t: min(x for x in (t.due_at, t.remind_at) if x))

        overdue = [t for t in open_tasks if t.due_at and t.due_at < start]
        today_tasks = by_time([t for t in open_tasks if t not in overdue and on(t, start, tomorrow)])
        tomorrow_tasks = by_time([t for t in open_tasks if on(t, tomorrow, after_tomorrow)])
        done_today = [
            t for t in get_tasks(db, user_id, status="done")
            if t.completed_at and t.completed_at >= start
        ]

        horizon = today + timedelta(days=RoutineService.GOAL_HORIZON_DAYS)
        goals = [
            g for g in get_goals(db, user_id)
            if g.status == "active" and g.target_date and g.target_date <= horizon
        ]

        sections = [f"Now: {now.strftime('%A %d %B, %H:%M')}"]

        def section(title: str, lines: list[str], empty: str | None = None):
            if lines:
                sections.append(f"{title}:\n" + "\n".join(lines))
            elif empty:
                sections.append(f"{title}: {empty}")

        if kind == "morning":
            section("Overdue", [RoutineService._task(t, now) for t in overdue])
            section("Today", [RoutineService._task(t, now) for t in today_tasks], "nothing scheduled")
        else:
            section("Finished today", [f"- {t.title}" for t in done_today], "nothing marked done")
            section("Still open from today", [RoutineService._task(t, now) for t in overdue + today_tasks])
            section("Tomorrow", [RoutineService._task(t, now) for t in tomorrow_tasks], "nothing scheduled")

        section("Goal deadlines", [
            f"- {g.title} ({g.progress}% done, "
            + ("overdue" if g.target_date < today else f"due {g.target_date.strftime('%A %d %B')}")
            + ")"
            for g in goals
        ])

        return "\n\n".join(sections)

    @staticmethod
    def last_mode(db: Session, user_id: int) -> str:
        """The persona the user last chatted with."""
        latest = (
            db.query(Conversation.mode)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.id.desc())
            .first()
        )
        return latest[0] if latest else "jarvis"

    @staticmethod
    def compose(kind: str, facts: str, mode: str) -> str:
        """The routine in the persona's voice; the plain facts if the LLM is down."""
        routine = ROUTINES[kind]
        system = (
            f"{LLMService.system_prompt(mode)}\n\n"
            f"Write {routine.brief}, from the facts below only. It will be read aloud: "
            "3 to 6 short sentences, no lists, headings or markdown. Give times as written. "
            "Keep every fact's meaning exact: overdue items are NOT done yet; \"40% done\" "
            "means 40% complete. Never add tasks, times or details that aren't in the facts; "
            "if a section is empty, say so briefly or skip it."
        )

        try:
            text = LLMService().generate_text(system, facts)
        except LLMUnavailableError as error:
            print(f"WARNING: {kind} routine written without the LLM: {error}")
            text = ""

        return text or f"{routine.title}.\n\n{facts}"

    # ---------- Running ----------

    @staticmethod
    def run(db: Session, user_id: int, kind: str, now: datetime | None = None) -> RoutineRun:
        """
        Writes today's routine of this kind. Running it again (e.g. on
        demand) rewrites it and shows it again.
        """
        now = now or local_now()
        text = RoutineService.compose(
            kind,
            RoutineService.facts(db, user_id, kind, now),
            mode := RoutineService.last_mode(db, user_id)
        )

        run = (
            db.query(RoutineRun)
            .filter_by(user_id=user_id, kind=kind, run_date=now.date())
            .first()
        )

        if run is None:
            run = RoutineRun(user_id=user_id, kind=kind, run_date=now.date())
            db.add(run)

        run.text = text
        run.mode = mode
        run.dismissed_at = None

        try:
            db.commit()
        except IntegrityError:
            # Another worker wrote today's run first; keep theirs.
            db.rollback()
            return db.query(RoutineRun).filter_by(user_id=user_id, kind=kind, run_date=now.date()).one()

        db.refresh(run)
        return run

    @staticmethod
    def run_due(db: Session, user_id: int, now: datetime | None = None) -> list[RoutineRun]:
        """Runs each routine whose time has come and that hasn't run today."""
        now = now or local_now()
        ran = []

        for kind in ROUTINES:
            if not RoutineService.is_due(kind, now):
                continue

            exists = (
                db.query(RoutineRun.id)
                .filter_by(user_id=user_id, kind=kind, run_date=now.date())
                .first()
            )
            if exists is None:
                ran.append(RoutineService.run(db, user_id, kind, now))

        return ran

    @staticmethod
    def pending(db: Session, user_id: int, now: datetime | None = None) -> list[RoutineRun]:
        """Today's routines the user hasn't dismissed yet."""
        now = now or local_now()
        return (
            db.query(RoutineRun)
            .filter(
                RoutineRun.user_id == user_id,
                RoutineRun.run_date == now.date(),
                RoutineRun.dismissed_at.is_(None)
            )
            .order_by(RoutineRun.id)
            .all()
        )

    @staticmethod
    def dismiss(db: Session, user_id: int, run_id: int) -> RoutineRun | None:
        run = db.query(RoutineRun).filter_by(id=run_id, user_id=user_id).first()
        if run is None:
            return None
        run.dismissed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run


class RoutineScheduler:
    """Checks every CHECK_SECONDS whether a routine is due (daemon thread)."""

    CHECK_SECONDS = 30

    def __init__(self, user_id: int):
        self.user_id = user_id
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, name="routines", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    for run in RoutineService.run_due(db, self.user_id):
                        print(f"Routine ready: {run.kind} ({run.run_date})")
            except Exception as error:
                print(f"WARNING: routine check failed: {error}")
            self._stop.wait(self.CHECK_SECONDS)
