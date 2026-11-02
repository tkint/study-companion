import base64

import pytest
from fastapi.testclient import TestClient

from app import accounts
from app.config import ConfigError, Settings
from app.main import create_app

from .conftest import PASSWORD
from .fake_moodle import BASE, TOKEN, FakeMoodle

NEW_PASSWORD = "a brand new long password"


@pytest.fixture
def moodle():
    return FakeMoodle()


@pytest.fixture
def app(settings, moodle):
    return create_app(settings, client_factory=moodle.client)


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


def login(client, password=PASSWORD):
    r = client.post("/login", data={"password": password})
    assert r.status_code == 303, r.text
    return r


def creds(app):
    return accounts.get_moodle(app.state.engine, app.state.settings.secret_key)


def test_settings_requires_login(client):
    assert client.get("/settings").headers["location"] == "/login"
    r = client.post("/settings/moodle", data={"url": BASE, "token": TOKEN})
    assert r.headers["location"] == "/login"


def test_home_points_to_settings_when_not_connected(client):
    login(client)
    r = client.get("/")
    assert "/settings" in r.text and "not connected" in r.text


def test_save_token_tests_it_encrypts_it_and_never_shows_it(client, app, moodle):
    login(client)
    r = client.post("/settings/moodle", data={"url": BASE + "/login/index.php", "token": TOKEN})
    assert r.status_code == 303 and r.headers["location"] == "/settings?saved=moodle"
    saved = creds(app)
    assert saved.url == BASE and saved.token == TOKEN and saved.check_ok
    assert moodle.calls[0][0] == "core_webservice_get_site_info"
    page = client.get("/settings?saved=moodle").text
    assert "A token is saved" in page and "Jo Doe" in page
    assert TOKEN not in page
    assert TOKEN.encode() not in (app.state.settings.data_dir / "app.db").read_bytes()


def test_pasted_moodlemobile_link_is_decoded(client, app):
    login(client)
    link = "moodlemobile://token=" + base64.b64encode(f"{'a' * 32}:::{TOKEN}".encode()).decode()
    assert client.post("/settings/moodle", data={"url": BASE, "token": link}).status_code == 303
    assert creds(app).token == TOKEN


def test_rejected_token_is_not_saved(client, app):
    login(client)
    r = client.post("/settings/moodle", data={"url": BASE, "token": "b" * 32})
    assert r.status_code == 400 and "refused" in r.text
    assert "b" * 32 not in r.text
    assert creds(app).token == ""


def test_invalid_url_and_token_format(client):
    login(client)
    assert client.post("/settings/moodle", data={"url": "http://x.ch", "token": TOKEN}).status_code == 400
    r = client.post("/settings/moodle", data={"url": BASE, "token": "not a token!"})
    assert r.status_code == 400 and "not a token!" not in r.text
    assert client.post("/settings/moodle", data={"url": BASE, "token": ""}).status_code == 400


def test_blank_token_keeps_saved_one_for_same_site(client, app):
    login(client)
    client.post("/settings/moodle", data={"url": BASE, "token": TOKEN})
    assert client.post("/settings/moodle", data={"url": BASE, "token": ""}).status_code == 303
    assert creds(app).token == TOKEN


def test_username_password_gets_a_token_without_storing_password(settings):
    moodle = FakeMoodle(token="fedcba9876543210fedcba9876543210")
    app = create_app(settings, client_factory=moodle.client)
    with TestClient(app, follow_redirects=False) as client:
        login(client)
        r = client.post("/settings/moodle",
                        data={"url": BASE, "token": "", "username": "jdoe", "password": "pw"})
        assert r.status_code == 303
    assert creds(app).token == "fedcba9876543210fedcba9876543210"
    assert b"pw" not in b"".join(
        line for line in (settings.data_dir / "app.db").read_bytes().split(b"\x00") if b"jdoe" in line
    )


def test_forget_token(client, app):
    login(client)
    client.post("/settings/moodle", data={"url": BASE, "token": TOKEN})
    assert client.post("/settings/moodle/forget").status_code == 303
    assert creds(app).token == "" and creds(app).url == BASE


def test_cross_site_post_is_rejected(client, app):
    login(client)
    r = client.post("/settings/moodle", data={"url": BASE, "token": TOKEN},
                    headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert creds(app).token == ""


def test_change_password_signs_out_other_sessions(app):
    with TestClient(app, follow_redirects=False) as phone, \
            TestClient(app, follow_redirects=False) as laptop:
        login(phone)
        login(laptop)
        r = phone.post("/settings/password",
                       data={"current": PASSWORD, "new": NEW_PASSWORD, "confirm": NEW_PASSWORD})
        assert r.status_code == 303
        assert phone.get("/").status_code == 200  # this device stays signed in
        assert laptop.get("/").status_code == 303  # others are signed out
        laptop.cookies.clear()
        assert laptop.post("/login", data={"password": PASSWORD}).status_code == 401
        login(laptop, NEW_PASSWORD)


def test_change_password_validation(client):
    login(client)
    bad_current = {"current": "wrong", "new": NEW_PASSWORD, "confirm": NEW_PASSWORD}
    assert client.post("/settings/password", data=bad_current).status_code == 400
    mismatch = {"current": PASSWORD, "new": NEW_PASSWORD, "confirm": NEW_PASSWORD + "x"}
    assert client.post("/settings/password", data=mismatch).status_code == 400
    short = {"current": PASSWORD, "new": "short", "confirm": "short"}
    assert client.post("/settings/password", data=short).status_code == 400


def test_app_password_env_is_only_the_initial_password(settings):
    app = create_app(settings)
    accounts.change_password(app.state.engine, NEW_PASSWORD)
    # Restart with the old APP_PASSWORD still in .env: the database password wins.
    app = create_app(settings)
    assert accounts.verify_password(app.state.engine, NEW_PASSWORD)
    assert not accounts.verify_password(app.state.engine, PASSWORD)
    # And APP_PASSWORD can be removed from .env after the first start.
    create_app(Settings(**{**settings.__dict__, "app_password": ""}))


def test_first_start_needs_app_password(tmp_path):
    with pytest.raises(ConfigError):
        create_app(Settings(app_password="", secret_key="s" * 64, data_dir=tmp_path))


def test_env_token_is_imported_once(settings):
    seeded = Settings(**{**settings.__dict__, "moodle_url": BASE, "moodle_token": TOKEN})
    app = create_app(seeded)
    assert creds(app).token == TOKEN
    accounts.forget_token(app.state.engine)
    app = create_app(seeded)  # restart: the DB is the source of truth now
    assert creds(app).token == ""


def test_sync_api(client, moodle):
    assert client.get("/api/sync").status_code == 401
    login(client)
    assert client.post("/api/sync").status_code == 409  # not connected yet
    client.post("/settings/moodle", data={"url": BASE, "token": TOKEN})
    status = client.get("/api/sync").json()
    assert status["configured"] is True
    # Saving started a sync in the background; wait for it via the API.
    for _ in range(200):
        status = client.get("/api/sync").json()
        if not status["running"] and status["last_run"]:
            break
    assert status["last_run"]["status"] == "ok", status
    courses = client.get("/api/courses").json()["courses"]
    assert {c["id"]: c["lang"] for c in courses} == {101: "fr", 202: "en", 303: "es"}
    assert TOKEN not in str(status)
