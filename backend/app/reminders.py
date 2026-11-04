"""Reminders without a push service: alarms in the calendar feed you already subscribe to,
and a "today" read model for the in-app banner.

- Deadlines get one VALARM per lead time (default 1 day and 2 hours before), until done.
  Ignored deadlines are not in the feed; optional ones are, but without alarms.
- A daily "study session" event at your reminder time for today and the next days, with
  the catch-up plan's minutes and items for that day and the flashcards due. Calendar apps
  show its alarm as a phone notification.

Settings are per user in SQLite (``ReminderPrefs``), edited on the Calendar page.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import select

from app import study, study_time
from app.api import ui
from app.config import Settings
from app.db import session
from app.models import ReminderPrefs, StudyQuestion
from app.planner import Planner, fmt_minutes

USER = 1
DEFAULT_ALARMS = (1440, 120)
MAX_ALARMS = 3
MAX_LEAD = 14 * 1440
DAILY_DAYS = 7  # daily events in the feed: today and the next 6 days
SOON = 2 * 86400  # banner: deadlines due in the next 48 hours
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ReminderError(ValueError):
    """Bad settings: the message is shown in the UI."""


def _alarms(text: str) -> list[int]:
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if part.isdigit() and 0 < int(part) <= MAX_LEAD:
            out.append(int(part))
    return sorted(set(out), reverse=True)[:MAX_ALARMS]


def prefs(engine: Engine) -> dict:
    with session(engine) as s:
        p = s.get(ReminderPrefs, USER)
    if p is None:
        return {"deadline_alarms": list(DEFAULT_ALARMS), "daily_enabled": True, "daily_time": "18:00"}
    return {"deadline_alarms": _alarms(p.deadline_alarms), "daily_enabled": p.daily_enabled,
            "daily_time": p.daily_time if _TIME.match(p.daily_time) else "18:00"}


def set_prefs(engine: Engine, data: dict, now: float | None = None) -> dict:
    """Update from ``{deadline_alarms: [minutes], daily_enabled: bool, daily_time: "HH:MM"}``
    (each key optional)."""
    current = prefs(engine)
    if "deadline_alarms" in data:
        raw = data["deadline_alarms"]
        if not isinstance(raw, list) or len(raw) > MAX_ALARMS or not all(
                isinstance(m, int) and not isinstance(m, bool) and 0 < m <= MAX_LEAD for m in raw):
            raise ReminderError(f"deadline_alarms: up to {MAX_ALARMS} lead times in minutes "
                                f"(1 to {MAX_LEAD})")
        current["deadline_alarms"] = sorted(set(raw), reverse=True)
    if "daily_enabled" in data:
        if not isinstance(data["daily_enabled"], bool):
            raise ReminderError("daily_enabled must be true or false")
        current["daily_enabled"] = data["daily_enabled"]
    if "daily_time" in data:
        if not isinstance(data["daily_time"], str) or not _TIME.match(data["daily_time"]):
            raise ReminderError('daily_time must look like "18:00"')
        current["daily_time"] = data["daily_time"]
    with session(engine) as s:
        p = s.get(ReminderPrefs, USER) or ReminderPrefs(user_id=USER)
        p.deadline_alarms = ",".join(str(m) for m in current["deadline_alarms"])
        p.daily_enabled = current["daily_enabled"]
        p.daily_time = current["daily_time"]
        p.updated_at = int(now if now is not None else time.time())
        s.add(p)
        s.commit()
    return current


def cards_due(engine: Engine, now: int) -> int:
    with session(engine) as s:
        qs = s.exec(select(StudyQuestion).where(StudyQuestion.user_id == USER)).all()
    return sum(1 for q in qs if study.is_due(q, now))


def daily_sessions(engine: Engine, settings: Settings, now: int, days: int = DAILY_DAYS) -> list[dict]:
    """One study reminder per day from today: start time, planned minutes and items."""
    p = prefs(engine)
    if not p["daily_enabled"]:
        return []
    tz = settings.tz
    hh, mm = (int(x) for x in p["daily_time"].split(":"))
    plan = Planner(settings, engine, now=now).plan(days=days)
    by_day: dict[date, list] = {d: slots for d, slots in plan.days}
    today = datetime.fromtimestamp(now, tz).date()
    due = cards_due(engine, now)
    out = []
    for i in range(days):
        d = today + timedelta(days=i)
        slots = by_day.get(d, [])
        minutes = sum(s.minutes for s in slots)
        cards = due if i == 0 else 0
        if not minutes and not cards:
            continue
        start = int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).timestamp())
        items = [f"{s.item.course_short or s.item.course_name}: {s.item.title}"
                 + (f" ({fmt_minutes(s.minutes)})" if s.minutes else "") for s in slots]
        out.append({"date": d.isoformat(), "start": start, "minutes": minutes,
                    "cards_due": cards, "items": items})
    return out


def today(engine: Engine, settings: Settings, now: float | None = None) -> dict:
    """The in-app reminder banner: what is worth doing today, in a friendly order."""
    ts = int(now if now is not None else time.time())
    soon = [d for d in ui.deadlines(engine, start=ts, end=ts + SOON, now=ts, include_ignored=False)
            if not d["done"] and d.get("mandatory", True)]
    sessions = daily_sessions(engine, settings, ts, days=1)
    tsum = study_time.time_summary(engine, settings.tz, now=ts, recent=0)
    return {
        "now": ts,
        "cards_due": cards_due(engine, ts),
        "deadlines_soon": [{"id": d["id"], "name": d["name"], "due_at": d["due_at"],
                            "course_shortname": d["course_shortname"], "url": d["url"]}
                           for d in soon[:5]],
        "planned_minutes": sessions[0]["minutes"] if sessions else 0,
        "studied_minutes": tsum["today_minutes"],
        "goal_minutes": tsum["goal_minutes_per_day"],
        "streak_days": tsum["streak_days"],
        "prefs": prefs(engine),
    }
