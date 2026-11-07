"""The published study schedule as a PDF, one A4 landscape page per week, laid out like a
printed timetable: your name and the week on top, a half-hour time grid with a column per day
(Monday to Friday, plus Saturday or Sunday when something is on), study sessions at their
times, deadlines and unavailabilities if asked, and the date it was printed.

Readable first:
- Study blocks are grouped by course like the web calendar (``app.planner.groups``): one box
  "09:00-10:00 - Spanish - Study" in the course's colour listing what to study, and each test
  or task its own box ("10:00-10:30 - Spanish - Test 1").
- The time grid covers only the hours that week uses, so boxes are as tall as possible.
- Text is never cut: it wraps, the font gets smaller when a box is short, and a box that still
  can't hold its text grows downwards.
- Courses are named by their full name (no short code next to it).

Built with ``app.pdf`` (no PDF library). Times are in the server's TIMEZONE, like the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.planner import groups
from app.pdf import BOLD, ITALIC, REGULAR, SERIF, Document, Page, fit, text_width, wrap

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
MAX_WEEKS = 8
MIN_SPAN = 180  # the grid shows at least 3 hours
SIZES = (8.0, 7.5, 7.0, 6.5, 6.0, 5.5)

W, H = 842.0, 595.0  # A4 landscape, points
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
    kind: str  # study, due, busy, allday
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


def _item(b: dict) -> str:
    title = b.get("title", "")
    if b.get("parts", 1) > 1:
        title += f" ({'review' if b.get('kind') == 'recall' else 'part'} {b['part']}/{b['parts']})"
    return title


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
    for g in plan.get("groups") or groups.group(blocks):
        day, s = local(g["start"])
        if not first <= day <= last:
            continue
        e = local(g["end"])[1] or 1440
        work: list[str] = []
        if g["kind"] != "task":  # a task's title is its work; a study box lists what to study
            for b in g["blocks"]:
                if (w := _item(b)) and w not in work:
                    work.append(w)
        entry = Entry(day, s, max(e, s + 5), "study", g["label"], [("", w) for w in work])
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
            course = dl.get("course_name") or dl.get("course_shortname") or ""
            out.append(Entry(day, s, s + 30, "due", name, [("", course)] if course else [], _hm(s)))
    for e in out:
        if e.kind in ("study", "busy"):
            e.time = f"{_hm(e.start)}-{_hm(e.end)}"
    out.sort(key=lambda e: (e.day, e.start))
    return out


def _paragraphs(e: Entry) -> list[tuple[str, str]]:
    """(text, font) paragraphs of a box: the time and title in bold, then the work."""
    if e.kind == "busy":
        return [(e.time, BOLD), (e.title, ITALIC)]
    paras = [(f"{e.time} - {e.title}", BOLD)]
    many = len(e.items) > 1
    return paras + [(("- " if many else "") + w, REGULAR) for _, w in e.items if w]


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
        timed = [e for e in mine if e.kind not in ("allday", "due")]
        if timed:
            lo, hi = min(e.start for e in timed), max(e.end for e in timed)
        else:
            lo = _minutes(config.get("day_start", "08:00"))
            hi = _minutes(config.get("day_end", "22:00"))
        lo, hi = max(0, lo // 30 * 30), min(1440, -(-hi // 30) * 30)
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
    return doc.render()


__all__ = ["render", "entries", "long_date", "text_width"]
