import pytest

from app.config import ConfigError, Settings

VALID = {"APP_PASSWORD": "a-long-enough-password", "SECRET_KEY": "k" * 32}


def test_from_env_reads_values():
    s = Settings.from_env(
        {**VALID, "DOMAIN": "study.example.ch", "MOODLE_URL": "https://moodle.example.ch/",
         "COOKIE_SECURE": "false", "SESSION_MAX_AGE": "3600"}
    )
    assert s.domain == "study.example.ch"
    assert s.moodle_url == "https://moodle.example.ch"
    assert s.cookie_secure is False
    assert s.session_max_age == 3600


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"APP_PASSWORD": "short", "SECRET_KEY": "k" * 32},
        {"APP_PASSWORD": "a-long-enough-password", "SECRET_KEY": "too-short"},
        {**VALID, "SESSION_MAX_AGE": "abc"},
    ],
)
def test_from_env_rejects_invalid(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_secrets_not_in_repr():
    s = Settings.from_env({**VALID, "MOODLE_TOKEN": "tok-123456"})
    text = repr(s)
    assert VALID["APP_PASSWORD"] not in text
    assert VALID["SECRET_KEY"] not in text
    assert "tok-123456" not in text
