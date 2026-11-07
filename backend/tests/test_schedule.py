"""Timed study schedule (issue #34): settings, capacity, unavailabilities, weights, buffer
days, activity mix and the .ics export."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import ics
from app.db import make_engine, session
from app.extract.index import extract_files, index_structure
from app.main import create_app
from app.models import StudyQuestion
from app.planner import published, schedule
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
    text = ics.build_ics([], blocks=[b.to_dict() for b in plan.blocks],
                         base_url="https://study.example.ch/", now=morning)
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


def test_busy_expands_unavailabilities_in_local_time(settings):
    config = {"weekly": [{"day": 0, "start": "08:00", "end": "10:00", "reason": "Class"}],
              "dates": [{"date": "2026-10-28", "start": "00:00", "end": "24:00", "reason": "Trip"}]}
    # Zurich leaves summer time on Sunday 25 October 2026: both Mondays stay 08:00 local.
    out = published.busy(config, date(2026, 10, 19), date(2026, 11, 1), settings.tz)
    assert [(u["date"], u["repeat"]) for u in out] == [
        ("2026-10-19", "weekly"), ("2026-10-26", "weekly"), ("2026-10-28", "date")]
    assert [local(settings, u["start"]).hour for u in out[:2]] == [8, 8]
    assert out[1]["start"] - out[0]["start"] == 7 * DAY + 3600
    assert out[2]["all_day"] and not out[0]["all_day"]
    body = ics.build_ics([], now=NOW, busy=out)
    assert "SUMMARY:Class" in body and "DTSTART;VALUE=DATE:20261028" in body
    assert "DTEND;VALUE=DATE:20261029" in body and body.count("TRANSP:TRANSPARENT") == 3


def test_publish_keeps_the_feed_stable_until_saved(settings, engine, morning):
    first = published.publish(settings, engine, now=morning)
    assert first["days"] and not first["preview"] and first["published_at"] == morning
    blocks = [b for d in first["days"] for b in d["blocks"]]
    # Later the same day, the published schedule is unchanged (no re-planning on read).
    later = published.current(settings, engine, now=morning + 3 * 3600)
    assert [b for d in later["days"] for b in d["blocks"]] == blocks
    # A preview of unsaved settings changes nothing.
    pre = published.preview(settings, engine, {"session_minutes": 25}, now=morning)
    assert pre["preview"] and pre["config"]["session_minutes"] == 25
    assert published.current(settings, engine, now=morning)["config"]["session_minutes"] == 50
    # Re-publishing later keeps the blocks that already ended and re-plans the rest.
    noon = morning + 5 * 3600
    again = published.publish(settings, engine, now=noon)
    today = again["days"][0]
    done = [b for b in blocks if b["end"] <= noon]
    assert done and today["blocks"][:len(done)] == done
    assert all(b["start"] >= noon for b in today["blocks"][len(done):])


def test_nightly_update_follows_auto_update(settings, engine, morning):
    assert published.nightly(settings, engine, now=morning)
    schedule.save(engine, {"auto_update": False}, now=morning)
    assert not published.nightly(settings, engine, now=morning + DAY)
    with pytest.raises(ScheduleError):
        schedule.save(engine, {"auto_update": "yes"})


@pytest.fixture
def c(settings, engine):
    client = TestClient(create_app(settings), follow_redirects=False)
    client.post("/login", data={"password": PASSWORD})
    return client


def test_api(settings, engine, c):
    anon = TestClient(create_app(settings), follow_redirects=False)
    assert anon.get("/api/schedule").status_code == 401
    assert anon.post("/api/schedule/preview", json={}, headers=SAME_ORIGIN).status_code == 401
    out = c.get("/api/schedule").json()
    assert out["config"]["days"] == 14 and {"days", "courses", "notes", "unscheduled"} <= out.keys()
    assert out["published_at"] and out["preview"] is False
    assert "owner" in out  # Moodle name for the printed weeks ("" before the first sync)
    assert c.post("/api/schedule/settings", json={"buffer_days": 2},
                  headers={"Sec-Fetch-Site": "cross-site"}).status_code == 401
    assert c.post("/api/schedule/settings", json={"buffer_days": 9},
                  headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/schedule/settings", content=b"[]", headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/schedule/preview", json={"buffer_days": 9},
                  headers=SAME_ORIGIN).status_code == 400
    pre = c.post("/api/schedule/preview", json={"buffer_days": 3}, headers=SAME_ORIGIN).json()
    assert pre["preview"] and pre["config"]["buffer_days"] == 3
    assert c.get("/api/schedule").json()["config"]["buffer_days"] == 1  # not saved
    saved = c.post("/api/schedule/settings", json={"buffer_days": 2, "daily_hours": 3},
                   headers=SAME_ORIGIN).json()
    assert saved["config"]["buffer_days"] == 2 and saved["config"]["daily_hours"] == 3
    assert saved["published_at"] and "days" in saved
    assert c.get("/api/plan").json()["hours_per_day"] == 3  # shared with the catch-up plan
    # One calendar for everything: the download has the study blocks and the deadlines.
    c.post("/api/schedule/settings", headers=SAME_ORIGIN, json={
        "weekly": [{"day": d, "start": "12:00", "end": "13:00", "reason": "Lunch"} for d in range(7)]})
    res = c.get("/calendar.ics?download=1")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/calendar")
    assert res.headers["content-disposition"].startswith('attachment; filename="study-calendar-')
    assert "UID:schedule-" in res.text and "SUMMARY:[Study]" in res.text
    assert "SUMMARY:Lunch" in res.text and "UID:assign-" in res.text
    c.post("/api/schedule/settings", json={"feed_unavailable": False}, headers=SAME_ORIGIN)
    assert "SUMMARY:Lunch" not in c.get("/calendar.ics").text


def test_pdf_export(settings, engine, c):
    from io import BytesIO

    from pypdf import PdfReader

    anon = TestClient(create_app(settings), follow_redirects=False)
    assert anon.get("/api/schedule.pdf").status_code == 401
    assert c.get("/api/schedule.pdf?weeks=9").status_code == 400
    assert c.get("/api/schedule.pdf?from=soon").status_code == 400
    c.post("/api/schedule/settings", headers=SAME_ORIGIN, json={
        "weekly": [{"day": d, "start": "12:00", "end": "13:00", "reason": "Lunch"} for d in range(7)]})
    res = c.get("/api/schedule.pdf?weeks=2")
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].startswith('inline; filename="study-plan-')
    pdf = PdfReader(BytesIO(res.content))
    assert len(pdf.pages) == 2
    assert pdf.pages[0].mediabox.width == 842 and pdf.pages[0].mediabox.height == 595
    text = pdf.pages[0].extract_text()
    assert "Study plan" in text and "Week of Monday" in text and "Printed on" in text
    assert "Lunch" in text and "Monday" in text and "Friday" in text
    blocks = [b for d in c.get("/api/schedule").json()["days"] for b in d["blocks"]]
    week = "".join(p.extract_text() for p in pdf.pages)
    assert any(b["title"][:8] in week for b in blocks)
    no_busy = PdfReader(BytesIO(c.get("/api/schedule.pdf?busy=0").content)).pages[0].extract_text()
    assert "Lunch" not in no_busy


def test_pdf_writer_escapes_and_fits():
    from app import pdf

    doc = pdf.Document(title="a (b) \\ c")
    page = doc.page()
    page.text(10, 20, "Matrices (part 1/2) é – ok ✓")
    assert pdf.fit("a" * 200, 50, 9).endswith("...")
    assert pdf.text_width(pdf.fit("a" * 200, 50, 9), 9) <= 50
    out = doc.render()
    assert out.startswith(b"%PDF-1.4") and out.rstrip().endswith(b"%%EOF")
    assert b"(a \\(b\\) \\\\ c)" in out
