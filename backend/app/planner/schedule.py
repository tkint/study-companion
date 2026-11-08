"""Timed study schedule (rule-based, no AI): the catch-up plan's work laid out as focus
blocks with start and end times, around your unavailabilities, exportable as ``.ics``.

Pipeline:

0. **Start.** The plan starts today, or on ``start_date`` when that is later (a new
   term, back from holidays); the ``days`` of the horizon count from there.
1. **Capacity.** Each day has a study window (``day_start``-``day_end``). Weekly
   unavailabilities (classes, work, training) and dated ones (appointments, travel) are cut
   out of it. What you can study that day is your hours per day, but never more than the
   free time minus ``rest_hours`` (leisure you keep) and never more than ``max_daily_hours``.
2. **Work.** The same items as the catch-up plan (``Planner.items``: sections left, open
   deadlines, trimmed to your catch-up goal). Each item must be done ``buffer_days`` before
   the date it is needed by, which leaves a contingency margin before hard deadlines.
3. **Picking the next block.** Earliest deadline first whenever the work due by a deadline
   would no longer fit in the capacity left before it (when it can't fit at all, only its
   assignments and quizzes go first: its reading shares the turns with a double weight, so
   one late course doesn't take every block); otherwise courses take turns in
   proportion to their weight (a weight of 2 gets twice the time of a weight of 1; 0 leaves
   the course out), with a bonus for courses with a deadline in the next week, and never
   one course for longer than about two focus blocks when another one has work (each course's
   time stays in one piece, then the next course has its turn). Urgent work may
   stretch a day up to ``max_daily_hours``.
4. **Activities.** Reading sections are *deep work* blocks of at most ``session_minutes``
   with ``break_minutes`` between blocks. Assignments and quizzes are *practice* blocks. A
   finished section gets two short *active recall* blocks one and four days later (spaced
   repetition); if you have flashcards, each day starts with a short *flashcards* block.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import select

from app import study
from app.config import Settings
from app.db import session
from app.materials import enrolled_courses
from app.models import ScheduleSettings, StudyQuestion
from app.planner import DEADLINE_MINUTES, MAX_SECTION_MINUTES, Planner, PlanItem, fmt_minutes

USER = 1
DAY = 86400
MAX_DAYS = 60
MAX_WEEKLY = 50
MAX_DATES = 100
MAX_DAILY = 10
IGNORED = {"feed_unavailable"}  # old setting: unavailabilities are never in the feed now
MAX_REASON = 80
MAX_WEIGHT = 3.0
MIN_BLOCK = 15  # never schedule a block shorter than this (except the end of an item)
RECALL_MINUTES = 15
RECALL_OFFSETS = (1, 4)  # days after a section is finished
FLASHCARD_MINUTES = 15
URGENT_LOAD = 0.85  # work due by D over capacity until D that makes it urgent
SOON = 7 * DAY  # a course with a deadline this close gets a bonus
BEHIND_BONUS = 2.0  # weight bonus of a course whose needed reading can't fit before its deadline
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_TIME = re.compile(r"^(?:([01]\d|2[0-3]):([0-5]\d)|24:00)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULTS: dict = {
    "start_date": "",  # "" = today; a later date starts the plan then
    "days": 14,
    "max_daily_hours": 6.0,
    "rest_hours": 2.0,
    "day_start": "08:00",
    "day_end": "22:00",
    "session_minutes": 50,
    "break_minutes": 0,
    "buffer_days": 1,
    "recall": True,
    "include_optional": False,
    "beyond_target": False,
    "auto_update": True,  # re-plan every night with your progress and new deadlines
    "course_weights": {},
    "daily": [],  # every day, e.g. 12:00-14:00 "Meal"
    "days_off": [],  # weekdays (0 Monday .. 6 Sunday) with no study at all
    "weekly": [],
    "dates": [],
}

KIND_LABEL = {"deep": "Deep work", "practice": "Practice", "recall": "Active recall",
              "flashcards": "Flashcards"}


class ScheduleError(ValueError):
    """Bad settings: the message is shown in the UI."""


# ---------------------------------------------------------------------- settings


def _minutes(hhmm: str) -> int:
    if hhmm == "24:00":
        return 1440
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _num(data: dict, key: str, lo: float, hi: float, integer: bool = False) -> float | int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
        raise ScheduleError(f"{key} must be a number")
    if not lo <= value <= hi:
        raise ScheduleError(f"{key} must be between {lo:g} and {hi:g}")
    if integer:
        if int(value) != value:
            raise ScheduleError(f"{key} must be a whole number")
        return int(value)
    return round(float(value), 2)


def _time(value, key: str) -> str:
    if not isinstance(value, str) or not _TIME.match(value):
        raise ScheduleError(f'{key} must look like "08:00"')
    return value


def _slot(raw, key: str, repeat: str) -> dict:
    """One unavailability; ``repeat`` is daily (no day), weekly (``day``) or date (``date``)."""
    if not isinstance(raw, dict):
        raise ScheduleError(f"{key}: each entry is an object")
    out: dict = {}
    if repeat == "date":
        d = raw.get("date")
        try:
            if not isinstance(d, str) or not _DATE.match(d):
                raise ValueError
            date.fromisoformat(d)
        except ValueError:
            raise ScheduleError(f'{key}: date must look like "2026-11-10"') from None
        out["date"] = d
    elif repeat == "weekly":
        day = raw.get("day")
        if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
            raise ScheduleError(f"{key}: day is 0 (Monday) to 6 (Sunday)")
        out["day"] = day
    out["start"] = _time(raw.get("start", "00:00"), f"{key} start")
    out["end"] = _time(raw.get("end", "24:00"), f"{key} end")
    if _minutes(out["end"]) <= _minutes(out["start"]):
        raise ScheduleError(f"{key}: the end must be after the start")
    reason = raw.get("reason", "")
    if not isinstance(reason, str):
        raise ScheduleError(f"{key}: reason must be text")
    out["reason"] = " ".join(reason.split())[:MAX_REASON]
    return out


def unavailable(config: dict, d: date) -> list[dict]:
    """Your unavailabilities on day ``d``: ``{start, end, reason, repeat}`` with repeat
    off (a day off), daily, weekly or date."""
    if d.weekday() in config.get("days_off", []):
        return [{"start": "00:00", "end": "24:00", "reason": "Day off", "repeat": "off"}]
    rules = [dict(r, repeat="daily") for r in config.get("daily", [])]
    rules += [dict(r, repeat="weekly") for r in config.get("weekly", []) if r["day"] == d.weekday()]
    rules += [dict(r, repeat="date") for r in config.get("dates", []) if r["date"] == d.isoformat()]
    return rules


def validate(data: dict, current: dict) -> dict:
    """Merge ``data`` (any subset of the keys) into ``current``; raises ScheduleError."""
    out = {**current}
    data = {k: v for k, v in data.items() if k not in IGNORED}
    unknown = set(data) - set(DEFAULTS) - {"daily_hours"}
    if unknown:
        raise ScheduleError(f"unknown setting: {sorted(unknown)[0]}")
    for key, lo, hi, integer in (("days", 1, MAX_DAYS, True), ("max_daily_hours", 1, 8, False),
                                 ("rest_hours", 0, 12, False), ("session_minutes", 15, 120, True),
                                 ("break_minutes", 0, 30, True), ("buffer_days", 0, 7, True)):
        if key in data:
            out[key] = _num(data, key, lo, hi, integer)
    for key in ("day_start", "day_end"):
        if key in data:
            out[key] = _time(data[key], key)
    if "start_date" in data:
        raw = data["start_date"]
        if raw is None or raw == "":
            out["start_date"] = ""
        else:
            try:
                if not isinstance(raw, str) or not _DATE.match(raw):
                    raise ValueError
                date.fromisoformat(raw)
            except ValueError:
                raise ScheduleError('start_date must look like "2026-11-10" (or be empty for '
                                    "today)") from None
            out["start_date"] = raw
    if _minutes(out["day_end"]) - _minutes(out["day_start"]) < 60:
        raise ScheduleError("the study window (day_start to day_end) must be at least 1 hour")
    for key in ("recall", "include_optional", "beyond_target", "auto_update"):
        if key in data:
            if not isinstance(data[key], bool):
                raise ScheduleError(f"{key} must be true or false")
            out[key] = data[key]
    if "course_weights" in data:
        raw = data["course_weights"]
        if not isinstance(raw, dict) or len(raw) > 200:
            raise ScheduleError('course_weights: {"<course id>": weight}')
        weights = {}
        for k, v in raw.items():
            if not str(k).isdigit():
                raise ScheduleError("course_weights: keys are course ids")
            weights[str(int(k))] = _num({"weight": v}, "weight", 0, MAX_WEIGHT)
        out["course_weights"] = weights
    for key, limit, repeat in (("daily", MAX_DAILY, "daily"), ("weekly", MAX_WEEKLY, "weekly"),
                               ("dates", MAX_DATES, "date")):
        if key in data:
            raw = data[key]
            if not isinstance(raw, list) or len(raw) > limit:
                raise ScheduleError(f"{key}: a list of up to {limit} entries")
            out[key] = [_slot(r, key, repeat) for r in raw]
    if "days_off" in data:
        raw = data["days_off"]
        if not isinstance(raw, list) or any(
                isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in raw):
            raise ScheduleError("days_off: a list of weekdays, 0 (Monday) to 6 (Sunday)")
        out["days_off"] = sorted(set(raw))
    if "daily_hours" in data:
        hours = _num(data, "daily_hours", 0.25, 8)
        if hours > out["max_daily_hours"]:
            raise ScheduleError("hours per day can't be more than the daily maximum")
    return out


def load(engine: Engine) -> dict:
    """Saved settings (defaults for anything missing or no longer valid), plus
    ``daily_hours`` from the catch-up plan's hours per day."""
    with session(engine) as s:
        row = s.get(ScheduleSettings, USER)
    config = dict(DEFAULTS)
    if row is not None:
        try:
            saved = json.loads(row.config or "{}")
        except ValueError:
            saved = {}
        if isinstance(saved, dict):
            for key in DEFAULTS:
                if key in saved:
                    try:
                        config = validate({key: saved[key]}, config)
                    except ScheduleError:
                        pass
    config["daily_hours"] = min(study.hours_per_day(engine), config["max_daily_hours"])
    return config


def save(engine: Engine, data: dict, now: float | None = None) -> dict:
    if not isinstance(data, dict):
        raise ScheduleError("send a JSON object")
    current = load(engine)
    if "daily_hours" not in data and "max_daily_hours" in data:
        # Lowering the cap below your hours per day lowers those too.
        data = {**data, "daily_hours": min(current["daily_hours"], float(data["max_daily_hours"]))
                if isinstance(data["max_daily_hours"], (int, float))
                and not isinstance(data["max_daily_hours"], bool) else current["daily_hours"]}
    merged = validate(data, current)
    if "daily_hours" in data:
        study.set_hours_per_day(engine, float(data["daily_hours"]), now=now)
    stored = {k: merged[k] for k in DEFAULTS}
    with session(engine) as s:
        row = s.get(ScheduleSettings, USER) or ScheduleSettings(user_id=USER)
        row.config = json.dumps(stored, separators=(",", ":"))
        row.updated_at = int(now if now is not None else time.time())
        s.add(row)
        s.commit()
    return load(engine)


def draft(engine: Engine, data: dict) -> dict:
    """Saved settings with ``data`` applied, without saving (the form's preview)."""
    if not isinstance(data, dict):
        raise ScheduleError("send a JSON object")
    current = load(engine)
    merged = validate(data, current)
    hours = data.get("daily_hours", current["daily_hours"])
    merged["daily_hours"] = min(float(hours), merged["max_daily_hours"])
    return merged


# ---------------------------------------------------------------------- schedule


@dataclass
class Work:
    item: PlanItem
    remaining: int
    deadline: int | None  # needed_by minus the buffer (never before now)
    blocks: list[Block] = field(default_factory=list)

    @property
    def course(self) -> int:
        return self.item.course_id or 0

    @property
    def kind(self) -> str:
        return "deep" if self.item.kind == "section" else "practice"


@dataclass
class Recall:
    item: PlanItem
    release: int  # day index from which it can be scheduled
    step: int  # 1 or 2


@dataclass
class Block:
    day: date
    start: int
    end: int
    kind: str  # deep, practice, recall, flashcards
    item: PlanItem | None
    part: int = 1
    parts: int = 1
    late: bool = False
    detail: str = ""

    @property
    def minutes(self) -> int:
        return (self.end - self.start) // 60

    @property
    def title(self) -> str:
        if self.item is None:
            return "Flashcard review"
        return self.item.title

    def summary(self) -> str:
        label = KIND_LABEL[self.kind]
        if self.item is None:
            return f"[Study] {self.title}"
        if self.kind == "practice":
            label = "Assignment" if self.item.kind == "assign" else "Quiz prep" \
                if self.item.kind == "quiz" else "Practice"
        part = f", part {self.part}/{self.parts}" if self.parts > 1 else ""
        course = self.item.course_short or self.item.course_name
        return f"[Study] {course + ': ' if course else ''}{self.title} ({label}{part})"

    def to_dict(self) -> dict:
        it = self.item
        return {
            "date": self.day.isoformat(), "start": self.start, "end": self.end,
            "minutes": self.minutes, "kind": self.kind, "label": KIND_LABEL[self.kind],
            "title": self.title, "summary": self.summary(), "detail": self.detail,
            "part": self.part, "parts": self.parts, "late": self.late,
            "item_kind": it.kind if it else None,
            "course_id": it.course_id if it else None,
            "course_name": it.course_name if it else "",
            "course_short": it.course_short if it else "",
            "section_id": it.section_id if it else None,
            "section_number": it.section_number if it else None,
            "deadline_id": it.deadline_id if it else None,
            "needed_by": it.needed_by if it else None,
            "needed_for": it.needed_for if it else "",
            "url": it.url if it else "",
            "files": [{"id": i, "name": n, "pages": p} for i, n, p in it.files] if it else [],
        }


@dataclass
class Day:
    day: date
    free_minutes: int
    capacity: int
    blocked: list[dict]
    blocks: list[Block] = field(default_factory=list)
    stretched: bool = False

    @property
    def minutes(self) -> int:
        return sum(b.minutes for b in self.blocks)

    def to_dict(self) -> dict:
        return {"date": self.day.isoformat(), "weekday": WEEKDAYS[self.day.weekday()],
                "minutes": self.minutes, "capacity": self.capacity,
                "free_minutes": self.free_minutes, "stretched": self.stretched,
                "blocked": self.blocked, "blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class Schedule:
    today: date
    start: date  # the first planned day: today, or the later start date
    generated_at: int
    config: dict
    days: list[Day]
    unscheduled: list[PlanItem]
    courses: list[dict]
    notes: list[str]
    cards_due: int = 0
    timezone: str = ""

    @property
    def blocks(self) -> list[Block]:
        return [b for d in self.days for b in d.blocks]

    def to_dict(self) -> dict:
        blocks = self.blocks
        by_kind: dict[str, int] = {}
        for b in blocks:
            by_kind[b.kind] = by_kind.get(b.kind, 0) + b.minutes
        return {
            "today": self.today.isoformat(), "start": self.start.isoformat(),
            "generated_at": self.generated_at,
            "timezone": self.timezone,
            "config": self.config, "weekdays": list(WEEKDAYS),
            "total_minutes": sum(b.minutes for b in blocks),
            "minutes_by_kind": by_kind,
            "late": sum(1 for b in blocks if b.late),
            "stretched_days": sum(1 for d in self.days if d.stretched),
            "cards_due": self.cards_due,
            "days": [d.to_dict() for d in self.days],
            "unscheduled": [i.to_dict() for i in self.unscheduled],
            "unscheduled_minutes": sum(i.minutes for i in self.unscheduled),
            "courses": self.courses, "notes": self.notes,
        }


def _subtract(free: list[tuple[int, int]], cut: tuple[int, int]) -> list[tuple[int, int]]:
    a, b = cut
    out = []
    for s, e in free:
        if b <= s or a >= e:
            out.append((s, e))
            continue
        if a > s:
            out.append((s, a))
        if b < e:
            out.append((b, e))
    return out


def start_day(config: dict, today: date) -> date:
    """The first planned day: ``start_date`` when it is after ``today``, else today."""
    raw = config.get("start_date") or ""
    try:
        start = date.fromisoformat(raw) if raw else today
    except ValueError:
        start = today
    return max(start, today)


class Generator:
    def __init__(self, settings: Settings, engine: Engine, now: float | None = None,
                 config: dict | None = None) -> None:
        self.settings = settings
        self.engine = engine
        self.tz = settings.tz
        self.now = int(now if now is not None else time.time())
        self.today = datetime.fromtimestamp(self.now, self.tz).date()
        self.config = config if config is not None else load(engine)
        self.start = start_day(self.config, self.today)

    # -- time helpers

    def _ts(self, d: date, minute: int) -> int:
        d = d + timedelta(days=minute // 1440)
        minute %= 1440
        return int(datetime(d.year, d.month, d.day, minute // 60, minute % 60,
                            tzinfo=self.tz).timestamp())

    def _free(self, d: date, first: bool) -> tuple[list[tuple[int, int]], list[dict]]:
        """Free intervals (minutes of the day) inside the study window, and what blocks it."""
        cfg = self.config
        start, end = _minutes(cfg["day_start"]), _minutes(cfg["day_end"])
        if first:
            local = datetime.fromtimestamp(self.now, self.tz)
            start = max(start, int(math.ceil((local.hour * 60 + local.minute + 1) / 5.0)) * 5)
        free = [(start, end)] if end > start else []
        blocked = []
        for r in unavailable(cfg, d):
            free = _subtract(free, (_minutes(r["start"]), _minutes(r["end"])))
            blocked.append({"start": r["start"], "end": r["end"], "reason": r["reason"],
                            "repeat": r["repeat"]})
        blocked.sort(key=lambda r: r["start"])
        return [(s, e) for s, e in free if e - s >= MIN_BLOCK], blocked

    # -- main

    def generate(self) -> Schedule:
        cfg = self.config
        notes: list[str] = []
        horizon = int(cfg["days"])
        planner = Planner(self.settings, self.engine, now=self.now)
        end_day = self.start + timedelta(days=horizon)
        later = self.start > self.today
        if later:
            notes.append(f"The plan starts on {self.start:%A %d %B}.")
        horizon_end = self._ts(end_day + timedelta(days=30), 0)
        found = planner.items(None, None, horizon_end, cfg["include_optional"])
        items = found.items
        if not cfg["beyond_target"]:
            items, _ = Planner._trim_to_target(items, found.progress)
        notes += found.notes

        courses = enrolled_courses(self.engine)
        weights = {c.id: float(cfg["course_weights"].get(str(c.id), 1.0)) for c in courses}
        weights[0] = 1.0  # site events without a course
        left_out = sorted({it.course_name for it in items
                           if it.course_id is not None and weights.get(it.course_id, 1.0) == 0})
        if left_out:
            notes.append(f"Left out (weight 0): {', '.join(left_out)}.")
        works = [self._work(it) for it in items
                 if it.course_id is None or weights.get(it.course_id, 1.0) > 0]
        weights = {k: v for k, v in weights.items() if v > 0}

        with session(self.engine) as s:
            qs = s.exec(select(StudyQuestion).where(StudyQuestion.user_id == USER)).all()
        cards_due = sum(1 for q in qs if study.is_due(q, self.now))
        has_cards = bool(qs)

        days: list[Day] = []
        free_by_day: list[list[tuple[int, int]]] = []
        stretch_caps: list[int] = []
        rest = int(round(cfg["rest_hours"] * 60))
        target = int(round(cfg["daily_hours"] * 60))
        cap = int(round(cfg["max_daily_hours"] * 60))
        for i in range(horizon):
            d = self.start + timedelta(days=i)
            first = d == self.today
            free, blocked = self._free(d, first)
            total = sum(e - s for s, e in free)
            room = max(0, total - rest)
            if first:  # today: what's left of the day, within today's share of rest
                full = sum(e - s for s, e in self._free(d, False)[0])
                room = max(0, total - max(0, rest - (full - total)))
            days.append(Day(d, total, min(target, cap, room), blocked))
            free_by_day.append(free)
            stretch_caps.append(min(cap, room))

        served: dict[int, int] = {}
        recalls: list[Recall] = []
        for i, day in enumerate(days):
            free = free_by_day[i]
            cursor = [0, free[0][0] if free else 0]  # interval index, minute
            used = 0
            last_course: int | None = None
            last_kind = ""
            run = 0  # minutes of the current run of one course

            def place(length: int, budget: int, allow_short: bool) -> tuple[int, int] | None:
                nonlocal used
                length = min(length, budget - used)
                if length <= 0 or (length < MIN_BLOCK and not allow_short):
                    return None
                while cursor[0] < len(free):
                    s, e = free[cursor[0]]
                    start = max(cursor[1], s)
                    take = min(length, e - start)
                    if take >= length or take >= MIN_BLOCK:
                        cursor[1] = start + take + cfg["break_minutes"]
                        used += take
                        return start, take
                    cursor[0] += 1
                    if cursor[0] < len(free):
                        cursor[1] = free[cursor[0]][0]
                return None

            if has_cards and day.capacity >= 2 * MIN_BLOCK:
                spot = place(FLASHCARD_MINUTES, day.capacity, True)
                if spot:
                    due = (f"{cards_due} card{'s' if cards_due != 1 else ''} due. "
                           if day.day == self.today else "")
                    day.blocks.append(Block(day.day, self._ts(day.day, spot[0]),
                                            self._ts(day.day, spot[0] + spot[1]), "flashcards", None,
                                            detail=f"{due}Review the flashcards due today in the "
                                                   "Study tab (spaced repetition)."))
            def recall(r: Recall) -> bool:
                spot = place(RECALL_MINUTES, day.capacity, True) \
                    if used + RECALL_MINUTES <= day.capacity else None
                if not spot:
                    return False
                recalls.remove(r)
                day.blocks.append(Block(
                    day.day, self._ts(day.day, spot[0]), self._ts(day.day, spot[0] + spot[1]),
                    "recall", r.item, part=r.step, parts=len(RECALL_OFFSETS),
                    detail=self._recall_detail(r)))
                return True

            while True:
                pending = [r for r in recalls if r.release <= i]
                work, urgent = self._pick(works, weights, served, last_course, run, i, days, used)
                # Active recall joins its course's study time: just before that course's next
                # block, or on its own when the course has no work left (or the day ends).
                course_of = lambda r: r.item.course_id or 0  # noqa: E731
                left = {w.course for w in works}
                due_now = [r for r in pending if work is not None and course_of(r) == work.course]
                if work is None or (work.course != last_course):
                    due_now += [r for r in pending if course_of(r) not in left and r not in due_now]
                if work is None:
                    due_now = pending
                if due_now:
                    placed = False
                    for r in due_now:
                        if recall(r):
                            placed = True
                            c = course_of(r)
                            run = run + RECALL_MINUTES if c == last_course else RECALL_MINUTES
                            last_course, last_kind = c, "recall"
                    if placed:
                        continue
                if work is None:
                    break
                budget = stretch_caps[i] if urgent else day.capacity
                length = min(cfg["session_minutes"], work.remaining)
                if 0 < work.remaining - length < MIN_BLOCK:  # no tiny tail for later
                    length = work.remaining
                spot = place(length, max(budget, used), length == work.remaining)
                if spot is None:
                    break
                if used > day.capacity:
                    day.stretched = True
                start, take = spot
                block = Block(day.day, self._ts(day.day, start), self._ts(day.day, start + take),
                              work.kind, work.item)
                work.blocks.append(block)
                work.remaining -= take
                served[work.course] = served.get(work.course, 0) + take
                day.blocks.append(block)
                run = run + take if work.course == last_course else take
                last_course, last_kind = work.course, work.kind
                if work.remaining <= 0:
                    works.remove(work)
                    if work.kind == "deep" and cfg["recall"]:
                        recalls += [Recall(work.item, i + off, n)
                                    for n, off in enumerate(RECALL_OFFSETS, start=1)]

        self._finish(days, works, notes)
        unscheduled = [PlanItem(**{**w.item.__dict__, "minutes": w.remaining}) for w in works]

        while days and not days[-1].blocks:
            days.pop()
        planned: dict[int, int] = {}
        for d in days:
            for b in d.blocks:
                if b.item is not None and b.item.course_id is not None:
                    planned[b.item.course_id] = planned.get(b.item.course_id, 0) + b.minutes
        total_weight = sum(float(cfg["course_weights"].get(str(c.id), 1.0)) for c in courses) or 1
        total_planned = sum(planned.values()) or 1
        course_rows = []
        for c in courses:
            w = float(cfg["course_weights"].get(str(c.id), 1.0))
            course_rows.append({
                "id": c.id, "shortname": c.shortname, "fullname": c.fullname, "weight": w,
                "target_share": round(100 * w / total_weight, 1),
                "planned_minutes": planned.get(c.id, 0),
                "planned_share": round(100 * planned.get(c.id, 0) / total_planned, 1)
                if planned else 0.0,
            })
        if any(d.stretched for d in days):
            notes.append("Some days go past your hours per day (up to your daily maximum) "
                         "to keep a deadline.")
        if any(b.late for d in days for b in d.blocks):
            notes.append("Some work only fits after the date it is needed by: add hours per day, "
                         "free up time or lower the weight of other courses.")
        if unscheduled:
            span = f"the {horizon} days from {self.start:%d %B}" if later else f"the next {horizon} days"
            notes.append(f"{fmt_minutes(sum(i.minutes for i in unscheduled))} of work doesn't fit "
                         f"in {span}.")
        if not any(d.capacity for d in days):
            notes.append("No free study time: check your study window, unavailabilities and "
                         "rest hours.")
        return Schedule(self.today, self.start, self.now, cfg, days, unscheduled, course_rows, notes,
                        cards_due, self.settings.timezone)

    def _work(self, item: PlanItem) -> Work:
        deadline = None
        if item.needed_by is not None:
            buffered = item.needed_by - int(self.config["buffer_days"]) * DAY
            deadline = max(self.now, buffered if buffered > self.now else item.needed_by)
        return Work(item, item.minutes, deadline)

    def _capacity_until(self, days: list[Day], i: int, used: int, until: int) -> int:
        """Study minutes left from now (day ``i``, ``used`` so far) until timestamp ``until``."""
        total = max(0, days[i].capacity - used)
        for d in days[i + 1:]:
            if self._ts(d.day, 0) >= until:
                return total
            total += d.capacity
        # Past the horizon: assume the average capacity of the days we know.
        after = self._ts(days[-1].day + timedelta(days=1), 0)
        if until > after:
            total += int((until - after) / DAY * sum(d.capacity for d in days) / len(days))
        return total

    def _pick(self, works: list[Work], weights: dict[int, float], served: dict[int, int],
              last_course: int | None, run: int, i: int, days: list[Day],
              used: int) -> tuple[Work | None, bool]:
        if not works:
            return None, False
        dated = sorted((w for w in works if w.deadline is not None), key=lambda w: w.deadline)
        demand = 0
        behind: set[int] = set()  # courses whose sections can't all fit before their deadline
        for w in dated:  # earliest deadline first when the load before a deadline is high
            demand += w.remaining
            room = self._capacity_until(days, i, used, w.deadline)
            if demand >= URGENT_LOAD * room:
                due = [x for x in dated if x.deadline <= w.deadline]
                order = lambda x: (x.deadline, x.item.key())  # noqa: E731
                if demand <= room:  # it still fits: nothing else until it's done
                    return min(due, key=order), True
                # It can't all fit anyway: hand-ins still come first, but the reading they
                # need no longer takes every block (that would make every other course late
                # too); its course gets a bigger share of the turns instead.
                tasks = [x for x in due if x.kind == "practice"]
                if tasks:
                    return min(tasks, key=order), True
                behind = {x.course for x in due}
                break
        heads: dict[int, Work] = {}
        for w in works:  # works keep the plan's order within a course
            heads.setdefault(w.course, w)
        # Keep going with the same course (its study time stays in one piece) up to about two
        # focus blocks, then let the course with the least time for its weight have a turn.
        if last_course in heads and run < self._run_limit():
            return heads[last_course], False
        candidates = list(heads)
        if len(candidates) > 1 and last_course in candidates:
            candidates.remove(last_course)
        now_day = self._ts(days[i].day, 0)

        def score(c: int) -> tuple:
            w = weights.get(c, 1.0)
            head = heads[c]
            if c in behind:
                w *= BEHIND_BONUS
            elif head.deadline is not None and head.deadline - now_day <= SOON:
                w *= 1.5
            return (served.get(c, 0) / w, head.item.key())

        return heads[min(candidates, key=score)], False

    def _run_limit(self) -> int:
        return max(60, 2 * int(self.config["session_minutes"]))

    def _recall_detail(self, r: Recall) -> str:
        when = "the day after" if r.step == 1 else "a few days after"
        return (f"Spaced repetition, {when} you studied it: answer this section's flashcards, "
                "or ask your AI assistant for a short quiz on it, then fix what you missed.")

    def _finish(self, days: list[Day], left: list[Work], notes: list[str]) -> None:
        """Part numbers, late flags and descriptions once every block is placed."""
        by_item: dict[int, list[Block]] = {}
        for d in days:
            for b in d.blocks:
                if b.item is not None and b.kind in ("deep", "practice"):
                    by_item.setdefault(id(b.item), []).append(b)
        unfinished = {id(w.item) for w in left}
        for key, blocks in by_item.items():
            n = len(blocks) + (1 if key in unfinished else 0)
            item = blocks[0].item
            for part, b in enumerate(blocks, start=1):
                b.part, b.parts = part, n
                b.late = bool(part == n and item.needed_by is not None
                              and item.needed_by >= self.now and b.end > item.needed_by)
                b.detail = self._detail(b)

    def _detail(self, b: Block) -> str:
        it = b.item
        assert it is not None
        lines = []
        if it.kind == "section":
            lines.append(f"Read and review section {it.section_number}: {it.title}"
                         + (f" ({it.pages} pages in total)" if it.pages else "") + ".")
            lines.append("Then try to recall the key points without the material.")
            if it.minutes >= MAX_SECTION_MINUTES:
                lines.append(f"Long reading: the time planned is capped at "
                             f"{fmt_minutes(MAX_SECTION_MINUTES)}, so skim it and focus on what "
                             "the course asks for.")
            if it.questions:
                lines.append(f"{it.questions} flashcards saved for this section.")
        elif it.kind == "assign":
            lines.append(f"Work on the assignment “{it.title}”"
                         + (f" ({it.grade:g} points)." if it.grade else "."))
        elif it.kind == "quiz":
            lines.append(f"Prepare and take the quiz “{it.title}”: review the related sections "
                         "first, then practice questions.")
        else:
            lines.append(f"{it.title}.")
        if it.needed_by:
            what = "Due" if it.kind != "section" else f"Needed for “{it.needed_for}” by"
            lines.append(f"{what} {datetime.fromtimestamp(it.needed_by, self.tz):%a %d %b %H:%M}.")
        if it.minutes > DEADLINE_MINUTES.get(it.kind, it.minutes) or b.parts > 1:
            lines.append(f"Estimated {fmt_minutes(it.minutes)} in total.")
        return "\n".join(lines)
