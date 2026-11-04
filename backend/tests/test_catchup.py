"""Realistic catch-up: mandatory vs optional, ignored items, the catch-up target."""

import pytest
from fastapi.testclient import TestClient

from app import catchup, prompts
from app.api import ui
from app.db import make_engine, session
from app.extract.index import extract_files, index_structure
from app.main import create_app
from app.mcp_tools import StudyTools
from app.models import Deadline
from app.planner import Planner

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
def tools(settings, engine):
    return StudyTools(settings, engine, "https://study.example.ch", clock=lambda: NOW)


@pytest.mark.parametrize("source,name,grade,modname,mandatory", [
    ("assign", "Devoir 1", 20, "", True),
    ("assign", "Devoir 2", None, "", True),  # unknown grade: mandatory, to be safe
    ("assign", "Exercice facultatif 3", 10, "", False),
    ("assign", "Bonus: série 4", 5, "", False),
    ("assign", "Übung (fakultativ)", 5, "", False),
    ("quiz", "Practice quiz", 10, "", False),
    ("quiz", "Quiz d'entraînement", 10, "", False),
    ("quiz", "Self-test chapter 2", 10, "", False),
    ("quiz", "Quiz 2", 0, "", False),  # graded out of 0
    ("assign", "Scale-graded report", -1, "", True),  # negative: graded with a scale
    ("event", "Feedback on the course", None, "feedback", False),
    ("event", "Workshop submission", None, "workshop", True),
    ("assign", "Optimisation project", 20, "", True),  # "optim..." is not "optional"
])
def test_auto_mandatory(source, name, grade, modname, mandatory):
    assert catchup.auto_mandatory(source, name, grade, modname)[0] is mandatory


def test_prefs_override_and_ignore(engine):
    d = {r["id"]: r for r in ui.deadlines(engine, now=NOW)}
    assert d[1]["mandatory"] and d[1]["criticality_by"] == "auto" and not d[1]["ignored"]

    catchup.set_pref(engine, "deadline", 1, criticality="optional")
    catchup.set_pref(engine, "deadline", 2, ignored=True)
    d = {r["id"]: r for r in ui.deadlines(engine, now=NOW)}
    assert d[1]["criticality"] == "optional" and d[1]["criticality_by"] == "you"
    assert d[2]["ignored"]
    assert [r["id"] for r in ui.deadlines(engine, now=NOW, include_ignored=False)] == [1]

    # Back to automatic and un-ignored: the row goes away.
    catchup.set_pref(engine, "deadline", 1, criticality=None)
    catchup.set_pref(engine, "deadline", 2, ignored=False)
    assert catchup.prefs(engine, "deadline") == {}
    assert catchup.set_pref(engine, "deadline", 999, ignored=True) is None
    with pytest.raises(catchup.PrefError):
        catchup.set_pref(engine, "deadline", 1, criticality="maybe")
    with pytest.raises(catchup.PrefError):
        catchup.set_pref(engine, "course", 1, ignored=True)


def test_dashboard_leaves_out_ignored(engine):
    assert [d["name"] for d in ui.dashboard(engine, now=NOW)["overdue"]] == ["Quiz 1"]
    catchup.set_pref(engine, "deadline", 2, ignored=True)
    dash = ui.dashboard(engine, now=NOW)
    assert dash["overdue"] == []
    stats = next(c for c in dash["courses"] if c["id"] == 11)
    assert stats["overdue"] == 0


def test_target_setting(engine):
    assert catchup.target_percent(engine) == 60
    assert catchup.set_target_percent(engine, 50) == 50
    assert catchup.target_percent(engine) == 50
    for bad in (5, 120, True, "60"):
        with pytest.raises(catchup.PrefError):
            catchup.set_target_percent(engine, bad)


def test_progress_and_plan_trimmed_to_target(settings, engine):
    planner = Planner(settings, engine, now=NOW)
    prog = planner.progress()
    # Sections Vecteurs (done in Moodle), Matrices, Eigen + the overdue Quiz 1.
    assert (prog.done_items, prog.total_items) == (1, 4)
    assert prog.done_minutes == 15 and prog.total_minutes == 90
    assert prog.percent == pytest.approx(16.7) and not prog.reached

    plan = planner.plan(hours=1, days=5)
    titles = [s.item.title for _, slots in plan.days for s in slots]
    # Matrices is needed for the upcoming Devoir 1; Quiz 1 covers the rest of the 60%.
    assert titles[:2] == ["Quiz 1", "Matrices"] and "Devoir 1" in titles
    assert "Eigen" not in titles and [i.title for i in plan.beyond_target] == ["Eigen"]
    assert plan.projected_percent >= 60
    data = plan.to_dict()
    assert data["target_percent"] == 60 and data["beyond_target_minutes"] == 15
    assert all("mandatory" in i and "catch_up" in i for d in data["days"] for i in d["items"])
    assert any("beyond your 60% catch-up target" in n for n in plan.notes)

    catchup.set_target_percent(engine, 100)
    assert not Planner(settings, engine, now=NOW).plan(hours=1, days=5).beyond_target


def test_plan_leaves_out_optional_and_ignored(settings, engine):
    catchup.set_pref(engine, "deadline", 1, criticality="optional")  # Devoir 1
    catchup.set_pref(engine, "section", 103, ignored=True)  # Eigen
    plan = Planner(settings, engine, now=NOW).plan(hours=1, days=5, beyond_target=True)
    titles = [s.item.title for _, slots in plan.days for s in slots]
    assert "Devoir 1" not in titles and "Eigen" not in titles
    assert plan.optional_left_out == 1 and plan.ignored == 1
    assert any("optional item(s) left out" in n for n in plan.notes)
    # Matrices is no longer needed by an upcoming mandatory deadline: it is backlog now.
    matrices = next(s.item for _, slots in plan.days for s in slots if s.item.title == "Matrices")
    assert matrices.catch_up and matrices.needed_by is None
    # Ignored work leaves the target too: Vecteurs, Matrices, Quiz 1.
    assert plan.progress.total_items == 3

    with_optional = Planner(settings, engine, now=NOW).plan(hours=1, days=5, include_optional=True,
                                                            beyond_target=True)
    assert any(s.item.title == "Devoir 1" and not s.item.mandatory
               for _, slots in with_optional.days for s in slots)

    catchup.set_pref(engine, "section", 102, criticality="optional")
    plan = Planner(settings, engine, now=NOW).plan(hours=1, days=5, beyond_target=True)
    assert all(s.item.title != "Matrices" for _, slots in plan.days for s in slots)


def test_closed_deadlines_leave_the_target(settings, engine):
    with session(engine) as s:
        quiz = s.get(Deadline, 2)
        quiz.cutoff_at = NOW - DAY
        s.add(quiz)
        s.commit()
    assert Planner(settings, engine, now=NOW).progress().total_items == 3


def test_mcp_tools_focus_on_mandatory(tools, engine):
    catchup.set_pref(engine, "deadline", 1, criticality="optional")
    out = tools.get_deadlines()
    assert "Devoir 1" in out and "· optional" in out and "1 are optional" in out
    assert "Devoir 1" not in tools.get_deadlines(mandatory_only=True)
    catchup.set_pref(engine, "deadline", 2, ignored=True)
    past = tools.get_deadlines(from_date="2000-01-01")
    assert "Quiz 1" not in past
    assert "ignored by the student" in tools.get_deadlines(from_date="2000-01-01",
                                                           include_ignored=True)

    catchup.set_pref(engine, "section", 103, ignored=True)
    assert "IGNORED by the student" in tools.get_materials(10)
    assert "(optional)" in tools.get_section(102)

    plan = tools.get_catch_up_plan(hours_per_day=1, days=5)
    assert "mandatory work only" in plan and "Target: catch up 60%" in plan
    assert "Devoir 1" not in plan
    assert "Devoir 1" in tools.get_catch_up_plan(hours_per_day=1, days=5, include_optional=True)


def test_mcp_plan_lists_beyond_target(tools):
    out = tools.get_catch_up_plan(hours_per_day=1, days=5)
    assert "Beyond the target" in out and "Eigen (section_id 103)" in out
    assert "Beyond the target" not in tools.get_catch_up_plan(hours_per_day=1, days=5,
                                                              beyond_target=True)


def test_prompts_mention_target(settings, engine):
    catchup.set_target_percent(engine, 55)
    builder = prompts.Builder(settings, engine, now=NOW)
    out = builder.build(prompts.Request.from_json({"course_ids": [10], "goal": "catch_up"}))
    text = out["prompts"][0]["text"]
    assert "about 55% of the mandatory work" in text and "get_catch_up_plan(course_id=10" in text
    plan = builder.build(prompts.Request.from_json({"course_ids": [10], "goal": "study_plan"}))
    assert "about 55% of the backlog" in plan["prompts"][0]["text"]


@pytest.fixture
def c(settings, engine):
    client = TestClient(create_app(settings), follow_redirects=False)
    client.post("/login", data={"password": PASSWORD})
    return client


def test_api(c):
    assert c.post("/api/deadlines/2/prefs", json={"ignored": True},
                  headers=SAME_ORIGIN).json() == {"id": 2, "ignored": True, "criticality": None}
    assert c.post("/api/deadlines/1/prefs", json={"criticality": "optional"},
                  headers=SAME_ORIGIN).json()["criticality"] == "optional"
    assert c.post("/api/deadlines/1/prefs", json={"criticality": "nope"},
                  headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/deadlines/1/prefs", json={}, headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/deadlines/999/prefs", json={"ignored": True},
                  headers=SAME_ORIGIN).status_code == 404
    assert c.post("/api/deadlines/1/prefs", json={"ignored": True},
                  headers={"Sec-Fetch-Site": "cross-site"}).status_code == 401
    assert c.post("/api/sections/103/prefs", json={"ignored": True},
                  headers=SAME_ORIGIN).json()["ignored"] is True

    course = c.get("/api/courses/10").json()
    eigen = next(s for s in course["sections"] if s["id"] == 103)
    assert eigen["ignored"] and eigen["mandatory"]
    devoir = next(d for d in course["deadlines"] if d["id"] == 1)
    assert devoir["criticality"] == "optional" and devoir["criticality_by"] == "you"

    dash = c.get("/api/dashboard").json()
    assert dash["overdue"] == []  # Quiz 1 ignored
    assert dash["catch_up"]["target_percent"] == 60 and "percent" in dash["catch_up"]
    assert dash["plan"]["optional_left_out"] == 1

    assert c.post("/api/plan/settings", json={"target_percent": 50},
                  headers=SAME_ORIGIN).json() == {"target_percent": 50}
    assert c.post("/api/plan/settings", json={"target_percent": 500},
                  headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/plan/settings", json={}, headers=SAME_ORIGIN).status_code == 400
    plan = c.get("/api/plan").json()
    assert plan["target_percent"] == 50 and plan["progress"]["target_percent"] == 50
    assert c.get("/api/plan?optional=1").json()["optional_left_out"] == 0
