"""Pull concrete entities out of a natural-language goal (ADR-076).

The planner assigns generic placeholder inputs (a stand-in recipient, "tomorrow
at 10am"). When the user's goal actually names an email address or a time, the
Node Executor uses these to override the placeholder so LIVE actions land where
the user asked.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def emails(text: str) -> List[str]:
    """Every distinct email address in `text`, in first-seen order."""
    seen: List[str] = []
    for m in _EMAIL.findall(text or ""):
        e = m.strip(".,;:)")
        if e.lower() not in [s.lower() for s in seen]:
            seen.append(e)
    return seen


_TIME = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b"
    r"|\b(\d{1,2}):(\d{2})\b",
    re.I,
)


def _parse_hm(text: str) -> Optional[tuple[int, int]]:
    m = _TIME.search(text or "")
    if not m:
        return None
    if m.group(1) is not None:  # 11am / 11:30 pm
        h = int(m.group(1)) % 12
        mn = int(m.group(2) or 0)
        if m.group(3).lower().startswith("p"):
            h += 12
        return h, mn
    return int(m.group(4)) % 24, int(m.group(5))  # 14:00


def event_datetime(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort "when" from phrases like 'at 11am tomorrow', 'tomorrow 3pm',
    'next Monday at 9:30'. Returns a naive local datetime, or None."""
    t = (text or "").lower()
    now = now or datetime.now()
    hm = _parse_hm(t)
    day = None

    if "day after tomorrow" in t:
        day = now.date() + timedelta(days=2)
    elif "tomorrow" in t:
        day = now.date() + timedelta(days=1)
    elif "today" in t or "this afternoon" in t or "tonight" in t:
        day = now.date()
    else:
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday",
                    "saturday", "sunday"]
        for i, wd in enumerate(weekdays):
            if wd in t:
                ahead = (i - now.weekday()) % 7
                if ahead == 0 or "next" in t:
                    ahead += 7 if ("next" in t or ahead == 0) else 0
                day = now.date() + timedelta(days=ahead or 7)
                break

    if day is None and hm is None:
        return None
    if day is None:
        day = now.date()
        if datetime.combine(day, datetime.min.time()).replace(
                hour=hm[0], minute=hm[1]) <= now:
            day += timedelta(days=1)
    h, mn = hm or (10, 0)
    return datetime.combine(day, datetime.min.time()).replace(hour=h, minute=mn)
