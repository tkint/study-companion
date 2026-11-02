"""FastAPI entry point.

Serves the password-protected status page, the sync API and a health check. Later
milestones add the React build and the MCP endpoint to this app.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.api.status import course_overview, run_to_dict
from app.auth.pages import home_page, login_page
from app.auth.session import (
    SESSION_COOKIE,
    LoginThrottle,
    check_password,
    create_session_token,
    verify_session_token,
)
from app.config import Settings
from app.db import make_engine
from app.moodle.scheduler import start_scheduler
from app.moodle.sync import ClientFactory, SyncAlreadyRunning, SyncService

logger = logging.getLogger("app")

MAX_LOGIN_BODY = 4096


def _client_key(request: Request) -> str:
    # Uvicorn runs with --proxy-headers behind Caddy, so this is the real client IP.
    return request.client.host if request.client else "unknown"


def create_app(
    settings: Settings | None = None, client_factory: ClientFactory | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    throttle = LoginThrottle(settings.login_max_attempts, settings.login_window_seconds)
    engine = make_engine(settings.data_dir)
    sync = SyncService(settings, engine, client_factory)
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        scheduler = None
        if settings.moodle_configured:
            scheduler = start_scheduler(sync, settings.sync_interval_hours)
        else:
            logger.warning("Moodle sync is off: set MOODLE_URL and MOODLE_TOKEN")
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

    def is_authenticated(request: Request) -> bool:
        return verify_session_token(settings.secret_key, request.cookies.get(SESSION_COOKIE))

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": settings.version})

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

        body = await request.body()
        if len(body) > MAX_LOGIN_BODY:
            return HTMLResponse(login_page("Request too large."), status_code=413)
        form = parse_qs(body.decode("utf-8", errors="replace"), max_num_fields=5)
        password = (form.get("password") or [""])[0]

        if not check_password(settings.app_password, password):
            throttle.record_failure(key)
            logger.warning("Failed login attempt from %s", key)
            return HTMLResponse(login_page("Wrong password."), status_code=401)

        throttle.reset(key)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            create_session_token(settings.secret_key, settings.session_max_age),
            max_age=settings.session_max_age,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/logout")
    async def logout() -> Response:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(
            SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        return HTMLResponse(
            home_page(
                settings.version,
                configured=settings.moodle_configured,
                running=sync.running,
                last_run=sync.last_run(),
                overview=course_overview(engine),
            )
        )

    @app.post("/sync")
    async def sync_form(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        if settings.moodle_configured:
            start_sync()
        return RedirectResponse("/", status_code=303)

    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "not signed in"}, status_code=401)

    @app.get("/api/sync")
    async def sync_status(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        run = sync.last_run()
        return JSONResponse(
            {
                "configured": settings.moodle_configured,
                "running": sync.running,
                "last_run": run_to_dict(run) if run else None,
            }
        )

    @app.post("/api/sync")
    async def sync_start(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        if not settings.moodle_configured:
            return JSONResponse({"error": "Moodle is not configured"}, status_code=409)
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
