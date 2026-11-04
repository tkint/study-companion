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
    s = Settings.from_env({**VALID, "MOODLE_TOKEN": "0123456789abcdef0123456789abcdef"})
    text = repr(s)
    assert VALID["APP_PASSWORD"] not in text
    assert VALID["SECRET_KEY"] not in text
    assert "0123456789abcdef" not in text


def test_m3_settings_from_env():
    from app.config import ConfigError, Settings
    import pytest

    base = {"SECRET_KEY": "s" * 40, "APP_PASSWORD": "x" * 12}
    s = Settings.from_env({**base, "OAUTH_REDIRECT_HOSTS": " Claude.ai , example.org ,",
                           "TIMEZONE": "Europe/Paris"})
    assert s.oauth_redirect_hosts == ("claude.ai", "example.org")
    assert s.timezone == "Europe/Paris"
    assert Settings.from_env(base).oauth_redirect_hosts[0] == "claude.ai"
    with pytest.raises(ConfigError, match="TIMEZONE"):
        Settings.from_env({**base, "TIMEZONE": "Mars/Olympus"})
    assert Settings.from_env({**base, "DOMAIN": "study.example.ch"}).public_url("http://x") == \
        "https://study.example.ch"
    assert Settings.from_env(base).public_url("http://testserver/") == "http://testserver"


def test_version_comes_from_app_version_env():
    assert Settings.from_env({**VALID, "APP_VERSION": "1.2.3"}).version == "1.2.3"
    # Without the env var (local runs) the version falls back to the module default.
    import os
    if not os.environ.get("APP_VERSION"):
        assert Settings.from_env(VALID).version == "dev"
