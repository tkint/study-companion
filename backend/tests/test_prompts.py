"""Prompt builder: templates, rendering, splitting and the JSON API."""

import re

import pytest
from fastapi.testclient import TestClient

from app import prompts
from app.db import make_engine
from app.extract.index import extract_files
from app.main import create_app
from app.mcp_tools import TOOL_NAMES

from .conftest import PASSWORD
from .m3_seed import seed

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
CALL = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\(")


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.data_dir)
    seed(engine, settings.data_dir)
    extract_files(engine, settings.data_dir)
    return engine


@pytest.fixture
def builder(settings, engine):
    return prompts.Builder(settings, engine)


def build(builder, **data):
    return builder.build(prompts.Request.from_json({"course_ids": [10], "goal": "catch_up", **data}))


def test_templates_load_and_reference_real_tools():
    templates = prompts.load_templates()
    assert list(templates)[:3] == ["catch_up", "study_plan", "explain"]
    assert len(templates) == 7
    for t in templates.values():
        assert t.title and t.description
        assert "{{steps}}" in t.body
        for name in CALL.findall(t.body):
            assert name in TOOL_NAMES, f"{t.id} mentions unknown tool {name}"
        leftover = prompts.render(t.body, {k: "x" for k in (
            "courses", "period", "steps", "language", "depth", "time", "topic", "part", "today",
            "deadlines", "completion")})
        assert "{{" not in leftover, t.id


def test_render_sections():
    body = "A{{#time}} for {{time}}{{/time}}.{{^topic}} No topic.{{/topic}}\n\n\n\nEnd {{missing}}"
    assert prompts.render(body, {"time": "2 hours"}) == "A for 2 hours. No topic.\n\nEnd\n"
    assert prompts.render(body, {"topic": "x"}) == "A.\n\nEnd\n"


def test_build_catch_up(builder):
    out = build(builder, **{"from": "2001-01-01", "hours_per_day": 2, "days": 7})
    assert out["summary"]["prompts"] == 1
    text = out["prompts"][0]["text"]
    assert text.startswith('You are my tutor for "Linear Algebra" (course_id 10).')
    assert 'get_materials(course_id=10, from_date="2001-01-01")' in text
    assert "get_deadlines(course_id=10" in text
    assert "2 hours per day for 7 days" in text
    assert "in French" in text  # course language
    for name in CALL.findall(text):
        assert name in TOOL_NAMES
    assert out["courses"][0]["pages"] == 7 and out["courses"][0]["readable_files"] == 4


def test_build_options(builder):
    text = build(builder, include_deadlines=False, include_completion=False, language="en",
                 depth="deep", hours_total=5)["prompts"][0]["text"]
    assert "get_deadlines" not in text and "✓ done" not in text
    assert "in English" in text and "Go in depth" in text and "5 hours in total" in text


def test_section_range_and_topic(builder):
    out = build(builder, goal="explain", topic='valeurs "propres"', section_from=3, section_to=3)
    text = out["prompts"][0]["text"]
    assert "section_from=3, section_to=3" in text
    assert "search_materials(query=\"valeurs 'propres'\", course_id=10)" in text
    assert out["summary"]["sections"] == 1
    with pytest.raises(prompts.PromptError, match="topic"):
        build(builder, goal="explain")


def test_large_periods_are_split(builder, monkeypatch):
    monkeypatch.setattr(prompts, "MAX_SECTIONS_PER_PROMPT", 2)
    out = build(builder)
    assert out["summary"]["prompts"] == 2
    first, second = (p["text"] for p in out["prompts"])
    assert "This is part 1 of 2" in first and "section_from=1, section_to=2" in first
    assert "section_from=3, section_to=3" in second
    assert out["prompts"][1]["title"].startswith("Part 2 of 2")


def test_multiple_courses(builder):
    out = builder.build(prompts.Request.from_json(
        {"course_ids": [10, 11], "goal": "study_plan", "language": "course"}))
    text = out["prompts"][0]["text"]
    assert "get_materials(course_id=11)" in text
    assert "language of each course" in text


@pytest.mark.parametrize("data,message", [
    ({"course_ids": []}, "course"),
    ({"course_ids": [10], "goal": "nope"}, "goal"),
    ({"course_ids": [10], "goal": "catch_up", "from": "2026-10-01", "to": "2026-09-01"}, "before"),
    ({"course_ids": [10], "goal": "catch_up", "depth": "extreme"}, "depth"),
    ({"course_ids": [10], "goal": "catch_up", "hours_per_day": 30}, "range"),
    ({"course_ids": [999], "goal": "catch_up"}, "unknown course"),
])
def test_bad_requests(builder, data, message):
    with pytest.raises(prompts.PromptError, match=message):
        builder.build(prompts.Request.from_json(data))


def test_api(settings, engine):
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/prompt/options").status_code == 401
        c.post("/login", data={"password": PASSWORD})
        options = c.get("/api/prompt/options").json()
        assert [x["id"] for x in options["courses"]] == [10, 11]
        assert options["courses"][0]["sections"][0] == {"id": 101, "number": 1, "name": "Vecteurs"}
        assert options["courses"][0]["next_deadline"] is not None
        assert options["goals"][0]["id"] == "catch_up"
        body = {"course_ids": [10], "goal": "quiz"}
        assert c.post("/api/prompt/build", json=body,
                      headers={"Sec-Fetch-Site": "cross-site"}).status_code == 401
        r = c.post("/api/prompt/build", json=body, headers=SAME_ORIGIN)
        assert r.status_code == 200 and "Quiz me" in r.json()["prompts"][0]["title"]
        r = c.post("/api/prompt/build", json={"course_ids": [10]}, headers=SAME_ORIGIN)
        assert r.status_code == 400 and r.json()["error"] == "choose a goal"
