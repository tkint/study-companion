"""How the study blocks of a schedule are shown: as course-level **study sessions**, the
same way everywhere (web calendar, PDF, Excel, ICS feed).

A session is time given to one course: back-to-back blocks of the same course (reading,
active recall, quizzes, assignments) are one session ("09:00-10:30 A3FPH12 Phonologie de
l'Anglais 3"). What to do in it is the session's *tasks* (``app.planner.tasks``), never part
of the session itself. Flashcard reviews (no course) are a **Flashcards** session.

Blocks count as back to back when the gap between them is at most ``GAP`` minutes.
"""

from __future__ import annotations

import re

GAP = 15 * 60  # seconds
PALETTE = ("#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626", "#65a30d")
NO_COURSE = "#64748b"


def course_color(course_id: int | None) -> str:
    """The course's colour, the same as the web UI's ``courseColor`` (src/format.ts)."""
    return NO_COURSE if course_id is None else PALETTE[abs(int(course_id)) % len(PALETTE)]


def _kind(b: dict) -> str:
    return "flashcards" if b.get("kind") == "flashcards" else "study"


def _key(b: dict) -> tuple:
    return (b.get("date"), b.get("course_id"), _kind(b))


# An academic year in front of a course name ("2026/2027-A3FPH12 ...", "2026-27 - ...").
_YEAR = re.compile(r"^\s*(?:19|20)\d\d\s*[/-]\s*(?:19|20)?\d\d\s*[-–:]?\s*(?=\S)")


def course_title(name: str) -> str:
    """The course name as shown: without the academic year in front
    ("2026/2027-A3FPH12 Phonologie" -> "A3FPH12 Phonologie")."""
    return _YEAR.sub("", name or "", count=1).strip() or (name or "").strip()


def course_code(short: str, full: str = "") -> str:
    """The course's identifier ("A3FPH12"): its short name without the academic year, or
    the first word of the full name when that looks like a code."""
    code = course_title(short or "")
    if code:
        return code
    first = course_title(full or "").split(" ", 1)[0]
    return first if re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{2,}", first) and any(
        ch.isdigit() for ch in first) else ""


def course_name(short: str, full: str) -> str:
    """The course's name without its identifier in front ("Phonologie de l'Anglais 3")."""
    name = course_title(full or short or "")
    code = course_code(short, full)
    if code and name.startswith(code) and name != code:
        name = name[len(code):].lstrip(" -–:_").strip() or name
    return name


def course_label(short: str, full: str) -> str:
    """Identifier and name, as a session's title: "A3FPH12 – Phonologie de l'Anglais 3"."""
    code, name = course_code(short, full), course_name(short, full)
    if code and name and name != code:
        return f"{code} – {name}"
    return name or code


def _runs(nums: list[int]) -> str:
    out: list[str] = []
    for n in sorted(set(nums)):
        if out and out[-1][1] == n - 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def work_lines(blocks: list[dict]) -> list[str]:
    """What a study entry covers, one line per piece of work in order, its parts merged:
    "Workbook parts 1-3/4", "Matrices review 1/2", "Vectors"."""
    order: list[tuple[str, str, int]] = []
    parts: dict[tuple[str, str, int], list[int]] = {}
    for b in blocks:
        title = (b.get("title") or "").strip()
        if not title:
            continue
        n = int(b.get("parts") or 1)
        word = "review" if b.get("kind") == "recall" else "part"
        key = (title, word, n) if n > 1 else (title, "", 1)
        if key not in parts:
            order.append(key)
            parts[key] = []
        parts[key].append(int(b.get("part") or 1))
    out = []
    for key in order:
        title, word, n = key
        if n <= 1:
            out.append(title)
            continue
        nums = parts[key]
        plural = "s" if len(set(nums)) > 1 else ""
        out.append(f"{title} {word}{plural} {_runs(nums)}/{n}")
    return out


def group(blocks: list[dict]) -> list[dict]:
    """Blocks (``Block.to_dict``) as course-level sessions, in time order: ``{id, date,
    start, end, minutes, course_id, course_code, course_name, kind (study | flashcards),
    title, label, work, color, late, blocks}``. ``label`` is ``course_label`` ("Flashcards"
    without a course), ``title`` the same; ``work`` is ``work_lines`` (what the session
    covers, for the session's dialog: the calendar itself never lists it)."""
    out: list[dict] = []
    for b in sorted(blocks, key=lambda b: b["start"]):
        kind = _kind(b)
        prev = out[-1] if out else None
        if prev and prev["_key"] == _key(b) and b["start"] - prev["end"] <= GAP:
            prev["end"] = max(prev["end"], b["end"])
            prev["minutes"] += b.get("minutes", 0)
            prev["late"] = prev["late"] or bool(b.get("late"))
            prev["blocks"].append(b)
            continue
        short, full = b.get("course_short") or "", b.get("course_name") or ""
        label = "Flashcards" if kind == "flashcards" else (
            course_label(short, full) or "Study")
        out.append({
            "_key": _key(b), "id": f"s{b['start']}", "date": b.get("date"), "start": b["start"],
            "end": b["end"], "minutes": b.get("minutes", 0), "course_id": b.get("course_id"),
            "course_code": course_code(short, full) if kind != "flashcards" else "",
            "course_name": course_name(short, full) if kind != "flashcards" else "",
            "kind": kind, "title": label, "label": label,
            "color": course_color(b.get("course_id")), "late": bool(b.get("late")), "blocks": [b],
        })
    for g in out:
        del g["_key"]
        g["work"] = work_lines(g["blocks"])
    return out
