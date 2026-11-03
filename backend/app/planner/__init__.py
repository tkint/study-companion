"""Rule-based catch-up plan (no AI).

What is left to study: every non-empty section of your enrolled courses that you have not
marked studied and that Moodle does not show as fully completed, plus the open assignment,
quiz and calendar deadlines. Each item gets an estimated time (from page counts) and a
*needed by* date: a deadline's own due date, and for a section the earliest open deadline
in that section or a later one of the same course (later work builds on earlier sections).

Items are ordered by needed-by date, then by grade weight, then by section number (so
courses without deadlines interleave), and laid out day by day within your hours per day.
An item that only fits after its date is flagged ``late``; what does not fit in the horizon
is listed as unscheduled.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.engine import Engine

from app.api.ui import OVERDUE_DAYS
from app.api.ui import deadlines as deadline_rows
from app.config import Settings
from app.materials import CourseMaterials, SectionInfo, bounds, enrolled_courses, load_course
from app.study import hours_per_day as saved_hours, section_counts, studied_sections

# Reading time per unit of extracted text, in minutes.
MINUTES_PER_UNIT = {"page": 3.0, "slide": 1.5, "part": 4.0}
MINUTES_PER_ACTIVITY = 5  # pages, links, books... without files
MIN_SECTION_MINUTES = 15
DEADLINE_MINUTES = {"assign": 120, "quiz": 45, "event": 30}
QUIET_MODULES = {"label", "forum", "feedback", "choice"}
MAX_DAYS = 90


@dataclass
class PlanItem:
    kind: str  # section, assign, quiz, event
    course_id: int | None
    course_name: str
    course_short: str
    title: str
    minutes: int
    needed_by: int | None = None
    needed_for: str = ""  # name of the deadline that sets needed_by
    section_id: int | None = None
    section_number: int | None = None
    deadline_id: int | None = None
    url: str = ""
    grade: float | None = None
    pages: int = 0
    files: list[tuple[int, str, int]] = field(default_factory=list)  # (file_id, name, pages)
    has_summary: bool = False
    questions: int = 0
    overdue: bool = False

    def key(self) -> tuple:
        rank = 0 if self.kind == "section" else 1
        return (
            self.needed_by if self.needed_by is not None else math.inf,
            rank,
            -(self.grade or 0),
            self.section_number if self.section_number is not None else 999,
            self.course_name,
            self.title,
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "course_id": self.course_id, "course_name": self.course_name,
            "course_short": self.course_short, "title": self.title, "minutes": self.minutes,
            "needed_by": self.needed_by, "needed_for": self.needed_for,
            "section_id": self.section_id, "section_number": self.section_number,
            "deadline_id": self.deadline_id, "url": self.url, "grade": self.grade,
            "pages": self.pages,
            "files": [{"id": i, "name": n, "pages": p} for i, n, p in self.files],
            "has_summary": self.has_summary, "questions": self.questions,
            "overdue": self.overdue,
        }


@dataclass
class Slot:
    item: PlanItem
    minutes: int
    part: int = 1
    parts: int = 1
    late: bool = False

    def to_dict(self) -> dict:
        return {**self.item.to_dict(), "minutes_today": self.minutes, "part": self.part,
                "parts": self.parts, "late": self.late}


@dataclass
class Plan:
    today: date
    hours_per_day: float
    days: list[tuple[date, list[Slot]]]
    unscheduled: list[PlanItem]
    total_minutes: int
    sections_left: int
    sections_done: int
    notes: list[str]

    @property
    def late(self) -> list[Slot]:
        return [s for _, slots in self.days for s in slots if s.late]

    def to_dict(self) -> dict:
        return {
            "today": self.today.isoformat(),
            "hours_per_day": self.hours_per_day,
            "total_minutes": self.total_minutes,
            "sections_left": self.sections_left,
            "sections_done": self.sections_done,
            "late": len(self.late),
            "notes": self.notes,
            "days": [
                {"date": d.isoformat(), "minutes": sum(s.minutes for s in slots),
                 "items": [s.to_dict() for s in slots]}
                for d, slots in self.days
            ],
            "unscheduled": [i.to_dict() for i in self.unscheduled],
            "unscheduled_minutes": sum(i.minutes for i in self.unscheduled),
        }


def _round5(minutes: float) -> int:
    return max(5, int(math.ceil(minutes / 5.0)) * 5)


def section_minutes(sec: SectionInfo) -> tuple[int, int]:
    """Estimated (minutes, pages) to study a section."""
    minutes, pages = 0.0, 0
    for f in sec.files:
        n = f.pages
        pages += n
        minutes += n * MINUTES_PER_UNIT.get(f.unit, 3.0)
    for m in sec.modules:
        if not m.files and m.row.modname not in QUIET_MODULES:
            minutes += MINUTES_PER_ACTIVITY
    return _round5(max(MIN_SECTION_MINUTES, minutes)), pages


def _section_done(sec: SectionInfo) -> bool:
    tracked = [m for m in sec.modules if m.row.completion_state is not None]
    return bool(tracked) and all(m.done for m in tracked)


def _worth_studying(sec: SectionInfo) -> bool:
    if sec.empty:
        return False
    return bool(sec.files) or any(m.row.modname not in QUIET_MODULES for m in sec.modules) \
        or len(sec.row.summary or "") > 200


class Planner:
    def __init__(self, settings: Settings, engine: Engine, now: float | None = None) -> None:
        self.settings = settings
        self.engine = engine
        self.tz = settings.tz
        self.now = int(now if now is not None else time.time())
        self.today = datetime.fromtimestamp(self.now, self.tz).date()

    def items(self, course_id: int | None = None, from_date: date | None = None,
              horizon_end: int | None = None) -> tuple[list[PlanItem], int, int, list[str]]:
        notes: list[str] = []
        courses = [c for c in enrolled_courses(self.engine)
                   if course_id is None or c.id == course_id]
        open_deadlines = [
            d for d in deadline_rows(self.engine, start=self.now - OVERDUE_DAYS * 86400,
                                     course_id=course_id, now=self.now)
            if not d["done"] and not d["closed"]
        ]
        studied = studied_sections(self.engine)
        items: list[PlanItem] = []
        left = done = 0
        start, _ = bounds(from_date, None, self.tz)
        course_ids = {c.id for c in courses}
        for c in courses:
            cm = load_course(self.engine, c.id)
            if cm is None:
                continue
            sections, note = cm.select(start, None)
            if note and from_date:
                notes.append(f"{c.fullname}: nothing is dated since {from_date}, so every "
                             "section is included.")
            by_module = self._deadlines_by_section(cm, open_deadlines)
            counts = section_counts(self.engine, [s.row.id for s in sections])
            for sec in sections:
                if not _worth_studying(sec):
                    continue
                if sec.row.id in studied or _section_done(sec):
                    done += 1
                    continue
                left += 1
                minutes, pages = section_minutes(sec)
                need = self._needed_by(cm, sec, by_module)
                info = counts.get(sec.row.id, {})
                items.append(PlanItem(
                    kind="section", course_id=c.id, course_name=c.fullname,
                    course_short=c.shortname, title=sec.row.name or f"Section {sec.row.number}",
                    minutes=minutes, needed_by=need[0] if need else None,
                    needed_for=need[1] if need else "", section_id=sec.row.id,
                    section_number=sec.row.number, pages=pages,
                    files=[(f.id, f.row.filename, f.pages) for f in sec.files if f.readable][:6],
                    has_summary=bool(info.get("summary_at")), questions=info.get("questions", 0),
                ))
        for d in open_deadlines:
            if d["course_id"] is not None and d["course_id"] not in course_ids:
                continue
            if horizon_end is not None and d["due_at"] >= horizon_end:
                continue
            items.append(PlanItem(
                kind=d["source"] if d["source"] in DEADLINE_MINUTES else "event",
                course_id=d["course_id"], course_name=d["course_name"],
                course_short=d["course_shortname"], title=d["name"],
                minutes=DEADLINE_MINUTES.get(d["source"], 30), needed_by=d["due_at"],
                needed_for=d["name"], deadline_id=d["id"], url=d["url"], grade=d["grade"],
                overdue=d["due_at"] < self.now,
            ))
        items.sort(key=PlanItem.key)
        return items, left, done, notes

    def _deadlines_by_section(self, cm: CourseMaterials, open_deadlines: list[dict]) -> dict[int, tuple[int, str]]:
        """Earliest open deadline per section number of this course."""
        module_section = {m.row.id: s.row.number for s in cm.sections for m in s.modules}
        out: dict[int, tuple[int, str]] = {}
        for d in open_deadlines:
            if d["course_id"] != cm.course.id or not d["module_id"]:
                continue
            num = module_section.get(d["module_id"])
            if num is None:
                continue
            if num not in out or d["due_at"] < out[num][0]:
                out[num] = (d["due_at"], d["name"])
        return out

    def _needed_by(self, cm: CourseMaterials, sec: SectionInfo,
                   by_section: dict[int, tuple[int, str]]) -> tuple[int, str] | None:
        later = [v for num, v in by_section.items() if num >= sec.row.number]
        return min(later) if later else None

    def plan(self, course_id: int | None = None, hours: float | None = None, days: int = 14,
             from_date: date | None = None) -> Plan:
        hours = hours if hours is not None else saved_hours(self.engine)
        days = max(1, min(MAX_DAYS, int(days)))
        budget = max(15, int(round(hours * 60)))
        end_day = self.today + timedelta(days=days)
        horizon_end = bounds(None, end_day + timedelta(days=30), self.tz)[1]
        items, left, done, notes = self.items(course_id, from_date, horizon_end)
        schedule: list[tuple[date, list[Slot]]] = [
            (self.today + timedelta(days=i), []) for i in range(days)]
        day_i, used = 0, 0
        unscheduled: list[PlanItem] = []
        for item in items:
            if day_i >= days:
                unscheduled.append(item)
                continue
            remaining, pieces = item.minutes, []
            while remaining > 0 and day_i < days:
                free = budget - used
                if free < 15 and used > 0:  # don't start something in the last minutes
                    day_i, used = day_i + 1, 0
                    continue
                take = min(free, remaining)
                pieces.append((day_i, take))
                used += take
                remaining -= take
                if used >= budget:
                    day_i, used = day_i + 1, 0
            if not pieces:
                unscheduled.append(item)
                continue
            n = len(pieces)
            for part, (d_i, take) in enumerate(pieces, start=1):
                day = schedule[d_i][0]
                # Late: finished only after the date it is needed by (overdue items are
                # flagged as overdue instead).
                late = bool(item.needed_by is not None and item.needed_by >= self.now
                            and part == n and bounds(day, None, self.tz)[0] >= item.needed_by)
                schedule[d_i][1].append(Slot(item, take, part, n + (1 if remaining > 0 else 0), late))
            if remaining > 0:
                unscheduled.append(PlanItem(**{**item.__dict__, "minutes": remaining}))
        while schedule and not schedule[-1][1]:
            schedule.pop()
        if any(s.late for _, slots in schedule for s in slots):
            notes.append("Some items only fit after the deadline they are needed for: add study "
                         "time per day or skip less important sections.")
        return Plan(
            today=self.today, hours_per_day=hours, days=schedule, unscheduled=unscheduled,
            total_minutes=sum(i.minutes for i in items), sections_left=left,
            sections_done=done, notes=notes,
        )


def fmt_minutes(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} h {m:02d}"
    return f"{h} h" if h else f"{m} min"
