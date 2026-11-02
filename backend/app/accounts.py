"""The user account and its Moodle credentials, stored in SQLite.

Nothing here needs ``.env`` edits after the first start: ``APP_PASSWORD`` only sets the
initial password, and ``MOODLE_URL``/``MOODLE_TOKEN`` are only imported when the database
has no Moodle settings yet. After that, the settings page is the source of truth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine
from sqlmodel import select

from app.auth.crypto import DecryptError, decrypt_secret, encrypt_secret, hash_password
from app.auth.crypto import verify_password as _verify
from app.config import ConfigError, Settings
from app.db import session
from app.models import Account, MoodleAccount

USER_ID = 1  # single user for now
MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class MoodleCredentials:
    url: str = ""
    token: str = field(default="", repr=False)
    token_unreadable: bool = False  # SECRET_KEY changed since it was saved
    token_updated_at: int | None = None
    checked_at: int | None = None
    check_ok: bool | None = None
    check_message: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)


def bootstrap(engine: Engine, settings: Settings, now: int | None = None) -> None:
    """Create the account on first start and import optional env values once."""
    now = int(now if now is not None else time.time())
    with session(engine) as s:
        account = s.get(Account, USER_ID)
        if account is None or not account.password_hash:
            if not settings.app_password:
                raise ConfigError(
                    "APP_PASSWORD must be set for the first start (it becomes the initial "
                    "web UI password; change it later on the settings page)"
                )
            account = account or Account(id=USER_ID, created_at=now)
            account.password_hash = hash_password(settings.app_password)
            account.updated_at = now
            s.add(account)
            s.commit()
        moodle = s.exec(select(MoodleAccount).where(MoodleAccount.user_id == USER_ID)).first()
        if moodle is None and settings.moodle_url:
            moodle = MoodleAccount(user_id=USER_ID, url=settings.moodle_url)
            if settings.moodle_token:
                moodle.token_encrypted = encrypt_secret(settings.secret_key, settings.moodle_token)
                moodle.token_updated_at = now
            s.add(moodle)
            s.commit()


def session_epoch(engine: Engine) -> int:
    with session(engine) as s:
        account = s.get(Account, USER_ID)
        return account.session_epoch if account else 0


def verify_password(engine: Engine, password: str) -> bool:
    with session(engine) as s:
        account = s.get(Account, USER_ID)
        return bool(account and account.password_hash and _verify(account.password_hash, password))


def change_password(engine: Engine, new_password: str, now: int | None = None) -> None:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"The new password must be at least {MIN_PASSWORD_LENGTH} characters")
    with session(engine) as s:
        account = s.get(Account, USER_ID)
        assert account is not None
        account.password_hash = hash_password(new_password)
        account.session_epoch += 1
        account.updated_at = int(now if now is not None else time.time())
        s.add(account)
        s.commit()


def _moodle_row(s) -> MoodleAccount | None:
    return s.exec(select(MoodleAccount).where(MoodleAccount.user_id == USER_ID)).first()


def get_moodle(engine: Engine, secret_key: str) -> MoodleCredentials:
    with session(engine) as s:
        row = _moodle_row(s)
    if row is None:
        return MoodleCredentials()
    token, unreadable = "", False
    if row.token_encrypted:
        try:
            token = decrypt_secret(secret_key, row.token_encrypted)
        except DecryptError:
            unreadable = True
    return MoodleCredentials(
        url=row.url,
        token=token,
        token_unreadable=unreadable,
        token_updated_at=row.token_updated_at,
        checked_at=row.checked_at,
        check_ok=row.check_ok,
        check_message=row.check_message,
    )


def save_moodle(
    engine: Engine,
    secret_key: str,
    url: str,
    token: str | None,
    *,
    check_message: str = "",
    now: int | None = None,
) -> None:
    """Save the site URL and, when given, a new token (``None`` keeps the stored one)."""
    now = int(now if now is not None else time.time())
    with session(engine) as s:
        row = _moodle_row(s) or MoodleAccount(user_id=USER_ID)
        row.url = url
        if token is not None:
            row.token_encrypted = encrypt_secret(secret_key, token) if token else ""
            row.token_updated_at = now if token else None
        row.checked_at, row.check_ok, row.check_message = now, True, check_message
        s.add(row)
        s.commit()


def record_check(engine: Engine, ok: bool, message: str, now: int | None = None) -> None:
    with session(engine) as s:
        row = _moodle_row(s)
        if row is None:
            return
        row.checked_at = int(now if now is not None else time.time())
        row.check_ok, row.check_message = ok, message[:300]
        s.add(row)
        s.commit()


def forget_token(engine: Engine) -> None:
    with session(engine) as s:
        row = _moodle_row(s)
        if row is not None:
            row.token_encrypted, row.token_updated_at = "", None
            row.check_ok, row.check_message = None, ""
            s.add(row)
            s.commit()
