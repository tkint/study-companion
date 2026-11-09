"""The published study plan as an Excel workbook (.xlsx), the same structure as the PDF:

1. **Calendar** sheets, one per week ("Calendar", or "Calendar 9 Nov" when there are
   several): your name and the week on top, a column per day and a row per quarter hour
   over the hours that week uses; each course session (``app.planner.groups``) a merged cell
   at its times in the course's colour with its course and times (never its tasks); a row
   under the day names for deadlines and days off, and breaks in grey, if asked. Rows grow
   so text is never cut; it prints landscape on one page.
2. **Daily task lists**, one sheet per planning day with tasks ("Mon 9 Nov – Tasks",
   ``app.planner.tasks``, the same as the web page): the date, tasks grouped by course (a
   coloured row with the session times), a Done cell per task (a ☐ / ☑ drop-down, printable
   as a box), priority, deadline, effort and a notes column, then ruled rows for notes. It
   prints portrait on one page.

Each sheet has its own print area, margins, orientation and scaling. Written with
``app.xlsx`` (no dependency). Times are in the server's TIMEZONE, like the plan.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil

from app.planner import groups, tasks
from app.planner.print_week import (MAX_WEEKS, MIN_SPAN, WEEKDAYS, Entry, _day_rows, _hm,
                                    _minutes, entries, long_date)
from app.xlsx import Rich, Style, Workbook

SLOT = 15  # minutes per row
SLOT_HEIGHT = 15.0  # points
DAY_WIDTH = 26  # characters
LINE = 13.0  # points per line of 10 pt text

FIRST_ROW = 5  # header rows: name, week, blank, day names
DAY_ROW = 4
GREY = "#555555"
BUSY_FILL = "#e5e7eb"
HEAD_FILL = "#f3f4f6"

TITLE = Style(bold=True, size=14)
SUBTITLE = Style(size=11)
HEAD = Style(bold=True, size=11, fill=HEAD_FILL, border=True, halign="center", valign="center")
TIME = Style(size=9, color=GREY, fill=HEAD_FILL, border=True)
EMPTY = Style(border=True)
OFF = Style(fill=BUSY_FILL, border=True)
BUSY = Style(italic=True, color="#374151", fill=BUSY_FILL, border=True, wrap=True)
TOP = Style(size=9, wrap=True, border=True)
TOP_OFF = Style(size=9, wrap=True, border=True, fill=BUSY_FILL)


def _lines(text: str, width: int = DAY_WIDTH) -> int:
    """About how many lines ``text`` takes in a column ``width`` characters wide."""
    per = max(1, int(width * 1.1))  # 10 pt Calibri fits a little more than the width
    return sum(max(1, ceil(len(line) / per)) for line in text.split("\n"))


def _text(e: Entry) -> Rich:
    """A cell's rich text: the title in bold, then what to study, one per line (no times:
    the rows show them)."""
    if e.kind == "busy":
        return [(e.title, False)]
    work = "".join("\n" + w for _, w in e.items if w)
    return [(e.title, True), (work, False)]


def _plain(value) -> str:
    return "".join(t for t, _ in value) if isinstance(value, list) else value


def render(plan: dict, deadlines: list[dict], first: date, weeks: int, tz, owner: str = "",
           with_deadlines: bool = True, with_busy: bool = True) -> bytes:
    monday = first - timedelta(days=first.weekday())
    weeks = max(1, min(MAX_WEEKS, int(weeks)))
    last = monday + timedelta(days=7 * weeks - 1)
    items = entries(plan, deadlines, monday, last, tz, with_deadlines, with_busy)
    config = plan.get("config", {})
    book = Workbook(title=f"Study plan, week of {long_date(monday, weekday=False)}")

    for w in range(weeks):
        start = monday + timedelta(days=7 * w)
        days = [start + timedelta(days=i) for i in range(7)]
        mine = [e for e in items if start <= e.day <= days[-1]]
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
        slots = (hi - lo) // SLOT

        ws = book.sheet("Calendar" if weeks == 1 else f"Calendar {start.day} {start:%b}")
        ws.landscape = True
        ws.fit_tall = 1
        ws.set(1, 1, owner or "Study plan", TITLE)
        ws.set(2, 1, f"Week of {long_date(start)} to {long_date(days[-1])}", SUBTITLE)
        ws.width(1, 11)
        ws.set(DAY_ROW, 1, "", HEAD)
        for i, d in enumerate(days):
            ws.width(i + 2, DAY_WIDTH)
            ws.set(DAY_ROW, i + 2, f"{WEEKDAYS[d.weekday()]} {d.day} {d:%b}", HEAD)
        ws.height(DAY_ROW, 20)

        # Deadlines and days off: a row of their own under the day names.
        top = [e for e in mine if e.kind in ("due", "allday", "reading")]
        row = FIRST_ROW
        if top:
            ws.set(row, 1, "All day", TIME)
            need = 1
            for i, d in enumerate(days):
                day_top = [e for e in top if e.day == d]
                off = any(e.kind == "allday" for e in day_top)
                lines = [e.title if e.kind == "allday" else
                         f"{e.title} ({e.items[0][1]})" if e.kind == "reading" and e.items else
                         f"{e.time} {e.title}" + "".join(f" ({c})" for _, c in e.items if c)
                         for e in day_top]
                text = "\n".join(lines)
                ws.set(row, i + 2, text, TOP_OFF if off else TOP)
                need = max(need, _lines(text))
            ws.height(row, max(SLOT_HEIGHT, need * 12.0 + 3))
            row += 1
        grid = row  # first time row

        heights = [SLOT_HEIGHT] * slots
        for r in range(slots):
            m = lo + r * SLOT
            ws.set(grid + r, 1, _hm(m) if m % 30 == 0 else "", TIME)
        for i, d in enumerate(days):
            col = i + 2
            off = any(e.kind == "allday" and e.day == d for e in mine)
            taken: dict[int, int] = {}  # slot -> first slot of the cell covering it
            for r in range(slots):
                ws.set(grid + r, col, "", OFF if off else EMPTY)
            for e in (e for e in mine if e.day == d and e.kind in ("study", "busy")):
                a = max(0, (e.start - lo) // SLOT)
                b = min(slots, max(a + 1, ceil((e.end - lo) / SLOT)))
                free = [r for r in range(a, b) if r not in taken]
                if not free:  # overlaps a cell already there: add its text to that cell
                    head = taken[a]
                    old = ws.get(grid + head, col)
                    runs = old if isinstance(old, list) else [(old, False)]
                    ws.set(grid + head, col, runs + [("\n", False)] + _text(e),
                           ws.cells[(grid + head, col)][1])
                    continue
                a = free[0]
                b = next((r for r in range(a, b) if r in taken), b)
                if e.kind == "busy":
                    style = BUSY
                else:  # the course's colour, as on the web calendar and the PDF
                    style = Style(color="#ffffff", fill=e.color or groups.NO_COURSE,
                                  border=True, wrap=True)
                for r in range(a, b):
                    taken[r] = a
                    ws.set(grid + r, col, "", style)
                ws.set(grid + a, col, _text(e), style)
                ws.merge(grid + a, col, grid + b - 1, col)
                # Never cut: share out the height the text needs over the cell's rows.
                need = _lines(_plain(_text(e))) * LINE + 4
                each = need / (b - a)
                for r in range(a, b):
                    heights[r] = max(heights[r], round(each, 1))
        for r, h in enumerate(heights):
            if h != SLOT_HEIGHT:
                ws.height(grid + r, h)
        ws.freeze(grid, 2)
        ws.print_area = (1, 1, grid + slots - 1, 8)

    for day in tasks.days_between(plan, monday, last):
        day_sheet(book, day, plan.get("sessions") or [], tz, owner)
    return book.render()


UNTICKED, TICKED = "☐", "☑"
TASK_COLS = (("Done", 6), ("Task", 46), ("Priority", 10), ("Deadline", 22), ("Effort", 10),
             ("Notes", 26))
LIST_HEAD = Style(bold=True, size=10, fill=HEAD_FILL, border=True, valign="center")
TICK = Style(size=14, border=True, halign="center", valign="center")
CELL = Style(border=True, wrap=True, valign="center")
CELL_DONE = Style(border=True, wrap=True, valign="center", color="#6b7280")
SMALL = Style(size=9, border=True, wrap=True, valign="center", color="#374151")
NOTE_LINE = Style(border=True)
NOTE_ROWS = 10


def day_sheet(book: Workbook, day: dict, sessions: list[dict], tz, owner: str = "") -> None:
    """One sheet with a day's tasks, printed portrait on one page."""
    d = date.fromisoformat(day["date"])
    ws = book.sheet(f"{d:%a} {d.day} {d:%b} – Tasks")
    ws.portrait = True
    ws.fit_tall = 1
    ws.margins = (0.5, 0.5, 0.6, 0.6)
    last_col = len(TASK_COLS)
    ws.set(1, 1, long_date(d), TITLE)
    ws.merge(1, 1, 1, 4)
    if owner:
        ws.set(1, 5, owner, Style(size=9, color=GREY, halign="right"))
        ws.merge(1, 5, 1, last_col)
    left = sum(1 for t in day.get("tasks", []) if not t.get("done"))
    sub = [f"{len(day.get('tasks', []))} tasks, {left} to do"]
    planned = tasks.effort({"minutes": day.get("minutes", 0)})
    if planned:
        sub.append(f"{planned} of study planned")
    ws.set(2, 1, " · ".join(sub), SUBTITLE)
    ws.merge(2, 1, 2, last_col)
    head = 4
    for c, (name, width) in enumerate(TASK_COLS, start=1):
        ws.width(c, width)
        ws.set(head, c, name, LIST_HEAD)
    ws.height(head, 18)
    row = head + 1
    first_task = None
    for r in _day_rows(day, sessions, tz):
        if r[0] == "course":
            _, label, times, color = r
            style = Style(bold=True, size=11, color="#ffffff", fill=color, border=True,
                          valign="center")
            ws.set(row, 1, f"{label}   {times}", style)
            for c in range(2, last_col + 1):
                ws.set(row, c, "", style)
            ws.merge(row, 1, row, last_col)
            ws.height(row, 20)
            row += 1
            continue
        _, t, _meta = r
        done = bool(t.get("done"))
        first_task = first_task or row
        title = t.get("title") or ""
        if t.get("part"):
            title += f" ({t['part']})"
        ws.set(row, 1, TICKED if done else UNTICKED, TICK)
        ws.set(row, 2, title, CELL_DONE if done else CELL)
        prio = t.get("priority")
        ws.set(row, 3, prio.capitalize() if prio in ("high", "medium") else "", SMALL)
        ws.set(row, 4, tasks.due_text(t, tz), SMALL)
        ws.set(row, 5, tasks.effort(t), SMALL)
        ws.set(row, 6, "", CELL)
        ws.height(row, max(22.0, _lines(title, 46) * LINE + 8))
        row += 1
    if first_task:
        ws.choices(first_task, 1, row - 1, 1, [UNTICKED, TICKED])
    row += 1
    ws.set(row, 1, "Notes", Style(bold=True, size=11))
    for n in range(1, NOTE_ROWS + 1):
        for c in range(1, last_col + 1):
            ws.set(row + n, c, "", NOTE_LINE)
        ws.merge(row + n, 1, row + n, last_col)
        ws.height(row + n, 22)
    ws.freeze(head + 1, 1)
    ws.print_area = (1, 1, row + NOTE_ROWS, last_col)


__all__ = ["render", "SLOT"]
