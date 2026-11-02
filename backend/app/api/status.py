"""Read-only summaries of the synced data for the status page and JSON API."""

from __future__ import annotations

import time

from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlmodel import select

from app.db import session
from app.models import Course, Deadline, File, SyncRun


def run_to_dict(run: SyncRun) -> dict:
    return run.model_dump()


def course_overview(engine: Engine, now: int | None = None) -> list[dict]:
    now = int(now if now is not None else time.time())
    with session(engine) as s:
        courses = s.exec(
            select(Course).where(Course.enrolled == True).order_by(Course.fullname)  # noqa: E712
        ).all()
        files: dict[int, dict[str, int]] = {}
        for course_id, status, count, size in s.exec(
            select(File.course_id, File.status, func.count(), func.sum(File.filesize)).group_by(
                File.course_id, File.status
            )
        ).all():
            files.setdefault(course_id, {})[status] = count
            files[course_id][f"{status}_bytes"] = int(size or 0)
        upcoming = dict(
            s.exec(
                select(Deadline.course_id, func.count())
                .where(Deadline.removed == False, Deadline.due_at >= now)  # noqa: E712
                .group_by(Deadline.course_id)
            ).all()
        )
        overdue = dict(
            s.exec(
                select(Deadline.course_id, func.count())
                .where(Deadline.removed == False, Deadline.due_at < now)  # noqa: E712
                .group_by(Deadline.course_id)
            ).all()
        )
    out = []
    for c in courses:
        f = files.get(c.id, {})
        out.append(
            {
                "id": c.id,
                "shortname": c.shortname,
                "fullname": c.fullname,
                "lang": c.lang,
                "lang_source": c.lang_source,
                "folder": c.folder,
                "files_ok": f.get("ok", 0),
                "files_total": sum(v for k, v in f.items() if not k.endswith("_bytes") and k != "removed"),
                "files_skipped": f.get("skipped_size", 0),
                "files_error": f.get("error", 0),
                "bytes_ok": f.get("ok_bytes", 0),
                "deadlines_upcoming": upcoming.get(c.id, 0),
                "deadlines_past": overdue.get(c.id, 0),
                "synced_at": c.synced_at,
            }
        )
    return out
