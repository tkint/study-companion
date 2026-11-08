"""The published study schedule as an Excel workbook (.xlsx), one sheet per week named by
that week's Monday (``2026-11-09``), laid out like the calendar:

- your name and the week on top, then a column per day (Monday to Sunday) and a row per
  quarter hour, covering only the hours that week uses (like the printed weeks);
- study sessions grouped by course (``app.planner.groups``) in merged cells at their times,
  in the course's colour: "09:00-10:00 - Spanish - Study" and what to study under it;
  each test or task its own cell;
- a row under the day names for deadlines and days off, and breaks in grey at their times,
  if asked;
- rows grow so text is never cut, the day names and times stay put when scrolling, and each
  sheet prints on one landscape page wide.

The same entries as the PDF (``print_week.entries``); written with ``app.xlsx`` (no
dependency). Times are in the server's TIMEZONE, like the plan.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil

from app.planner import groups
from app.planner.print_week import MAX_WEEKS, MIN_SPAN, WEEKDAYS, Entry, _hm, _minutes, entries, long_date
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
    """A cell's rich text: the time and title in bold, then what to study."""
    if e.kind == "busy":
        return [(f"{e.time}\n{e.title}", False)]
    many = len(e.items) > 1
    work = "".join("\n" + ("- " if many else "") + w for _, w in e.items if w)
    return [(f"{e.time} - {e.title}", True), (work, False)]


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
        lo, hi = max(0, lo // 30 * 30), min(1440, -(-hi // 30) * 30)
        if hi - lo < MIN_SPAN:
            hi = min(1440, lo + MIN_SPAN)
            lo = max(0, hi - MIN_SPAN)
        slots = (hi - lo) // SLOT

        ws = book.sheet(start.isoformat())
        ws.landscape = True
        ws.set(1, 1, owner or "Study plan", TITLE)
        ws.set(2, 1, f"Week of {long_date(start)} to {long_date(days[-1])}", SUBTITLE)
        ws.width(1, 11)
        ws.set(DAY_ROW, 1, "", HEAD)
        for i, d in enumerate(days):
            ws.width(i + 2, DAY_WIDTH)
            ws.set(DAY_ROW, i + 2, f"{WEEKDAYS[d.weekday()]} {d.day} {d:%b}", HEAD)
        ws.height(DAY_ROW, 20)

        # Deadlines and days off: a row of their own under the day names.
        top = [e for e in mine if e.kind in ("due", "allday")]
        row = FIRST_ROW
        if top:
            ws.set(row, 1, "Due / off", TIME)
            need = 1
            for i, d in enumerate(days):
                day_top = [e for e in top if e.day == d]
                off = any(e.kind == "allday" for e in day_top)
                lines = [e.title if e.kind == "allday" else
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
    return book.render()


__all__ = ["render", "SLOT"]
