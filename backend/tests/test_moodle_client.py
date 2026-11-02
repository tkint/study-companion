import asyncio
import logging

import pytest

from app.moodle.client import (
    MoodleAuthError,
    MoodleError,
    MoodleUnavailable,
    RateLimiter,
    flatten_params,
    redact_url,
    strip_secrets,
)

from .fake_moodle import TOKEN, FakeMoodle


def run(coro):
    return asyncio.run(coro)


def test_flatten_params_matches_moodle_rest_encoding():
    assert flatten_params({"courseids": [3, 4], "options": [{"name": "a", "value": True}]}) == [
        ("courseids[0]", "3"),
        ("courseids[1]", "4"),
        ("options[0][name]", "a"),
        ("options[0][value]", "1"),
    ]
    assert flatten_params({"skip": None}) == []


def test_redact_and_strip_secrets():
    url = f"https://m.example.ch/webservice/pluginfile.php/1/a.pdf?forcedownload=1&token={TOKEN}"
    assert TOKEN not in redact_url(url)
    assert "token=***" in redact_url(url)
    assert strip_secrets(url) == "https://m.example.ch/webservice/pluginfile.php/1/a.pdf?forcedownload=1"


def test_token_goes_in_post_body_not_url():
    moodle = FakeMoodle()

    async def go():
        async with moodle.client() as c:
            return await c.call("core_webservice_get_site_info")

    assert run(go())["userid"] == 42
    req = moodle.requests[0]
    assert req.method == "POST"
    assert TOKEN not in str(req.url)
    assert TOKEN not in repr(moodle.client())


def test_invalid_token_raises_auth_error():
    moodle = FakeMoodle()

    async def go():
        async with moodle.client(token="f" * 32) as c:
            await c.call("core_webservice_get_site_info")

    with pytest.raises(MoodleAuthError) as exc:
        run(go())
    assert exc.value.errorcode == "invalidtoken"


def test_no_token_raises_auth_error():
    async def go():
        async with FakeMoodle().client(token="") as c:
            await c.call("core_webservice_get_site_info")

    with pytest.raises(MoodleAuthError):
        run(go())


def test_other_moodle_error_is_not_retried():
    moodle = FakeMoodle()

    async def go():
        async with moodle.client() as c:
            await c.call("unknown_function")

    with pytest.raises(MoodleError) as exc:
        run(go())
    assert not isinstance(exc.value, MoodleAuthError)
    assert len(moodle.calls) == 1


def test_server_errors_are_retried_with_backoff():
    moodle = FakeMoodle()
    moodle.fail_next["core_webservice_get_site_info"] = [503, 502]
    delays = []

    async def sleep(s):
        delays.append(s)

    async def go():
        async with moodle.client(sleep=sleep, rate_limit=1000) as c:
            return await c.call("core_webservice_get_site_info")

    assert run(go())["sitename"]
    assert len(moodle.calls) == 3
    assert [d for d in delays if d >= 1] == [1.0, 2.0]


def test_gives_up_after_max_retries(caplog):
    moodle = FakeMoodle()
    moodle.fail_next["core_webservice_get_site_info"] = [500] * 10

    async def go():
        async with moodle.client(max_retries=2) as c:
            await c.call("core_webservice_get_site_info")

    with caplog.at_level(logging.DEBUG), pytest.raises(MoodleUnavailable):
        run(go())
    assert len(moodle.calls) == 3
    assert TOKEN not in caplog.text


def test_rate_limiter_spaces_requests():
    clock = [0.0]
    slept = []

    async def sleep(s):
        slept.append(s)
        clock[0] += s

    limiter = RateLimiter(2.0, clock=lambda: clock[0], sleep=sleep)

    async def go():
        for _ in range(5):
            await limiter.wait()

    run(go())
    assert slept == [0.5, 0.5, 0.5, 0.5]


def test_download_writes_file_and_hides_token(tmp_path, caplog):
    moodle = FakeMoodle()
    url = "https://moodle.example.ch/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf"

    async def go():
        async with moodle.client() as c:
            return await c.download(url, tmp_path / "a" / "notes.pdf")

    with caplog.at_level(logging.DEBUG):
        assert run(go()) == 9
    assert (tmp_path / "a" / "notes.pdf").read_bytes() == b"%PDF-note"
    assert not list(tmp_path.rglob("*.part"))
    assert TOKEN not in caplog.text


def test_plain_pluginfile_url_is_rewritten_to_webservice():
    moodle = FakeMoodle()
    url = "https://moodle.example.ch/pluginfile.php/1200/mod_resource/content/3/notes.pdf"

    async def go(tmp):
        async with moodle.client() as c:
            await c.download(url, tmp)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        run(go(Path(d) / "n.pdf"))
    assert moodle.downloads == ["/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf"]


def test_download_refuses_other_hosts(tmp_path):
    moodle = FakeMoodle()

    async def go():
        async with moodle.client() as c:
            await c.download("https://evil.example.com/x.pdf?token=abc", tmp_path / "x")

    with pytest.raises(MoodleError) as exc:
        run(go())
    assert "abc" not in str(exc.value)
    assert moodle.requests == []


def test_download_error_message_is_redacted(tmp_path):
    moodle = FakeMoodle()
    url = "https://moodle.example.ch/webservice/pluginfile.php/404/missing.pdf"

    async def go():
        async with moodle.client() as c:
            await c.download(url, tmp_path / "x")

    with pytest.raises(MoodleError) as exc:
        run(go())
    assert TOKEN not in str(exc.value)
    assert not (tmp_path / "x").exists()


def test_download_retries_server_errors(tmp_path):
    moodle = FakeMoodle()
    path = "/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf"
    moodle.fail_next[path] = [503]

    async def go():
        async with moodle.client() as c:
            return await c.download("https://moodle.example.ch" + path, tmp_path / "n.pdf")

    assert run(go()) == 9
    assert len(moodle.downloads) == 2


def test_download_with_expired_token_reports_json_error(tmp_path):
    moodle = FakeMoodle()
    path = "/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf"

    async def go():
        async with moodle.client(token="e" * 32) as c:
            await c.download("https://moodle.example.ch" + path, tmp_path / "n.pdf")

    with pytest.raises(MoodleError) as exc:
        run(go())
    assert "e" * 32 not in str(exc.value)


def test_download_respects_max_bytes(tmp_path):
    moodle = FakeMoodle()
    path = "/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf"

    async def go():
        async with moodle.client() as c:
            await c.download("https://moodle.example.ch" + path, tmp_path / "n.pdf", max_bytes=4)

    with pytest.raises(MoodleError):
        run(go())
    assert not (tmp_path / "n.pdf").exists()


def test_login_with_password_fallback():
    moodle = FakeMoodle(token="fedcba9876543210fedcba9876543210")

    async def go(password):
        async with moodle.client(token="") as c:
            await c.login_with_password("jdoe", password)
            return await c.call("core_webservice_get_site_info")

    assert run(go("pw"))["userid"] == 42
    with pytest.raises(MoodleAuthError) as exc:
        run(go("wrong"))
    assert exc.value.errorcode == "invalidlogin"
    login = [r for r in moodle.requests if r.url.path == "/login/token.php"][0]
    assert "pw" not in str(login.url)
    assert b"service=moodle_mobile_app" in login.content
