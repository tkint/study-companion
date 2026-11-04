"""Positive home page stats: streaks, this week, totals."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import stats, study
from app.db import make_engine, session
from app.models import Course, Deadline, DeadlineMark, Section, StudyQuestion

TZ = ZoneInfo("Europe/Zurich")
DAY = 86400
NOW = int(datetime(2026, 11, 4, 15, 0, tzinfo=TZ).timestamp())


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.data_dir)
    with session(engine) as s:
        s.add(Course(id=10, shortname="LA", fullname="Linear Algebra", enrolled=True))
        for sid in (101, 102, 103):
            s.add(Section(id=sid, course_id=10, number=sid - 100, name=f"S{sid}"))
        for did in (1, 2):
            s.add(Deadline(id=did, source_id=did, course_id=10, source="assign", name=f"A{did}", due_at=NOW))
        s.commit()
    return engine


def test_empty_database_has_zero_stats(engine):
    data = stats.stats(engine, TZ, now=NOW)
    assert data["streak"] == 0 and data["best_streak"] == 0 and not data["studied_today"]
    assert len(data["week"]) == 7 and not any(d["active"] for d in data["week"])
    assert data["week"][-1]["date"] == "2026-11-04"
    assert data["this_week"]["quiz_percent"] is None
    assert set(data["total"].values()) == {0}


def test_streak_counts_days_in_a_row_from_any_activity(engine):
    study.set_studied(engine, 101, True, now=NOW)  # today
    with session(engine) as s:
        s.add(DeadlineMark(deadline_id=1, done_at=NOW - DAY))  # yesterday
        s.add(StudyQuestion(course_id=10, question="q", answer="a", reps=1,
                            last_reviewed_at=NOW - 2 * DAY))  # two days ago
        s.add(DeadlineMark(deadline_id=2, done_at=NOW - 10 * DAY))  # gap, then an older day
        s.commit()
    study.record_result(engine, 3, 4, course_id=10, now=NOW - 2 * DAY)
    data = stats.stats(engine, TZ, now=NOW)
    assert data["streak"] == 3 and data["studied_today"]
    assert [d["active"] for d in data["week"]] == [False] * 4 + [True] * 3
    week = data["this_week"]
    assert week == {"deadlines_done": 1, "sections_studied": 1, "cards_reviewed": 1,
                    "quizzes": 1, "quiz_percent": 75}
    assert data["total"]["deadlines_done"] == 2 and data["total"]["cards_learned"] == 1


def test_streak_survives_until_the_end_of_today(engine):
    study.set_studied(engine, 101, True, now=NOW - DAY)
    study.set_studied(engine, 102, True, now=NOW - 2 * DAY)
    data = stats.stats(engine, TZ, now=NOW)
    assert data["streak"] == 2 and not data["studied_today"]
    # A day without anything breaks it; the best streak remembers it.
    data = stats.stats(engine, TZ, now=NOW + DAY)
    assert data["streak"] == 0 and data["best_streak"] == 2


def test_days_follow_the_configured_time_zone(engine):
    # 23:30 in Zurich is the next day in UTC+14; the streak follows TIMEZONE.
    late = int(datetime(2026, 11, 3, 23, 30, tzinfo=TZ).timestamp())
    study.set_studied(engine, 101, True, now=late)
    data = stats.stats(engine, TZ, now=NOW)
    assert data["week"][-2] == {"date": "2026-11-03", "active": True}
