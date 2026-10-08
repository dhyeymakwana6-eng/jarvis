import os
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo


def local_timezone() -> tzinfo:
    """
    The user's timezone, for "today" and for showing times to the LLM.
    JARVIS_TIMEZONE (e.g. "Asia/Kolkata") overrides the machine's own,
    which matters on a server or Pi set to UTC.
    """
    name = os.getenv("JARVIS_TIMEZONE")

    if name:
        return ZoneInfo(name)

    return datetime.now().astimezone().tzinfo


def local_now() -> datetime:
    return datetime.now(local_timezone())


def clock_context(now: datetime) -> str:
    """
    The date and time for the chat prompt. Tomorrow is spelled out
    because small models get "tomorrow" wrong from a date alone.
    """
    tomorrow = now + timedelta(days=1)

    return (
        f"Now: {now.strftime('%A %d %B %Y, %H:%M')} ({now.tzname()}). "
        f"Today is {now.strftime('%Y-%m-%d')}; tomorrow is "
        f"{tomorrow.strftime('%A')} {tomorrow.strftime('%Y-%m-%d')}."
    )
