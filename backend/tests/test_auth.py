from app.auth.session import (
    SESSION_COOKIE,
    LoginThrottle,
    create_session_token,
    verify_session_token,
)

from .conftest import PASSWORD

KEY = "x" * 40


def test_healthz_is_public(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_home_redirects_to_login_when_signed_out(client):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_page_is_phone_friendly(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert 'name="viewport"' in r.text
    assert r.headers["cache-control"] == "no-store"


def test_wrong_password_is_rejected(client):
    r = client.post("/login", data={"password": "nope"})
    assert r.status_code == 401
    assert SESSION_COOKIE not in r.cookies


def test_login_then_home_then_logout(client):
    r = client.post("/login", data={"password": PASSWORD})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie

    r = client.get("/")
    assert r.status_code == 200
    assert "Sync now" in r.text

    r = client.post("/logout")
    assert r.status_code == 303
    client.cookies.clear()
    assert client.get("/").status_code == 303


def test_secure_cookie_flag_by_default(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    secure = settings.__class__(**{**settings.__dict__, "cookie_secure": True})
    c = TestClient(create_app(secure), base_url="https://testserver", follow_redirects=False)
    r = c.post("/login", data={"password": PASSWORD})
    assert "secure" in r.headers["set-cookie"].lower()


def test_tampered_cookie_is_rejected(client):
    client.cookies.set(SESSION_COOKIE, "1.99999999999.deadbeef")
    assert client.get("/").status_code == 303


def test_login_is_throttled_after_repeated_failures(client):
    for _ in range(3):
        assert client.post("/login", data={"password": "bad"}).status_code == 401
    r = client.post("/login", data={"password": PASSWORD})
    assert r.status_code == 429


def test_session_token_expiry_and_signature():
    token = create_session_token(KEY, max_age=60, now=1000)
    assert verify_session_token(KEY, token, now=1030)
    assert not verify_session_token(KEY, token, now=1061)
    assert not verify_session_token("y" * 40, token, now=1030)
    assert not verify_session_token(KEY, None)
    assert not verify_session_token(KEY, "garbage")


def test_throttle_window_slides():
    t = LoginThrottle(max_attempts=2, window_seconds=10)
    t.record_failure("ip", now=0)
    t.record_failure("ip", now=1)
    assert t.is_blocked("ip", now=5)
    assert not t.is_blocked("ip", now=12)
