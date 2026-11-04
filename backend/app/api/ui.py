"""Read models for the web UI: dashboard, course detail and deadlines.

Every function takes an engine and returns plain dicts ready for JSON. Times stay Unix
seconds (UTC); the browser formats them in your local time zone.

A deadline counts as *done* when Moodle marks its activity complete (completion state 1
or 2) or when you marked it done in the UI. *Overdue* means past due, not done, in a course
you are still enrolled in, and due within the last ``OVERDUE_DAYS`` (older items from past
semesters would otherwise stay on the dashboard forever).
"""

from __future__ import annotations

import time

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from app.catchup import auto_mandatory, prefs, resolve
from app.db import session
from app.models import Course, Deadline, DeadlineMark, File, ItemPref, Module, Section

OVERDUE_DAYS = 120
WEEK = 7 * 86400
DONE_STATES = {1, 2}  # Moodle completion: 1 complete, 2 complete with pass


def _deadline_dict(d: Deadline, course: Course | None, module: Module | None,
                   mark: DeadlineMark | None, now: int, pref: ItemPref | None = None) -> dict:
    moodle_done = bool(module and module.completion_state in DONE_STATES)
    auto, reason = auto_mandatory(d.source, d.name, d.grade, module.modname if module else "")
    return {
        "id": d.id,
        "source": d.source,
        "kind": d.kind,
        "name": d.name or "(untitled)",
        "due_at": d.due_at,
        "open_at": d.open_at or None,
        "cutoff_at": d.cutoff_at or None,
        "closed": bool(d.cutoff_at and d.cutoff_at < now),
        "url": d.url,
        "grade": d.grade,
        "course_id": d.course_id,
        "course_name": course.fullname if course else "",
        "course_shortname": course.shortname if course else "",
        "module_id": d.module_id,
        "done": moodle_done or mark is not None,
        "done_by": "moodle" if moodle_done else ("you" if mark else None),
        **resolve(pref, auto, reason),
    }


def deadlines(
    engine: Engine,
    start: int | None = None,
    end: int | None = None,
    course_id: int | None = None,
    now: int | None = None,
    include_ignored: bool = True,
) -> list[dict]:
    """Deadlines with a due date in ``[start, end)``, oldest first (enrolled courses only,
    plus site/user calendar events without a course). Each carries ``mandatory`` and
    ``ignored`` (``app.catchup``); ``include_ignored=False`` leaves ignored ones out."""
    now = int(now if now is not None else time.time())
    with session(engine) as s:
        q = select(Deadline).where(Deadline.removed == False, Deadline.due_at != None)  # noqa: E711,E712
        if start is not None:
            q = q.where(Deadline.due_at >= start)
        if end is not None:
            q = q.where(Deadline.due_at < end)
        if course_id is not None:
            q = q.where(Deadline.course_id == course_id)
        rows = s.exec(q.order_by(Deadline.due_at, Deadline.id)).all()
        courses = {c.id: c for c in s.exec(select(Course)).all()}
        module_ids = {d.module_id for d in rows if d.module_id}
        modules = (
            {m.id: m for m in s.exec(select(Module).where(col(Module.id).in_(module_ids))).all()}
            if module_ids else {}
        )
        ids = [d.id for d in rows]
        marks = (
            {m.deadline_id: m for m in s.exec(
                select(DeadlineMark).where(col(DeadlineMark.deadline_id).in_(ids))
            ).all()}
            if ids else {}
        )
    item_prefs = prefs(engine, "deadline", ids)
    out = []
    for d in rows:
        course = courses.get(d.course_id) if d.course_id else None
        if d.course_id and (course is None or not course.enrolled):
            continue
        row = _deadline_dict(d, course, modules.get(d.module_id or 0), marks.get(d.id), now,
                             item_prefs.get(d.id))
        if row["ignored"] and not include_ignored:
            continue
        out.append(row)
    return out


def dashboard(engine: Engine, now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    items = deadlines(engine, start=now - OVERDUE_DAYS * 86400, now=now, include_ignored=False)
    overdue = [d for d in items if d["due_at"] < now and not d["done"]]
    this_week = [d for d in items if now <= d["due_at"] < now + WEEK]
    later = [d for d in items if d["due_at"] >= now + WEEK]
    per_course: dict[int, dict[str, int]] = {}
    for d in items:
        if d["course_id"] is None:
            continue
        c = per_course.setdefault(d["course_id"], {"overdue": 0, "upcoming": 0})
        if d["done"] or not d["mandatory"]:
            continue
        if d["due_at"] < now:
            c["overdue"] += 1
        else:
            c["upcoming"] += 1
    return {
        "now": now,
        "overdue": overdue,
        "this_week": this_week,
        "later": later,
        "courses": [
            {**c, **per_course.get(c["id"], {"overdue": 0, "upcoming": 0})}
            for c in course_progress(engine)
        ],
    }


def course_progress(engine: Engine) -> list[dict]:
    """Enrolled courses with their catch-up progress: activities you completed out of the
    activities Moodle tracks completion for (Moodle's own percentage when it has one)."""
    with session(engine) as s:
        courses = s.exec(
            select(Course).where(Course.enrolled == True).order_by(Course.fullname)  # noqa: E712
        ).all()
        mods = s.exec(
            select(Module.course_id, Module.completion_state).where(
                Module.removed == False, Module.completion_state != None  # noqa: E711,E712
            )
        ).all()
    tracked: dict[int, list[int]] = {}
    for course_id, state in mods:
        t = tracked.setdefault(course_id, [0, 0])
        t[1] += 1
        if state in DONE_STATES:
            t[0] += 1
    out = []
    for c in courses:
        done, total = tracked.get(c.id, [0, 0])
        out.append({
            "id": c.id,
            "shortname": c.shortname,
            "fullname": c.fullname,
            "lang": c.lang,
            "progress": c.progress if c.progress is not None else (
                round(100 * done / total, 1) if total else None
            ),
            "activities_done": done,
            "activities_tracked": total,
            "synced_at": c.synced_at,
        })
    return out


def course_detail(engine: Engine, course_id: int, now: int | None = None) -> dict | None:
    with session(engine) as s:
        course = s.get(Course, course_id)
        if course is None:
            return None
        sections = s.exec(
            select(Section).where(Section.course_id == course_id).order_by(Section.number)
        ).all()
        modules = s.exec(
            select(Module)
            .where(Module.course_id == course_id, Module.removed == False)  # noqa: E712
            .order_by(Module.position, Module.id)
        ).all()
        files = s.exec(
            select(File)
            .where(File.course_id == course_id, File.status != "removed")
            .order_by(File.filepath, File.filename)
        ).all()
    section_prefs = prefs(engine, "section", [sec.id for sec in sections])
    files_by_module: dict[int, list[dict]] = {}
    for f in files:
        files_by_module.setdefault(f.module_id, []).append(file_dict(f))
    mods_by_section: dict[int | None, list[dict]] = {}
    for m in modules:
        mods_by_section.setdefault(m.section_id, []).append({
            "id": m.id,
            "modname": m.modname,
            "name": m.name,
            "description": m.description,
            "url": m.url,
            "visible": m.visible,
            "completion_state": m.completion_state,
            "files": files_by_module.get(m.id, []),
        })
    return {
        "id": course.id,
        "shortname": course.shortname,
        "fullname": course.fullname,
        "summary": course.summary,
        "lang": course.lang,
        "enrolled": course.enrolled,
        "progress": course.progress,
        "synced_at": course.synced_at,
        "sections": [
            {
                "id": sec.id,
                "number": sec.number,
                "name": sec.name,
                "summary": sec.summary,
                "visible": sec.visible,
                "modules": mods_by_section.get(sec.id, []),
                **resolve(section_prefs.get(sec.id), True),
            }
            for sec in sections
        ],
        "deadlines": deadlines(engine, course_id=course_id, now=now),
    }


def file_dict(f: File) -> dict:
    return {
        "id": f.id,
        "filename": f.filename,
        "filepath": f.filepath,
        "mimetype": f.mimetype,
        "filesize": f.filesize,
        "timemodified": f.timemodified,
        "status": f.status,
        "available": f.status == "ok" and bool(f.local_path),
    }


def set_done(engine: Engine, deadline_id: int, done: bool, now: int | None = None) -> bool:
    """Mark a deadline done (or not) by hand. False if it doesn't exist."""
    with session(engine) as s:
        if s.get(Deadline, deadline_id) is None:
            return False
        mark = s.get(DeadlineMark, deadline_id)
        if done and mark is None:
            s.add(DeadlineMark(deadline_id=deadline_id, done_at=int(now or time.time())))
        elif not done and mark is not None:
            s.delete(mark)
        s.commit()
    return True
