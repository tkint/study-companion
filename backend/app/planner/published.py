"""The published study schedule: what the calendar view, the printed weeks and the ICS feed
show.

The schedule is generated from your saved settings when you save them (and, with
``auto_update``, every night), then kept as is. A calendar app that refreshes the feed
therefore sees the same blocks until the plan changes on purpose, instead of blocks that
move every time it asks. Blocks that already ended are kept for ``HISTORY_DAYS``, so the
calendar keeps a record of what you planned.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta

from sqlalchemy.engine import Engine

from app.config import Settings
from app.db import session
from app.models import PublishedSchedule
from app.planner import schedule, tasks

logger = logging.getLogger("app.planner.published")

USER = 1
HISTORY_DAYS = 42


def _stored(engine: Engine) -> tuple[dict | None, int]:
    with session(engine) as s:
        row = s.get(PublishedSchedule, USER)
    if row is None:
        return None, 0
    try:
        data = json.loads(row.data or "{}")
    except ValueError:
        return None, 0
    return (data if isinstance(data, dict) and isinstance(data.get("days"), list) else None,
            row.published_at)


def _merge_history(old: dict | None, new: dict, now: int) -> dict:
    """``new`` with the blocks of ``old`` that ended before ``now`` (within HISTORY_DAYS).

    A plan that starts on a later day (``start_date``) keeps nothing from before it, not even
    blocks that already passed: the calendar shows no study before the start."""
    if not old or new.get("start", new["today"]) > new["today"]:
        return new
    today = new["today"]
    oldest = (date.fromisoformat(today) - timedelta(days=HISTORY_DAYS)).isoformat()
    past: dict[str, dict] = {}
    for d in old.get("days", []):
        if not isinstance(d, dict) or not isinstance(d.get("date"), str):
            continue
        if not oldest <= d["date"] <= today:
            continue
        done = [b for b in d.get("blocks", []) if isinstance(b, dict) and b.get("end", 0) <= now]
        if done:
            past[d["date"]] = {**d, "blocks": done, "minutes": sum(b.get("minutes", 0) for b in done)}
    days = []
    for d in new["days"]:
        if d["date"] in past:
            kept = past.pop(d["date"])["blocks"]
            blocks = kept + [b for b in d["blocks"] if b["start"] >= now]
            d = {**d, "blocks": blocks, "minutes": sum(b["minutes"] for b in blocks)}
        days.append(d)
    history = [past[k] for k in sorted(past)]
    # Readings that ended before today stay too; the new plan has the rest.
    read = [r for r in old.get("readings", []) if isinstance(r, dict)
            and oldest <= str(r.get("end_date", "")) < today]
    return {**new, "days": history + days, "readings": read + new.get("readings", [])}


def publish(settings: Settings, engine: Engine, now: float | None = None) -> dict:
    """Generate the schedule from the saved settings and make it the published one."""
    ts = int(now if now is not None else time.time())
    plan = schedule.Generator(settings, engine, now=ts).generate().to_dict()
    old, _ = _stored(engine)
    data = _merge_history(old, plan, ts)
    with session(engine) as s:
        row = s.get(PublishedSchedule, USER) or PublishedSchedule(user_id=USER)
        row.data = json.dumps(data, separators=(",", ":"))
        row.published_at = ts
        s.add(row)
        s.commit()
    return _with_busy(settings, engine, {**data, "published_at": ts, "preview": False})


def current(settings: Settings, engine: Engine, now: float | None = None) -> dict:
    """The published schedule (published now if there is none yet), with today's date and
    the saved settings as they are now."""
    data, at = _stored(engine)
    if data is None:
        return publish(settings, engine, now)
    ts = int(now if now is not None else time.time())
    return _with_busy(settings, engine, {
        **data, "today": datetime.fromtimestamp(ts, settings.tz).date().isoformat(),
        "config": schedule.load(engine), "published_at": at, "preview": False})


def preview(settings: Settings, engine: Engine, data: dict, now: float | None = None) -> dict:
    """The schedule the unsaved settings ``data`` would give. Raises ScheduleError."""
    config = schedule.draft(engine, data)
    plan = schedule.Generator(settings, engine, now=now, config=config).generate().to_dict()
    return _with_busy(settings, engine, {**plan, "published_at": None, "preview": True})


def busy_range(data: dict) -> tuple[date, date]:
    """From the first day kept in ``data`` (or today) to the end of the planning horizon,
    which counts from the plan's start (today or a later start date)."""
    today = date.fromisoformat(data["today"])
    first = today
    if data.get("days"):
        first = min(first, date.fromisoformat(data["days"][0]["date"]))
    try:
        start = max(today, date.fromisoformat(data.get("start") or data["today"]))
    except ValueError:
        start = today
    return first, start + timedelta(days=int(data["config"]["days"]) - 1)


def _with_busy(settings: Settings, engine: Engine, data: dict) -> dict:
    """``data`` plus ``busy`` (your unavailabilities over its range), ``sessions`` (the
    blocks as course-level study sessions) and ``plan_days`` (each day's tasks, with their
    completion): ``app.planner.tasks``, what every view and export shows."""
    first, last = busy_range(data)
    view = tasks.build(data, settings.tz, tasks.marks(engine, data))
    return {**data, "busy": busy(data["config"], first, last, settings.tz),
            "sessions": view["sessions"],
            "plan_days": view["plan_days"]}


def nightly(settings: Settings, engine: Engine, now: float | None = None) -> bool:
    """Re-plan if ``auto_update`` is on. Returns whether it did."""
    if not schedule.load(engine).get("auto_update", True):
        return False
    publish(settings, engine, now)
    logger.info("Study schedule updated for the night")
    return True


def busy(config: dict, start: date, end: date, tz) -> list[dict]:
    """Your unavailabilities from ``start`` to ``end`` (inclusive) as timed intervals:
    ``{date, start, end (timestamps), reason, repeat}``. Weekly ones are expanded day by
    day so every occurrence keeps its local time across daylight saving changes."""
    out = []
    d = start
    while d <= end:
        for r in schedule.unavailable(config, d):
            s_min, e_min = schedule._minutes(r["start"]), schedule._minutes(r["end"])
            s = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=s_min)
            e = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=e_min)
            out.append({"date": d.isoformat(), "start": int(s.timestamp()), "end": int(e.timestamp()),
                        "all_day": s_min == 0 and e_min == 1440,
                        "reason": r.get("reason", ""), "repeat": r["repeat"]})
        d += timedelta(days=1)
    out.sort(key=lambda x: x["start"])
    return out
