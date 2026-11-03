"""Study loop: Claude's notes and questions, quiz results and spaced repetition.

Shared by the MCP write tools (``app.mcp_tools``) and the web UI's JSON API
(``app.api.study``). Everything is per user (single user id 1 for now). Input from Claude
is validated here and errors raise :class:`StudyError` with a message Claude can act on.

Spaced repetition is a small SM-2 variant. Grades: 0 again, 1 hard, 2 good, 3 easy.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from app.db import session
from app.models import (
    Course,
    QuizResult,
    Section,
    SectionMark,
    StudyNote,
    StudyPrefs,
    StudyQuestion,
)

USER = 1
DAY = 86400
MAX_MARKDOWN = 30_000
MAX_TITLE = 200
MAX_ITEMS = 50
MAX_QUESTION = 1_000
MAX_ANSWER = 4_000
MAX_CHOICE = 300
MAX_SOURCE = 200
MAX_TOPIC = 200
MAX_NOTES = 2_000
KINDS = ("short", "mcq", "flashcard")
GRADES = {0: "again", 1: "hard", 2: "good", 3: "easy"}
AGAIN_DELAY = 10 * 60  # a failed card comes back in the same session
MIN_EASE, MAX_INTERVAL = 1.3, 365.0


class StudyError(ValueError):
    """Bad input: the message is shown to Claude or in the UI."""


def _now(now: float | None) -> int:
    return int(now if now is not None else time.time())


def _text(value: object, name: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise StudyError(f"{name} must be text")
    value = value.replace("\r\n", "\n").strip()
    if required and not value:
        raise StudyError(f"{name} is empty")
    if len(value) > limit:
        raise StudyError(f"{name} is too long ({len(value)} characters, at most {limit})")
    return value


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _section(s, section_id: object) -> Section:
    try:
        sid = int(section_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise StudyError("section_id must be a number") from None
    row = s.get(Section, sid)
    if row is None:
        raise StudyError(f"no section with id {section_id}; get_materials lists the section ids")
    return row


# ---------------------------------------------------------------------- notes


def save_summary(engine: Engine, section_id: int, markdown: str, title: str = "",
                 source: str = "claude", now: float | None = None) -> tuple[StudyNote, bool]:
    """Save (or replace) the section's summary. Returns the note and whether it replaced one."""
    markdown = _text(markdown, "markdown", MAX_MARKDOWN, required=True)
    title = _text(title, "title", MAX_TITLE)
    ts = _now(now)
    with session(engine) as s:
        sec = _section(s, section_id)
        note = s.exec(select(StudyNote).where(
            StudyNote.user_id == USER, StudyNote.section_id == sec.id,
            StudyNote.kind == "summary")).first()
        replaced = note is not None
        if note is None:
            note = StudyNote(user_id=USER, course_id=sec.course_id, section_id=sec.id,
                             created_at=ts)
        note.course_id = sec.course_id
        note.markdown = markdown
        note.title = title or sec.name
        note.source = source
        note.updated_at = ts
        s.add(note)
        s.commit()
        s.refresh(note)
    return note, replaced


def delete_note(engine: Engine, note_id: int) -> bool:
    with session(engine) as s:
        note = s.get(StudyNote, note_id)
        if note is None or note.user_id != USER:
            return False
        s.delete(note)
        s.commit()
    return True


# ---------------------------------------------------------------------- questions


@dataclass
class SavedQuestions:
    section: Section
    created: list[StudyQuestion]
    updated: list[StudyQuestion]


def _item(raw: object, n: int) -> dict:
    if isinstance(raw, str):
        raise StudyError(f"item {n}: send an object with question and answer, not plain text")
    if not isinstance(raw, dict):
        raise StudyError(f"item {n} must be an object with question and answer")
    where = f"item {n}"
    question = _text(raw.get("question") or raw.get("front"), f"{where} question", MAX_QUESTION, True)
    answer = _text(raw.get("answer") or raw.get("back"), f"{where} answer", MAX_ANSWER, True)
    choices = raw.get("choices") or []
    if not isinstance(choices, list) or not all(isinstance(c, str) for c in choices):
        raise StudyError(f"{where}: choices must be a list of strings")
    choices = [_text(c, f"{where} choice", MAX_CHOICE) for c in choices]
    choices = [c for c in choices if c]
    if choices and not 2 <= len(choices) <= 8:
        raise StudyError(f"{where}: give 2 to 8 choices (or none)")
    kind = raw.get("kind") or ("mcq" if choices else "short")
    if kind not in KINDS:
        raise StudyError(f"{where}: kind must be one of {', '.join(KINDS)}")
    if kind == "mcq" and not choices:
        raise StudyError(f"{where}: a multiple choice question needs choices")
    return {
        "question": question,
        "answer": answer,
        "kind": kind,
        "choices": json.dumps(choices, ensure_ascii=False) if choices else "",
        "explanation": _text(raw.get("explanation"), f"{where} explanation", MAX_ANSWER),
        "source": _text(raw.get("source"), f"{where} source", MAX_SOURCE),
    }


def save_questions(engine: Engine, section_id: int, items: object, origin: str = "claude",
                   now: float | None = None) -> SavedQuestions:
    """Add questions to a section. A question already saved for the section (same text,
    ignoring case and spacing) is updated in place and keeps its review history."""
    if not isinstance(items, list) or not items:
        raise StudyError("items must be a non-empty list of {question, answer} objects")
    if len(items) > MAX_ITEMS:
        raise StudyError(f"at most {MAX_ITEMS} questions per call; send the rest in another call")
    clean = [_item(raw, n) for n, raw in enumerate(items, start=1)]
    ts = _now(now)
    created: list[StudyQuestion] = []
    updated: list[StudyQuestion] = []
    seen: set[int] = set()  # python ids of rows already counted (duplicates in one call)
    with session(engine) as s:
        sec = _section(s, section_id)
        existing = {
            _norm(q.question): q for q in s.exec(select(StudyQuestion).where(
                StudyQuestion.user_id == USER, StudyQuestion.section_id == sec.id)).all()
        }
        for item in clean:
            key = _norm(item["question"])
            q = existing.get(key)
            if q is None:
                q = StudyQuestion(user_id=USER, course_id=sec.course_id, section_id=sec.id,
                                  origin=origin, created_at=ts, **item)
                existing[key] = q
                created.append(q)
                seen.add(id(q))
            else:
                for k, v in item.items():
                    setattr(q, k, v)
                if id(q) not in seen:
                    updated.append(q)
                    seen.add(id(q))
            s.add(q)
        s.commit()
        for q in created + updated:
            s.refresh(q)
    return SavedQuestions(sec, created, updated)


def delete_question(engine: Engine, question_id: int) -> bool:
    with session(engine) as s:
        q = s.get(StudyQuestion, question_id)
        if q is None or q.user_id != USER:
            return False
        s.delete(q)
        s.commit()
    return True


def is_due(q: StudyQuestion, now: int) -> bool:
    return q.due_at is None or q.due_at <= now


def questions(engine: Engine, course_id: int | None = None, section_id: int | None = None,
              due_only: bool = False, now: float | None = None) -> list[StudyQuestion]:
    """Questions, due ones first (new cards after cards you reviewed before)."""
    ts = _now(now)
    with session(engine) as s:
        q = select(StudyQuestion).where(StudyQuestion.user_id == USER)
        if course_id is not None:
            q = q.where(StudyQuestion.course_id == course_id)
        if section_id is not None:
            q = q.where(StudyQuestion.section_id == section_id)
        rows = list(s.exec(q).all())
    if due_only:
        rows = [r for r in rows if is_due(r, ts)]

    def key(r: StudyQuestion):
        due = is_due(r, ts)
        return (not due, r.due_at is None, r.due_at or 0, r.section_id or 0, r.id or 0)

    return sorted(rows, key=key)


def schedule(q: StudyQuestion, grade: int, now: int) -> None:
    """Apply one review to the card (SM-2 variant)."""
    if grade not in GRADES:
        raise StudyError("grade must be 0 (again), 1 (hard), 2 (good) or 3 (easy)")
    if grade == 0:
        q.lapses += 1
        q.reps = 0
        q.ease = max(MIN_EASE, q.ease - 0.2)
        q.interval = 0.0
        q.due_at = now + AGAIN_DELAY
    else:
        if grade == 1:
            interval = max(1.0, q.interval * 1.2) if q.reps else 1.0
            q.ease = max(MIN_EASE, q.ease - 0.15)
        elif q.reps == 0:
            interval = 1.0 if grade == 2 else 4.0
        elif q.reps == 1:
            interval = 3.0 if grade == 2 else 6.0
        else:
            interval = max(q.interval + 1, q.interval * q.ease * (1.3 if grade == 3 else 1.0))
        if grade == 3:
            q.ease += 0.15
        q.reps += 1
        q.interval = min(MAX_INTERVAL, round(interval, 2))
        q.due_at = now + int(q.interval * DAY)
    q.last_grade = grade
    q.last_reviewed_at = now


def review(engine: Engine, question_id: int, grade: int, now: float | None = None) -> StudyQuestion:
    ts = _now(now)
    with session(engine) as s:
        q = s.get(StudyQuestion, question_id)
        if q is None or q.user_id != USER:
            raise StudyError(f"no question with id {question_id}")
        schedule(q, grade, ts)
        s.add(q)
        s.commit()
        s.refresh(q)
    return q


# ---------------------------------------------------------------------- quiz results


def record_result(
    engine: Engine,
    score: object,
    total: object,
    course_id: int | None = None,
    section_id: int | None = None,
    topic: str = "",
    notes: str = "",
    items: object = None,
    source: str = "claude",
    now: float | None = None,
) -> tuple[QuizResult, int]:
    """Record a quiz. ``items`` ([{question_id, correct}]) also updates those saved
    questions' review schedule. Returns the result and how many questions were updated."""
    try:
        score_f, total_f = float(score), float(total)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise StudyError("score and total must be numbers") from None
    if not (0 < total_f <= 1000) or not (0 <= score_f <= total_f):
        raise StudyError("total must be 1 to 1000 and score between 0 and total")
    topic = _text(topic, "topic", MAX_TOPIC)
    notes = _text(notes, "notes", MAX_NOTES)
    reviews: list[tuple[int, bool]] = []
    if items:
        if not isinstance(items, list) or len(items) > 200:
            raise StudyError("items must be a list of {question_id, correct} (at most 200)")
        for n, it in enumerate(items, start=1):
            if (not isinstance(it, dict) or not isinstance(it.get("question_id"), int)
                    or not isinstance(it.get("correct"), bool)):
                raise StudyError(f"item {n} must look like {{\"question_id\": 12, \"correct\": true}}")
            reviews.append((it["question_id"], it["correct"]))
    ts = _now(now)
    with session(engine) as s:
        if section_id is not None:
            sec = _section(s, section_id)
            if course_id is not None and int(course_id) != sec.course_id:
                raise StudyError(f"section {sec.id} belongs to course {sec.course_id}, not {course_id}")
            course_id = sec.course_id
        elif course_id is not None:
            if s.get(Course, int(course_id)) is None:
                raise StudyError(f"no course with id {course_id}; call list_courses for the ids")
        else:
            raise StudyError("give course_id or section_id")
        cards = {
            q.id: q for q in s.exec(select(StudyQuestion).where(
                col(StudyQuestion.id).in_([qid for qid, _ in reviews]),
                StudyQuestion.user_id == USER)).all()
        } if reviews else {}
        missing = [qid for qid, _ in reviews if qid not in cards]
        if missing:
            raise StudyError(f"unknown question id(s): {', '.join(map(str, missing))}; "
                             "use the ids that save_questions or get_questions returned")
        for qid, correct in reviews:
            schedule(cards[qid], 2 if correct else 0, ts)
            s.add(cards[qid])
        result = QuizResult(user_id=USER, course_id=int(course_id), section_id=section_id,
                            source=source, topic=topic, score=score_f, total=total_f,
                            notes=notes, taken_at=ts)
        s.add(result)
        s.commit()
        s.refresh(result)
    return result, len(reviews)


def delete_result(engine: Engine, result_id: int) -> bool:
    with session(engine) as s:
        r = s.get(QuizResult, result_id)
        if r is None or r.user_id != USER:
            return False
        s.delete(r)
        s.commit()
    return True


# ---------------------------------------------------------------------- sections, prefs


def set_studied(engine: Engine, section_id: int, studied: bool, now: float | None = None) -> bool:
    with session(engine) as s:
        if s.get(Section, section_id) is None:
            return False
        mark = s.exec(select(SectionMark).where(SectionMark.user_id == USER,
                                                SectionMark.section_id == section_id)).first()
        if studied and mark is None:
            s.add(SectionMark(user_id=USER, section_id=section_id, studied_at=_now(now)))
        elif not studied and mark is not None:
            s.delete(mark)
        s.commit()
    return True


def studied_sections(engine: Engine) -> dict[int, int]:
    with session(engine) as s:
        return {m.section_id: m.studied_at for m in s.exec(
            select(SectionMark).where(SectionMark.user_id == USER)).all()}


def hours_per_day(engine: Engine) -> float:
    with session(engine) as s:
        prefs = s.get(StudyPrefs, USER)
    return prefs.hours_per_day if prefs else 2.0


def set_hours_per_day(engine: Engine, hours: float, now: float | None = None) -> float:
    if not (0.25 <= hours <= 16):
        raise StudyError("hours per day must be between 0.25 and 16")
    with session(engine) as s:
        prefs = s.get(StudyPrefs, USER) or StudyPrefs(user_id=USER)
        prefs.hours_per_day = round(hours, 2)
        prefs.updated_at = _now(now)
        s.add(prefs)
        s.commit()
    return round(hours, 2)


# ---------------------------------------------------------------------- read models


def question_dict(q: StudyQuestion, now: int) -> dict:
    try:
        choices = json.loads(q.choices) if q.choices else []
    except ValueError:
        choices = []
    return {
        "id": q.id,
        "course_id": q.course_id,
        "section_id": q.section_id,
        "kind": q.kind,
        "question": q.question,
        "answer": q.answer,
        "choices": choices,
        "explanation": q.explanation,
        "source": q.source,
        "reps": q.reps,
        "lapses": q.lapses,
        "interval": q.interval,
        "due_at": q.due_at,
        "due": is_due(q, now),
        "new": q.last_reviewed_at is None,
        "last_grade": q.last_grade,
        "created_at": q.created_at,
    }


def note_dict(n: StudyNote) -> dict:
    return {"id": n.id, "course_id": n.course_id, "section_id": n.section_id, "kind": n.kind,
            "title": n.title, "markdown": n.markdown, "source": n.source,
            "created_at": n.created_at, "updated_at": n.updated_at}


def result_dict(r: QuizResult) -> dict:
    return {"id": r.id, "course_id": r.course_id, "section_id": r.section_id,
            "source": r.source, "topic": r.topic, "score": r.score, "total": r.total,
            "percent": round(100 * r.score / r.total) if r.total else None,
            "notes": r.notes, "taken_at": r.taken_at}


def course_study(engine: Engine, course_id: int, now: float | None = None) -> dict:
    """Notes, question counts and quiz results of a course, for the course page."""
    ts = _now(now)
    with session(engine) as s:
        notes = s.exec(select(StudyNote).where(StudyNote.user_id == USER,
                                               StudyNote.course_id == course_id)).all()
        qs = s.exec(select(StudyQuestion).where(StudyQuestion.user_id == USER,
                                                StudyQuestion.course_id == course_id)).all()
        results = s.exec(select(QuizResult).where(
            QuizResult.user_id == USER, QuizResult.course_id == course_id
        ).order_by(col(QuizResult.taken_at).desc()).limit(50)).all()
    counts: dict[str, dict[str, int]] = {}
    for q in qs:
        key = str(q.section_id or 0)
        c = counts.setdefault(key, {"questions": 0, "due": 0})
        c["questions"] += 1
        c["due"] += int(is_due(q, ts))
    studied = studied_sections(engine)
    return {
        "notes": [note_dict(n) for n in notes],
        "questions": counts,
        "questions_total": len(qs),
        "questions_due": sum(int(is_due(q, ts)) for q in qs),
        "results": [result_dict(r) for r in results],
        "studied": [sid for sid in studied],
    }


def overview(engine: Engine, now: float | None = None) -> dict:
    """Totals for the dashboard and the study page: cards due per course."""
    ts = _now(now)
    with session(engine) as s:
        qs = s.exec(select(StudyQuestion).where(StudyQuestion.user_id == USER)).all()
        courses = {c.id: c for c in s.exec(select(Course)).all()}
        notes = s.exec(select(StudyNote.course_id).where(StudyNote.user_id == USER)).all()
        last = s.exec(select(QuizResult).where(QuizResult.user_id == USER)
                      .order_by(col(QuizResult.taken_at).desc()).limit(5)).all()
    per: dict[int, dict] = {}
    for q in qs:
        c = per.setdefault(q.course_id, {"questions": 0, "due": 0, "new": 0, "notes": 0})
        c["questions"] += 1
        if is_due(q, ts):
            c["due"] += 1
            c["new"] += int(q.last_reviewed_at is None)
    for cid in notes:
        per.setdefault(cid, {"questions": 0, "due": 0, "new": 0, "notes": 0})["notes"] += 1
    rows = []
    for cid, c in per.items():
        course = courses.get(cid)
        if course is None:
            continue
        rows.append({"id": cid, "fullname": course.fullname, "shortname": course.shortname,
                     "enrolled": course.enrolled, **c})
    rows.sort(key=lambda r: (-r["due"], r["fullname"]))
    return {
        "due": sum(r["due"] for r in rows),
        "questions": sum(r["questions"] for r in rows),
        "courses": rows,
        "recent_results": [
            {**result_dict(r), "course_name": courses[r.course_id].fullname
             if r.course_id in courses else ""} for r in last
        ],
    }


def section_counts(engine: Engine, section_ids: list[int]) -> dict[int, dict]:
    """Saved summary and question counts per section (for the MCP read tools)."""
    if not section_ids:
        return {}
    with session(engine) as s:
        notes = s.exec(select(StudyNote).where(StudyNote.user_id == USER,
                                               col(StudyNote.section_id).in_(section_ids))).all()
        qs = s.exec(select(StudyQuestion.section_id).where(
            StudyQuestion.user_id == USER, col(StudyQuestion.section_id).in_(section_ids))).all()
    out: dict[int, dict] = {}
    for n in notes:
        out.setdefault(n.section_id, {"summary_at": None, "questions": 0})["summary_at"] = n.updated_at
    for sid in qs:
        if sid is not None:
            out.setdefault(sid, {"summary_at": None, "questions": 0})["questions"] += 1
    return out
