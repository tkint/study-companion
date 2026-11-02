"""FastAPI entry point.

Serves the password-protected status and settings pages, the sync API and a health check.
Later milestones add the React build and the MCP endpoint to this app.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app import accounts
from app.api.status import course_overview, run_to_dict
from app.auth.pages import home_page, login_page, settings_page
from app.auth.session import (
    SESSION_COOKIE,
    LoginThrottle,
    create_session_token,
    verify_session_token,
)
from app.config import Settings, validate_moodle_url
from app.db import make_engine
from app.moodle import api as moodle_api
from app.moodle.client import MoodleAuthError, MoodleError
from app.moodle.scheduler import start_scheduler
from app.moodle.sync import ClientFactory, SyncAlreadyRunning, SyncService, default_client_factory
from app.moodle.token import TokenFormatError, parse_pasted_token

logger = logging.getLogger("app")

MAX_FORM_BODY = 8192


def _client_key(request: Request) -> str:
    # Uvicorn runs with --proxy-headers behind Caddy, so this is the real client IP.
    return request.client.host if request.client else "unknown"


async def _form(request: Request) -> dict[str, str] | None:
    body = await request.body()
    if len(body) > MAX_FORM_BODY:
        return None
    form = parse_qs(body.decode("utf-8", errors="replace"), max_num_fields=10)
    return {k: v[0] for k, v in form.items()}


def _same_origin(request: Request) -> bool:
    """Reject cross-site form posts (defence in depth on top of SameSite=Lax cookies)."""
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin is None
    return urlsplit(origin).netloc == request.headers.get("host", "")


def create_app(
    settings: Settings | None = None, client_factory: ClientFactory | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    throttle = LoginThrottle(settings.login_max_attempts, settings.login_window_seconds)
    engine = make_engine(settings.data_dir)
    accounts.bootstrap(engine, settings)
    client_factory = client_factory or default_client_factory(settings)
    sync = SyncService(settings, engine, client_factory)
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        scheduler = start_scheduler(sync, settings.sync_interval_hours)
        if not sync.configured():
            logger.warning("Moodle is not connected yet: add it on the settings page")
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        for task in tasks:
            task.cancel()

    app = FastAPI(
        title="Study Companion",
        version=settings.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sync = sync

    def session_key() -> str:
        # Changing the password bumps the epoch, which signs every other session out.
        return f"{settings.secret_key}:{accounts.session_epoch(engine)}"

    def is_authenticated(request: Request) -> bool:
        return verify_session_token(session_key(), request.cookies.get(SESSION_COOKIE))

    def set_session_cookie(response: Response) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            create_session_token(session_key(), settings.session_max_age),
            max_age=settings.session_max_age,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )

    def start_sync() -> bool:
        """Start a sync in the background; False if one is already running."""
        if sync.running:
            return False

        async def runner() -> None:
            try:
                await sync.run("manual")
            except SyncAlreadyRunning:
                pass

        task = asyncio.get_running_loop().create_task(runner())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return True

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": settings.version})

    # ------------------------------------------------------------------ login

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> Response:
        if is_authenticated(request):
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(login_page())

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request) -> Response:
        key = _client_key(request)
        if throttle.is_blocked(key):
            return HTMLResponse(
                login_page("Too many failed attempts. Try again in a few minutes."),
                status_code=429,
            )
        form = await _form(request)
        if form is None:
            return HTMLResponse(login_page("Request too large."), status_code=413)
        if not accounts.verify_password(engine, form.get("password", "")):
            throttle.record_failure(key)
            logger.warning("Failed login attempt from %s", key)
            return HTMLResponse(login_page("Wrong password."), status_code=401)

        throttle.reset(key)
        response = RedirectResponse("/", status_code=303)
        set_session_cookie(response)
        return response

    @app.post("/logout")
    async def logout() -> Response:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(
            SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
        )
        return response

    # ------------------------------------------------------------------ pages

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        return HTMLResponse(
            home_page(
                settings.version,
                configured=sync.configured(),
                running=sync.running,
                last_run=sync.last_run(),
                overview=course_overview(engine),
            )
        )

    @app.post("/sync")
    async def sync_form(request: Request) -> Response:
        if not is_authenticated(request) or not _same_origin(request):
            return RedirectResponse("/login", status_code=303)
        if sync.configured():
            start_sync()
        return RedirectResponse("/", status_code=303)

    def render_settings(
        message: str = "",
        error: str = "",
        status: int = 200,
        moodle_error: str = "",
        url_value: str | None = None,
    ) -> HTMLResponse:
        creds = accounts.get_moodle(engine, settings.secret_key)
        return HTMLResponse(
            settings_page(
                creds,
                message=message,
                error=error,
                moodle_error=moodle_error,
                url_value=url_value,
                version=settings.version,
            ),
            status_code=status,
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_form(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        saved = request.query_params.get("saved")
        message = {
            "moodle": "Moodle connection saved. A sync has started.",
            "password": "Password changed. Other devices have been signed out.",
            "forgot": "Token removed.",
        }.get(saved or "", "")
        return render_settings(message=message)

    @app.post("/settings/moodle", response_class=HTMLResponse)
    async def save_moodle(request: Request) -> Response:
        if not is_authenticated(request) or not _same_origin(request):
            return RedirectResponse("/login", status_code=303)
        form = await _form(request)
        if form is None:
            return render_settings(error="Request too large.", status=413)
        current = accounts.get_moodle(engine, settings.secret_key)
        entered_url = form.get("url", "").strip()

        def failed(reason: str) -> HTMLResponse:
            # Keep what was typed (except secrets) and say plainly that nothing was saved.
            logger.warning("Moodle settings not saved: %s", reason)
            return render_settings(
                moodle_error=f"Not saved: {reason}", url_value=entered_url, status=400
            )

        try:
            url = validate_moodle_url(entered_url)
            token = parse_pasted_token(form.get("token", ""))
        except (ValueError, TokenFormatError) as exc:
            return failed(str(exc))
        username, password = form.get("username", "").strip(), form.get("password", "")
        if not token and not (username and password):
            if url != current.url or not current.token:
                return failed("paste a token (or enter your Moodle username and password).")
            token_to_test = current.token
        else:
            token_to_test = token
        try:
            async with client_factory(url, token_to_test) as client:
                if not token_to_test:
                    await client.login_with_password(username, password)
                    token = client.token
                site = await moodle_api.get_site_info(client)
        except MoodleAuthError as exc:
            return failed(f"Moodle refused the token ({exc}).")
        except MoodleError as exc:
            return failed(f"could not reach Moodle at {url} ({exc}).")
        accounts.save_moodle(
            engine,
            settings.secret_key,
            url,
            token or None,
            check_message=f"Signed in to {site['sitename']} as {site['fullname']}",
        )
        start_sync()
        return RedirectResponse("/settings?saved=moodle", status_code=303)

    @app.post("/settings/moodle/forget")
    async def forget_moodle(request: Request) -> Response:
        if not is_authenticated(request) or not _same_origin(request):
            return RedirectResponse("/login", status_code=303)
        accounts.forget_token(engine)
        return RedirectResponse("/settings?saved=forgot", status_code=303)

    @app.post("/settings/password", response_class=HTMLResponse)
    async def save_password(request: Request) -> Response:
        if not is_authenticated(request) or not _same_origin(request):
            return RedirectResponse("/login", status_code=303)
        key = _client_key(request)
        if throttle.is_blocked(key):
            return render_settings(error="Too many failed attempts. Try again later.", status=429)
        form = await _form(request)
        if form is None:
            return render_settings(error="Request too large.", status=413)
        if not accounts.verify_password(engine, form.get("current", "")):
            throttle.record_failure(key)
            return render_settings(error="The current password is wrong.", status=400)
        new, confirm = form.get("new", ""), form.get("confirm", "")
        if new != confirm:
            return render_settings(error="The new passwords do not match.", status=400)
        try:
            accounts.change_password(engine, new)
        except ValueError as exc:
            return render_settings(error=str(exc), status=400)
        throttle.reset(key)
        response = RedirectResponse("/settings?saved=password", status_code=303)
        set_session_cookie(response)  # keep this device signed in
        return response

    # ------------------------------------------------------------------ JSON API

    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "not signed in"}, status_code=401)

    @app.get("/api/sync")
    async def sync_status(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        run = sync.last_run()
        return JSONResponse(
            {
                "configured": sync.configured(),
                "running": sync.running,
                "last_run": run_to_dict(run) if run else None,
            }
        )

    @app.post("/api/sync")
    async def sync_start(request: Request) -> JSONResponse:
        if not is_authenticated(request) or not _same_origin(request):
            return unauthorized()
        if not sync.configured():
            return JSONResponse({"error": "Moodle is not connected"}, status_code=409)
        if not start_sync():
            return JSONResponse({"status": "already running"}, status_code=409)
        return JSONResponse({"status": "started"}, status_code=202)

    @app.get("/api/courses")
    async def courses(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse({"courses": course_overview(engine)})

    return app


def get_app() -> FastAPI:
    """Factory for uvicorn: ``uvicorn app.main:get_app --factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
