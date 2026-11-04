"""M4 study loop: notes, questions, spaced repetition, quiz results, catch-up plan, API."""

import pytest
from fastapi.testclient import TestClient

from app import study
from app.db import make_engine
from app.extract.index import extract_files, index_structure
from app.main import create_app
from app.mcp_tools import StudyTools, ToolInputError
from app.models import StudyQuestion
from app.planner import Planner, section_minutes
from app.materials import load_course

from .conftest import PASSWORD
from .m3_seed import DAY, NOW, seed

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
CROSS_SITE = {"Sec-Fetch-Site": "cross-site"}


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.data_dir)
    seed(engine, settings.data_dir)
    extract_files(engine, settings.data_dir)
    index_structure(engine)
    return engine


@pytest.fixture
def tools(settings, engine):
    return StudyTools(settings, engine, "https://study.example.ch")


# ---------------------------------------------------------------- notes and questions


def test_save_summary_replaces_the_previous_one(engine):
    note, replaced = study.save_summary(engine, 102, "# One", now=NOW)
    assert not replaced and note.course_id == 10 and note.title == "Matrices"
    again, replaced = study.save_summary(engine, 102, "# Two", title="Matrices, part 2", now=NOW + 5)
    assert replaced and again.id == note.id and again.markdown == "# Two"
    assert again.created_at == NOW and again.updated_at == NOW + 5
    assert len(study.course_study(engine, 10)["notes"]) == 1
    with pytest.raises(study.StudyError, match="no section"):
        study.save_summary(engine, 999, "x")
    with pytest.raises(study.StudyError, match="empty"):
        study.save_summary(engine, 102, "   ")
    with pytest.raises(study.StudyError, match="too long"):
        study.save_summary(engine, 102, "x" * (study.MAX_MARKDOWN + 1))


def test_save_questions_validates_and_deduplicates(engine):
    saved = study.save_questions(engine, 102, [
        {"question": "What is an inverse?", "answer": "A^-1 with AA^-1 = I"},
        {"front": "det(I)?", "back": "1", "kind": "flashcard"},
        {"question": "Pick one", "answer": "b", "choices": ["a", "b", "c"]},
    ], now=NOW)
    assert len(saved.created) == 3 and not saved.updated
    assert [q.kind for q in saved.created] == ["short", "flashcard", "mcq"]
    # The same question (case and spacing ignored) updates in place and keeps its history.
    study.review(engine, saved.created[0].id, 2, now=NOW)
    again = study.save_questions(engine, 102, [
        {"question": "what is  an INVERSE?", "answer": "better answer"},
        {"question": "New one", "answer": "x"},
        {"question": "New one", "answer": "y"},  # duplicate inside one call
    ], now=NOW)
    assert len(again.created) == 1 and len(again.updated) == 1
    assert again.updated[0].id == saved.created[0].id and again.updated[0].reps == 1
    assert again.updated[0].answer == "better answer"
    assert again.created[0].answer == "y"

    for bad, msg in [
        ([], "non-empty"),
        (["plain text"], "not plain text"),
        ([{"question": "q"}], "answer is empty"),
        ([{"question": "q", "answer": "a", "kind": "essay"}], "kind must be"),
        ([{"question": "q", "answer": "a", "kind": "mcq"}], "needs choices"),
        ([{"question": "q", "answer": "a", "choices": ["only one"]}], "2 to 8"),
        ([{"question": "q", "answer": "a"}] * 51, "at most 50"),
    ]:
        with pytest.raises(study.StudyError, match=msg):
            study.save_questions(engine, 102, bad)


def test_spaced_repetition_schedule():
    q = StudyQuestion(course_id=1, question="q", answer="a")
    study.schedule(q, 2, NOW)
    assert q.reps == 1 and q.interval == 1 and q.due_at == NOW + DAY
    study.schedule(q, 2, NOW)
    assert q.interval == 3
    study.schedule(q, 2, NOW)
    assert q.interval == pytest.approx(7.5)
    study.schedule(q, 3, NOW)
    assert q.interval > 7.5 * 2.5 and q.ease == pytest.approx(2.65)
    study.schedule(q, 0, NOW)
    assert q.reps == 0 and q.lapses == 1 and q.due_at == NOW + study.AGAIN_DELAY
    assert q.ease == pytest.approx(2.45)
    study.schedule(q, 1, NOW)
    assert q.interval == 1 and q.ease == pytest.approx(2.3)
    with pytest.raises(study.StudyError):
        study.schedule(q, 7, NOW)
    for _ in range(40):
        study.schedule(q, 3, NOW)
    assert q.interval == study.MAX_INTERVAL


def test_due_questions_come_first(engine):
    saved = study.save_questions(engine, 102, [
        {"question": f"q{i}", "answer": "a"} for i in range(3)], now=NOW)
    a, b, c = saved.created
    study.review(engine, a.id, 3, now=NOW)  # due in 4 days
    study.review(engine, b.id, 0, now=NOW - 3600)  # failed an hour ago: due again
    due = study.questions(engine, course_id=10, due_only=True, now=NOW)
    assert [q.id for q in due] == [b.id, c.id]  # reviewed-and-due before new
    assert len(study.questions(engine, section_id=102, now=NOW)) == 3


def test_record_result_updates_the_schedule(engine):
    saved = study.save_questions(engine, 103, [
        {"question": "q1", "answer": "a"}, {"question": "q2", "answer": "a"}], now=NOW)
    q1, q2 = saved.created
    result, reviewed = study.record_result(
        engine, 1, 2, section_id=103, topic="Eigen", notes="Review the spectral theorem",
        items=[{"question_id": q1.id, "correct": True}, {"question_id": q2.id, "correct": False}],
        now=NOW)
    assert reviewed == 2 and result.course_id == 10 and result.source == "claude"
    cards = {q.id: q for q in study.questions(engine, section_id=103, now=NOW)}
    assert cards[q1.id].reps == 1 and cards[q2.id].lapses == 1
    assert study.course_study(engine, 10, now=NOW)["results"][0]["percent"] == 50

    for kwargs, msg in [
        ({"score": 3, "total": 2, "course_id": 10}, "between 0 and total"),
        ({"score": "x", "total": 2, "course_id": 10}, "numbers"),
        ({"score": 1, "total": 2}, "course_id or section_id"),
        ({"score": 1, "total": 2, "course_id": 999}, "no course"),
        ({"score": 1, "total": 2, "course_id": 11, "section_id": 103}, "belongs to course 10"),
        ({"score": 1, "total": 2, "course_id": 10, "items": [{"question_id": 12345, "correct": True}]},
         "unknown question"),
        ({"score": 1, "total": 2, "course_id": 10, "items": [{"question_id": q1.id}]}, "must look like"),
    ]:
        with pytest.raises(study.StudyError, match=msg):
            study.record_result(engine, **kwargs)


def test_overview(engine):
    study.save_summary(engine, 102, "# Notes")
    study.save_questions(engine, 102, [{"question": "q", "answer": "a"}])
    study.record_result(engine, 3, 4, course_id=10)
    data = study.overview(engine)
    assert data["due"] == 1 and data["questions"] == 1
    assert data["courses"][0]["notes"] == 1 and data["recent_results"][0]["course_name"] == "Linear Algebra"


# ---------------------------------------------------------------- catch-up plan


def test_section_minutes(engine):
    cm = load_course(engine, 10)
    eigen = cm.section(103)
    minutes, pages = section_minutes(eigen)
    assert pages == 3  # 2 slides + 1 HTML part; the video counts for nothing
    assert minutes == 15  # the minimum


def test_plan_orders_by_deadline_and_skips_studied(settings, engine):
    planner = Planner(settings, engine, now=NOW)
    plan = planner.plan(hours=1, days=5, beyond_target=True)
    kinds = [(s.item.kind, s.item.title) for _, slots in plan.days for s in slots]
    # The overdue quiz first, then the section the assignment needs, then the assignment;
    # Vecteurs is complete in Moodle, Eigen has no deadline so it comes last.
    assert kinds[0] == ("quiz", "Quiz 1")
    assert kinds.index(("section", "Matrices")) < kinds.index(("assign", "Devoir 1"))
    assert kinds[-1] == ("section", "Eigen")
    assert ("section", "Vecteurs") not in kinds
    assert plan.sections_left == 2 and plan.sections_done == 1
    # The 2 h assignment is split over two 1 h days.
    devoir = [s for _, slots in plan.days for s in slots if s.item.title == "Devoir 1"]
    assert [(s.part, s.parts, s.minutes) for s in devoir] == [(1, 2, 60), (2, 2, 60)]
    assert all(sum(s.minutes for s in slots) <= 60 for _, slots in plan.days)

    study.set_studied(engine, 103, True)
    after = Planner(settings, engine, now=NOW).plan(hours=1, days=5)
    assert all(s.item.title != "Eigen" for _, slots in after.days for s in slots)
    assert after.sections_done == 2
    study.set_studied(engine, 103, False)
    assert Planner(settings, engine, now=NOW).plan().sections_left == 2


def test_plan_flags_late_and_unscheduled(settings, engine):
    plan = Planner(settings, engine, now=NOW).plan(hours=0.25, days=2)
    data = plan.to_dict()
    assert data["unscheduled"] and data["unscheduled_minutes"] > 0
    only_la = Planner(settings, engine, now=NOW).plan(course_id=10, hours=0.25, days=30)
    assert only_la.late  # Devoir 1 (due in 3 days) only finishes after a week at 15 min/day
    assert any("after the deadline" in n for n in only_la.notes)
    assert all(s.item.course_id == 10 for _, slots in only_la.days for s in slots)


def test_hours_per_day_setting(engine):
    assert study.hours_per_day(engine) == 2.0
    assert study.set_hours_per_day(engine, 3.5) == 3.5
    assert study.hours_per_day(engine) == 3.5
    with pytest.raises(study.StudyError):
        study.set_hours_per_day(engine, 30)


# ---------------------------------------------------------------- MCP tools (text)


def test_mcp_write_tools(tools, engine):
    out = tools.save_summary(102, "# Matrices\n- inverse")
    assert "Saved a summary of section 102" in out and "#/course/10?section=102" in out
    assert "Replaced the summary" in tools.save_summary(102, "# Matrices v2")
    out = tools.save_questions(102, [{"question": "det(I)?", "answer": "1", "source": "td.docx p. 1"}])
    assert "saved 1 new question(s)" in out and "#/study?section=102" in out
    qid = int(out.split("question_id: ")[1].split(".")[0])

    listed = tools.get_questions(course_id=10)
    assert f"question_id {qid}" in listed and "Q: det(I)?" in listed and "1 due" in listed
    assert "Source: td.docx p. 1" in listed
    out = tools.record_quiz_result(1, 1, section_id=102, topic="det",
                                   items=[{"question_id": qid, "correct": True}])
    assert "Recorded 1/1 (100%)" in out and "1 saved question(s)" in out
    assert "0 due" in tools.get_questions(section_id=102)
    assert "Saved in the app: summary" in tools.get_section(102)
    assert "1 question(s)" in tools.get_materials(10)

    with pytest.raises(ToolInputError, match="no section"):
        tools.save_summary(999, "x")
    with pytest.raises(ToolInputError, match="answer is empty"):
        tools.save_questions(102, [{"question": "q"}])
    with pytest.raises(ToolInputError, match="course_id or section_id"):
        tools.get_questions()
    with pytest.raises(ToolInputError):
        tools.record_quiz_result(5, 2, course_id=10)


def test_mcp_catch_up_plan(tools):
    out = tools.get_catch_up_plan(hours_per_day=1, days=5)
    assert "Catch-up plan from" in out and "at 1 h/day" in out
    assert 'Quiz "Quiz 1"' in out and "OVERDUE since" in out
    assert 'study section 2 "Matrices"' in out and 'for "Devoir 1"' in out
    assert '"td.docx" file_id 2' in out and "(part 1/2)" in out
    assert "2 section(s) left, 1 done" in out
    with pytest.raises(ToolInputError):
        tools.get_catch_up_plan(days=0)
    with pytest.raises(ToolInputError):
        tools.get_catch_up_plan(course_id=999)


def test_trigger_sync(settings, engine):
    class Fake:
        def __init__(self, configured, starts):
            self._c, self._s, self.calls = configured, starts, 0

        def configured(self):
            return self._c

        def start(self):
            self.calls += 1
            return self._s

    assert "not connected" in StudyTools(settings, engine).trigger_sync()
    assert "not connected" in StudyTools(settings, engine, sync=Fake(False, True)).trigger_sync()
    fake = Fake(True, True)
    assert "Started a sync" in StudyTools(settings, engine, sync=fake).trigger_sync()
    assert fake.calls == 1
    assert "already running" in StudyTools(settings, engine, sync=Fake(True, False)).trigger_sync()


# ---------------------------------------------------------------- JSON API


@pytest.fixture
def c(settings, engine):
    with TestClient(create_app(settings), follow_redirects=False) as client:
        client.post("/login", data={"password": PASSWORD})
        yield client


def test_api_requires_login(settings, engine):
    with TestClient(create_app(settings), follow_redirects=False) as anon:
        assert anon.get("/api/study").status_code == 401
        assert anon.get("/api/plan").status_code == 401
        assert anon.get("/api/courses/10/study").status_code == 401
        assert anon.post("/api/sections/102/studied", json={"studied": True},
                         headers=SAME_ORIGIN).status_code == 401


def test_api_study_flow(c, engine):
    study.save_summary(engine, 102, "# Notes")
    saved = study.save_questions(engine, 102, [{"question": "q1", "answer": "a"},
                                               {"question": "q2", "answer": "b"}])
    data = c.get("/api/study?section=102").json()
    assert len(data["questions"]) == 2 and data["overview"]["due"] == 2
    qid = data["questions"][0]["id"]

    assert c.post(f"/api/study/questions/{qid}/review", json={"grade": 2},
                  headers=CROSS_SITE).status_code == 401
    r = c.post(f"/api/study/questions/{qid}/review", json={"grade": 2}, headers=SAME_ORIGIN)
    assert r.status_code == 200 and r.json()["due"] is False and r.json()["reps"] == 1
    assert c.post(f"/api/study/questions/{qid}/review", json={"grade": 9},
                  headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/study/questions/9999/review", json={"grade": 1},
                  headers=SAME_ORIGIN).status_code == 404
    assert len(c.get("/api/study?section=102").json()["questions"]) == 1
    assert len(c.get("/api/study?section=102&all=1").json()["questions"]) == 2

    r = c.post("/api/study/results", json={"course_id": 10, "section_id": 102, "score": 1,
                                           "total": 2, "topic": "Flashcards"}, headers=SAME_ORIGIN)
    assert r.status_code == 201 and r.json()["source"] == "web"
    assert c.post("/api/study/results", json={"course_id": 10, "score": 3, "total": 2},
                  headers=SAME_ORIGIN).status_code == 400

    page = c.get("/api/courses/10/study").json()
    assert page["questions"]["102"] == {"questions": 2, "due": 1}
    assert page["results"][0]["topic"] == "Flashcards"
    assert c.get("/api/courses/999/study").status_code == 404

    assert c.delete(f"/api/study/notes/{page['notes'][0]['id']}", headers=SAME_ORIGIN).status_code == 200
    assert c.delete(f"/api/study/questions/{saved.created[1].id}", headers=SAME_ORIGIN).status_code == 200
    assert c.delete(f"/api/study/results/{page['results'][0]['id']}", headers=SAME_ORIGIN).status_code == 200
    assert c.delete("/api/study/notes/9999", headers=SAME_ORIGIN).status_code == 404
    page = c.get("/api/courses/10/study").json()
    assert not page["notes"] and page["questions_total"] == 1 and not page["results"]


def test_api_plan_and_sections(c):
    plan = c.get("/api/plan?days=5").json()
    assert plan["sections_left"] == 2 and plan["days"][0]["items"][0]["title"] == "Quiz 1"
    assert c.post("/api/sections/103/studied", json={"studied": True}, headers=SAME_ORIGIN).json() == {
        "id": 103, "studied": True}
    assert c.post("/api/sections/9999/studied", json={"studied": True},
                  headers=SAME_ORIGIN).status_code == 404
    assert c.post("/api/sections/103/studied", json={"studied": "yes"},
                  headers=SAME_ORIGIN).status_code == 400
    assert c.get("/api/plan").json()["sections_left"] == 1
    assert 103 in c.get("/api/courses/10/study").json()["studied"]

    assert c.post("/api/plan/settings", json={"hours_per_day": 3}, headers=SAME_ORIGIN).json() == {
        "hours_per_day": 3.0}
    assert c.post("/api/plan/settings", json={"hours_per_day": 0}, headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/plan/settings", json={"hours_per_day": True}, headers=SAME_ORIGIN).status_code == 400
    assert c.get("/api/plan").json()["hours_per_day"] == 3.0

    dash = c.get("/api/dashboard").json()
    assert dash["plan"]["hours_per_day"] == 3.0 and dash["plan"]["today"]["items"]
    assert dash["study"]["due"] == 0
