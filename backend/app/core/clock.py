import os
from datetime import datetime, tzinfo
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
