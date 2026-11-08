"""The shared study plan (``app.planner.tasks``): course-level sessions, each day's tasks
(grouped by course, priority, deadlines, effort), ticking them, and one session per course
a day in the scheduler."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.extract.index import extract_files, index_structure
from app.main import create_app
from app.planner import published, tasks
from app.planner.schedule import Generator, Work

from .conftest import PASSWORD
from .m3_seed import NOW, seed

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.data_dir)
    seed(engine, settings.data_dir)
    extract_files(engine, settings.data_dir)
    index_structure(engine)
    return engine


def _plan(tz):
    def ts(day, h, m=0):
        return int(datetime(2026, 11, day, h, m, tzinfo=tz).timestamp())

    def b(day, h, m, minutes, kind, title, cid=1, **kw):
        course = {1: ("A3FPH12", "2026/2027-A3FPH12 Phonologie de l'Anglais 3"),
                  2: ("STAT", "Statistics")}[cid] if cid else ("", "")
        return {"date": f"2026-11-{day:02d}", "start": ts(day, h, m),
                "end": ts(day, h, m) + minutes * 60, "minutes": minutes, "kind": kind,
                "title": title, "part": kw.pop("part", 1), "parts": kw.pop("parts", 1),
                "course_id": cid, "course_short": course[0], "course_name": course[1],
                "item_kind": kw.pop("item_kind", "section"), **kw}

    blocks9 = [
        b(9, 9, 0, 15, "flashcards", "Flashcard review", cid=None, item_kind=None),
        b(9, 9, 15, 50, "deep", "Workbook", section_id=11, section_number=1, part=1, parts=3,
          needed_by=ts(20, 23, 59), needed_for="Exam"),
        b(9, 10, 5, 50, "deep", "Workbook", section_id=11, section_number=1, part=2, parts=3,
          needed_by=ts(20, 23, 59), needed_for="Exam"),
        b(9, 10, 55, 30, "practice", "Exercise 1", item_kind="assign", deadline_id=5,
          needed_by=ts(12, 12)),
        b(9, 11, 25, 45, "deep", "Probability", cid=2, section_id=21, section_number=3),
    ]
    blocks10 = [b(10, 9, 0, 15, "recall", "Vowels", section_id=12, part=1, parts=2)]
    return {"days": [{"date": "2026-11-09", "blocks": blocks9},
                     {"date": "2026-11-10", "blocks": blocks10},
                     {"date": "2026-11-12", "blocks": []}],
            "readings": [{"start_date": "2026-11-10", "end_date": "2026-11-11", "title": "Novel",
                          "course_id": 2, "course_short": "STAT", "course_name": "Statistics",
                          "section_id": 22, "per_day": 30, "late": False}]}


def test_sessions_and_tasks(settings):
    tz = settings.tz
    view = tasks.build(_plan(tz), tz, {"section-11": True})
    sessions = view["sessions"]
    # Course-level sessions: the assignment is part of its course's session.
    assert [(s["label"], s["minutes"]) for s in sessions] == [
        ("Flashcards", 15), ("A3FPH12 – Phonologie de l'Anglais 3", 130),
        ("STAT – Statistics", 45), ("A3FPH12 – Phonologie de l'Anglais 3", 15)]
    assert sessions[1]["task_keys"] == ["section-11", "deadline-5"]
    assert sessions[1]["objective"] == "Section 1: Workbook + 1 more"
    assert sessions[1]["course_code"] == "A3FPH12"
    days = {d["date"]: d for d in view["plan_days"]}
    assert list(days) == ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
    nine = days["2026-11-09"]
    # Grouped by course in session order; within a course by priority (the hand-in first).
    assert [t["key"] for t in nine["tasks"]] == [
        "flashcards-2026-11-09", "deadline-5", "section-11", "section-21"]
    assert [c["course_label"] for c in nine["courses"]] == [
        "Flashcards", "A3FPH12 – Phonologie de l'Anglais 3", "STAT – Statistics"]
    work = {t["key"]: t for t in nine["tasks"]}
    # The two parts of the workbook that day are one task, with their effort added up.
    assert work["section-11"]["minutes"] == 100 and work["section-11"]["part"] == "parts 1-2/3"
    assert work["section-11"]["done"] and not work["deadline-5"]["done"] and nine["open"] == 3
    assert work["deadline-5"]["priority"] == "medium"  # a hand-in, due in 3 days
    assert work["section-11"]["priority"] == "low" and work["section-21"]["priority"] == "low"
    assert work["section-11"]["session_id"] == sessions[1]["id"]
    # Tasks without a time slot: a reading on each of its days, a hand-in on its due day.
    ten = {t["key"]: t for t in days["2026-11-10"]["tasks"]}
    assert ten["reading-22"]["session_id"] is None and ten["reading-22"]["pages"] == 30
    assert ten["recall-12-1"]["title"] == "Review: Vowels"
    assert "reading-22" in {t["key"] for t in days["2026-11-11"]["tasks"]}
    due = days["2026-11-12"]["tasks"]
    assert [(t["key"], t["session_id"], t["title"]) for t in due] == [
        ("deadline-5", None, "Due: Exercise 1")]
    assert due[0]["priority"] == "high"  # due that day


def test_priority_rules():
    day = 1_000_000
    assert tasks.priority(None, True, day, "study") == "high"  # late
    assert tasks.priority(day - 1, False, day, "study") == "high"  # overdue
    assert tasks.priority(day + 5 * 86400, False, day, "study") == "medium"
    assert tasks.priority(None, False, day, "quiz") == "medium"
    assert tasks.priority(day + 30 * 86400, False, day, "study") == "low"


def test_tick_tasks_keeps_the_calendar(settings, engine):
    c = TestClient(create_app(settings), follow_redirects=False)
    c.post("/login", data={"password": PASSWORD})
    before = c.get("/api/schedule").json()
    assert before["sessions"] and before["plan_days"]
    keys = [t["key"] for d in before["plan_days"] for t in d["tasks"]]
    section = next(k for k in keys if k.startswith("section-"))
    deadline = next(k for k in keys if k.startswith("deadline-"))
    for key in (section, deadline, "recall-102-1", "flashcards-2026-11-09"):
        res = c.post("/api/plan/tasks", json={"key": key, "done": True}, headers=SAME_ORIGIN)
        assert res.status_code == 200 and res.json() == {"key": key, "done": True}
    after = c.get("/api/schedule").json()
    # Ticking never moves a session.
    assert [(s["id"], s["start"], s["end"]) for s in after["sessions"]] == [
        (s["id"], s["start"], s["end"]) for s in before["sessions"]]
    done = {t["key"] for d in after["plan_days"] for t in d["tasks"] if t["done"]}
    assert {section, deadline} <= done
    assert c.get("/api/plan").json()  # the section is marked studied in the catch-up plan too
    c.post("/api/plan/tasks", json={"key": section, "done": False}, headers=SAME_ORIGIN)
    again = c.get("/api/schedule").json()
    assert section not in {t["key"] for d in again["plan_days"] for t in d["tasks"] if t["done"]}
    for bad in ({"key": "../x", "done": True}, {"key": section, "done": "yes"}, {"key": 5}):
        assert c.post("/api/plan/tasks", json=bad, headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/plan/tasks", json={"key": "section-999999", "done": True},
                  headers=SAME_ORIGIN).status_code == 404
    assert c.post("/api/plan/tasks", json={"key": section, "done": True},
                  headers={"Sec-Fetch-Site": "cross-site"}).status_code == 401
    anon = TestClient(create_app(settings))
    assert anon.post("/api/plan/tasks", json={"key": section, "done": True},
                     headers=SAME_ORIGIN).status_code == 401


def test_preview_and_published_share_the_model(settings, engine):
    pub = published.publish(settings, engine, now=NOW)
    pre = published.preview(settings, engine, {}, now=NOW)
    assert [s["id"] for s in pub["sessions"]] == [s["id"] for s in pre["sessions"]]
    assert [d["date"] for d in pub["plan_days"]] == [d["date"] for d in pre["plan_days"]]


def test_a_course_left_today_comes_after_the_others(settings, engine):
    from app.planner import PlanItem

    gen = Generator(settings, engine, now=NOW)
    plan = gen.generate()

    def work(cid, title):
        return Work(PlanItem("section", cid, f"C{cid}", f"C{cid}", title, 120), 120, None)

    a, b = work(1, "A"), work(2, "B")
    # Equal time so far: without the rule the first course would win the tie.
    pick, _ = gen._pick([a, b], {1: 1.0, 2: 1.0}, {1: 60, 2: 60}, 3, 0, 0, plan.days or [None],
                        0, left_today={1})
    assert pick is b
    pick, _ = gen._pick([a, b], {1: 1.0, 2: 1.0}, {1: 60, 2: 60}, 3, 0, 0, plan.days or [None],
                        0, left_today=set())
    assert pick is a


def test_sessions_per_course_a_day(settings, engine):
    local = datetime.fromtimestamp(NOW, settings.tz).replace(hour=7, minute=0, second=0)
    plan = Generator(settings, engine, now=int(local.timestamp())).generate().to_dict()
    view = tasks.build(plan, settings.tz)
    seen = [(s["date"], s["course_id"]) for s in view["sessions"]]
    assert len(seen) == len(set(seen))
    # Every scheduled block belongs to exactly one session, and each session has tasks.
    blocks = [b for d in plan["days"] for b in d["blocks"]]
    assert sum(len(s["blocks"]) for s in view["sessions"]) == len(blocks)
    assert all(s["task_keys"] for s in view["sessions"])
