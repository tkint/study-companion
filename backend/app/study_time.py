"""Study-time tracking: sessions you log (web timer, manual entry, or Claude's
``log_study_time``) and the totals shown in the web UI.

Days are counted in the configured TIMEZONE. The daily goal is the catch-up plan's
"hours per day" (``app.study.hours_per_day``), so both stay in step.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from app import study
from app.db import session
from app.models import Course, StudyTime

USER = 1
MAX_MINUTES = 12 * 60  # one entry; a forgotten timer shouldn't log a whole day
MAX_NOTE = 200
SOURCES = ("timer", "manual", "claude")
DAYS_SHOWN = 14
MAX_FUTURE = 5 * 60  # clock skew allowance for started_at
MAX_STREAK = 366


class TimeError(ValueError):
    """Bad input: the message is shown in the UI or to Claude."""


def _minutes(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TimeError("minutes must be a number")
    minutes = round(value)
    if not 1 <= minutes <= MAX_MINUTES:
        raise TimeError(f"minutes must be between 1 and {MAX_MINUTES}")
    return minutes


def log_time(engine: Engine, minutes: object, course_id: object = None,
             started_at: object = None, source: str = "manual", note: object = "",
             now: float | None = None) -> StudyTime:
    """Store one study session. ``started_at`` defaults to ``minutes`` before now."""
    ts = int(now if now is not None else time.time())
    mins = _minutes(minutes)
    if source not in SOURCES:
        raise TimeError(f"source must be one of {', '.join(SOURCES)}")
    if course_id is not None and (isinstance(course_id, bool) or not isinstance(course_id, int)):
        raise TimeError("course_id must be a number")
    if started_at is None:
        start = ts - mins * 60
    elif isinstance(started_at, bool) or not isinstance(started_at, (int, float)):
        raise TimeError("started_at must be a Unix time in seconds")
    else:
        start = int(started_at)
        if start > ts + MAX_FUTURE:
            raise TimeError("started_at is in the future")
        if start < ts - 366 * study.DAY:
            raise TimeError("started_at is more than a year ago")
    text = note.strip() if isinstance(note, str) else ""
    if len(text) > MAX_NOTE:
        raise TimeError(f"note is too long (max {MAX_NOTE} characters)")
    with session(engine) as s:
        if course_id is not None and s.get(Course, course_id) is None:
            raise TimeError(f"no course with id {course_id}")
        row = StudyTime(user_id=USER, course_id=course_id, started_at=start, minutes=mins,
                        source=source, note=text, created_at=ts)
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def delete_time(engine: Engine, entry_id: int) -> bool:
    with session(engine) as s:
        row = s.get(StudyTime, entry_id)
        if row is None or row.user_id != USER:
            return False
        s.delete(row)
        s.commit()
    return True


def _day(ts: int, tz: ZoneInfo) -> date:
    return datetime.fromtimestamp(ts, tz).date()


def time_dict(row: StudyTime, courses: dict[int, Course]) -> dict:
    course = courses.get(row.course_id) if row.course_id is not None else None
    return {"id": row.id, "course_id": row.course_id,
            "course_name": course.fullname if course else "",
            "course_shortname": course.shortname if course else "",
            "started_at": row.started_at, "minutes": row.minutes, "source": row.source,
            "note": row.note}


def streak(per_day: dict[date, int], today: date) -> int:
    """Days in a row with some study, ending today (or yesterday: today isn't over)."""
    day = today if per_day.get(today) else today - timedelta(days=1)
    n = 0
    while per_day.get(day) and n < MAX_STREAK:
        n += 1
        day -= timedelta(days=1)
    return n


def time_summary(engine: Engine, tz: ZoneInfo, now: float | None = None,
                 recent: int = 20) -> dict:
    """Totals for the study-time page: today, this week (Mon-Sun), last 14 days, per course
    over the last 7 days, the streak, the best day, and the latest entries."""
    ts = int(now if now is not None else time.time())
    today = _day(ts, tz)
    since = ts - (MAX_STREAK + 1) * study.DAY
    with session(engine) as s:
        rows = s.exec(select(StudyTime).where(
            StudyTime.user_id == USER, StudyTime.started_at >= since
        ).order_by(col(StudyTime.started_at).desc(), col(StudyTime.id).desc())).all()
        total = sum(s.exec(select(StudyTime.minutes).where(StudyTime.user_id == USER)).all())
        courses = {c.id: c for c in s.exec(select(Course)).all()}
    per_day: dict[date, int] = {}
    per_course: dict[int | None, int] = {}
    week_start = today - timedelta(days=today.weekday())
    last7 = today - timedelta(days=6)
    for r in rows:
        d = _day(r.started_at, tz)
        per_day[d] = per_day.get(d, 0) + r.minutes
        if last7 <= d <= today:
            per_course[r.course_id] = per_course.get(r.course_id, 0) + r.minutes
    days = [{"date": (today - timedelta(days=i)).isoformat(),
             "minutes": per_day.get(today - timedelta(days=i), 0)}
            for i in range(DAYS_SHOWN - 1, -1, -1)]
    best = max(per_day.items(), key=lambda kv: (kv[1], kv[0]), default=None)
    course_rows = []
    for cid, mins in per_course.items():
        course = courses.get(cid) if cid is not None else None
        course_rows.append({"course_id": cid, "course_name": course.fullname if course else "",
                            "course_shortname": course.shortname if course else "",
                            "minutes": mins})
    course_rows.sort(key=lambda r: (-r["minutes"], r["course_name"]))
    return {
        "today": today.isoformat(),
        "today_minutes": per_day.get(today, 0),
        "week_minutes": sum(m for d, m in per_day.items() if week_start <= d <= today),
        "last7_minutes": sum(m for d, m in per_day.items() if last7 <= d <= today),
        "total_minutes": total,
        "goal_minutes_per_day": round(study.hours_per_day(engine) * 60),
        "streak_days": streak(per_day, today),
        "best_day": {"date": best[0].isoformat(), "minutes": best[1]} if best else None,
        "days": days,
        "courses": course_rows,
        "recent": [time_dict(r, courses) for r in rows[:recent]],
    }
