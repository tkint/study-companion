"""The study plan as it is shown everywhere (web calendar, ICS, PDF, Excel): course-level
**sessions** for time allocation, and per day the **tasks** for execution.

Both come from the published schedule (``app.planner.published``), never from separate
logic per output:

- ``sessions`` are ``groups.group`` of the schedule's blocks: one per run of one course.
- Each day lists its ``tasks``: one per piece of work planned that day (a section to study,
  an active recall review, a quiz or an assignment, the flashcard review, a long reading,
  a hand-in due that day), with the session it belongs to (``session_id``) or none (a
  reading, a hand-in whose work was planned earlier). A session can hold several tasks; a
  task that runs over several blocks of the day is one task.
- Tasks of a day are grouped by course (in session order), then by priority and urgency.

A task's completion is not part of the plan: ``marks`` reads it when the plan is shown
(a section marked studied, a deadline marked done here or completed on Moodle, any other
task ticked in ``PlanTaskMark``), so ticking a task never changes the calendar.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from app import study
from app.db import session
from app.models import Deadline, DeadlineMark, Module, PlanTaskMark
from app.planner import groups

USER = 1
DAY = 86400
DONE_STATES = {1, 2}  # Moodle completion: complete, pass
KEY = re.compile(r"^(section|deadline|recall|reading)-\d{1,12}(-\d)?$|^flashcards-\d{4}-\d\d-\d\d$")
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
KIND_OF_ITEM = {"assign": "assignment", "quiz": "quiz", "event": "event"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def task_key(b: dict) -> str:
    """A stable key for the work of a block (the same on every day it is planned)."""
    if b.get("kind") == "flashcards":
        return f"flashcards-{b.get('date')}"
    if b.get("kind") == "recall":
        return f"recall-{b.get('section_id') or 0}-{int(b.get('part') or 1)}"
    if b.get("deadline_id") and b.get("item_kind") != "section":
        return f"deadline-{b['deadline_id']}"
    return f"section-{b.get('section_id') or 0}"


def _kind(b: dict) -> str:
    if b.get("kind") == "flashcards":
        return "flashcards"
    if b.get("kind") == "recall":
        return "review"
    return KIND_OF_ITEM.get(b.get("item_kind") or "", "study")


def _title(b: dict) -> str:
    title = (b.get("title") or "").strip()
    if b.get("kind") == "recall":
        return f"Review: {title}"
    if b.get("kind") == "flashcards":
        return "Flashcard review"
    if b.get("item_kind") == "section" and b.get("section_number") is not None:
        return f"Section {b['section_number']}: {title}"
    return title or "Study"


def priority(due: int | None, late: bool, day_start: int, kind: str) -> str:
    """By rule: high when late, overdue or due within 2 days of the day; medium within a
    week (or any hand-in); low otherwise."""
    if late or (due is not None and due < day_start + 2 * DAY):
        return "high"
    if (due is not None and due < day_start + 7 * DAY) or kind in ("assignment", "quiz"):
        return "medium"
    return "low"


def _course(b: dict) -> dict:
    short, full = b.get("course_short") or "", b.get("course_name") or ""
    return {"course_id": b.get("course_id"), "course_code": groups.course_code(short, full),
            "course_name": groups.course_name(short, full),
            "course_label": "Flashcards" if b.get("kind") == "flashcards"
            else groups.course_label(short, full),
            "color": groups.course_color(b.get("course_id"))}


def _day_start(d: str, tz) -> int:
    x = date.fromisoformat(d)
    return int(datetime(x.year, x.month, x.day, tzinfo=tz).timestamp())


def build(data: dict, tz, done: dict[str, bool] | None = None) -> dict:
    """``{"sessions": [...], "plan_days": [...]}`` for a published (or preview) schedule
    ``data``. ``done`` maps task keys to their completion (``marks``)."""
    done = done or {}
    blocks = [b for d in data.get("days", []) for b in d.get("blocks", []) if isinstance(b, dict)]
    sessions = groups.group(blocks)
    session_of: dict[int, dict] = {}
    for s in sessions:
        s["task_keys"] = []
        for b in s["blocks"]:
            session_of[id(b)] = s

    days: dict[str, dict] = {}

    def day(d: str) -> dict:
        if d not in days:
            x = date.fromisoformat(d)
            days[d] = {"date": d, "weekday": WEEKDAYS[x.weekday()], "minutes": 0,
                       "session_ids": [], "tasks": {}}
        return days[d]

    for s in sessions:
        out = day(s["date"])
        out["minutes"] += s["minutes"]
        out["session_ids"].append(s["id"])

    hand_ins: dict[int, dict] = {}  # deadline id -> its last block, for "due today"
    for b in sorted(blocks, key=lambda b: b.get("start", 0)):
        key = task_key(b)
        s = session_of.get(id(b))
        out = day(b["date"])
        task = out["tasks"].get(key)
        if task is None:
            due = b.get("needed_by")
            task = out["tasks"][key] = {
                "key": key, "kind": _kind(b), "title": _title(b), **_course(b),
                "section_id": b.get("section_id"), "section_number": b.get("section_number"),
                "deadline_id": b.get("deadline_id"), "due": due,
                "due_for": b.get("needed_for") or "" if b.get("item_kind") == "section" else "",
                "minutes": 0, "parts": [], "of_parts": int(b.get("parts") or 1),
                "session_id": s["id"] if s else None, "start": b.get("start"),
                "late": False, "url": b.get("url") or "", "files": b.get("files") or [],
                "detail": b.get("detail") or "", "done": False,
            }
        task["minutes"] += int(b.get("minutes") or 0)
        task["parts"].append(int(b.get("part") or 1))
        task["late"] = task["late"] or bool(b.get("late"))
        if s and key not in s["task_keys"]:
            s["task_keys"].append(key)
        if task["kind"] in ("assignment", "quiz", "event") and b.get("deadline_id"):
            hand_ins[int(b["deadline_id"])] = b

    # A hand-in is on the list of the day it is due, even when its work was planned before
    # (within the planned days).
    dates = [d["date"] for d in data.get("days", []) if isinstance(d, dict) and d.get("date")]
    first_day, last_day = (min(dates), max(dates)) if dates else ("", "")
    for b in hand_ins.values():
        due = b.get("needed_by")
        if not due:
            continue
        d = datetime.fromtimestamp(due, tz).date().isoformat()
        if not first_day <= d <= last_day:
            continue
        key = task_key(b)
        out = day(d)
        if key not in out["tasks"]:
            out["tasks"][key] = {
                "key": key, "kind": _kind(b), "title": f"Due: {_title(b)}", **_course(b),
                "section_id": b.get("section_id"), "section_number": b.get("section_number"),
                "deadline_id": b.get("deadline_id"), "due": due, "due_for": "",
                "minutes": 0, "parts": [], "of_parts": 1, "session_id": None, "start": due,
                "late": False, "url": b.get("url") or "", "files": [],
                "detail": f"Hand in “{b.get('title') or ''}” today.", "done": False,
            }

    # Long readings: a task on each day they run, without a time slot.
    for r in data.get("readings", []) or []:
        try:
            first = date.fromisoformat(r["start_date"])
            last = date.fromisoformat(r["end_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if (last - first).days > 120:
            continue
        key = f"reading-{r.get('section_id') or 0}"
        short, full = r.get("course_short") or "", r.get("course_name") or ""
        x = first
        while x <= last:
            d = x.isoformat()
            out = day(d)
            out["tasks"].setdefault(key, {
                "key": key, "kind": "reading", "title": f"Read: {r.get('title') or ''}",
                "course_id": r.get("course_id"),
                "course_code": groups.course_code(short, full),
                "course_name": groups.course_name(short, full),
                "course_label": groups.course_label(short, full),
                "color": groups.course_color(r.get("course_id")),
                "section_id": r.get("section_id"), "section_number": r.get("section_number"),
                "deadline_id": None, "due": r.get("needed_by"),
                "due_for": r.get("needed_for") or "",
                "minutes": 0, "pages": int(r.get("per_day") or 0), "parts": [], "of_parts": 1,
                "session_id": None, "start": None, "late": bool(r.get("late")), "url": "",
                "files": r.get("files") or [], "detail": r.get("detail") or "",
                "done": False,
            })
            x += timedelta(days=1)

    session_start = {s["id"]: s["start"] for s in sessions}
    plan_days = []
    for d in sorted(days):
        out = days[d]
        start = _day_start(d, tz)
        tasks = list(out["tasks"].values())
        for t in tasks:
            t["done"] = bool(done.get(t["key"]))
            t["priority"] = priority(t["due"], t["late"], start, t["kind"])
            t["part"] = _parts(t.pop("parts"), t["of_parts"])
        # Courses in the order of their first session that day (courses without one last),
        # each course's tasks by priority, then deadline, then time.
        first: dict = {}
        for t in tasks:
            at = session_start.get(t["session_id"] or "", None)
            c = t["course_id"]
            if at is not None:
                first[c] = min(first.get(c, at), at)
        inf = float("inf")
        tasks.sort(key=lambda t: (
            first.get(t["course_id"], inf), t["course_label"], PRIORITY_RANK[t["priority"]],
            t["due"] if t["due"] is not None else inf,
            session_start.get(t["session_id"] or "", inf), t["title"]))
        plan_days.append({**out, "tasks": tasks, "courses": _by_course(tasks),
                          "open": sum(1 for t in tasks if not t["done"])})
    for s in sessions:
        s["objective"] = _objective(s, days)
    return {"sessions": sessions, "plan_days": plan_days}


def _parts(nums: list[int], of: int) -> str:
    """"" for a task done in one go, "part 2/4" or "parts 1-2/4" otherwise."""
    if of <= 1 or not nums:
        return ""
    runs = groups._runs(nums)
    return f"part{'s' if len(set(nums)) > 1 else ''} {runs}/{of}"


def _by_course(tasks: list[dict]) -> list[dict]:
    """The day's tasks grouped by course, in order: ``{course_id, course_code,
    course_name, course_label, color, keys}``."""
    out: list[dict] = []
    for t in tasks:
        if not out or out[-1]["course_id"] != t["course_id"]:
            out.append({k: t[k] for k in ("course_id", "course_code", "course_name",
                                           "course_label", "color")} | {"keys": []})
        out[-1]["keys"].append(t["key"])
    return out


def _objective(s: dict, days: dict[str, dict]) -> str:
    """A short line on what a session is for: its first task, "+ n more"."""
    keys = s.get("task_keys") or []
    if not keys:
        return ""
    tasks = days.get(s["date"], {}).get("tasks", {})
    first = tasks.get(keys[0], {}).get("title", "")
    if len(first) > 70:
        first = first[:67].rstrip() + "…"
    return first + (f" + {len(keys) - 1} more" if len(keys) > 1 else "")


# ---------------------------------------------------------------------- completion


def marks(engine: Engine, data: dict) -> dict[str, bool]:
    """Completion of the plan's tasks, by key: sections studied, deadlines done (by you or
    on Moodle), other tasks ticked."""
    blocks = [b for d in data.get("days", []) for b in d.get("blocks", []) if isinstance(b, dict)]
    deadline_ids = {int(b["deadline_id"]) for b in blocks
                    if b.get("deadline_id") and b.get("item_kind") != "section"}
    out: dict[str, bool] = {f"section-{sid}": True for sid in study.studied_sections(engine)}
    with session(engine) as s:
        for m in s.exec(select(PlanTaskMark).where(PlanTaskMark.user_id == USER)).all():
            out[m.key] = True
        if deadline_ids:
            for m in s.exec(select(DeadlineMark).where(
                    col(DeadlineMark.deadline_id).in_(deadline_ids))).all():
                out[f"deadline-{m.deadline_id}"] = True
            rows = s.exec(select(Deadline).where(col(Deadline.id).in_(deadline_ids))).all()
            module_ids = {d.module_id for d in rows if d.module_id}
            if module_ids:
                done_modules = {m.id for m in s.exec(select(Module).where(
                    col(Module.id).in_(module_ids))).all() if m.completion_state in DONE_STATES}
                for d in rows:
                    if d.module_id in done_modules:
                        out[f"deadline-{d.id}"] = True
    return out


class TaskError(ValueError):
    """A bad task key: the message is shown in the UI."""


def set_done(engine: Engine, key: str, done: bool, now: float | None = None) -> bool:
    """Tick (or untick) a task. A section is marked studied, a deadline done; anything
    else is kept in ``PlanTaskMark``. False if the section or deadline doesn't exist."""
    if not isinstance(key, str) or not KEY.match(key):
        raise TaskError("unknown task")
    kind, _, rest = key.partition("-")
    ts = int(now if now is not None else time.time())
    if kind == "section":
        return study.set_studied(engine, int(rest), done, now=ts)
    if kind == "deadline":
        from app.api.ui import set_done as deadline_done
        return deadline_done(engine, int(rest), done, now=ts)
    with session(engine) as s:
        mark = s.exec(select(PlanTaskMark).where(PlanTaskMark.user_id == USER,
                                                 PlanTaskMark.key == key)).first()
        if done and mark is None:
            s.add(PlanTaskMark(user_id=USER, key=key, done_at=ts))
        elif not done and mark is not None:
            s.delete(mark)
        s.commit()
    return True
