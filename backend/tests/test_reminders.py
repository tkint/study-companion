"""M5 reminders: settings, deadline alarms and daily study events in the ICS feed, the
in-app "today" read model and its API."""

import pytest
from fastapi.testclient import TestClient

from app import reminders, study, study_time
from app.api import ics
from app.db import make_engine
from app.extract.index import extract_files, index_structure
from app.main import create_app

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


def test_prefs_defaults_and_validation(engine):
    assert reminders.prefs(engine) == {"deadline_alarms": [1440, 120], "daily_enabled": True,
                                       "daily_time": "18:00"}
    out = reminders.set_prefs(engine, {"deadline_alarms": [60, 2880, 60], "daily_time": "07:30"})
    assert out["deadline_alarms"] == [2880, 60] and out["daily_time"] == "07:30"
    assert reminders.prefs(engine) == out
    assert reminders.set_prefs(engine, {"deadline_alarms": []})["deadline_alarms"] == []
    for bad in [{"deadline_alarms": [0]}, {"deadline_alarms": [1, 2, 3, 4]},
                {"deadline_alarms": "60"}, {"deadline_alarms": [True]},
                {"daily_time": "25:00"}, {"daily_time": 18}, {"daily_enabled": "yes"}]:
        with pytest.raises(reminders.ReminderError):
            reminders.set_prefs(engine, bad)


def test_lead_times_in_ics():
    assert ics._lead(1440) == "-P1D" and ics._lead(120) == "-PT2H"
    assert ics._lead(1530) == "-P1DT1H30M" and ics._lead(15) == "-PT15M"
    item = {"id": 1, "source": "assign", "name": "HW", "due_at": NOW + DAY}
    body = ics.build_ics([item], now=NOW, alarms=[1440, 120])
    assert body.count("BEGIN:VALARM") == 2 and "TRIGGER:-PT2H" in body
    done = ics.build_ics([{**item, "done": True}], now=NOW, alarms=[1440, 120])
    assert "VALARM" not in done
    assert "VALARM" not in ics.build_ics([item], now=NOW, alarms=[])


def test_daily_sessions_follow_the_plan(settings, engine):
    sessions = reminders.daily_sessions(engine, settings, NOW)
    assert sessions and len(sessions) <= reminders.DAILY_DAYS
    first = sessions[0]
    assert first["minutes"] > 0 and first["items"]
    assert first["start"] >= NOW - DAY
    body = ics.build_ics([], now=NOW, sessions=sessions)
    assert f"UID:study-{first['date']}@study-companion" in body
    assert "SUMMARY:Study time:" in body and "TRIGGER:PT0M" in body
    reminders.set_prefs(engine, {"daily_enabled": False})
    assert reminders.daily_sessions(engine, settings, NOW) == []


def test_daily_session_counts_due_cards_today(settings, engine):
    study.save_questions(engine, 102, [{"question": "q", "answer": "a"}], now=NOW)
    sessions = reminders.daily_sessions(engine, settings, NOW)
    assert sessions[0]["cards_due"] == 1
    assert all(s["cards_due"] == 0 for s in sessions[1:])
    body = ics.build_ics([], now=NOW, sessions=sessions[:1])
    assert "1 card to review" in body


def test_today_read_model(settings, engine):
    study_time.log_time(engine, 30, now=NOW)
    t = reminders.today(engine, settings, now=NOW)
    assert t["studied_minutes"] == 30 and t["goal_minutes"] == 120
    assert t["planned_minutes"] > 0 and t["cards_due"] == 0
    # Devoir 1 is due in 3 days: not "soon"; move the clock a day before it
    later = reminders.today(engine, settings, now=NOW + 2 * DAY)
    assert [d["name"] for d in later["deadlines_soon"]] == ["Devoir 1"]


def test_reminders_api(settings, engine):
    with TestClient(create_app(settings), follow_redirects=False) as c:
        assert c.get("/api/reminders").status_code == 401
        c.post("/login", data={"password": PASSWORD})
        assert c.get("/api/reminders").json()["prefs"]["daily_time"] == "18:00"
        url = "/api/reminders/settings"
        assert c.post(url, json={"daily_time": "08:00"}, headers=CROSS_SITE).status_code == 401
        assert c.post(url, json={"daily_time": "8h"}, headers=SAME_ORIGIN).status_code == 400
        assert c.post(url, content=b"[]", headers=SAME_ORIGIN).status_code == 400
        r = c.post(url, json={"daily_time": "08:00", "deadline_alarms": [180]}, headers=SAME_ORIGIN)
        assert r.status_code == 200 and r.json()["daily_time"] == "08:00"
        body = c.get("/calendar.ics").text
        assert "TRIGGER:-PT3H" in body and "TRIGGER:-P1D" not in body


def test_optional_deadlines_have_no_alarm():
    item = {"id": 1, "source": "assign", "name": "HW", "due_at": NOW + DAY, "mandatory": False}
    assert "VALARM" not in ics.build_ics([item], now=NOW, alarms=[1440])
