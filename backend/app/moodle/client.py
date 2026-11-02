"""Async Moodle web service client (REST, JSON).

* The token is sent in the POST body, never in a logged URL. File downloads need it in the
  query string, so those URLs are redacted in every message and exception we raise, and
  httpx's own request logging is silenced.
* Every request (API and file) goes through one rate limiter (default 2 req/s).
* Network errors, HTTP 429 and 5xx are retried with exponential backoff. Moodle-level errors
  (HTTP 200 with an ``exception`` body) are raised at once: retrying would not help.
* The token is only ever sent to the configured Moodle host.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

logger = logging.getLogger("app.moodle")

# httpx logs full request URLs at INFO, which would include file-download tokens.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_SECRET_PARAMS = {"token", "wstoken", "password", "privatetoken"}
AUTH_ERROR_CODES = {"invalidtoken", "accessexception", "invalidlogin", "usernotfullysetup"}


class MoodleError(RuntimeError):
    """Moodle answered with an error."""

    def __init__(self, message: str, errorcode: str = "", wsfunction: str = "") -> None:
        super().__init__(message)
        self.errorcode = errorcode
        self.wsfunction = wsfunction


class MoodleAuthError(MoodleError):
    """The token is invalid or expired: paste a new one."""


class MoodleUnavailable(MoodleError):
    """Moodle could not be reached after retries."""


def redact_url(url: str) -> str:
    """Return ``url`` with secret query parameters replaced by ``***``."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid url>"
    if not parts.query:
        return url
    query = [
        (k, "***" if k.lower() in _SECRET_PARAMS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(query, safe="*")))


def strip_secrets(url: str) -> str:
    """Return ``url`` without any token/password query parameters (safe to store)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _SECRET_PARAMS
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def redact_text(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"(?i)(token|wstoken)=[^&\s\"']+", r"\1=***", text)


def flatten_params(params: Mapping[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Encode nested lists/dicts the way Moodle's REST server expects (``a[0][b]=x``)."""
    out: list[tuple[str, str]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, Mapping):
            out.extend(flatten_params(value, name))
        elif isinstance(value, (list, tuple)):
            out.extend(flatten_params({str(i): v for i, v in enumerate(value)}, name))
        elif isinstance(value, bool):
            out.append((name, "1" if value else "0"))
        elif value is None:
            continue
        else:
            out.append((name, str(value)))
    return out


class RateLimiter:
    """Spaces calls at least ``1 / rate`` seconds apart."""

    def __init__(
        self,
        rate: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval = 1.0 / rate
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            if now < self._next:
                await self._sleep(self._next - now)
                now = self._next
            self._next = now + self.interval


class MoodleClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        *,
        rate_limit: float = 2.0,
        timeout: float = 60.0,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        service: str = "moodle_mobile_app",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._host = (urlsplit(self.base_url).hostname or "").lower()
        self._token = token
        self.service = service
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep
        self.limiter = RateLimiter(rate_limit, sleep=sleep)
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": "StudyCompanion (personal sync; MoodleMobile compatible)"},
        )

    def __repr__(self) -> str:  # never show the token
        return f"MoodleClient({self.base_url!r})"

    async def __aenter__(self) -> "MoodleClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    def _redact(self, text: str) -> str:
        return redact_text(text, [self._token])

    # ---- low-level request with rate limit and backoff ----

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            await self.limiter.wait()
            try:
                response = await self._http.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                error: str = f"{type(exc).__name__}"
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    error = f"HTTP {response.status_code}"
                else:
                    return response
            attempt += 1
            if attempt > self.max_retries:
                raise MoodleUnavailable(
                    f"Moodle unreachable ({error}) for {redact_url(url)}"
                )
            delay = self.backoff_base * (2 ** (attempt - 1))
            logger.warning(
                "Moodle request failed (%s), retry %d/%d in %.0fs",
                error, attempt, self.max_retries, delay,
            )
            await self._sleep(delay)

    # ---- web service calls ----

    async def call(self, wsfunction: str, **params: Any) -> Any:
        if not self._token:
            raise MoodleAuthError("No Moodle token configured", "notoken", wsfunction)
        data = [
            ("wstoken", self._token),
            ("wsfunction", wsfunction),
            ("moodlewsrestformat", "json"),
            # Apply filters (e.g. multilang) and return plain strings where Moodle supports it.
            ("moodlewssettingfilter", "true"),
            ("moodlewssettingfileurl", "true"),
            *flatten_params(params),
        ]
        response = await self._request(
            "POST",
            f"{self.base_url}/webservice/rest/server.php",
            content=urlencode(data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise MoodleError(f"HTTP {response.status_code} from {wsfunction}", "", wsfunction)
        try:
            body = response.json()
        except ValueError:
            raise MoodleError(f"{wsfunction} did not return JSON", "", wsfunction) from None
        if isinstance(body, dict) and ("exception" in body or "errorcode" in body):
            code = str(body.get("errorcode") or "")
            message = self._redact(str(body.get("message") or code or "Moodle error"))
            cls = MoodleAuthError if code in AUTH_ERROR_CODES else MoodleError
            raise cls(f"{wsfunction}: {message}", code, wsfunction)
        return body

    async def login_with_password(self, username: str, password: str) -> None:
        """Fallback for non-SSO sites: get a token from /login/token.php."""
        response = await self._request(
            "POST",
            f"{self.base_url}/login/token.php",
            data={"username": username, "password": password, "service": self.service},
        )
        try:
            body = response.json()
        except ValueError:
            raise MoodleError("login/token.php did not return JSON") from None
        token = body.get("token") if isinstance(body, dict) else None
        if not token:
            code = str(body.get("errorcode") or "") if isinstance(body, dict) else ""
            raise MoodleAuthError(
                "Moodle rejected the username/password"
                + (f" ({code})" if code else "")
                + ". If your site uses SSO, paste a token instead (docs/moodle-token.md).",
                code,
            )
        self._token = str(token)

    # ---- files ----

    def is_moodle_url(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        return parts.scheme in {"https", "http"} and (parts.hostname or "").lower() == self._host

    def _file_url(self, fileurl: str) -> str:
        parts = urlsplit(strip_secrets(fileurl))
        query = parse_qsl(parts.query, keep_blank_values=True)
        query.append(("token", self._token))
        path = parts.path
        # Plain pluginfile.php does not accept tokens; the webservice variant does.
        if "/pluginfile.php" in path and "/webservice/pluginfile.php" not in path:
            path = path.replace("/pluginfile.php", "/webservice/pluginfile.php", 1)
        return urlunsplit(parts._replace(path=path, query=urlencode(query)))

    async def download(self, fileurl: str, dest: Path, max_bytes: int | None = None) -> int:
        """Stream ``fileurl`` to ``dest`` atomically; returns the number of bytes written."""
        if not self.is_moodle_url(fileurl):
            # Never send the token to another host.
            raise MoodleError(f"Refusing to download from a non-Moodle host: {redact_url(fileurl)}")
        url = self._file_url(fileurl)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        attempt = 0
        while True:
            await self.limiter.wait()
            written = 0
            try:
                async with self._http.stream("GET", url) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "retry", request=response.request, response=response
                        )
                    if response.status_code != 200:
                        raise MoodleError(
                            f"HTTP {response.status_code} downloading {redact_url(url)}"
                        )
                    ctype = response.headers.get("content-type", "")
                    if "application/json" in ctype:
                        # Moodle reports token problems as a JSON body.
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise MoodleError(self._redact(f"Moodle refused file: {body[:300]}"))
                    with tmp.open("wb") as fh:
                        async for chunk in response.aiter_bytes(64 * 1024):
                            written += len(chunk)
                            if max_bytes is not None and written > max_bytes:
                                raise MoodleError("file larger than MOODLE_MAX_FILE_MB")
                            fh.write(chunk)
                tmp.replace(dest)
                return written
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                tmp.unlink(missing_ok=True)
                attempt += 1
                reason = (
                    f"HTTP {exc.response.status_code}"
                    if isinstance(exc, httpx.HTTPStatusError)
                    else type(exc).__name__
                )
                if attempt > self.max_retries:
                    raise MoodleUnavailable(
                        f"Download failed ({reason}) for {redact_url(url)}"
                    ) from None
                delay = self.backoff_base * (2 ** (attempt - 1))
                logger.warning("Download failed (%s), retry %d in %.0fs", reason, attempt, delay)
                await self._sleep(delay)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
