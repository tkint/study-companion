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

import re

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


# An academic year in front of a course name ("2026/2027-A3FPH12 ...", "2026-27 - ...").
_YEAR = re.compile(r"^\s*(?:19|20)\d\d\s*[/-]\s*(?:19|20)?\d\d\s*[-–:]?\s*(?=\S)")


def course_title(name: str) -> str:
    """The course name as shown: without the academic year in front
    ("2026/2027-A3FPH12 Phonologie" -> "A3FPH12 Phonologie")."""
    return _YEAR.sub("", name or "", count=1).strip() or (name or "").strip()


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
    """Blocks (``Block.to_dict``) as display entries, in time order: ``{date, start, end,
    minutes, course_id, course_name, kind (study | task | flashcards), title, label, work,
    color, late, blocks}``. ``course_name`` is ``course_title``; ``label`` is "Course - Title"
    (just the title without a course); ``work`` is ``work_lines`` (empty for a task)."""
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
        course = course_title(b.get("course_name") or b.get("course_short") or "")
        title = _title(b, kind)
        out.append({
            "_key": _key(b), "date": b.get("date"), "start": b["start"], "end": b["end"],
            "minutes": b.get("minutes", 0), "course_id": b.get("course_id"), "course_name": course,
            "kind": kind, "title": title, "label": f"{course} - {title}" if course else title,
            "color": course_color(b.get("course_id")), "late": bool(b.get("late")), "blocks": [b],
        })
    for g in out:
        del g["_key"]
        # A task's title is its work; a study entry lists what to study.
        g["work"] = [] if g["kind"] == "task" else work_lines(g["blocks"])
    return out
