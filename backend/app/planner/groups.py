"""How the study blocks of a schedule are shown: grouped by course, the same way everywhere
(web calendar, PDF export, ICS feed).

- Back-to-back reading and active recall blocks of one course are one **Study** entry
  ("09:00-10:00 Spanish - Study").
- Tests and tasks (quizzes, assignments) are always their own entry, named after the work
  ("10:00-10:30 Spanish - Test 1"); back-to-back parts of the same one stay together.
- Flashcard reviews (no course) are a **Flashcards** entry.

Blocks count as back to back when the gap between them is at most ``GAP`` minutes.
"""

from __future__ import annotations

GAP = 15 * 60  # seconds
PALETTE = ("#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626", "#65a30d")
NO_COURSE = "#64748b"


def course_color(course_id: int | None) -> str:
    """The course's colour, the same as the web UI's ``courseColor`` (src/format.ts)."""
    return NO_COURSE if course_id is None else PALETTE[abs(int(course_id)) % len(PALETTE)]


def _kind(b: dict) -> str:
    if b.get("kind") == "flashcards":
        return "flashcards"
    return "task" if b.get("kind") == "practice" else "study"


def _key(b: dict) -> tuple:
    kind = _kind(b)
    task = (b.get("item_kind"), b.get("deadline_id"), b.get("title")) if kind == "task" else None
    return (b.get("date"), b.get("course_id"), kind, task)


def _title(b: dict, kind: str) -> str:
    if kind == "study":
        return "Study"
    if kind == "flashcards":
        return "Flashcards"
    return b.get("title") or b.get("label") or "Task"


def sections_text(numbers: list) -> str:
    """Section numbers as a short text: "§2", "§2, 5", "§2–4" (consecutive runs joined)."""
    nums = sorted({int(n) for n in numbers if isinstance(n, int) or str(n).isdigit()})
    runs: list[list[int]] = []
    for n in nums:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    parts = [str(a) if a == b else f"{a}, {b}" if b == a + 1 else f"{a}–{b}" for a, b in runs]
    return f"§{', '.join(parts)}" if parts else ""


def short_label(g: dict) -> str:
    """What the web calendar's week and month views show: the course's short name and the
    section numbers ("LA · §2, 3"), or the task's name ("LA · Quiz 1"). The details stay in
    the entry's dialog."""
    if g["kind"] == "flashcards":
        return "Flashcards"
    course = g.get("course_short") or g.get("course_name") or ""
    what = g["title"]
    if g["kind"] == "study":
        what = sections_text([b.get("section_number") for b in g["blocks"]]) or "Study"
    return f"{course} · {what}" if course else what


def group(blocks: list[dict]) -> list[dict]:
    """Blocks (``Block.to_dict``) as display entries, in time order: ``{date, start, end,
    minutes, course_id, course_name, course_short, kind (study | task | flashcards), title,
    label, short, color, late, blocks}``. ``label`` is "Course - Title" (just the title
    without a course); ``short`` is ``short_label``."""
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
        course = b.get("course_name") or b.get("course_short") or ""
        title = _title(b, kind)
        out.append({
            "_key": _key(b), "date": b.get("date"), "start": b["start"], "end": b["end"],
            "minutes": b.get("minutes", 0), "course_id": b.get("course_id"), "course_name": course,
            "course_short": b.get("course_short") or "",
            "kind": kind, "title": title, "label": f"{course} - {title}" if course else title,
            "color": course_color(b.get("course_id")), "late": bool(b.get("late")), "blocks": [b],
        })
    for g in out:
        del g["_key"]
        g["short"] = short_label(g)
    return out
