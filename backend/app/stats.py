"""Positive stats for the home page: what you did, not what is left.

A *study day* is a calendar day (in ``TIMEZONE``) on which you did at least one thing: marked
a deadline or a section done, reviewed a flashcard, took a quiz (in Claude or in the app), or
Claude saved a summary for you. The streak counts study days in a row up to today; a streak
that ended yesterday still counts (you have the rest of today to keep it going).

Flashcards only keep their last review time, so "cards reviewed" counts cards whose most recent
review falls in the window: a lower bound, never an inflated number.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.engine import Engine
from sqlmodel import select

from app.db import session
from app.models import DeadlineMark, QuizResult, SectionMark, StudyNote, StudyQuestion

USER = 1
WEEK_DAYS = 7
MAX_STREAK = 366


def _day(ts: int, tz: ZoneInfo) -> date:
    return datetime.fromtimestamp(ts, tz).date()


def stats(engine: Engine, tz: ZoneInfo, now: float | None = None) -> dict:
    ts = int(now if now is not None else time.time())
    today = _day(ts, tz)
    week_start = today - timedelta(days=WEEK_DAYS - 1)
    with session(engine) as s:
        marks = [m for m in s.exec(select(DeadlineMark.done_at)).all() if m]
        sections = [m for m in s.exec(
            select(SectionMark.studied_at).where(SectionMark.user_id == USER)).all() if m]
        reviews = [r for r in s.exec(select(StudyQuestion.last_reviewed_at).where(
            StudyQuestion.user_id == USER)).all() if r]
        learned = len(s.exec(select(StudyQuestion.id).where(
            StudyQuestion.user_id == USER, StudyQuestion.reps > 0)).all())
        results = s.exec(select(QuizResult).where(QuizResult.user_id == USER)).all()
        notes = [n for n in s.exec(
            select(StudyNote.updated_at).where(StudyNote.user_id == USER)).all() if n]

    days: set[date] = set()
    for t in (*marks, *sections, *reviews, *notes, *(r.taken_at for r in results if r.taken_at)):
        days.add(_day(t, tz))

    def in_week(t: int) -> bool:
        return week_start <= _day(t, tz) <= today

    streak = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days and streak < MAX_STREAK:
        streak += 1
        cursor -= timedelta(days=1)
    best = _best_streak(days)

    week_results = [r for r in results if r.taken_at and in_week(r.taken_at) and r.total]
    avg = (round(100 * sum(r.score for r in week_results) / sum(r.total for r in week_results))
           if week_results else None)
    return {
        "streak": streak,
        "best_streak": max(best, streak),
        "studied_today": today in days,
        # Oldest first, today last: the week strip on the home page.
        "week": [
            {"date": (week_start + timedelta(days=i)).isoformat(),
             "active": (week_start + timedelta(days=i)) in days}
            for i in range(WEEK_DAYS)
        ],
        "this_week": {
            "deadlines_done": sum(1 for t in marks if in_week(t)),
            "sections_studied": sum(1 for t in sections if in_week(t)),
            "cards_reviewed": sum(1 for t in reviews if in_week(t)),
            "quizzes": len([r for r in results if r.taken_at and in_week(r.taken_at)]),
            "quiz_percent": avg,
        },
        "total": {
            "sections_studied": len(sections),
            "cards_learned": learned,
            "summaries": len(notes),
            "quizzes": len(results),
            "deadlines_done": len(marks),
        },
    }


def _best_streak(days: set[date]) -> int:
    best = run = 0
    prev: date | None = None
    for d in sorted(days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best
