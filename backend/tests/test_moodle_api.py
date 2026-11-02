"""One test per Moodle web service function, using recorded JSON fixtures."""

import asyncio

from app.moodle import api

from .fake_moodle import FakeMoodle


def call(moodle, fn, *args):
    async def go():
        async with moodle.client() as c:
            return await fn(c, *args)

    return asyncio.run(go())


def test_core_webservice_get_site_info():
    site = call(FakeMoodle(), api.get_site_info)
    assert site["userid"] == 42
    assert site["lang"] == "fr_ch"
    assert "core_course_get_contents" in site["functions"]


def test_core_webservice_get_site_info_minimal_response():
    moodle = FakeMoodle()
    moodle.responses["core_webservice_get_site_info"] = {"userid": "7"}
    site = call(moodle, api.get_site_info)
    assert site == {"sitename": "", "userid": 7, "fullname": "", "release": "", "lang": "",
                    "siteurl": "", "functions": set()}


def test_core_enrol_get_users_courses():
    moodle = FakeMoodle()
    courses = call(moodle, api.get_user_courses, 42)
    assert [c["id"] for c in courses] == [101, 202, 303]  # front page (id 1) dropped
    math, cs, his = courses
    assert math["lang"] == "fr" and math["progress"] == 25.5
    assert cs["lang"] == "" and cs["enddate"] is None  # 0 means no date
    assert his["lang"] == "" and his["visible"] is True and his["startdate"] is None
    assert moodle.calls[0][1]["userid"] == "42"


def test_core_course_get_contents():
    sections = call(FakeMoodle(), api.get_course_contents, 101)
    assert [s["number"] for s in sections] == [0, 1]
    folder = sections[1]["modules"][0]
    assert folder["modname"] == "folder"
    assert [f["filename"] for f in folder["files"]] == ["cours1.pptx", "../../../etc/passwd", "vidéo.mp4"]
    url_mod = sections[1]["modules"][1]
    assert url_mod["url"] == "https://example.org/article" and url_mod["files"] == []
    assign = sections[1]["modules"][2]
    assert assign["files"] == [] and "Exercices" in assign["description"]


def test_core_course_get_contents_tolerates_missing_fields():
    moodle = FakeMoodle()
    moodle.contents[999] = [{"id": 1, "modules": [{"id": 2, "contents": [{"type": "file"}]}]},
                            {"name": "no id"}]
    sections = call(moodle, api.get_course_contents, 999)
    assert len(sections) == 1
    assert sections[0]["modules"][0]["files"] == []
    assert sections[0]["modules"][0]["modname"] == ""


def test_mod_assign_get_assignments():
    moodle = FakeMoodle()
    items = call(moodle, api.get_assignments, [101, 202])
    assert items == [{
        "id": 81, "course_id": 101, "cmid": 5004, "name": "Devoir 1", "duedate": 1762000000,
        "cutoffdate": None, "opendate": 1756684800, "grade": 20.0,
        "intro": "<p>Exercices 1 à 5.</p>",
    }]
    params = moodle.calls[0][1]
    assert params["courseids[0]"] == "101" and params["courseids[1]"] == "202"


def test_mod_quiz_get_quizzes_by_courses():
    items = call(FakeMoodle(), api.get_quizzes, [202])
    assert items[0]["cmid"] == 6004 and items[0]["timeclose"] == 1761600000


def test_core_calendar_get_action_events_by_timesort():
    moodle = FakeMoodle()
    events = call(moodle, api.get_action_events, 1000, 2000)
    assert [e["id"] for e in events] == [9001, 9002]
    assert events[1]["course_id"] == 303 and events[1]["name"] == "Ensayo final"
    assert moodle.calls[0][1]["timesortfrom"] == "1000"


def test_action_events_paginate_with_aftereventid(monkeypatch):
    monkeypatch.setattr(api, "ACTION_EVENTS_PAGE", 2)
    moodle = FakeMoodle()
    pages = [
        {"events": [{"id": 1, "timesort": 5}, {"id": 2, "timesort": 6}], "lastid": 2},
        {"events": [{"id": 3, "timesort": 7}], "lastid": 3},
    ]
    original = moodle.handler

    def handler(request):
        response = original(request)
        if moodle.calls and moodle.calls[-1][0] == "core_calendar_get_action_events_by_timesort":
            import httpx
            return httpx.Response(200, json=pages[len(
                [c for c in moodle.calls if c[0].startswith("core_calendar")]) - 1])
        return response

    moodle.handler = handler
    events = call(moodle, api.get_action_events, 0, 10)
    assert [e["id"] for e in events] == [1, 2, 3]
    assert moodle.calls[1][1]["aftereventid"] == "2"


def test_core_completion_get_activities_completion_status():
    status = call(FakeMoodle(), api.get_completion, 101, 42)
    assert status[5001] == {"state": 1, "timecompleted": 1757000000}
    assert status[5004] == {"state": 0, "timecompleted": None}
