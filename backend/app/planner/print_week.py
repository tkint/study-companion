"""The published study schedule as a PDF, one A4 landscape page per week, laid out like a
printed timetable: your name and the week on top, a half-hour time grid with a column per day
(Monday to Friday, plus Saturday or Sunday when something is on), the study blocks at their
times, deadlines and unavailabilities if asked, and the date it was printed.

Built with ``app.pdf`` (no PDF library). Times are in the server's TIMEZONE, like the plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.pdf import BOLD, ITALIC, REGULAR, SERIF, Document, fit, text_width

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
MAX_WEEKS = 8

W, H = 842.0, 595.0  # A4 landscape, points
MARGIN = 28.0
HOURS_COL = 38.0
HEAD_ROW = 20.0

INK = (0, 0, 0)
GRID = (0.78, 0.78, 0.78)
HOURS_BG = (0.95, 0.95, 0.95)
KIND_FILL = {"deep": (0.31, 0.65, 0.84), "practice": (0.31, 0.65, 0.84),
             "recall": (0.81, 0.87, 0.91), "flashcards": (0.81, 0.87, 0.91)}
BUSY_FILL = (0.92, 0.92, 0.92)


@dataclass
class Entry:
    day: date
    start: int  # minutes since local midnight
    end: int
    kind: str  # deep, practice, recall, flashcards, due, busy, allday
    title: str
    sub: str = ""
    time: str = ""


def long_date(d: date, weekday: bool = True) -> str:
    out = f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    return f"{WEEKDAYS[d.weekday()]} {out}" if weekday else out


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _minutes(hhmm: str) -> int:
    return 1440 if hhmm == "24:00" else int(hhmm[:2]) * 60 + int(hhmm[3:5])


def entries(plan: dict, deadlines: list[dict], first: date, last: date, tz,
            with_deadlines: bool = True, with_busy: bool = True) -> list[Entry]:
    """What goes on the pages between ``first`` and ``last`` (inclusive)."""
    out: list[Entry] = []

    def local(ts: int) -> tuple[date, int]:
        dt = datetime.fromtimestamp(ts, tz)
        return dt.date(), dt.hour * 60 + dt.minute

    for d in plan.get("days", []):
        for b in d.get("blocks", []):
            day, s = local(b["start"])
            if not first <= day <= last:
                continue
            _, e = local(b["end"])
            e = e or 1440
            title = b.get("title", "")
            if b.get("parts", 1) > 1:
                title += f" ({'review' if b['kind'] == 'recall' else 'part'} {b['part']}/{b['parts']})"
            course = b.get("course_short") or b.get("course_name") or ""
            out.append(Entry(day, s, max(e, s + 5), b.get("kind", "deep"), title,
                             " · ".join(x for x in (course, b.get("label", "")) if x),
                             f"{_hm(s)}-{_hm(e)}"))
    if with_busy:
        for u in plan.get("busy", []):
            day = date.fromisoformat(u["date"])
            if not first <= day <= last:
                continue
            if u.get("all_day"):
                out.append(Entry(day, 0, 1440, "allday", u.get("reason") or "Unavailable"))
                continue
            _, s = local(u["start"])
            _, e = local(u["end"])
            out.append(Entry(day, s, e or 1440, "busy", u.get("reason") or "Unavailable",
                             time=f"{_hm(s)}-{_hm(e or 1440)}"))
    if with_deadlines:
        for dl in deadlines:
            if not dl.get("due_at"):
                continue
            day, s = local(dl["due_at"])
            if not first <= day <= last:
                continue
            name = ("Done: " if dl.get("done") else "Due: ") + dl.get("name", "")
            out.append(Entry(day, s, s + 20, "due", name, dl.get("course_shortname") or "", _hm(s)))
    out.sort(key=lambda e: (e.day, e.start))
    return out


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
        timed = [e for e in mine if e.kind not in ("due", "allday")]
        lo = min([_minutes(config.get("day_start", "08:00"))] + [e.start for e in timed])
        hi = max([_minutes(config.get("day_end", "22:00"))] + [e.end for e in timed])
        lo, hi = max(0, lo // 30 * 30), min(1440, -(-hi // 30) * 30)
        span = max(60, hi - lo)

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

        # frame, hours column, half-hour lines
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
            for e in (e for e in mine if e.day == d):
                if e.kind == "allday":
                    page.rect(x, grid_top, col_w, bottom - grid_top, fill=BUSY_FILL)
                    page.text(x + 4, grid_top + 11, fit(e.title, col_w - 8, 8, ITALIC), 8, ITALIC,
                              (0.3, 0.3, 0.3))
                    continue
                if e.kind == "due":
                    s = min(max(e.start, lo), hi - 20)
                    bx, bw = x + col_w * 0.5, col_w * 0.5 - 3
                    bt, bh = y(s), max(9.0, 20 * scale)
                    page.rect(bx, bt, bw, bh, fill=(1, 1, 1), stroke=INK, line=0.8, dash=True)
                    page.text(bx + 2, bt + 7.5, fit(f"{e.time} {e.title}", bw - 4, 6.8, BOLD), 6.8, BOLD)
                    continue
                bx, bw = x + 3, col_w - 6
                bt = y(e.start)
                bh = max(4.0, y(e.end) - bt - 1)
                busy = e.kind == "busy"
                page.rect(bx, bt, bw, bh, fill=BUSY_FILL if busy else KIND_FILL.get(e.kind, KIND_FILL["deep"]),
                          stroke=(0.55, 0.55, 0.55) if busy else (0.2, 0.2, 0.2), line=0.6)
                small = bh < 16
                size = 6.8 if small else 8
                if bh >= 7:
                    base = bt + (bh / 2 + size / 2.8 if small else size + 1.5)
                    tw = page.text(bx + 2, base, e.time, size, BOLD) if e.time else 0
                    title_font = ITALIC if busy else REGULAR
                    page.text(bx + 2 + tw + 3, base, fit(e.title, bw - tw - 7, size, title_font), size,
                              title_font)
                    if not small and e.sub and bh >= 2 * size + 6:
                        page.text(bx + 2, base + size + 1.5, fit(e.sub, bw - 4, 7, REGULAR), 7)

        for i in range(len(days) + 1):  # column borders on top of the blocks' edges
            x = MARGIN + HOURS_COL + i * col_w
            page.line(x, top, x, bottom, INK, 0.6)
        page.rect(MARGIN, top, W - 2 * MARGIN, bottom - top, stroke=INK, line=0.8)
        page.line(MARGIN, grid_top, W - MARGIN, grid_top, INK, 0.6)
        page.line(MARGIN + HOURS_COL, top, MARGIN + HOURS_COL, bottom, INK, 0.6)
        page.text(MARGIN, H - MARGIN + 2, f"Printed on {long_date(printed, weekday=False)}", 9, SERIF)
    return doc.render()


__all__ = ["render", "entries", "long_date", "text_width"]
