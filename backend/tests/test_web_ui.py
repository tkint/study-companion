"""Web UI API: dashboard, course detail, deadlines, files, ICS feed and the SPA shell."""

import logging
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api import ics
from app.db import session
from app.main import RedactTokens, create_app
from app.models import Course, Deadline, File, Module, Section

from .conftest import PASSWORD

NOW = int(time.time())
DAY = 86400
# What a browser sends for fetch() from the page itself behind Caddy (Referrer-Policy
# same-origin): Sec-Fetch-Site decides.
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin", "Origin": "https://study.example.ch",
               "Host": "study.example.ch"}
CROSS_SITE = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}


def seed(engine, data_dir):
    with session(engine) as s:
        s.add(Course(id=10, shortname="LA", fullname="Linear Algebra", enrolled=True,
                     folder="LA"))
        s.add(Course(id=11, shortname="OLD", fullname="Old course", enrolled=False))
        s.add(Section(id=100, course_id=10, number=0, name="General"))
        s.add(Section(id=101, course_id=10, number=1, name="Week 1", summary="Vectors"))
        s.flush()
        s.add(Module(id=1000, course_id=10, section_id=101, modname="resource", name="Slides",
                     completion_state=1))
        s.add(Module(id=1001, course_id=10, section_id=101, modname="assign", name="HW 1",
                     completion_state=0))
        s.add(Module(id=1002, course_id=10, section_id=101, modname="assign", name="HW 0",
                     completion_state=1))
        s.add(Module(id=1003, course_id=10, section_id=101, modname="page", name="Gone",
                     removed=True))
        s.flush()
        s.add(File(id=1, module_id=1000, course_id=10, section_id=101, filename="slides.pdf",
                   mimetype="application/pdf", filesize=8, status="ok",
                   local_path="courses/LA/01 Week 1/slides.pdf"))
        s.add(File(id=2, module_id=1000, course_id=10, section_id=101, filename="page.html",
                   mimetype="text/html", filesize=10, status="ok",
                   local_path="courses/LA/01 Week 1/page.html"))
        s.add(File(id=3, module_id=1000, course_id=10, section_id=101, filename="video.mp4",
                   mimetype="video/mp4", status="skipped_size"))
        s.add(File(id=4, module_id=1000, course_id=10, section_id=101, filename="evil.pdf",
                   mimetype="application/pdf", status="ok", local_path="../../etc/passwd"))
        deadlines = [
            # overdue, not done
            Deadline(id=1, source="assign", source_id=1, course_id=10, module_id=1001,
                     name="HW 1", kind="due", due_at=NOW - 3 * DAY, url="https://m/assign/1"),
            # past, done in Moodle -> not overdue
            Deadline(id=2, source="assign", source_id=2, course_id=10, module_id=1002,
                     name="HW 0", kind="due", due_at=NOW - 10 * DAY),
            # this week
            Deadline(id=3, source="quiz", source_id=3, course_id=10, name="Quiz, part 1; A\\B",
                     kind="close", due_at=NOW + 2 * DAY),
            # later
            Deadline(id=4, source="event", source_id=4, course_id=None, name="Exam",
                     kind="action", due_at=NOW + 30 * DAY),
            # too old to be overdue
            Deadline(id=5, source="assign", source_id=5, course_id=10, name="Ancient",
                     due_at=NOW - 400 * DAY),
            # not enrolled anymore
            Deadline(id=6, source="assign", source_id=6, course_id=11, name="Old HW",
                     due_at=NOW - DAY),
            # removed in Moodle
            Deadline(id=7, source="assign", source_id=7, course_id=10, name="Removed",
                     due_at=NOW + DAY, removed=True),
            # no due date
            Deadline(id=8, source="assign", source_id=8, course_id=10, name="Open", due_at=None),
        ]
        for d in deadlines:
            s.add(d)
        s.commit()
    folder = data_dir / "courses" / "LA" / "01 Week 1"
    folder.mkdir(parents=True)
    (folder / "slides.pdf").write_bytes(b"%PDF-1.4")
    (folder / "page.html").write_text("<script>alert(1)</script>")


@pytest.fixture
def app(settings):
    app = create_app(settings)
    seed(app.state.engine, settings.data_dir)
    return app


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


def login(client):
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303


@pytest.mark.parametrize(
    "path",
    ["/api/dashboard", "/api/courses/10", "/api/deadlines?from=0&to=1", "/files/1",
     "/api/calendar/feed"],
)
def test_requires_login(client, path):
    assert client.get(path).status_code == 401


def test_dashboard_groups_deadlines(client):
    login(client)
    data = client.get("/api/dashboard").json()
    assert [d["id"] for d in data["overdue"]] == [1]
    assert [d["id"] for d in data["this_week"]] == [3]
    assert [d["id"] for d in data["later"]] == [4]
    assert data["overdue"][0]["course_name"] == "Linear Algebra"
    assert data["overdue"][0]["url"] == "https://m/assign/1"
    assert data["sync"]["configured"] is False
    (course,) = data["courses"]
    assert course["id"] == 10
    assert course["overdue"] == 1 and course["upcoming"] == 1
    # 2 of 3 tracked activities are complete (the removed one doesn't count)
    assert course["activities_done"] == 2 and course["activities_tracked"] == 3
    assert course["progress"] == pytest.approx(66.7)


def test_mark_done_moves_item_off_overdue(client):
    login(client)
    r = client.post("/api/deadlines/1/done", json={"done": True}, headers=SAME_ORIGIN)
    assert r.status_code == 200
    data = client.get("/api/dashboard").json()
    assert data["overdue"] == []
    assert data["courses"][0]["overdue"] == 0
    r = client.post("/api/deadlines/1/done", json={"done": False}, headers=SAME_ORIGIN)
    assert [d["id"] for d in client.get("/api/dashboard").json()["overdue"]] == [1]


def test_mark_done_rejects_cross_site_and_bad_input(client):
    login(client)
    assert client.post("/api/deadlines/1/done", json={"done": True},
                       headers=CROSS_SITE).status_code == 401
    assert client.post("/api/deadlines/1/done", json={"done": "yes"},
                       headers=SAME_ORIGIN).status_code == 400
    assert client.post("/api/deadlines/1/done", content=b"nope",
                       headers=SAME_ORIGIN).status_code == 400
    assert client.post("/api/deadlines/999/done", json={"done": True},
                       headers=SAME_ORIGIN).status_code == 404


def test_done_in_moodle_is_reported(client):
    login(client)
    items = client.get(f"/api/deadlines?from={NOW - 20 * DAY}&to={NOW}").json()["deadlines"]
    hw0 = next(d for d in items if d["id"] == 2)
    assert hw0["done"] is True and hw0["done_by"] == "moodle"
    assert {d["id"] for d in items} == {1, 2}  # not enrolled / removed are left out


def test_deadlines_range_is_validated(client):
    login(client)
    assert client.get("/api/deadlines").status_code == 400
    assert client.get("/api/deadlines?from=10&to=5").status_code == 400
    assert client.get(f"/api/deadlines?from=0&to={500 * DAY}").status_code == 400


def test_course_detail(client):
    login(client)
    data = client.get("/api/courses/10").json()
    assert [s["name"] for s in data["sections"]] == ["General", "Week 1"]
    week1 = data["sections"][1]
    assert [m["name"] for m in week1["modules"]] == ["Slides", "HW 1", "HW 0"]
    files = {f["id"]: f for f in week1["modules"][0]["files"]}
    assert files[1]["available"] is True
    assert files[3]["available"] is False and files[3]["status"] == "skipped_size"
    assert {d["id"] for d in data["deadlines"]} == {1, 2, 3, 5}  # whole history
    assert client.get("/api/courses/999").status_code == 404


def test_pdf_is_served_inline(client):
    login(client)
    r = client.get("/files/1")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert "sandbox" in r.headers["content-security-policy"]
    r = client.get("/files/1/slides.pdf?download=1")
    assert r.headers["content-disposition"].startswith("attachment")


def test_html_is_never_rendered_inline(client):
    login(client)
    r = client.get("/files/2")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")


def test_missing_and_unsafe_files_are_404(client):
    login(client)
    assert client.get("/files/3").status_code == 404  # never downloaded
    assert client.get("/files/4").status_code == 404  # path escapes DATA_DIR
    assert client.get("/files/999").status_code == 404


def test_ics_feed(app, client):
    assert client.get("/calendar.ics").status_code == 404
    assert client.get("/calendar.ics?token=wrong").status_code == 404
    login(client)
    feed = client.get("/api/calendar/feed").json()
    assert feed["webcal"].startswith("webcal://")
    token = feed["url"].split("token=")[1]
    with TestClient(app) as anonymous:  # a calendar app: no cookie
        r = anonymous.get(f"/calendar.ics?token={token}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert body.count("BEGIN:VEVENT") == 4  # ids 1, 2, 3, 4
    assert "SUMMARY:LA: Quiz\\, part 1\\; A\\\\B" in body
    assert "SUMMARY:✓ LA: HW 0" in body
    assert "UID:assign-1@study-companion" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))


def test_ics_new_link_revokes_old(app, client):
    login(client)
    old = client.get("/api/calendar/feed").json()["url"].split("token=")[1]
    assert client.post("/api/calendar/feed", headers=CROSS_SITE).status_code == 401
    new = client.post("/api/calendar/feed", headers=SAME_ORIGIN).json()["url"].split("token=")[1]
    assert new != old
    with TestClient(app) as anonymous:
        assert anonymous.get(f"/calendar.ics?token={old}").status_code == 404
        assert anonymous.get(f"/calendar.ics?token={new}").status_code == 200


def test_ics_folds_long_lines():
    item = {"id": 1, "source": "assign", "name": "é" * 100, "due_at": NOW,
            "course_shortname": "", "course_name": "", "url": "", "done": False}
    body = ics.build_ics([item], now=NOW)
    lines = body.split("\r\n")
    assert all(len(line.encode()) <= 75 for line in lines)
    unfolded = body.replace("\r\n ", "").split("\r\n")
    assert "SUMMARY:" + "é" * 100 in unfolded


def test_access_log_redacts_feed_token():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", "/calendar.ics?token=abc123", "1.1", 200), None,
    )
    RedactTokens().filter(record)
    assert "abc123" not in record.getMessage()
    assert "token=***" in record.getMessage()


def test_static_cache_headers_and_spa_shell(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "index-abc.js").write_text("console.log(1)")
    (dist / "manifest.webmanifest").write_text("{}")
    (dist / "sw.js").write_text("")
    app = create_app(replace(settings, frontend_dir=dist))
    with TestClient(app, follow_redirects=False) as c:
        assert c.get("/").headers["location"] == "/login"  # the shell needs a session
        assert c.get("/manifest.webmanifest").status_code == 200  # fetched without cookies
        assert c.get("/sw.js").headers["cache-control"] == "no-cache"
        r = c.get("/assets/index-abc.js")
        assert "immutable" in r.headers["cache-control"]
        login(c)
        assert "id=root" in c.get("/").text
        assert "Study Companion" in c.get("/status").text
        assert c.get("/api/dashboard").headers["cache-control"] == "no-store"
