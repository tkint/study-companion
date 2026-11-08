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
    # Blocks of a day never overlap, with the break between them (none by default).
    assert plan.config["break_minutes"] == 0
    for day in plan.days:
        for a, b in zip(day.blocks, day.blocks[1:]):
            assert b.start >= a.end


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


def test_keeps_a_course_together_then_takes_turns(settings, engine, morning):
    """A course's work stays in one run (up to about two focus blocks), then the other course
    gets its turn: fewer switches than strict interleaving, but both courses get time."""
    from app.models import Deadline

    with session(engine) as s:
        for i in range(3):
            s.add(Deadline(id=50 + i, source="assign", source_id=50 + i, course_id=11,
                           name=f"Série {i + 1}", kind="due", due_at=NOW + 40 * DAY, grade=10))
        s.commit()
    plan = generate(settings, engine, morning, beyond_target=True, buffer_days=0)
    for day in plan.days:
        order = [b.item.course_id for b in day.blocks if b.item is not None]
        runs = [order[0]] if order else []
        for c in order[1:]:
            if c != runs[-1]:
                runs.append(c)
        assert len(runs) == len(set(runs)) or len(runs) <= len(order) // 2 + 1  # grouped
    courses = {b.item.course_id for b in plan.blocks if b.item is not None}
    assert {10, 11} <= courses
    first_day = [b for b in plan.days[0].blocks if b.item is not None]
    assert first_day[0].item.course_id == first_day[1].item.course_id  # no forced switch


def test_no_time_left(settings, engine, morning):
    plan = generate(settings, engine, morning, days=2,
                    weekly=[{"day": d, "start": "00:00", "end": "24:00", "reason": "Busy"}
                            for d in range(7)])
    assert plan.blocks == [] and plan.unscheduled
    assert any("No free study time" in n for n in plan.notes)


def test_ics_export(settings, engine, morning):
    from app.planner import groups

    plan = generate(settings, engine, morning, beyond_target=True)
    text = ics.build_ics([], blocks=[b.to_dict() for b in plan.blocks],
                         base_url="https://study.example.ch/", now=morning)
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == len(groups.group([b.to_dict() for b in plan.blocks]))
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY:Linear Algebra - Study" in unfolded and "\\n\\nMatrices" in unfolded
    # The link to the entry in the app comes first, on its own line; paragraphs are spaced.
    assert "DESCRIPTION:Open in Study Companion:\\nhttps://study.example.ch/#/calendar?at=" in unfolded
    assert "URL:https://study.example.ch/#/calendar?at=" in unfolded
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


def test_daily_breaks_and_days_off(settings, engine, morning):
    config = {"daily": [{"start": "12:00", "end": "14:00", "reason": "Meal"}], "days_off": [6],
              "weekly": [], "dates": []}
    out = published.busy(config, date(2026, 11, 7), date(2026, 11, 9), settings.tz)  # Sat-Mon
    assert [(u["date"], u["reason"], u["all_day"]) for u in out] == [
        ("2026-11-07", "Meal", False), ("2026-11-08", "Day off", True), ("2026-11-09", "Meal", False)]
    schedule.save(engine, {"daily": config["daily"], "days_off": [6], "feed_unavailable": True})
    plan = generate(settings, engine, morning, days=7)
    assert plan.config["days_off"] == [6] and plan.blocks
    assert any(d.blocked and d.blocked[0]["repeat"] == "off" for d in plan.days)
    for b in plan.blocks:
        start = local(settings, b.start)
        assert start.weekday() != 6
        m = start.hour * 60 + start.minute
        assert not 12 * 60 <= m < 14 * 60
    with pytest.raises(schedule.ScheduleError):
        schedule.save(engine, {"days_off": [7]})
    assert "feed_unavailable" not in schedule.load(engine)


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
    assert "UID:schedule-" in res.text and " - Study" in res.text
    # Breaks are not events in the feed (only the web calendar and the PDF show them).
    assert "SUMMARY:Lunch" not in res.text and "UID:assign-" in res.text


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


def test_pdf_groups_by_course_and_never_cuts_text(settings):
    from datetime import date as d_

    from app import pdf
    from app.planner import print_week

    tz = settings.tz
    day = d_(2026, 11, 9)

    def ts(h, m):
        return int(datetime(2026, 11, 9, h, m, tzinfo=tz).timestamp())

    def block(h, m, minutes, title, course, kind="deep", cid=1):
        return {"start": ts(h, m), "end": ts(h, m) + minutes * 60, "kind": kind, "title": title,
                "label": "Deep work", "parts": 1, "part": 1, "course_id": cid,
                "course_name": course, "course_short": "LA", "item_kind": "section"}

    long = "A very long section title that would never fit on one line of a narrow column"
    plan = {"config": {"day_start": "08:00", "day_end": "22:00"}, "busy": [], "days": [{"blocks": [
        block(8, 0, 30, "Matrices", "Linear Algebra"),
        block(8, 30, 15, "Vectors", "Linear Algebra", "recall"),
        block(8, 45, 30, "Quiz 1", "Linear Algebra", "practice"),
        block(9, 15, 50, long, "Statistics", cid=2),
        block(14, 0, 15, "Eigen", "Linear Algebra", "recall"),
    ]}]}
    out = print_week.entries(plan, [], day, day, tz)
    assert [(e.time, e.title) for e in out] == [
        ("08:00-08:45", "Linear Algebra - Study"), ("08:45-09:15", "Linear Algebra - Quiz 1"),
        ("09:15-10:05", "Statistics - Study"), ("14:00-14:15", "Linear Algebra - Study")]
    assert [w for _, w in out[0].items] == ["Matrices", "Vectors"]
    assert out[1].items == []  # a task's title is its work
    assert out[0].color == out[1].color != out[2].color  # one colour per course
    assert all("LA" not in e.title for e in out)  # full course names only
    lines = pdf.wrap(long, 60, 8)
    assert len(lines) > 2 and " ".join(lines) == long
    body = print_week.render(plan, [], day, 1, tz)
    from io import BytesIO

    from pypdf import PdfReader
    text = PdfReader(BytesIO(body)).pages[0].extract_text()
    assert "..." not in text and "Linear Algebra - Study" in text and "Statistics" in text
    assert "narrow" in text and "column" in text  # the end of the long title is there


def test_groups_by_course_with_tasks_apart():
    from app.planner import groups

    def b(start, minutes, kind, cid, title="Sec", course="Spanish"):
        return {"date": "2026-11-09", "start": start, "end": start + minutes * 60,
                "minutes": minutes, "kind": kind, "title": title, "course_id": cid,
                "course_name": course, "item_kind": "quiz" if kind == "practice" else "section",
                "deadline_id": 7 if kind == "practice" else None}

    h = 9 * 3600
    out = groups.group([
        b(h, 30, "deep", 3), b(h + 1800, 30, "recall", 3),  # 09:00-10:00 Spanish - Study
        b(h + 3600, 15, "practice", 3, "Test 1"), b(h + 4500, 15, "practice", 3, "Test 1"),
        b(h + 9000, 30, "deep", 4, course="Literature 3"),
        {"date": "2026-11-09", "start": h + 12600, "end": h + 13500, "minutes": 15,
         "kind": "flashcards", "title": "Flashcard review", "course_id": None, "course_name": ""},
    ])
    assert [(g["label"], g["minutes"], len(g["blocks"])) for g in out] == [
        ("Spanish - Study", 60, 2), ("Spanish - Test 1", 30, 2),
        ("Literature 3 - Study", 30, 1), ("Flashcards", 15, 1)]
    assert out[0]["color"] == out[1]["color"] == groups.course_color(3) != out[2]["color"]
    assert out[3]["color"] == groups.NO_COURSE


def test_start_date(settings, engine, morning):
    today = local(settings, morning).date()
    start = today + timedelta(days=5)
    plan = generate(settings, engine, morning, start_date=start.isoformat(), days=7,
                    beyond_target=True)
    assert plan.start == start and plan.today == today
    assert plan.days and plan.days[0].day >= start and plan.days[-1].day < start + timedelta(days=7)
    assert all(local(settings, b.start).date() >= start for b in plan.blocks)
    # A start day gets its full study window, not "what's left of today".
    assert local(settings, plan.days[0].blocks[0].start).hour == 8
    assert any("starts on" in n for n in plan.notes)
    out = plan.to_dict()
    assert out["start"] == start.isoformat() and out["today"] == today.isoformat()
    # The busy range follows the horizon from the start date.
    assert published.busy_range(out)[1] == start + timedelta(days=6)
    # A start date that has passed (or none) means today.
    past = generate(settings, engine, morning, start_date=(today - timedelta(days=3)).isoformat())
    assert past.start == today and past.days[0].day == today
    assert generate(settings, engine, morning, start_date="").start == today
    saved = schedule.save(engine, {"start_date": start.isoformat()}, now=morning)
    assert saved["start_date"] == start.isoformat()
    assert schedule.save(engine, {"start_date": None})["start_date"] == ""
    for bad in ("2026-02-30", "tomorrow", 20261110):
        with pytest.raises(ScheduleError):
            schedule.save(engine, {"start_date": bad})


def test_later_start_date_clears_passed_blocks(settings, engine, morning):
    published.publish(settings, engine, now=morning)
    noon = morning + 5 * 3600
    kept = published.publish(settings, engine, now=noon)
    assert any(b["end"] <= noon for d in kept["days"] for b in d["blocks"])  # history kept
    start = local(settings, morning).date() + timedelta(days=3)
    schedule.save(engine, {"start_date": start.isoformat()}, now=noon)
    out = published.publish(settings, engine, now=noon)
    assert out["days"] and all(d["date"] >= start.isoformat() for d in out["days"])
    assert published.current(settings, engine, now=noon)["days"][0]["date"] >= start.isoformat()


def _xlsx(content: bytes) -> dict:
    """Sheet name -> {cell ref: text}, and the merges, read with the standard library."""
    import re
    import zipfile
    from io import BytesIO
    from xml.etree import ElementTree as ET

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    z = zipfile.ZipFile(BytesIO(content))
    assert z.testzip() is None
    for name in z.namelist():  # every part is well-formed XML
        ET.fromstring(z.read(name))
    book = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in book.find("m:sheets", ns)]
    out = {}
    for i, name in enumerate(names, 1):
        root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
        cells = {c.get("r"): "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                 for c in root.iter(f"{{{ns['m']}}}c")}
        merges = [m.get("ref") for m in root.iter(f"{{{ns['m']}}}mergeCell")]
        out[name] = {"cells": {k: v for k, v in cells.items() if v}, "merges": merges,
                     "frozen": root.find(".//m:pane", ns) is not None}
        assert all(re.fullmatch(r"[A-Z]+\d+:[A-Z]+\d+", m) for m in merges)
    return out


def test_xlsx_export(settings, engine, c):
    anon = TestClient(create_app(settings), follow_redirects=False)
    assert anon.get("/api/schedule.xlsx").status_code == 401
    assert c.get("/api/schedule.xlsx?weeks=9").status_code == 400
    assert c.get("/api/schedule.xlsx?from=soon").status_code == 400
    c.post("/api/schedule/settings", headers=SAME_ORIGIN, json={
        "weekly": [{"day": d, "start": "12:00", "end": "13:00", "reason": "Lunch"} for d in range(7)]})
    plan = c.get("/api/schedule").json()
    first = plan["days"][0]["date"]
    res = c.get(f"/api/schedule.xlsx?weeks=2&from={first}")
    assert res.status_code == 200
    assert res.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    monday = date.fromisoformat(first) - timedelta(days=date.fromisoformat(first).weekday())
    assert res.headers["content-disposition"] == (
        f'attachment; filename="study-plan-{monday.isoformat()}.xlsx"')
    book = _xlsx(res.content)
    # One sheet per week, named by its Monday.
    assert list(book) == [monday.isoformat(), (monday + timedelta(days=7)).isoformat()]
    week = book[monday.isoformat()]
    assert week["cells"]["A1"] == "Study plan" and week["cells"]["A2"].startswith("Week of Monday")
    assert week["cells"]["B4"].startswith("Monday") and week["cells"]["H4"].startswith("Sunday")
    both = "\n".join(v for sheet in book.values() for v in sheet["cells"].values())
    assert "Lunch" in both and " - Study" in both and week["merges"] and week["frozen"]
    blocks = [b for d in plan["days"] for b in d["blocks"]]
    assert any(b["title"][:8] in both for b in blocks)
    no_busy = _xlsx(c.get(f"/api/schedule.xlsx?busy=0&weeks=2&from={first}").content)
    assert "Lunch" not in "\n".join(v for s in no_busy.values() for v in s["cells"].values())


def test_xlsx_week_layout(settings):
    from datetime import date as d_

    from app.planner import sheet_week

    tz = settings.tz

    def ts(day, h, m):
        return int(datetime(2026, 11, day, h, m, tzinfo=tz).timestamp())

    def block(day, h, m, minutes, title, cid=1, kind="deep"):
        return {"start": ts(day, h, m), "end": ts(day, h, m) + minutes * 60, "kind": kind,
                "title": title, "label": "Deep work", "parts": 1, "part": 1, "course_id": cid,
                "course_name": "Linear Algebra", "course_short": "LA", "item_kind": "section"}

    long = "A very long section title that would never fit on one line of a narrow column " * 3
    plan = {"config": {"day_start": "08:00", "day_end": "22:00"}, "days": [{"blocks": [
        block(9, 9, 0, 30, "Matrices"), block(9, 9, 30, 15, long),
        block(11, 14, 0, 60, "Vectors"),
    ]}], "busy": [
        {"date": "2026-11-10", "start": ts(10, 12, 0), "end": ts(10, 13, 0), "reason": "Lunch"},
        {"date": "2026-11-13", "all_day": True, "reason": "Holiday"},
    ]}
    deadlines = [{"due_at": ts(12, 23, 59), "name": "Assignment 2", "course_name": "Linear Algebra"}]
    out = sheet_week.render(plan, deadlines, d_(2026, 11, 11), 1, tz, owner="Ada <Lovelace> & co")
    book = _xlsx(out)
    assert list(book) == ["2026-11-09"]
    cells = book["2026-11-09"]["cells"]
    assert cells["A1"] == "Ada <Lovelace> & co"
    assert cells["A2"] == "Week of Monday 9 November 2026 to Sunday 15 November 2026"
    assert cells["B4"] == "Monday 9 Nov" and cells["F4"] == "Friday 13 Nov"
    # Deadlines and days off in the row under the day names.
    assert cells["E5"] == "23:59 Due: Assignment 2 (Linear Algebra)" and cells["F5"] == "Holiday"
    # The grid starts at 09:00 (first block), a row per quarter hour.
    assert cells["A6"] == "09:00" and "A7" not in cells and cells["A8"] == "09:30"
    # Back-to-back study of one course is one merged cell listing the work.
    study = cells["B6"]
    assert study.startswith("09:00-09:45 - Linear Algebra - Study")
    assert "- Matrices" in study and long.strip() in study
    merges = book["2026-11-09"]["merges"]
    assert "B6:B8" in merges
    assert cells["C18"] == "12:00-13:00\nLunch" and "C18:C21" in merges  # 12:00 = 6 + 12 rows
    assert cells["D26"].startswith("14:00-15:00 - Linear Algebra - Study") and "D26:D29" in merges
    import zipfile
    from io import BytesIO
    sheet = zipfile.ZipFile(BytesIO(out)).read("xl/worksheets/sheet1.xml").decode()
    assert 'customHeight="1"' in sheet  # the long cell's rows grew so the text isn't cut
    assert 'orientation="landscape"' in sheet


def test_xlsx_writer_names_and_escaping():
    from app import xlsx

    assert xlsx.col_name(1) == "A" and xlsx.col_name(26) == "Z" and xlsx.col_name(27) == "AA"
    assert xlsx.sheet_name("a/b:c*d?[e]") == "a-b-c-d--e-"
    assert len(xlsx.sheet_name("x" * 50)) == 31
    assert xlsx.sheet_name("Week", {"week"}) == "Week (2)"
    book = xlsx.Workbook(title='a "b" <c>')
    ws = book.sheet("2026-11-09")
    ws.set(1, 1, "bad \x00\x07 chars & <tags>")
    ws.set(2, 1, [("bold", True), (" plain", False)], xlsx.Style(fill="#2563eb"))
    assert book.sheet("2026-11-09").name == "2026-11-09 (2)"
    cells = _xlsx(book.render())["2026-11-09"]["cells"]
    assert cells == {"A1": "bad  chars & <tags>", "A2": "bold plain"}



def add_literature(engine, sections=3, notes=True, essay_in=None):
    """Course 13 "Literature 3": each section holds a novel (300 extracted pages), the same
    novel again in a folder, a scan whose 50 pages are only guessed from its size and, with
    ``notes``, an 8-page handout to study."""
    from app.models import Course, Deadline, File, FileText, Module, Section

    with session(engine) as s:
        s.add(Course(id=13, shortname="LIT3", fullname="Literature 3", enrolled=True,
                     folder="LIT3"))
        for n in range(1, sections + 1):
            sid, mid, fid = 1300 + n, 13000 + 10 * n, 1300 + 10 * n
            s.add(Section(id=sid, course_id=13, number=n, name=f"Novel {n}"))
            s.flush()
            files = [("novel.pdf", 3_000_000), ("novel.pdf", 3_000_000), ("scan.pdf", 3_000_000)]
            if notes:
                files.append(("notes.pdf", 40_000))
            for j, (name, size) in enumerate(files):
                s.add(Module(id=mid + j, course_id=13, section_id=sid,
                             modname="folder" if j == 1 else "resource",
                             name=f"Reading {n}.{j}", position=j))
                s.flush()
                s.add(File(id=fid + j, module_id=mid + j, course_id=13, section_id=sid,
                           filename=name, mimetype="application/pdf", filesize=size,
                           timemodified=NOW - 10 * DAY, status="ok"))
            s.flush()
            s.add(FileText(file_id=fid, status="ok", pages=300, chars=10**6))
            s.add(FileText(file_id=fid + 1, status="ok", pages=300, chars=10**6))
            s.add(FileText(file_id=fid + 2, status="too_large"))
            if notes:
                s.add(FileText(file_id=fid + 3, status="ok", pages=8, chars=20_000))
        if essay_in is not None:
            s.add(Module(id=13999, course_id=13, section_id=1300 + min(2, sections),
                         modname="assign", name="Essay", position=9))
            s.flush()
            s.add(Deadline(id=99, source="assign", source_id=99, course_id=13, module_id=13999,
                           name="Essay", kind="due", due_at=NOW + essay_in * DAY, grade=20))
        s.commit()


def test_long_readings_are_not_timed(engine):
    """A novel (once, though it is in a folder too) and a big scan are readings; only the
    handout is timed study."""
    from app.materials import load_course
    from app.planner import section_work

    add_literature(engine, sections=2)
    work = section_work(load_course(engine, 13).section(1301))
    assert [(name, pages) for _, name, pages in work.readings] == [("novel.pdf", 300),
                                                                    ("scan.pdf", 50)]
    assert work.pages == 8 and work.minutes == 25 and not work.reading_only
    with session(engine) as s:  # without the handout, there is nothing to time
        from app.models import Module

        s.get(Module, 13013).removed = True
        s.commit()
    assert section_work(load_course(engine, 13).section(1301)).reading_only


def test_readings_are_day_entries(settings, engine, morning):
    """Readings are day entries at the pace you set, one after the other within a course,
    and take none of the study time."""
    add_literature(engine, sections=3)
    plan = generate(settings, engine, morning, beyond_target=True, reading_pages_per_day=30)
    start = plan.start
    reads = plan.readings
    assert [r["title"] for r in reads] == ["Novel 1", "Novel 2"]  # Novel 3 starts too late
    assert reads[0]["start_date"] == start.isoformat() and reads[0]["days"] == 12
    assert reads[0]["per_day"] == 30 and reads[0]["pages"] == 350
    assert reads[1]["start_date"] == (start + timedelta(days=12)).isoformat()
    assert reads[1]["continues"] and reads[1]["end_date"] == (start + timedelta(days=13)).isoformat()
    assert any("1 reading starts after" in n for n in plan.notes)
    lit = [b for b in plan.blocks if b.item and b.item.course_id == 13 and b.kind == "deep"]
    assert lit and all(b.parts == 1 and b.minutes <= 25 for b in lit)
    assert "planned apart" in lit[0].detail
    assert plan.to_dict()["readings"] == reads
    faster = generate(settings, engine, morning, beyond_target=True, reading_pages_per_day=100)
    assert [r["days"] for r in faster.readings] == [4, 4, 4]


def test_readings_follow_deadlines(settings, engine, morning):
    """A reading needed sooner gets more pages a day; one that can't start in time keeps the
    pace and is flagged late. Sections with nothing but readings get no study block."""
    add_literature(engine, sections=2, notes=False, essay_in=6)
    plan = generate(settings, engine, morning, beyond_target=True, buffer_days=0)
    first, second = plan.readings
    due = local(settings, NOW + 6 * DAY).date()
    assert first["end_date"] == due.isoformat() and first["per_day"] > 30 and not first["late"]
    assert second["late"] and second["per_day"] == 30
    assert not any(b.item and b.item.title == "Novel 1" and b.kind == "deep" for b in plan.blocks)
    assert any(b.item and b.item.title == "Essay" for b in plan.blocks)  # still timed


def test_readings_in_exports(settings, engine, c):
    """The calendar feed has an all-day event per reading (free time), the PDF and Excel
    weeks show it on each of its days."""
    from io import BytesIO

    from pypdf import PdfReader

    add_literature(engine, sections=1)
    c.post("/api/schedule/settings", headers=SAME_ORIGIN, json={"beyond_target": True})
    plan = c.get("/api/schedule").json()
    assert plan["readings"][0]["title"] == "Novel 1"
    feed = c.get("/calendar.ics").text.replace("\r\n ", "")
    assert "SUMMARY:Literature 3 - Read: Novel 1" in feed
    start = plan["readings"][0]["start_date"].replace("-", "")
    assert f"DTSTART;VALUE=DATE:{start}" in feed and "TRANSP:TRANSPARENT" in feed
    first = plan["readings"][0]["start_date"]
    pdf = PdfReader(BytesIO(c.get(f"/api/schedule.pdf?from={first}").content))
    assert "Read: Novel 1" in pdf.pages[0].extract_text()
    book = _xlsx(c.get(f"/api/schedule.xlsx?from={first}").content)
    cells = "\n".join(v for sheet in book.values() for v in sheet["cells"].values())
    assert "Literature 3 - Read: Novel 1 (30 pages)" in cells


def test_one_course_does_not_flood_the_schedule(settings, engine, morning):
    """Literature 3 has far more study than fits before its essay: the essay still comes
    first, but the other courses keep getting time and no item has dozens of parts."""
    from app.models import Deadline, FileText

    add_literature(engine, sections=14, essay_in=6)
    with session(engine) as s:  # long handouts (just under a reading): lots of timed study
        for n in range(1, 15):
            s.get(FileText, 1300 + 10 * n + 3).pages = 40
        for i in range(4):  # Statistics work with no deadline pressure
            s.add(Deadline(id=60 + i, source="assign", source_id=60 + i, course_id=11,
                           name=f"Série {i + 1}", kind="due", due_at=NOW + 40 * DAY, grade=10))
        s.commit()
    with session(engine) as s:  # the essay needs every section
        from app.models import Module

        s.get(Module, 13999).section_id = 1314
        s.commit()
    plan = generate(settings, engine, morning, beyond_target=True, daily_hours=4, buffer_days=0)
    lit = [b for b in plan.blocks if b.item and b.item.course_id == 13]
    others = [b for b in plan.blocks if b.item and b.item.course_id in (10, 11)]
    assert lit and others
    assert max(b.parts for b in plan.blocks) <= 4
    essay = [b for b in lit if b.item.kind == "assign"]
    assert essay and max(b.end for b in essay) <= NOW + 6 * DAY
    # Literature is behind, so it gets the bigger share, but not every block.
    lit_min = sum(b.minutes for b in lit)
    other_min = sum(b.minutes for b in others)
    assert lit_min > other_min and other_min >= 0.15 * (lit_min + other_min)
    week = [d for d in plan.days[:6] if d.blocks]
    assert sum(1 for d in week if any(b.item and b.item.course_id != 13 for b in d.blocks)) >= 3
