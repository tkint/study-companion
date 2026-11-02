"""Application settings, read from environment variables only.

Secrets (APP_PASSWORD, SECRET_KEY, MOODLE_TOKEN, MOODLE_PASSWORD) are never logged or
rendered, and are kept out of ``repr``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from app import __version__
from app.moodle.token import TokenFormatError, parse_pasted_token

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


def _float(name: str, value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _token(value: str) -> str:
    try:
        return parse_pasted_token(value)
    except TokenFormatError as exc:
        # The message never contains the value itself.
        raise ConfigError(f"MOODLE_TOKEN: {exc}") from None


@dataclass(frozen=True)
class Settings:
    app_password: str = field(repr=False)
    secret_key: str = field(repr=False)
    domain: str = "localhost"
    data_dir: Path = Path("/data")
    moodle_url: str = ""
    moodle_token: str = field(default="", repr=False)
    # Fallback for sites without SSO: exchange username/password at /login/token.php.
    moodle_username: str = ""
    moodle_password: str = field(default="", repr=False)
    moodle_service: str = "moodle_mobile_app"
    moodle_rate_limit: float = 2.0  # requests per second
    moodle_timeout: float = 60.0
    moodle_max_file_mb: int = 200  # bigger files (usually videos) are recorded, not downloaded
    sync_interval_hours: float = 6.0  # 0 disables the scheduled sync
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
        if self.moodle_url:
            parts = urlsplit(self.moodle_url)
            local = parts.hostname in {"localhost", "127.0.0.1"}
            if parts.scheme != "https" and not (parts.scheme == "http" and local):
                raise ConfigError("MOODLE_URL must start with https://")
            if not parts.hostname:
                raise ConfigError("MOODLE_URL is not a valid URL")
        if self.moodle_rate_limit <= 0:
            raise ConfigError("MOODLE_RATE_LIMIT must be positive")
        if self.sync_interval_hours < 0:
            raise ConfigError("SYNC_INTERVAL_HOURS must be 0 (off) or positive")

    @property
    def moodle_configured(self) -> bool:
        return bool(self.moodle_url and (self.moodle_token or self.moodle_password))

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        return cls(
            app_password=env.get("APP_PASSWORD", ""),
            secret_key=env.get("SECRET_KEY", ""),
            domain=env.get("DOMAIN", "localhost") or "localhost",
            data_dir=Path(env.get("DATA_DIR", "/data") or "/data"),
            moodle_url=env.get("MOODLE_URL", "").rstrip("/"),
            moodle_token=_token(env.get("MOODLE_TOKEN", "")),
            moodle_username=env.get("MOODLE_USERNAME", ""),
            moodle_password=env.get("MOODLE_PASSWORD", ""),
            moodle_service=env.get("MOODLE_SERVICE", "") or "moodle_mobile_app",
            moodle_rate_limit=_float("MOODLE_RATE_LIMIT", env.get("MOODLE_RATE_LIMIT"), 2.0),
            moodle_timeout=_float("MOODLE_TIMEOUT", env.get("MOODLE_TIMEOUT"), 60.0),
            moodle_max_file_mb=_int("MOODLE_MAX_FILE_MB", env.get("MOODLE_MAX_FILE_MB"), 200),
            sync_interval_hours=_float(
                "SYNC_INTERVAL_HOURS", env.get("SYNC_INTERVAL_HOURS"), 6.0
            ),
            cookie_secure=_bool(env.get("COOKIE_SECURE"), True),
            session_max_age=_int("SESSION_MAX_AGE", env.get("SESSION_MAX_AGE"), 7 * 24 * 3600),
            login_max_attempts=_int("LOGIN_MAX_ATTEMPTS", env.get("LOGIN_MAX_ATTEMPTS"), 5),
            login_window_seconds=_int(
                "LOGIN_WINDOW_SECONDS", env.get("LOGIN_WINDOW_SECONDS"), 15 * 60
            ),
            version=env.get("APP_VERSION", "") or __version__,
        )
