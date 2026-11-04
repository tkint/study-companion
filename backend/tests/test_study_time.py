"""M5 study-time tracking: entries, daily totals, streak, the API and the MCP tool."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import study, study_time
from app.db import make_engine
from app.main import create_app
from app.mcp_tools import StudyTools, ToolInputError

from .conftest import PASSWORD
from .m3_seed import seed

TZ = ZoneInfo("Europe/Zurich")
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
CROSS_SITE = {"Sec-Fetch-Site": "cross-site"}
# Wednesday 2026-11-04, 18:00 in Zurich
NOW = int(datetime(2026, 11, 4, 18, 0, tzinfo=TZ).timestamp())
HOUR = 3600
DAY = 86400


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.data_dir)
    seed(engine, settings.data_dir)
    return engine


def test_log_time_validates(engine):
    row = study_time.log_time(engine, 25, 10, now=NOW)
    assert row.minutes == 25 and row.started_at == NOW - 25 * 60 and row.source == "manual"
    assert study_time.log_time(engine, 24.6, now=NOW).minutes == 25
    for bad, match in [(0, "between"), (721, "between"), ("10", "number"), (True, "number")]:
        with pytest.raises(study_time.TimeError, match=match):
            study_time.log_time(engine, bad, now=NOW)
    with pytest.raises(study_time.TimeError, match="no course"):
        study_time.log_time(engine, 10, 999, now=NOW)
    with pytest.raises(study_time.TimeError, match="future"):
        study_time.log_time(engine, 10, started_at=NOW + DAY, now=NOW)
    with pytest.raises(study_time.TimeError, match="year"):
        study_time.log_time(engine, 10, started_at=NOW - 400 * DAY, now=NOW)
    with pytest.raises(study_time.TimeError, match="source"):
        study_time.log_time(engine, 10, source="x", now=NOW)
    with pytest.raises(study_time.TimeError, match="too long"):
        study_time.log_time(engine, 10, note="x" * 201, now=NOW)
    assert study_time.delete_time(engine, row.id) and not study_time.delete_time(engine, row.id)


def test_summary_totals_streak_and_courses(engine):
    study.set_hours_per_day(engine, 1.5)
    # today 30 + 20 (one for course 10), yesterday 40, 2 days ago 15, gap, 5 days ago 60
    study_time.log_time(engine, 30, 10, started_at=NOW - HOUR, now=NOW)
    study_time.log_time(engine, 20, started_at=NOW - 2 * HOUR, now=NOW)
    study_time.log_time(engine, 40, 10, started_at=NOW - DAY, now=NOW)
    study_time.log_time(engine, 15, started_at=NOW - 2 * DAY, now=NOW)
    study_time.log_time(engine, 60, started_at=NOW - 5 * DAY, now=NOW)
    s = study_time.time_summary(engine, TZ, now=NOW)
    assert s["today"] == "2026-11-04" and s["today_minutes"] == 50
    assert s["streak_days"] == 3
    # week starts Monday 2026-11-02: today, yesterday and Monday
    assert s["week_minutes"] == 50 + 40 + 15
    assert s["last7_minutes"] == 165 and s["total_minutes"] == 165
    assert s["goal_minutes_per_day"] == 90
    assert s["best_day"] == {"date": "2026-10-30", "minutes": 60}
    assert len(s["days"]) == 14 and s["days"][-1] == {"date": "2026-11-04", "minutes": 50}
    assert [(r["course_id"], r["minutes"]) for r in s["courses"]] == [(None, 95), (10, 70)]
    assert [r["minutes"] for r in s["recent"]] == [30, 20, 40, 15, 60]


def test_streak_counts_from_yesterday_until_today_has_study(engine):
    assert study_time.time_summary(engine, TZ, now=NOW)["streak_days"] == 0
    study_time.log_time(engine, 10, started_at=NOW - DAY, now=NOW)
    study_time.log_time(engine, 10, started_at=NOW - 2 * DAY, now=NOW)
    assert study_time.time_summary(engine, TZ, now=NOW)["streak_days"] == 2
    study_time.log_time(engine, 10, now=NOW)
    assert study_time.time_summary(engine, TZ, now=NOW)["streak_days"] == 3


def test_days_follow_the_time_zone(engine):
    # 23:30 in Zurich on Nov 3 is 22:30 UTC: it belongs to Nov 3, not Nov 4
    late = int(datetime(2026, 11, 3, 23, 30, tzinfo=TZ).timestamp())
    study_time.log_time(engine, 20, started_at=late, now=NOW)
    s = study_time.time_summary(engine, TZ, now=NOW)
    assert s["today_minutes"] == 0 and s["days"][-2] == {"date": "2026-11-03", "minutes": 20}


def test_log_study_time_tool(settings, engine):
    tools = StudyTools(settings, engine, "https://study.example.ch", clock=lambda: NOW)
    out = tools.log_study_time(45, 10, "matrices")
    assert "Logged 45 min of study for course 10" in out and "Today: 45 min" in out
    assert "#/time" in out
    with pytest.raises(ToolInputError, match="between"):
        tools.log_study_time(0)


@pytest.fixture
def c(settings, engine):
    with TestClient(create_app(settings), follow_redirects=False) as client:
        client.post("/login", data={"password": PASSWORD})
        yield client


def test_api_study_time(settings, engine, c):
    with TestClient(create_app(settings), follow_redirects=False) as anon:
        assert anon.get("/api/study/time").status_code == 401
    assert c.post("/api/study/time", json={"minutes": 25}, headers=CROSS_SITE).status_code == 401
    r = c.post("/api/study/time", json={"minutes": 25, "course_id": 10, "source": "timer",
                                        "note": "pomodoro"}, headers=SAME_ORIGIN)
    assert r.status_code == 201
    data = r.json()
    assert data["summary"]["today_minutes"] == 25
    assert data["summary"]["recent"][0]["source"] == "timer"
    assert c.post("/api/study/time", json={"minutes": 25, "source": "claude"},
                  headers=SAME_ORIGIN).json()["summary"]["recent"][0]["source"] == "manual"
    assert c.post("/api/study/time", json={"minutes": -1}, headers=SAME_ORIGIN).status_code == 400
    assert c.post("/api/study/time", content=b"[]", headers=SAME_ORIGIN).status_code == 400
    assert c.get("/api/study/time").json()["today_minutes"] == 50
    eid = data["entry"]["id"]
    assert c.delete(f"/api/study/time/{eid}", headers=SAME_ORIGIN).status_code == 200
    assert c.delete(f"/api/study/time/{eid}", headers=SAME_ORIGIN).status_code == 404
