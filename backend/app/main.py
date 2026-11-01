"""FastAPI entry point.

M0 serves a password-protected hello page and a health check. Later milestones add
the REST API, the React build and the MCP endpoint to this app.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.auth.pages import home_page, login_page
from app.auth.session import (
    SESSION_COOKIE,
    LoginThrottle,
    check_password,
    create_session_token,
    verify_session_token,
)
from app.config import Settings

logger = logging.getLogger("app")

MAX_LOGIN_BODY = 4096


def _client_key(request: Request) -> str:
    # Uvicorn runs with --proxy-headers behind Caddy, so this is the real client IP.
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    throttle = LoginThrottle(settings.login_max_attempts, settings.login_window_seconds)

    app = FastAPI(
        title="Moodle Study Companion",
        version=settings.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings

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
        return HTMLResponse(home_page(settings.version))

    return app


def get_app() -> FastAPI:
    """Factory for uvicorn: ``uvicorn app.main:get_app --factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
