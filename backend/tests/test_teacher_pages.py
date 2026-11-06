"""Teacher pages (Moodle page and book activities, exported as index.html): synced, shown
inside the app as sanitised HTML with their images and attachments resolved, named after
the activity, and searchable."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app import accounts
from app.config import Settings
from app.db import session
from app.main import create_app
from app.mcp_tools import StudyTools as Tools
from app.models import File
from app.moodle.sync import SyncService

from .conftest import PASSWORD
from .fake_moodle import BASE, TOKEN, FakeMoodle, load

NOW = 1761500000

PAGE_HTML = """<!DOCTYPE html><html><head><title>x</title>
<style>body{display:none}</style><script>alert('page')</script></head>
<body onload="steal()">
<p style="color:red" class="lead" onclick="evil()">Le <strong>tri rapide</strong> partitionne
<span lang="fr" class="multilang">le tableau</span><span lang="en" class="multilang">the array</span>.</p>
<img src="sch%C3%A9ma%20tri.png" alt="Schéma" width="900" onerror="evil()">
<img src="https://moodle.example.ch/webservice/pluginfile.php/1500/mod_page/content/4/graph.gif">
<img src="https://moodle.example.ch/pluginfile.php/1500/mod_page/content/4/missing.png" alt="Absent">
<img src="data:image/png;base64,AAAA">
<p><a href="exercices.pdf">Exercices</a> · <a href="javascript:evil()">piège</a> ·
<a href="https://moodle.example.ch/mod/book/view.php?id=6102">le manuel</a> ·
<a href="https://fr.wikipedia.org/wiki/Tri_rapide">Wikipédia</a></p>
<iframe src="https://www.youtube.com/embed/abc"></iframe>
<form action="/x"><input name="q"></form>
<table><tr><td colspan="2" style="x">a</td><td rowspan="x">b</td></tr></table>
<!-- teacher comment -->
</body></html>"""

CHAPTER_1 = "<h3>1. Introduction</h3><p>Pourquoi trier ?</p>"
CHAPTER_2 = '<h3>2. Complexité</h3><p>O(n log n)</p><img src="courbe.png" alt="Courbe">'


def add_page_modules(moodle: FakeMoodle) -> None:
    moodle.contents[202][1]["modules"] += load("modules_pages.json")
    moodle.files.update({
        "/webservice/pluginfile.php/1500/mod_page/content/index.html": PAGE_HTML.encode(),
        "/webservice/pluginfile.php/1500/mod_page/content/4/schéma tri.png": b"\x89PNG-img",
        "/webservice/pluginfile.php/1500/mod_page/content/4/exercices.pdf": b"%PDF-exer",
        "/webservice/pluginfile.php/1500/mod_page/content/4/graph.gif": b"GIF89a",
        "/webservice/pluginfile.php/1501/mod_book/chapter/71/index.html": CHAPTER_1.encode(),
        "/webservice/pluginfile.php/1501/mod_book/chapter/72/index.html": CHAPTER_2.encode(),
        "/webservice/pluginfile.php/1501/mod_book/chapter/72/courbe.png": b"\x89PNG",
    })


@pytest.fixture
def settings(tmp_path):
    return Settings(
        app_password=PASSWORD,
        secret_key="s" * 64,
        data_dir=tmp_path,
        cookie_secure=False,
        moodle_url=BASE,
        moodle_token=TOKEN,
        moodle_max_file_mb=1,
    )


@pytest.fixture
def synced(settings):
    """An app whose data dir holds a synced course with a page and a book."""
    moodle = FakeMoodle()
    add_page_modules(moodle)
    app = create_app(settings)
    engine = app.state.engine
    accounts.bootstrap(engine, settings)
    run = asyncio.run(SyncService(settings, engine, moodle.client, clock=lambda: NOW).run("test"))
    assert run.status == "ok", run.message
    with session(engine) as s:
        files = s.exec(select(File).where(File.course_id == 202)).all()
    by_key = {(f.module_id, f.filepath, f.filename): f for f in files}
    return app, by_key


@pytest.fixture
def client(synced):
    app, _ = synced
    with TestClient(app, follow_redirects=False) as c:
        assert c.post("/login", data={"password": PASSWORD}).status_code == 303
        yield c


def test_page_is_sanitised_and_references_resolved(synced, client):
    _, files = synced
    page = files[(6101, "/", "index.html")]
    img = files[(6101, "/", "schéma tri.png")]
    gif = files[(6101, "/", "graph.gif")]
    pdf = files[(6101, "/", "exercices.pdf")]
    book_first = files[(6102, "/71/", "index.html")]

    r = client.get(f"/api/files/{page.id}/page")
    assert r.status_code == 200
    data = r.json()
    html = data["html"]
    assert data["title"] == "Notes du prof: le tri rapide"
    assert data["module"]["modname"] == "page"
    # Nothing that can run or restyle the app.
    for bad in ("<script", "alert(", "<style", "onclick", "onload", "onerror", "style=",
                "class=", "javascript:", "<iframe", "<form", "<input", "data:image",
                "teacher comment", "width="):
        assert bad not in html, bad
    # Multilang resolved to the course language (this course is in English).
    assert "the array" in html and "le tableau" not in html
    # Relative, URL-encoded and absolute pluginfile references point at the synced copies.
    assert f'src="/files/{img.id}/sch%C3%A9ma%20tri.png"' in html
    assert f'src="/files/{gif.id}/graph.gif"' in html
    assert f'href="#/file/{pdf.id}?course=202"' in html
    # A link to another activity opens its page in the app; outside links stay.
    assert f'href="#/file/{book_first.id}?course=202"' in html
    assert 'href="https://fr.wikipedia.org/wiki/Tri_rapide"' in html
    # Unknown Moodle file: alt text instead of a broken (login-only) image.
    assert "[Absent]" in html and "missing.png" not in html
    # The video becomes a link.
    assert 'href="https://www.youtube.com/embed/abc"' in html and "Open embedded" in html
    assert 'colspan="2"' in html and "rowspan" not in html
    # Everything the page uses is inside it, so no separate attachment list.
    assert data["attachments"] == []
    assert data["chapters"] == []


def test_book_chapters_get_titles_and_navigation(synced, client):
    _, files = synced
    ch1 = files[(6102, "/71/", "index.html")]
    ch2 = files[(6102, "/72/", "index.html")]
    curve = files[(6102, "/72/", "courbe.png")]

    data = client.get(f"/api/files/{ch2.id}/page").json()
    assert data["title"] == "2. Complexité"
    assert f'src="/files/{curve.id}/courbe.png"' in data["html"]
    assert data["chapters"] == [
        {"id": ch1.id, "title": "1. Introduction"},
        {"id": ch2.id, "title": "2. Complexité"},
    ]


def test_course_detail_and_file_info_use_readable_titles(synced, client):
    _, files = synced
    page = files[(6101, "/", "index.html")]
    course = client.get("/api/courses/202").json()
    listed = {f["id"]: f for sec in course["sections"] for m in sec["modules"] for f in m["files"]}
    assert listed[page.id]["title"] == "Notes du prof: le tri rapide"
    assert listed[page.id]["page"] is True
    assert listed[files[(6101, "/", "exercices.pdf")].id]["page"] is False
    ch2 = files[(6102, "/72/", "index.html")]
    assert listed[ch2.id]["title"] == "2. Complexité"
    info = client.get(f"/api/files/{ch2.id}").json()
    assert info["title"] == "2. Complexité" and info["page"] is True


def test_page_endpoint_rejects_other_files_and_needs_login(synced, client, settings):
    app, files = synced
    pdf = files[(6101, "/", "exercices.pdf")]
    assert client.get(f"/api/files/{pdf.id}/page").status_code == 404
    assert client.get("/api/files/999999/page").status_code == 404
    with TestClient(app) as anon:
        page = files[(6101, "/", "index.html")]
        assert anon.get(f"/api/files/{page.id}/page").status_code == 401


def test_pages_are_searchable_by_activity_name(synced, settings):
    app, files = synced
    tools = Tools(settings, app.state.engine, base_url="https://study.example.ch",
                  clock=lambda: NOW)
    out = tools.search_materials("partitionne")
    assert "Notes du prof: le tri rapide" in out
    page = files[(6101, "/", "index.html")]
    text = tools.read_file(page.id)
    assert '"Notes du prof: le tri rapide" (teacher page' in text
    assert "tri rapide" in text and "alert" not in text
    materials = tools.get_materials(202)
    assert '"Notes du prof: le tri rapide" (teacher page) file_id' in materials
    assert "Manuel: 2. Complexité" in tools.search_materials("log")


def test_chapter_heading_not_repeated_under_the_title(synced, client):
    _, files = synced
    data = client.get(f"/api/files/{files[(6102, '/72/', 'index.html')].id}/page").json()
    assert "<h3>" not in data["html"] and "O(n log n)" in data["html"]
