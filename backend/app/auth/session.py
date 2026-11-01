"""Signed, stateless session cookies and a login throttle for the single user.

The cookie value is ``<issued_at>.<expires_at>.<hmac>``; the HMAC uses SECRET_KEY,
so rotating SECRET_KEY logs every session out.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque

SESSION_COOKIE = "msc_session"


def _sign(secret_key: str, payload: str) -> str:
    return hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_token(secret_key: str, max_age: int, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = f"{issued}.{issued + max_age}"
    return f"{payload}.{_sign(secret_key, payload)}"


def verify_session_token(secret_key: str, token: str | None, now: float | None = None) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    issued, expires, signature = parts
    if not (issued.isdigit() and expires.isdigit()):
        return False
    expected = _sign(secret_key, f"{issued}.{expires}")
    if not hmac.compare_digest(expected, signature):
        return False
    current = now if now is not None else time.time()
    return int(issued) <= current + 60 and current < int(expires)


def check_password(expected: str, supplied: str) -> bool:
    return hmac.compare_digest(expected.encode(), supplied.encode())


class LoginThrottle:
    """Blocks a client after too many failed logins within a sliding window."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        failures = self._failures[key]
        while failures and failures[0] <= now - self.window_seconds:
            failures.popleft()
        return failures

    def is_blocked(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        with self._lock:
            return len(self._prune(key, now)) >= self.max_attempts

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
