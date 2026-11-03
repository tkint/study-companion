import asyncio
import logging

import pytest
from sqlmodel import select

from app import accounts
from app.config import Settings
from app.db import make_engine, session, snapshot
from app.models import Course, Deadline, File, Module, Section, Site
from app.moodle.sync import SyncAlreadyRunning, SyncService

from .fake_moodle import BASE, TOKEN, FakeMoodle

NOW = 1761500000  # 2025-10-26, between the quiz opening and the assignment due date


@pytest.fixture
def settings(tmp_path):
    return Settings(
        app_password="correct horse battery staple",
        secret_key="s" * 64,
        data_dir=tmp_path,
        moodle_url=BASE,
        moodle_token=TOKEN,
        moodle_max_file_mb=1,
    )


@pytest.fixture
def moodle():
    return FakeMoodle()


def make_service(settings, factory):
    engine = make_engine(settings.data_dir)
    accounts.bootstrap(engine, settings)  # imports MOODLE_URL/MOODLE_TOKEN into the DB
    return SyncService(settings, engine, factory, clock=lambda: NOW)


@pytest.fixture
def service(settings, moodle):
    return make_service(settings, moodle.client)


def sync(service, trigger="test"):
    return asyncio.run(service.run(trigger))


def rows(service, model):
    with session(service.engine) as s:
        return s.exec(select(model)).all()


def files_by_name(service):
    return {f.filename: f for f in rows(service, File)}


def test_full_sync_stores_courses_sections_modules(service, settings):
    run = sync(service)
    assert run.status == "ok", run.message
    assert run.courses == 3

    site = rows(service, Site)[0]
    assert site.userid == 42 and site.lang == "fr" and site.sitename == "Université Exemple Moodle"

    courses = {c.id: c for c in rows(service, Course)}
    assert set(courses) == {101, 202, 303}
    assert courses[101].fullname == "Algèbre linéaire"
    assert courses[202].folder == "CS 202_Algorithms"
    assert courses[303].fullname == "Latin American History"  # multilang, before lang known

    sections = {s.id: s for s in rows(service, Section)}
    assert sections[2001].name == "General"
    assert sections[1002].folder == "01 Semaine 1 _ Vecteurs _ matrices"

    modules = {m.id: m for m in rows(service, Module)}
    assert modules[5001].completion_state == 1
    assert modules[5003].url == "https://example.org/article"
    assert modules[5004].description == "Exercices 1 à 5."


def test_course_language_forced_detected_or_site(service):
    sync(service)
    courses = {c.id: c for c in rows(service, Course)}
    assert (courses[101].lang, courses[101].lang_source) == ("fr", "course")
    assert (courses[202].lang, courses[202].lang_source) == ("en", "detected")
    assert (courses[303].lang, courses[303].lang_source) == ("es", "detected")
    # Second sync knows the language, so multilang names resolve to Spanish.
    sync(service)
    courses = {c.id: c for c in rows(service, Course)}
    assert courses[303].fullname == "Historia de América Latina"


def test_language_falls_back_to_site(service, moodle):
    for sec in moodle.contents[202]:
        sec["summary"] = ""
        sec["name"] = ""
        for m in sec["modules"]:
            m["name"] = "X"
    moodle.responses["core_enrol_get_users_courses"][1]["summary"] = ""
    moodle.responses["core_enrol_get_users_courses"][1]["fullname"] = "CS"
    sync(service)
    course = [c for c in rows(service, Course) if c.id == 202][0]
    assert (course.lang, course.lang_source) == ("fr", "site")


def test_files_downloaded_to_safe_paths(service, settings, moodle):
    run = sync(service)
    files = files_by_name(service)
    base = settings.data_dir / "courses"

    plan = files["plan_du_cours.pdf"]
    assert plan.status == "ok"
    assert plan.local_path == "courses/MATH-101/00 Généralités/plan_du_cours.pdf"
    assert (settings.data_dir / plan.local_path).read_bytes() == b"%PDF-plan-1"
    assert TOKEN not in plan.fileurl

    evil = files["../../../etc/passwd"]
    assert evil.status == "ok"
    assert evil.local_path == "courses/MATH-101/01 Semaine 1 _ Vecteurs _ matrices/Diapositives/_.._.._etc_passwd"
    for path in settings.data_dir.rglob("*"):
        assert settings.data_dir in path.resolve().parents

    assert files["vidéo.mp4"].status == "skipped_size"
    assert files["vidéo.mp4"].local_path.endswith("Diapositives/vidéos/vidéo.mp4")
    assert files["ailleurs.pdf"].status == "external"
    assert not any("evil.example.com" in str(r.url) for r in moodle.requests)

    # Page modules get their own folder, so several index.html never collide.
    assert files["index.html"].local_path == (
        "courses/CS 202_Algorithms/01 Week 1_ Introduction to sorting/"
        "Reading_ sorting in practice/index.html"
    )
    assert (base / "HIS-303" / "01 Semana 1_ La independencia" / "lectura.pdf").exists()
    assert run.files_downloaded == 6
    assert run.bytes_downloaded == sum(len(b) for b in moodle.files.values())


def test_resync_skips_unchanged_files(service, moodle):
    sync(service)
    moodle.downloads.clear()
    run = sync(service)
    assert run.files_downloaded == 0
    assert run.files_unchanged == 6
    assert moodle.downloads == []


def test_resync_downloads_changed_and_missing_files(service, moodle, settings):
    sync(service)
    moodle.downloads.clear()
    # Teacher uploads a new version of the notes; the user deletes a local copy.
    moodle.contents[202][1]["modules"][0]["contents"][0]["timemodified"] = 1756999999
    moodle.files["/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf"] = b"%PDF-v2"
    moodle.contents[202][1]["modules"][0]["contents"][0]["filesize"] = 7
    (settings.data_dir / files_by_name(service)["lectura.pdf"].local_path).unlink()

    run = sync(service)
    assert run.files_downloaded == 2
    assert sorted(moodle.downloads) == [
        "/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf",
        "/webservice/pluginfile.php/1300/mod_resource/content/1/lectura.pdf",
    ]
    notes = files_by_name(service)["notes.pdf"]
    assert (settings.data_dir / notes.local_path).read_bytes() == b"%PDF-v2"


def test_removed_files_and_modules_are_flagged_and_kept(service, moodle, settings):
    sync(service)
    path = settings.data_dir / files_by_name(service)["lectura.pdf"].local_path
    moodle.contents[303][0]["modules"] = []
    sync(service)
    lectura = files_by_name(service)["lectura.pdf"]
    assert lectura.status == "removed"
    assert path.exists()
    assert [m.removed for m in rows(service, Module) if m.id == 7001] == [True]


def test_renamed_section_moves_files(service, moodle, settings):
    sync(service)
    old = settings.data_dir / files_by_name(service)["lectura.pdf"].local_path
    moodle.contents[303][0]["name"] = "Semana 1: Independencias"
    moodle.downloads.clear()
    sync(service)
    new = settings.data_dir / files_by_name(service)["lectura.pdf"].local_path
    assert new != old and new.exists() and not old.exists()
    assert moodle.downloads == []


def test_unenrolled_course_is_kept_but_flagged(service, moodle):
    sync(service)
    moodle.responses["core_enrol_get_users_courses"] = moodle.responses[
        "core_enrol_get_users_courses"
    ][:2]
    sync(service)
    assert {c.id: c.enrolled for c in rows(service, Course)}[303] is False


def test_deadlines(service, moodle):
    run = sync(service)
    deadlines = {(d.source, d.source_id): d for d in rows(service, Deadline)}
    assert run.deadlines == 3
    assign = deadlines[("assign", 81)]
    assert assign.due_at == 1762000000 and assign.course_id == 101 and assign.module_id == 5004
    assert assign.url == f"{BASE}/mod/assign/view.php?id=5004"
    assert assign.description == "Exercices 1 à 5."
    assert deadlines[("quiz", 21)].due_at == 1761600000
    # The calendar event for the assignment is not duplicated; the lesson one is kept.
    assert ("event", 9001) not in deadlines
    assert deadlines[("event", 9002)].name == "Ensayo final"

    moodle.responses["mod_quiz_get_quizzes_by_courses"] = {"quizzes": []}
    sync(service)
    assert {(d.source, d.source_id): d for d in rows(service, Deadline)}[("quiz", 21)].removed


def test_course_error_marks_run_partial(service, moodle):
    moodle.contents[202] = {"exception": "x", "errorcode": "nopermissions", "message": "No access"}
    run = sync(service)
    assert run.status == "partial"
    assert "CS 202/Algorithms" in run.message
    assert {c.id for c in rows(service, Course) if c.synced_at} == {101, 303}


def test_file_errors_mark_run_partial(service, moodle):
    del moodle.files["/webservice/pluginfile.php/1300/mod_resource/content/1/lectura.pdf"]
    run = sync(service)
    assert run.status == "partial" and run.files_failed == 1
    assert files_by_name(service)["lectura.pdf"].status == "error"


def test_invalid_token_stops_sync_with_clear_message(settings, moodle, caplog):
    bad = "b" * 32
    service = make_service(settings, lambda url, token: moodle.client(token=bad))
    with caplog.at_level(logging.DEBUG):
        run = sync(service)
    assert run.status == "error"
    assert "settings page" in run.message and "expired" in run.message
    assert bad not in caplog.text and bad not in run.message
    creds = accounts.get_moodle(service.engine, settings.secret_key)
    assert creds.check_ok is False


def test_no_saved_token(settings, moodle):
    no_token = {**settings.__dict__, "moodle_url": "https://moodle.uni-test.ch", "moodle_token": ""}
    service = make_service(Settings(**no_token), moodle.client)
    assert not service.configured()
    run = sync(service)
    assert run.status == "error" and "No Moodle token saved" in run.message


def test_token_unreadable_after_secret_key_change(settings, moodle):
    make_service(settings, moodle.client)
    rotated = Settings(**{**settings.__dict__, "secret_key": "r" * 64, "moodle_token": ""})
    service = make_service(rotated, moodle.client)
    run = sync(service)
    assert run.status == "error" and "SECRET_KEY changed" in run.message


def test_token_is_encrypted_at_rest(service, settings):
    raw = (settings.data_dir / "app.db").read_bytes()
    assert TOKEN.encode() not in raw


def test_logs_never_contain_the_token(service, caplog):
    with caplog.at_level(logging.DEBUG):
        sync(service)
        sync(service)
    assert TOKEN not in caplog.text


def test_only_one_sync_at_a_time(settings, moodle):
    gate = asyncio.Event()

    async def blocking_sleep(_s):
        await gate.wait()

    service = make_service(settings, lambda url, token: moodle.client(url, token, sleep=blocking_sleep))

    async def go():
        first = asyncio.create_task(service.run("a"))
        for _ in range(100):
            if service.running:
                break
            await asyncio.sleep(0)
        assert service.running
        with pytest.raises(SyncAlreadyRunning):
            await service.run("b")
        gate.set()
        return await first

    assert asyncio.run(go()).status == "ok"


def test_snapshot_db(service, settings):
    sync(service)
    dest = snapshot(settings.data_dir, settings.data_dir / "backup" / "app.db")
    with session(make_engine(dest.parent)) as s:
        assert len(s.exec(select(Course)).all()) == 3


def test_sync_extracts_text_and_indexes(service, settings):
    from app.extract.index import search
    from app.models import FileText

    run = sync(service)
    assert run.status in {"ok", "partial"}
    states = {f.filename: t for f in rows(service, File)
              for t in rows(service, FileText) if t.file_id == f.id}
    # The fake PDFs are not real PDFs: recorded as errors, never fatal.
    assert states["plan_du_cours.pdf"].status == "error"
    assert states["index.html"].status in {"ok", "empty"}
    assert "vidéo.mp4" not in states
    # Section and activity names are searchable right after the sync.
    hits, total = search(service.engine, "vecteurs")
    assert total >= 1
