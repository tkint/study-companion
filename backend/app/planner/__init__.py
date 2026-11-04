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
from app.catchup import prefs, resolve, target_percent
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
    mandatory: bool = True
    catch_up: bool = False  # behind (overdue or needed by nothing upcoming) vs upcoming work

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
            "overdue": self.overdue, "mandatory": self.mandatory, "catch_up": self.catch_up,
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
    progress: Progress | None = None
    beyond_target: list[PlanItem] = field(default_factory=list)
    projected_percent: float = 100.0
    optional_left_out: int = 0
    ignored: int = 0

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
            "target_percent": self.progress.target_percent if self.progress else None,
            "progress": self.progress.to_dict() if self.progress else None,
            "projected_percent": self.projected_percent,
            "beyond_target": [i.to_dict() for i in self.beyond_target],
            "beyond_target_minutes": sum(i.minutes for i in self.beyond_target),
            "optional_left_out": self.optional_left_out,
            "ignored": self.ignored,
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


@dataclass
class Progress:
    """Catch-up progress on mandatory, non-ignored work, weighted by estimated minutes.

    The scope is every studyable section of your enrolled courses plus the mandatory
    deadlines due in the last ``OVERDUE_DAYS`` (closed ones you can no longer hand in are
    left out). Done: sections marked studied or complete in Moodle, deadlines done.
    """

    target_percent: float
    done_minutes: int = 0
    total_minutes: int = 0
    done_items: int = 0
    total_items: int = 0

    @property
    def percent(self) -> float:
        return round(100 * self.done_minutes / self.total_minutes, 1) if self.total_minutes else 100.0

    @property
    def target_minutes(self) -> int:
        return int(math.ceil(self.total_minutes * self.target_percent / 100))

    @property
    def left_to_target(self) -> int:
        return max(0, self.target_minutes - self.done_minutes)

    @property
    def reached(self) -> bool:
        return self.left_to_target == 0

    def to_dict(self) -> dict:
        return {
            "target_percent": self.target_percent, "percent": self.percent,
            "reached": self.reached, "done_items": self.done_items,
            "total_items": self.total_items, "done_minutes": self.done_minutes,
            "total_minutes": self.total_minutes, "left_minutes_to_target": self.left_to_target,
        }


@dataclass
class Items:
    items: list[PlanItem]
    sections_left: int
    sections_done: int
    notes: list[str]
    progress: Progress
    optional_left_out: int = 0
    ignored: int = 0


class Planner:
    def __init__(self, settings: Settings, engine: Engine, now: float | None = None) -> None:
        self.settings = settings
        self.engine = engine
        self.tz = settings.tz
        self.now = int(now if now is not None else time.time())
        self.today = datetime.fromtimestamp(self.now, self.tz).date()

    def items(self, course_id: int | None = None, from_date: date | None = None,
              horizon_end: int | None = None, include_optional: bool = False) -> Items:
        notes: list[str] = []
        progress = Progress(target_percent=target_percent(self.engine))
        courses = [c for c in enrolled_courses(self.engine)
                   if course_id is None or c.id == course_id]
        recent = deadline_rows(self.engine, start=self.now - OVERDUE_DAYS * 86400,
                               course_id=course_id, now=self.now)
        ignored = sum(1 for d in recent if d["ignored"] and not d["done"])
        recent = [d for d in recent if not d["ignored"]]
        open_deadlines = [d for d in recent if not d["done"] and not d["closed"]]
        optional_left_out = 0
        if not include_optional:
            optional_left_out = sum(1 for d in open_deadlines if not d["mandatory"])
            open_deadlines = [d for d in open_deadlines if d["mandatory"]]
        studied = studied_sections(self.engine)
        items: list[PlanItem] = []
        left = done = 0
        start, _ = bounds(from_date, None, self.tz)
        course_ids = {c.id for c in courses}
        for d in recent:  # mandatory past deadlines count towards the target
            if d["mandatory"] and d["due_at"] < self.now and (d["done"] or not d["closed"]) \
                    and (d["course_id"] is None or d["course_id"] in course_ids):
                minutes = DEADLINE_MINUTES.get(d["source"], 30)
                progress.total_items += 1
                progress.total_minutes += minutes
                if d["done"]:
                    progress.done_items += 1
                    progress.done_minutes += minutes
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
            sec_prefs = prefs(self.engine, "section", [s.row.id for s in cm.sections])
            for sec in sections:
                if not _worth_studying(sec):
                    continue
                state = resolve(sec_prefs.get(sec.row.id), True)
                if state["ignored"]:
                    ignored += 1
                    continue
                minutes, pages = section_minutes(sec)
                is_done = sec.row.id in studied or _section_done(sec)
                if state["mandatory"]:
                    progress.total_items += 1
                    progress.total_minutes += minutes
                    if is_done:
                        progress.done_items += 1
                        progress.done_minutes += minutes
                if is_done:
                    done += 1
                    continue
                if not state["mandatory"] and not include_optional:
                    optional_left_out += 1
                    continue
                left += 1
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
                    mandatory=state["mandatory"],
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
                overdue=d["due_at"] < self.now, mandatory=d["mandatory"],
            ))
        for it in items:
            it.catch_up = it.needed_by is None or it.needed_by < self.now
        items.sort(key=PlanItem.key)
        return Items(items, left, done, notes, progress, optional_left_out, ignored)

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

    def progress(self) -> Progress:
        return self.items().progress

    @staticmethod
    def _trim_to_target(items: list[PlanItem], progress: Progress) -> tuple[list[PlanItem], list[PlanItem]]:
        """Keep what upcoming work needs, plus backlog items in priority order until the
        target is covered; the rest of the backlog is *beyond target*."""
        need = progress.left_to_target
        covered = sum(i.minutes for i in items if i.mandatory and not i.catch_up
                      and i.kind == "section")
        keep, beyond = [], []
        for it in items:
            if not it.catch_up:
                keep.append(it)
            elif covered < need:
                keep.append(it)
                if it.mandatory:
                    covered += it.minutes
            else:
                beyond.append(it)
        return keep, beyond

    def plan(self, course_id: int | None = None, hours: float | None = None, days: int = 14,
             from_date: date | None = None, include_optional: bool = False,
             beyond_target: bool = False) -> Plan:
        hours = hours if hours is not None else saved_hours(self.engine)
        days = max(1, min(MAX_DAYS, int(days)))
        budget = max(15, int(round(hours * 60)))
        end_day = self.today + timedelta(days=days)
        horizon_end = bounds(None, end_day + timedelta(days=30), self.tz)[1]
        found = self.items(course_id, from_date, horizon_end, include_optional)
        items, notes, progress = found.items, found.notes, found.progress
        beyond: list[PlanItem] = []
        if not beyond_target:
            items, beyond = self._trim_to_target(items, progress)
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
        if found.optional_left_out:
            notes.append(f"{found.optional_left_out} optional item(s) left out to focus on "
                         "mandatory work.")
        if beyond:
            notes.append(f"{len(beyond)} backlog item(s) ({fmt_minutes(sum(i.minutes for i in beyond))}) "
                         f"are beyond your {progress.target_percent:g}% catch-up target: do them "
                         "only if you have time left.")
        scheduled_mandatory = {}
        for _, slots in schedule:
            for sl in slots:
                if sl.item.mandatory and (sl.item.kind == "section" or sl.item.overdue):
                    key = id(sl.item)
                    scheduled_mandatory[key] = scheduled_mandatory.get(key, 0) + sl.minutes
        projected = progress.done_minutes + sum(scheduled_mandatory.values())
        projected_percent = (round(100 * min(projected, progress.total_minutes) / progress.total_minutes, 1)
                             if progress.total_minutes else 100.0)
        return Plan(
            today=self.today, hours_per_day=hours, days=schedule, unscheduled=unscheduled,
            total_minutes=sum(i.minutes for i in items), sections_left=found.sections_left,
            sections_done=found.sections_done, notes=notes, progress=progress,
            beyond_target=beyond, projected_percent=projected_percent,
            optional_left_out=found.optional_left_out, ignored=found.ignored,
        )


def fmt_minutes(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} h {m:02d}"
    return f"{h} h" if h else f"{m} min"
