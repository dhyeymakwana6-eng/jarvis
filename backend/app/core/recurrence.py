"""
Repeating tasks. A rule is a short string:

    daily               every day
    weekdays            Monday to Friday
    weekly              every week, on the first occurrence's weekday
    weekly:mon,thu      every week on those days
    days:3              every 3 days
    monthly             every month, on the first occurrence's day
    monthly:31          every month on that day (the month's last day
                        when it's shorter)

"weekly" and "monthly" are pinned to a weekday/day when a task gets them
(see pin), so a 31st that falls back to the 28th doesn't stay there.

Occurrences keep the local wall-clock time of the first one ("4 pm every
day" stays 4 pm across DST changes).
"""
import calendar
import re
from datetime import datetime, timedelta

from app.core.clock import local_timezone


WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

FORMATS = "daily, weekdays, weekly, weekly:mon,thu (any days), days:N (every N days), monthly or monthly:D (day D)"


class RecurrenceError(ValueError):
    pass


def normalize(rule: str) -> str:
    """The canonical form of a rule; RecurrenceError if it isn't one."""
    rule = re.sub(r"\s+", "", rule.strip().lower())

    if rule in ("daily", "weekdays", "weekly", "monthly"):
        return rule

    if rule.startswith("weekly:"):
        days = [day[:3] for day in rule.removeprefix("weekly:").split(",") if day]
        if days and all(day in WEEKDAYS for day in days):
            return "weekly:" + ",".join(sorted(set(days), key=WEEKDAYS.index))

    if match := re.fullmatch(r"monthly:(\d{1,2})", rule):
        if 1 <= int(match.group(1)) <= 31:
            return f"monthly:{int(match.group(1))}"

    if match := re.fullmatch(r"days:(\d{1,3})", rule):
        interval = int(match.group(1))
        if interval == 1:
            return "daily"
        if interval > 1:
            return rule

    raise RecurrenceError(f"unknown repeat rule {rule!r}; use {FORMATS}")


def pin(rule: str, anchor: datetime) -> str:
    """Fixes "weekly"/"monthly" to the first occurrence's weekday/day."""
    local = anchor.astimezone(local_timezone())
    if rule == "weekly":
        return f"weekly:{WEEKDAYS[local.weekday()]}"
    if rule == "monthly":
        return f"monthly:{local.day}"
    return rule


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def describe(rule: str) -> str:
    """Human wording: "every day", "every Mon and Thu"."""
    if rule == "daily":
        return "every day"
    if rule == "weekdays":
        return "every weekday"
    if rule == "weekly":
        return "every week"
    if rule == "monthly":
        return "every month"
    if rule.startswith("monthly:"):
        return f"every month on the {_ordinal(int(rule.removeprefix('monthly:')))}"
    if rule.startswith("weekly:"):
        days = [day.capitalize() for day in rule.removeprefix("weekly:").split(",")]
        return "every " + (" and ".join(days) if len(days) <= 2 else ", ".join(days[:-1]) + " and " + days[-1])
    return f"every {rule.removeprefix('days:')} days"


def _add_months(moment: datetime, months: int, day: int) -> datetime:
    month_index = moment.month - 1 + months
    year, month = moment.year + month_index // 12, month_index % 12 + 1
    return moment.replace(year=year, month=month, day=min(day, calendar.monthrange(year, month)[1]))


def next_occurrence(rule: str, anchor: datetime, after: datetime) -> datetime:
    """
    The first occurrence of `rule` strictly after `after`, counting from
    `anchor` (an existing occurrence, which sets the time of day and, for
    weekly/monthly, the weekday or day of month). Missed occurrences are
    skipped, not queued.
    """
    tz = local_timezone()
    first = anchor.astimezone(tz)
    after = after.astimezone(tz)

    def at(day) -> datetime:
        # Same wall-clock time on another day (DST-safe).
        return datetime.combine(day, first.timetz().replace(tzinfo=None), tz)

    if rule.startswith("monthly"):
        day = int(rule.removeprefix("monthly:")) if ":" in rule else first.day
        months = 1
        candidate = _add_months(first, months, day)
        while candidate <= after:
            months += 1
            candidate = _add_months(first, months, day)
        return candidate

    if rule.startswith("days:"):
        interval = int(rule.removeprefix("days:"))
        # Jump close to `after`, then step to the first one past it.
        steps = max(1, (after.date() - first.date()).days // interval)
        while at(first.date() + timedelta(days=steps * interval)) <= after:
            steps += 1
        return at(first.date() + timedelta(days=steps * interval))

    if rule == "daily":
        allowed = set(range(7))
    elif rule == "weekdays":
        allowed = set(range(5))
    elif rule == "weekly":
        allowed = {first.weekday()}
    else:
        allowed = {WEEKDAYS.index(day) for day in rule.removeprefix("weekly:").split(",")}

    day = max(first.date(), after.date())
    for _ in range(8):
        candidate = at(day)
        if candidate > after and candidate > first and day.weekday() in allowed:
            return candidate
        day += timedelta(days=1)

    raise RecurrenceError(f"no occurrence for {rule!r}")  # unreachable for valid rules
