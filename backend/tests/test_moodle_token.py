import base64

import pytest

from app.config import ConfigError, Settings
from app.moodle.token import TokenFormatError, parse_pasted_token

TOKEN = "0123456789abcdef0123456789abcdef"
PRIVATE = "p" * 64
SITEID = "9f86d081884c7d659a2feaa0c55ad015"


def launch_link(with_private: bool = True) -> str:
    raw = f"{SITEID}:::{TOKEN}" + (f":::{PRIVATE}" if with_private else "")
    return "moodlemobile://token=" + base64.b64encode(raw.encode()).decode()


def test_plain_token_is_kept():
    assert parse_pasted_token(f"  {TOKEN}\n") == TOKEN


def test_empty_is_empty():
    assert parse_pasted_token("") == ""
    assert parse_pasted_token(None) == ""


@pytest.mark.parametrize("with_private", [True, False])
def test_moodlemobile_link_is_decoded(with_private):
    assert parse_pasted_token(launch_link(with_private)) == TOKEN


def test_link_with_trailing_slash_and_quotes():
    assert parse_pasted_token(f'"{launch_link()}/"') == TOKEN


def test_bare_base64_payload_is_decoded():
    payload = launch_link().split("token=", 1)[1]
    assert parse_pasted_token(payload) == TOKEN


def test_unpadded_payload_is_decoded():
    payload = launch_link(False).split("token=", 1)[1].rstrip("=")
    assert parse_pasted_token(payload) == TOKEN


@pytest.mark.parametrize("bad", ["not a token!", "moodlemobile://token=%%%", "abc:::def"])
def test_garbage_is_rejected_without_echoing_it(bad):
    with pytest.raises(TokenFormatError) as exc:
        parse_pasted_token(bad)
    assert bad not in str(exc.value)


def test_settings_decode_pasted_link():
    s = Settings.from_env(
        {"APP_PASSWORD": "a-long-enough-password", "SECRET_KEY": "k" * 32,
         "MOODLE_URL": "https://moodle.example.ch", "MOODLE_TOKEN": launch_link()}
    )
    assert s.moodle_token == TOKEN
    assert TOKEN not in repr(s)


def test_settings_reject_bad_token_and_http_url():
    base = {"APP_PASSWORD": "a-long-enough-password", "SECRET_KEY": "k" * 32}
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "MOODLE_TOKEN": "nope nope"})
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "MOODLE_URL": "http://moodle.example.ch"})
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "SYNC_INTERVAL_HOURS": "-1"})
