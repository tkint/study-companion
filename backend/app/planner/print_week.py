"""The published study plan as a PDF: first the calendar, then one page of tasks per day.

1. **Calendar**: one A4 landscape page per week, laid out like a printed timetable: your name
   and the week on top, a half-hour time grid with a column per day (Monday to Friday, plus
   Saturday or Sunday when something is on), a box per course session in the course's colour
   (``app.planner.groups``: the course, its times; never its tasks), deadlines and
   unavailabilities if asked, and the date it was printed. The grid covers only the hours
   that week uses; text wraps and a box too short for it grows, nothing is cut.
2. **Daily task lists**: one A4 portrait page per planning day with tasks
   (``app.planner.tasks``, the same as the web page): the date, the tasks grouped by course
   with the session times, a checkbox each (ticked when done), priority, deadline and effort,
   and ruled lines for notes. The text gets smaller before a day takes a second page.

Built with ``app.pdf`` (no PDF library). Times are in the server's TIMEZONE, like the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.planner import groups, tasks
from app.pdf import BOLD, ITALIC, REGULAR, SERIF, Document, Page, fit, text_width, wrap

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
MAX_WEEKS = 8
MIN_SPAN = 180  # the grid shows at least 3 hours
SIZES = (8.0, 7.5, 7.0, 6.5, 6.0, 5.5)

W, H = 842.0, 595.0  # A4 landscape, points
PW, PH = 595.0, 842.0  # A4 portrait (daily task lists)
DAY_MARGIN = 42.0
DAY_SCALES = (1.0, 0.92, 0.84, 0.76, 0.7)  # shrink a day's list before it takes two pages
MUTED = (0.35, 0.35, 0.35)
RULE = (0.75, 0.75, 0.75)
MARGIN = 28.0
HOURS_COL = 38.0
HEAD_ROW = 20.0
PAD = 2.0

INK = (0, 0, 0)
GRID = (0.78, 0.78, 0.78)
HOURS_BG = (0.95, 0.95, 0.95)
WHITE = (1, 1, 1)
BUSY_FILL = (0.92, 0.92, 0.92)


@dataclass
class Entry:
    day: date
    start: int  # minutes since local midnight
    end: int
    kind: str  # study, due, busy, allday, reading
    title: str  # "Course - Study", deadline or reason
    items: list[tuple[str, str]] = field(default_factory=list)  # ("", work) lines under the title
    time: str = ""
    color: str = ""  # the course's colour (study boxes)


def long_date(d: date, weekday: bool = True) -> str:
    out = f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    return f"{WEEKDAYS[d.weekday()]} {out}" if weekday else out


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _minutes(hhmm: str) -> int:
    return 1440 if hhmm == "24:00" else int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def entries(plan: dict, deadlines: list[dict], first: date, last: date, tz,
            with_deadlines: bool = True, with_busy: bool = True) -> list[Entry]:
    """What goes on the pages between ``first`` and ``last`` (inclusive)."""
    out: list[Entry] = []

    def local(ts: int) -> tuple[date, int]:
        dt = datetime.fromtimestamp(ts, tz)
        return dt.date(), dt.hour * 60 + dt.minute

    blocks = [b for d in plan.get("days", []) for b in d.get("blocks", [])]
    for g in plan.get("sessions") or groups.group(blocks):
        day, s = local(g["start"])
        if not first <= day <= last:
            continue
        e = local(g["end"])[1] or 1440
        span = f"{_hm(s)}-{_hm(e)} · {tasks.effort({'minutes': g.get('minutes') or e - s})}"
        entry = Entry(day, s, max(e, s + 5), "study", g["label"], [("", span)])
        entry.color = g["color"]
        out.append(entry)
    if with_busy:
        for u in plan.get("busy", []):
            day = date.fromisoformat(u["date"])
            if not first <= day <= last:
                continue
            if u.get("all_day"):
                out.append(Entry(day, 0, 1440, "allday", u.get("reason") or "Unavailable"))
                continue
            s, e = local(u["start"])[1], local(u["end"])[1] or 1440
            out.append(Entry(day, s, e, "busy", u.get("reason") or "Unavailable"))
    if with_deadlines:
        for dl in deadlines:
            if not dl.get("due_at"):
                continue
            day, s = local(dl["due_at"])
            if not first <= day <= last:
                continue
            name = ("Done: " if dl.get("done") else "Due: ") + dl.get("name", "")
            course = groups.course_title(dl.get("course_name") or dl.get("course_shortname") or "")
            out.append(Entry(day, s, s + 30, "due", name, [("", course)] if course else [], _hm(s)))
    for e in out:
        if e.kind in ("study", "busy"):
            e.time = f"{_hm(e.start)}-{_hm(e.end)}"
    out.sort(key=lambda e: (e.day, e.start))
    return out


def reading_label(r: dict) -> str:
    """"Literature 3 - Read: Novel 1" (just "Read: Novel 1" without a course)."""
    course = groups.course_title(r.get("course_name") or "")
    return f"{course + ' - ' if course else ''}Read: {r.get('title', '')}"


def _paragraphs(e: Entry) -> list[tuple[str, str]]:
    """(text, font) paragraphs of a box: the title in bold, then the work, one per line.
    No times: the grid shows them. A deadline keeps its time (it is a moment, not a span)."""
    if e.kind == "busy":
        return [(e.title, ITALIC)]
    title = f"{e.time} {e.title}" if e.kind == "due" else e.title
    return [(title, BOLD)] + [(w, REGULAR) for _, w in e.items if w]


def _layout(paras: list[tuple[str, str]], width: float, height: float) -> tuple[float, list]:
    """The biggest font size whose wrapped text fits ``height`` (else the smallest), with
    the lines as (text, font)."""
    for size in SIZES:
        lines = [(line, font) for text, font in paras for line in wrap(text, width, size, font)]
        if len(lines) * size * 1.18 + PAD * 2 <= height or size == SIZES[-1]:
            return size, lines
    raise AssertionError  # unreachable


def _box(page: Page, e: Entry, x: float, top: float, w: float, h: float, fill, stroke,
         dash: bool = False, ink=INK) -> None:
    size, lines = _layout(_paragraphs(e), w - 2 * PAD, h)
    needed = len(lines) * size * 1.18 + PAD * 2
    h = max(h, needed)  # never cut: a box too short for its text grows
    page.rect(x, top, w, h, fill=fill, stroke=stroke, line=0.8 if dash else 0.6, dash=dash)
    base = top + PAD + size * 0.9
    for text, font in lines:
        page.text(x + PAD, base, text, size, font, ink)
        base += size * 1.18


def render(plan: dict, deadlines: list[dict], first: date, weeks: int, tz, owner: str = "",
           printed: date | None = None, with_deadlines: bool = True, with_busy: bool = True) -> bytes:
    monday = first - timedelta(days=first.weekday())
    weeks = max(1, min(MAX_WEEKS, int(weeks)))
    last = monday + timedelta(days=7 * weeks - 1)
    items = entries(plan, deadlines, monday, last, tz, with_deadlines, with_busy)
    config = plan.get("config", {})
    printed = printed or datetime.now(tz).date()
    doc = Document(W, H, title=f"Study plan, week of {long_date(monday, weekday=False)}")

    for w in range(weeks):
        start = monday + timedelta(days=7 * w)
        week_days = [start + timedelta(days=i) for i in range(7)]
        mine = [e for e in items if start <= e.day <= week_days[-1]]
        days = [d for i, d in enumerate(week_days) if i < 5 or any(e.day == d for e in mine)]
        # Only the hours this week uses (the study window when it has no blocks).
        # Deadlines don't stretch it (a 23:59 or 02:00 deadline sits at the grid's edge).
        timed = [e for e in mine if e.kind in ("study", "busy")]
        if timed:
            lo, hi = min(e.start for e in timed), max(e.end for e in timed)
        else:
            lo = _minutes(config.get("day_start", "08:00"))
            hi = _minutes(config.get("day_end", "22:00"))
        # One more half hour after the last end, so the grid shows the end time
        # (a block ending at 17:00 has a 17:00 row under it, not 16:30 as the last row).
        lo, hi = max(0, lo // 30 * 30), min(1440, -(-hi // 30) * 30 + 30)
        if hi - lo < MIN_SPAN:
            hi = min(1440, lo + MIN_SPAN)
            lo = max(0, hi - MIN_SPAN)
        span = hi - lo

        page = doc.page()
        page.text(MARGIN, MARGIN + 12, fit(owner or "Study plan", W - 2 * MARGIN, 14, BOLD), 14, BOLD)
        page.text(MARGIN, MARGIN + 28, f"Week of {long_date(start)} to {long_date(days[-1])}", 11.5)

        top = MARGIN + 38
        bottom = H - MARGIN - 18
        grid_top = top + HEAD_ROW
        col_w = (W - 2 * MARGIN - HOURS_COL) / len(days)
        scale = (bottom - grid_top) / span

        def y(m: int) -> float:
            return grid_top + (min(max(m, lo), hi) - lo) * scale

        page.rect(MARGIN, grid_top, HOURS_COL, bottom - grid_top, fill=HOURS_BG)
        for m in range(lo + 30, hi, 30):
            page.line(MARGIN + HOURS_COL, y(m), W - MARGIN, y(m), GRID, 0.3)
        for m in range(lo, hi, 30):
            page.text(MARGIN + 3, y(m) + 8, _hm(m), 7, REGULAR, (0.2, 0.2, 0.2))
        for i, d in enumerate(days):
            x = MARGIN + HOURS_COL + i * col_w
            page.centered(x + col_w / 2, top + 14, f"{WEEKDAYS[d.weekday()]} {d.day}", 11, BOLD)

        for i, d in enumerate(days):
            x = MARGIN + HOURS_COL + i * col_w
            day_items = [e for e in mine if e.day == d]
            for e in (e for e in day_items if e.kind == "allday"):
                page.rect(x, grid_top, col_w, bottom - grid_top, fill=BUSY_FILL)
                lines = wrap(e.title, col_w - 8, 8, ITALIC)
                for n, line in enumerate(lines):
                    page.text(x + 4, grid_top + 11 + n * 9.5, line, 8, ITALIC, (0.3, 0.3, 0.3))
            for e in (e for e in day_items if e.kind in ("study", "busy")):
                bt = y(e.start)
                bh = max(6.0, y(e.end) - bt - 1)
                if e.kind == "busy":
                    _box(page, e, x + 3, bt, col_w - 6, bh, BUSY_FILL, (0.55, 0.55, 0.55))
                else:  # the course's colour, as on the web calendar
                    fill = _rgb(e.color or groups.NO_COURSE)
                    _box(page, e, x + 3, bt, col_w - 6, bh, fill, fill, ink=WHITE)
            for e in (e for e in day_items if e.kind == "due"):  # on top, right half
                s = min(max(e.start, lo), hi - 30)
                _box(page, e, x + col_w * 0.45, y(s), col_w * 0.55 - 3, 30 * scale - 1,
                     (1, 1, 1), INK, dash=True)

        for i in range(len(days) + 1):
            x = MARGIN + HOURS_COL + i * col_w
            page.line(x, top, x, bottom, INK, 0.6)
        page.rect(MARGIN, top, W - 2 * MARGIN, bottom - top, stroke=INK, line=0.8)
        page.line(MARGIN, grid_top, W - MARGIN, grid_top, INK, 0.6)
        page.text(MARGIN, H - MARGIN + 2, f"Printed on {long_date(printed, weekday=False)}", 9, SERIF)

    for day in tasks.days_between(plan, monday, last):
        day_pages(doc, day, plan.get("sessions") or [], tz, owner)
    return doc.render()


def _day_rows(day: dict, sessions: list[dict], tz) -> list[tuple]:
    """A day's list as rows: ("course", label, times, colour) then ("task", task, meta)."""
    by_key = {t["key"]: t for t in day.get("tasks", [])}
    rows: list[tuple] = []
    for c in day.get("courses", []):
        own = [s for s in sessions if s["date"] == day["date"] and (
            s["kind"] == "flashcards" if c["course_label"] == "Flashcards" and c["course_id"] is None
            else s.get("course_id") == c["course_id"] and s["kind"] != "flashcards")]
        times = ", ".join(f"{datetime.fromtimestamp(s['start'], tz):%H:%M}-"
                          f"{datetime.fromtimestamp(s['end'], tz):%H:%M}" for s in own)
        rows.append(("course", c["course_label"] or "Other", times or "no time slot",
                     c.get("color") or groups.NO_COURSE))
        for k in c.get("keys", []):
            if k in by_key:
                rows.append(("task", by_key[k], " · ".join(tasks.meta(by_key[k], tz))))
    return rows


def _row_height(row: tuple, width: float, k: float) -> float:
    if row[0] == "course":
        return 26 * k
    _, t, meta = row
    lines = len(wrap(t.get("title") or "", width - 22 * k, 11 * k, REGULAR))
    return lines * 13.5 * k + (12 * k if meta else 0) + 9 * k


def day_pages(doc: Document, day: dict, sessions: list[dict], tz, owner: str = "") -> None:
    """One portrait page with a day's tasks (more only when even the smallest text can't
    hold them): the date, tasks grouped by course, checkboxes, notes lines."""
    d = date.fromisoformat(day["date"])
    rows = _day_rows(day, sessions, tz)
    width = PW - 2 * DAY_MARGIN
    head = 74.0
    room = PH - DAY_MARGIN - head - DAY_MARGIN - 4 * 22  # keep room for 4 note lines
    for k in DAY_SCALES:
        if sum(_row_height(r, width, k) for r in rows) <= room:
            break
    pages: list[list[tuple]] = [[]]
    used = 0.0
    for r in rows:
        h = _row_height(r, width, k)
        if pages[-1] and used + h > PH - 2 * DAY_MARGIN - head - 22:
            pages.append([("course", *rows_course(pages[-1], rows, r))] if r[0] == "task" else [])
            used = sum(_row_height(x, width, k) for x in pages[-1])
        pages[-1].append(r)
        used += h
    planned = tasks.effort({"minutes": day.get("minutes", 0)})
    left = sum(1 for t in day.get("tasks", []) if not t.get("done"))
    for n, chunk in enumerate(pages):
        page = doc.page(PW, PH)
        x0 = DAY_MARGIN
        title = f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"
        if n:
            title += " (continued)"
        page.text(x0, DAY_MARGIN + 16, fit(title, width * 0.7, 18, BOLD), 18, BOLD)
        if owner:
            ow = fit(owner, width * 0.3, 9, REGULAR)
            page.text(PW - DAY_MARGIN - text_width(ow, 9), DAY_MARGIN + 14, ow, 9, REGULAR, MUTED)
        sub = [f"{len(day.get('tasks', []))} tasks, {left} to do"]
        if planned:
            sub.append(f"{planned} of study planned")
        page.text(x0, DAY_MARGIN + 36, " · ".join(sub), 10.5, REGULAR, MUTED)
        page.line(x0, DAY_MARGIN + 48, PW - DAY_MARGIN, DAY_MARGIN + 48, INK, 0.8)
        top = DAY_MARGIN + head
        for r in chunk:
            h = _row_height(r, width, k)
            if r[0] == "course":
                _, label, times, color = r
                page.rect(x0, top + 6 * k, 4, 14 * k, fill=_rgb(color))
                tw = text_width(times, 9.5 * k, REGULAR)
                page.text(x0 + 10, top + 17 * k, fit(label, width - tw - 24, 12.5 * k, BOLD),
                          12.5 * k, BOLD)
                page.text(PW - DAY_MARGIN - tw, top + 17 * k, times, 9.5 * k, REGULAR, MUTED)
                page.line(x0, top + h - 1, PW - DAY_MARGIN, top + h - 1, RULE, 0.4)
            else:
                _, t, meta = r
                box = 10 * k
                bx, by = x0 + 6, top + 4 * k
                page.rect(bx, by, box, box, stroke=INK, line=0.8)
                if t.get("done"):
                    page.line(bx + 2 * k, by + 5 * k, bx + 4.5 * k, by + 8 * k, INK, 1.2)
                    page.line(bx + 4.5 * k, by + 8 * k, bx + 8.5 * k, by + 1.5 * k, INK, 1.2)
                tx = x0 + 6 + 16 * k
                base = top + 12.5 * k
                for line in wrap(t.get("title") or "", width - 22 * k, 11 * k, REGULAR):
                    page.text(tx, base, line, 11 * k, REGULAR, MUTED if t.get("done") else INK)
                    base += 13.5 * k
                if meta:
                    page.text(tx, base - 1.5 * k, fit(meta, width - 22 * k, 8.5 * k, REGULAR),
                              8.5 * k, REGULAR, MUTED)
            top += h
        if n == len(pages) - 1:  # notes: ruled lines to the bottom of the page
            top += 14
            page.text(x0, top + 10, "Notes", 10.5, BOLD)
            line_y = top + 32
            while line_y <= PH - DAY_MARGIN:
                page.line(x0, line_y, PW - DAY_MARGIN, line_y, RULE, 0.4)
                line_y += 22
        page.text(x0, PH - DAY_MARGIN + 22, title.replace(" (continued)", ""), 8, SERIF, MUTED)


def rows_course(chunk: list[tuple], rows: list[tuple], row: tuple) -> tuple:
    """The course header to repeat at the top of a new page, for the task ``row``."""
    i = rows.index(row)
    for r in reversed(rows[:i]):
        if r[0] == "course":
            return r[1:]
    return ("", "", groups.NO_COURSE)


__all__ = ["render", "entries", "long_date", "text_width"]
