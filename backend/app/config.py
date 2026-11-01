"""Application settings, read from environment variables only.

Secrets (APP_PASSWORD, SECRET_KEY, MOODLE_TOKEN) are never logged or rendered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app import __version__

MIN_SECRET_KEY_LENGTH = 32
MIN_PASSWORD_LENGTH = 12


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    app_password: str = field(repr=False)
    secret_key: str = field(repr=False)
    domain: str = "localhost"
    data_dir: Path = Path("/data")
    moodle_url: str = ""
    moodle_token: str = field(default="", repr=False)
    cookie_secure: bool = True
    session_max_age: int = 7 * 24 * 3600
    login_max_attempts: int = 5
    login_window_seconds: int = 15 * 60
    version: str = __version__

    def __post_init__(self) -> None:
        if len(self.app_password) < MIN_PASSWORD_LENGTH:
            raise ConfigError(
                f"APP_PASSWORD must be set and at least {MIN_PASSWORD_LENGTH} characters long"
            )
        if len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
            raise ConfigError(
                f"SECRET_KEY must be set and at least {MIN_SECRET_KEY_LENGTH} characters long "
                "(generate one with: openssl rand -hex 32)"
            )
        if self.session_max_age <= 0:
            raise ConfigError("SESSION_MAX_AGE must be positive")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        return cls(
            app_password=env.get("APP_PASSWORD", ""),
            secret_key=env.get("SECRET_KEY", ""),
            domain=env.get("DOMAIN", "localhost") or "localhost",
            data_dir=Path(env.get("DATA_DIR", "/data") or "/data"),
            moodle_url=env.get("MOODLE_URL", "").rstrip("/"),
            moodle_token=env.get("MOODLE_TOKEN", ""),
            cookie_secure=_bool(env.get("COOKIE_SECURE"), True),
            session_max_age=_int("SESSION_MAX_AGE", env.get("SESSION_MAX_AGE"), 7 * 24 * 3600),
            login_max_attempts=_int("LOGIN_MAX_ATTEMPTS", env.get("LOGIN_MAX_ATTEMPTS"), 5),
            login_window_seconds=_int(
                "LOGIN_WINDOW_SECONDS", env.get("LOGIN_WINDOW_SECONDS"), 15 * 60
            ),
            version=env.get("APP_VERSION", "") or __version__,
        )
