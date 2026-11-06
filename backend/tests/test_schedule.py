"""Timed study schedule (issue #34): settings, capacity, unavailabilities, weights, buffer
days, activity mix and the .ics export."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import ics
from app.db import make_engine, session
from app.extract.index import extract_files, index_structure
from app.main import create_app
from app.models import StudyQuestion
from app.planner import schedule
from app.planner.schedule import Generator, ScheduleError

from .conftest import PASSWORD
from .m3_seed import DAY, NOW, seed

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.data_dir)
    seed(engine, settings.data_dir)
    extract_files(engine, settings.data_dir)
    index_structure(engine)
    return engine


@pytest.fixture
def morning(settings):
    """07:00 local time on the seed's day, so today has a full study window."""
    local = datetime.fromtimestamp(NOW, settings.tz)
    return int(local.replace(hour=7, minute=0, second=0, microsecond=0).timestamp())


def generate(settings, engine, now, **config):
    cfg = schedule.validate(config, schedule.load(engine)) if config else None
    return Generator(settings, engine, now=now, config=cfg).generate()


def local(settings, ts):
    return datetime.fromtimestamp(ts, settings.tz)


def test_settings_defaults_save_and_validation(engine):
    cfg = schedule.load(engine)
    assert cfg["days"] == 14 and cfg["max_daily_hours"] == 6 and cfg["daily_hours"] == 2
    saved = schedule.save(engine, {
        "daily_hours": 3, "rest_hours": 1.5, "buffer_days": 2,
        "course_weights": {"10": 2, "11": 0.5},
        "weekly": [{"day": 0, "start": "08:00", "end": "12:00", "reason": "  Classes  "}],
        "dates": [{"date": "2030-01-02", "reason": "Travel"}],
    }, now=NOW)
    assert saved["daily_hours"] == 3 and saved["rest_hours"] == 1.5
    assert saved["course_weights"] == {"10": 2.0, "11": 0.5}
    assert saved["weekly"] == [{"day": 0, "start": "08:00", "end": "12:00", "reason": "Classes"}]
    assert saved["dates"] == [{"date": "2030-01-02", "start": "00:00", "end": "24:00",
                               "reason": "Travel"}]
    assert schedule.load(engine) == saved
    # Lowering the daily maximum lowers hours per day with it (shared with the plan).
    assert schedule.save(engine, {"max_daily_hours": 2})["daily_hours"] == 2
    for bad in ({"days": 0}, {"days": 1.5}, {"max_daily_hours": 9}, {"rest_hours": "2"},
                {"daily_hours": 5}, {"day_start": "8:00"}, {"day_start": "21:30"},
                {"weekly": [{"day": 7, "start": "08:00", "end": "09:00"}]},
                {"weekly": [{"day": 1, "start": "10:00", "end": "09:00"}]},
                {"dates": [{"date": "2030-02-30"}]}, {"course_weights": {"x": 1}},
                {"course_weights": {"10": 4}}, {"recall": "yes"}, {"colour": "red"},
                {"weekly": [{"day": 1}] * 51}):
        with pytest.raises(ScheduleError):
            schedule.save(engine, bad)


def test_blocks_respect_window_unavailability_and_caps(settings, engine, morning):
    today = local(settings, morning).date()
    weekly = [{"day": d, "start": "09:00", "end": "12:00", "reason": "Classes"} for d in range(7)]
    off = (today + timedelta(days=1)).isoformat()
    plan = generate(settings, engine, morning, daily_hours=3, max_daily_hours=4, rest_hours=8,
                    weekly=weekly, dates=[{"date": off, "start": "00:00", "end": "24:00",
                                           "reason": "Travel"}], beyond_target=True)
    assert plan.blocks
    for day in plan.days:
        assert day.minutes <= 4 * 60
        # 14 h window - 3 h classes - 8 h rest: 3 h at most, also when stretched.
        assert day.minutes <= max(0, day.free_minutes - 8 * 60)
        if not day.stretched:
            assert day.minutes <= day.capacity
        for b in day.blocks:
            start, end = local(settings, b.start), local(settings, b.end)
            assert start.hour >= 8 and (end.hour, end.minute) <= (22, 0)
            assert not (start.hour < 12 and end.hour * 60 + end.minute > 9 * 60), b.summary()
            assert b.minutes >= 15 or b.parts > 1 or b.item is None
    travel = next(d for d in plan.days if d.day.isoformat() == off)
    assert travel.blocks == [] and travel.blocked[0]["reason"] == "Travel"
    # Blocks of a day never overlap, with a break between them.
    for day in plan.days:
        for a, b in zip(day.blocks, day.blocks[1:]):
            assert b.start >= a.end + 10 * 60


def test_buffer_days_and_deadlines_first(settings, engine, morning):
    plan = generate(settings, engine, morning, buffer_days=1, beyond_target=True)
    devoir = [b for b in plan.blocks if b.item and b.item.kind == "assign"]
    assert devoir and sum(b.minutes for b in devoir) == 120
    due = NOW + 3 * DAY
    assert max(b.end for b in devoir) <= due - DAY
    assert [b.part for b in devoir] == list(range(1, len(devoir) + 1))
    assert all(b.parts == len(devoir) and not b.late for b in devoir)
    # The overdue quiz comes first.
    first = next(b for b in plan.blocks if b.kind != "flashcards")
    assert first.item.title == "Quiz 1"


def test_activity_mix_recall_and_flashcards(settings, engine, morning):
    with session(engine) as s:
        s.add(StudyQuestion(course_id=10, section_id=102, question="det?", answer="ad-bc"))
        s.commit()
    plan = generate(settings, engine, morning, beyond_target=True)
    kinds = {b.kind for b in plan.blocks}
    assert {"deep", "practice", "recall", "flashcards"} <= kinds
    assert plan.cards_due == 1
    first = plan.days[0].blocks[0]
    assert first.kind == "flashcards" and "1 card due" in first.detail
    # Two spaced recall blocks per finished section, after it is finished.
    for section in {b.item.section_id for b in plan.blocks if b.kind == "deep"
                    and b.part == b.parts}:
        done = max(b.end for b in plan.blocks if b.kind == "deep" and b.item.section_id == section)
        recalls = [b for b in plan.blocks if b.kind == "recall" and b.item.section_id == section]
        assert all(r.start > done for r in recalls)
        assert len({local(settings, r.start).date() for r in recalls}) == len(recalls)
    no_recall = generate(settings, engine, morning, beyond_target=True, recall=False)
    assert not any(b.kind == "recall" for b in no_recall.blocks)


def test_course_weights(settings, engine, morning):
    plan = generate(settings, engine, morning, beyond_target=True, course_weights={"11": 0})
    assert not any(b.item and b.item.course_id == 11 for b in plan.blocks)
    assert any("Statistics" in n for n in plan.notes)
    rows = {c["id"]: c for c in plan.to_dict()["courses"]}
    assert rows[11]["weight"] == 0 and rows[11]["target_share"] == 0
    assert rows[10]["target_share"] == 100 and rows[10]["planned_share"] == 100


def test_interleaves_courses(settings, engine, morning):
    """Two courses of equal weight take turns instead of one long block of one course."""
    from app.models import Deadline

    with session(engine) as s:
        for i in range(3):
            s.add(Deadline(id=50 + i, source="assign", source_id=50 + i, course_id=11,
                           name=f"Série {i + 1}", kind="due", due_at=NOW + 40 * DAY, grade=10))
        s.commit()
    plan = generate(settings, engine, morning, beyond_target=True, buffer_days=0)
    order = [b.item.course_id for b in plan.blocks if b.kind in ("deep", "practice")]
    switches = sum(1 for a, b in zip(order, order[1:]) if a != b)
    assert switches >= 2


def test_no_time_left(settings, engine, morning):
    plan = generate(settings, engine, morning, days=2,
                    weekly=[{"day": d, "start": "00:00", "end": "24:00", "reason": "Busy"}
                            for d in range(7)])
    assert plan.blocks == [] and plan.unscheduled
    assert any("No free study time" in n for n in plan.notes)


def test_ics_export(settings, engine, morning):
    plan = generate(settings, engine, morning, beyond_target=True)
    text = ics.build_schedule_ics([b.to_dict() for b in plan.blocks], "https://study.example.ch/",
                                  now=morning)
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == len(plan.blocks)
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY:[Study] LA: Matrices (Deep work)" in unfolded
    assert "https://study.example.ch/#/file/2?course=10" in unfolded
    assert "URL:https://study.example.ch/#/course/10?section=102" in unfolded
    first = plan.blocks[0]
    stamp = datetime.fromtimestamp(first.start, tz=timezone.utc)
    assert f"DTSTART:{stamp:%Y%m%dT%H%M%SZ}" in text
    uids = [line for line in unfolded.split("\r\n") if line.startswith("UID:")]
    assert len(uids) == len(set(uids))


@pytest.fixture
def c(settings, engine):
    client = TestClient(create_app(settings), follow_redirects=False)
    client.post("/login", data={"password": PASSWORD})
    return client


def test_api(settings, engine, c):
    anon = TestClient(create_app(settings), follow_redirects=False)
    assert anon.get("/api/schedule").status_code == 401
    assert anon.get("/api/schedule.ics").status_code == 401
    out = c.get("/api/schedule").json()
    assert out["config"]["days"] == 14 and {"days", "courses", "notes", "unscheduled"} <= out.keys()
    assert c.post("/api/schedule/settings", json={"buffer_days": 2},
                  headers={"Sec-Fetch-Site": "cross-site"}).status_code == 401
    assert c.post("/api/schedule/settings", json={"buffer_days": 9},
                  headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/schedule/settings", content=b"[]", headers=SAME_ORIGIN).status_code == 400
    saved = c.post("/api/schedule/settings", json={"buffer_days": 2, "daily_hours": 3},
                   headers=SAME_ORIGIN).json()
    assert saved["buffer_days"] == 2 and saved["daily_hours"] == 3
    assert c.get("/api/plan").json()["hours_per_day"] == 3  # shared with the catch-up plan
    res = c.get("/api/schedule.ics")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/calendar")
    assert res.headers["content-disposition"].startswith('attachment; filename="study-schedule-')
    assert "BEGIN:VCALENDAR" in res.text
