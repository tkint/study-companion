"""The published study schedule as a PDF, one A4 landscape page per week, laid out like a
printed timetable: your name and the week on top, a half-hour time grid with a column per day
(Monday to Friday, plus Saturday or Sunday when something is on), study sessions at their
times, deadlines and unavailabilities if asked, and the date it was printed.

Readable first:
- Back-to-back study blocks (the short breaks between them included) become one box per study
  session, listing each piece of work with its course.
- The time grid covers only the hours that week uses, so boxes are as tall as possible.
- Text is never cut: it wraps, the font gets smaller when a box is short, and a box that still
  can't hold its text grows downwards.
- Courses are named by their full name (no short code next to it).

Built with ``app.pdf`` (no PDF library). Times are in the server's TIMEZONE, like the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.pdf import BOLD, ITALIC, REGULAR, SERIF, Document, Page, fit, text_width, wrap

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
MAX_WEEKS = 8
GROUP_GAP = 20  # minutes: blocks this close together share a box (one study session)
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
STUDY_FILL = (0.31, 0.65, 0.84)
REVIEW_FILL = (0.81, 0.87, 0.91)
BUSY_FILL = (0.92, 0.92, 0.92)


@dataclass
class Entry:
    day: date
    start: int  # minutes since local midnight
    end: int
    kind: str  # study, review, due, busy, allday
    title: str  # course name, deadline or reason
    items: list[tuple[str, str]] = field(default_factory=list)  # (course, work) in a study box
    time: str = ""


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
    label = b.get("label", "")
    return f"{title}, {label.lower()}" if label and b.get("kind") != "flashcards" else title


def entries(plan: dict, deadlines: list[dict], first: date, last: date, tz,
            with_deadlines: bool = True, with_busy: bool = True) -> list[Entry]:
    """What goes on the pages between ``first`` and ``last`` (inclusive)."""
    out: list[Entry] = []

    def local(ts: int) -> tuple[date, int]:
        dt = datetime.fromtimestamp(ts, tz)
        return dt.date(), dt.hour * 60 + dt.minute

    blocks = sorted((b for d in plan.get("days", []) for b in d.get("blocks", [])),
                    key=lambda b: b["start"])
    for b in blocks:
        day, s = local(b["start"])
        if not first <= day <= last:
            continue
        e = local(b["end"])[1] or 1440
        name = b.get("course_name") or b.get("course_short") or ""
        kind = "review" if b.get("kind") in ("recall", "flashcards") else "study"
        prev = out[-1] if out else None
        if prev and prev.day == day and s - prev.end <= GROUP_GAP:
            prev.end = max(prev.end, e)
            prev.items.append((name, _item(b)))
            if kind == "study":
                prev.kind = "study"
            continue
        out.append(Entry(day, s, max(e, s + 5), kind, "", [(name, _item(b))]))
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
        if e.kind in ("study", "review", "busy"):
            e.time = f"{_hm(e.start)}-{_hm(e.end)}"
    out.sort(key=lambda e: (e.day, e.start))
    return out


def _paragraphs(e: Entry) -> list[tuple[str, str]]:
    """(text, font) paragraphs of a box: the time and title in bold, then the work."""
    if e.kind == "busy":
        return [(e.time, BOLD), (e.title, ITALIC)]
    courses = {c for c, _ in e.items}
    if e.kind == "due":
        return [(f"{e.time} {e.title}", BOLD)] + [(w, REGULAR) for _, w in e.items if w]
    if len(courses) == 1:  # one course: its name once, in the heading
        paras = [(f"{e.time} {next(iter(courses))}".strip(), BOLD)]
        paras += [(("- " if len(e.items) > 1 else "") + w, REGULAR) for _, w in e.items]
        return paras
    return [(e.time, BOLD)] + [(f"{c}: {w}" if c else w, REGULAR) for c, w in e.items]


def _layout(paras: list[tuple[str, str]], width: float, height: float) -> tuple[float, list]:
    """The biggest font size whose wrapped text fits ``height`` (else the smallest), with
    the lines as (text, font)."""
    for size in SIZES:
        lines = [(line, font) for text, font in paras for line in wrap(text, width, size, font)]
        if len(lines) * size * 1.18 + PAD * 2 <= height or size == SIZES[-1]:
            return size, lines
    raise AssertionError  # unreachable


def _box(page: Page, e: Entry, x: float, top: float, w: float, h: float, fill, stroke,
         dash: bool = False) -> None:
    size, lines = _layout(_paragraphs(e), w - 2 * PAD, h)
    needed = len(lines) * size * 1.18 + PAD * 2
    h = max(h, needed)  # never cut: a box too short for its text grows
    page.rect(x, top, w, h, fill=fill, stroke=stroke, line=0.8 if dash else 0.6, dash=dash)
    base = top + PAD + size * 0.9
    for text, font in lines:
        page.text(x + PAD, base, text, size, font)
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
            for e in (e for e in day_items if e.kind in ("study", "review", "busy")):
                bt = y(e.start)
                bh = max(6.0, y(e.end) - bt - 1)
                fill = {"study": STUDY_FILL, "review": REVIEW_FILL, "busy": BUSY_FILL}[e.kind]
                stroke = (0.55, 0.55, 0.55) if e.kind == "busy" else (0.2, 0.2, 0.2)
                _box(page, e, x + 3, bt, col_w - 6, bh, fill, stroke)
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
