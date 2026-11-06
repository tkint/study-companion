"""FastAPI entry point.

Serves the React web UI (``frontend/dist``) behind the password login, its JSON API, file
downloads and the ICS feed, the server-rendered login/settings/status pages, the sync API
and a health check, and the MCP endpoint for Claude's connector.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from app import accounts
from app.api import prompts as prompt_routes
from app.api import routes
from app.api import study as study_routes
from app.api.status import course_overview, run_to_dict
from app.auth import oauth, oauth_routes
from app.auth.pages import home_page, login_page, settings_page
from app.auth.session import (
    SESSION_COOKIE,
    LoginThrottle,
    create_session_token,
    verify_session_token,
)
from app.config import Settings, validate_moodle_url
from app.db import make_engine
from app.mcp_server import AppsClients, MCPEndpoint, build_server
from app.mcp_tools import StudyTools
from app.moodle import api as moodle_api
from app.moodle.client import MoodleAuthError, MoodleError, redact_text
from app.moodle.scheduler import start_scheduler
from app.moodle.sync import ClientFactory, SyncAlreadyRunning, SyncService, default_client_factory
from app.moodle.token import TokenFormatError, parse_pasted_token

logger = logging.getLogger("app")

MAX_FORM_BODY = 8192
# Files from frontend/public served at the site root without signing in: browsers fetch
# the manifest and icons without cookies, and the service worker must live at /.
PUBLIC_FILES = {
    "manifest.webmanifest",
    "sw.js",
    "favicon.svg",
    "icon-192.png",
    "icon-512.png",
    "icon-maskable-512.png",
    "apple-touch-icon.png",
}


# Slim images have no /etc/mime.types: the pdf.js worker must be served as JavaScript.
for _ext, _type in ((".mjs", "text/javascript"), (".wasm", "application/wasm"),
                    (".webmanifest", "application/manifest+json")):
    mimetypes.add_type(_type, _ext)


class RedactTokens(logging.Filter):
    """Hide ``token=`` values (the ICS feed URL) in uvicorn's access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Keep the args tuple: uvicorn's access formatter unpacks it.
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_text(a, []) if isinstance(a, str) else a for a in record.args
            )
        return True


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
    """Reject cross-site form posts (defence in depth on top of SameSite=Lax cookies).

    ``Sec-Fetch-Site`` is set by the browser and can't be forged by a page, so it decides
    when present (all current browsers). Under ``Referrer-Policy: no-referrer`` browsers
    send ``Origin: null`` even on same-site posts, which is why Origin alone isn't enough;
    the Caddyfile now uses ``same-origin``. Without Sec-Fetch-Site, Origin must be absent
    or match the host; ``null`` is rejected, since sandboxed frames can send it too.
    """
    site = request.headers.get("sec-fetch-site")
    if site:
        return site in {"same-origin", "none"}
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return origin != "null" and urlsplit(origin).netloc == request.headers.get("host", "")


def _forbidden() -> HTMLResponse:
    return HTMLResponse(
        "Blocked a request that did not come from this site. Reload the page and try again.",
        status_code=403,
    )


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
    access_log = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTokens) for f in access_log.filters):
        access_log.addFilter(RedactTokens())
    frontend = settings.frontend_dir
    index_html = frontend / "index.html" if frontend else None
    if index_html is not None and not index_html.is_file():
        logger.warning("No web UI build in %s: serving the basic status page", frontend)
        index_html = None

    def public_base(request) -> str:
        return settings.public_url(str(request.base_url))

    class SyncControl:
        """trigger_sync's view of the sync service (start_sync is defined below)."""

        def configured(self) -> bool:
            return sync.configured()

        def start(self) -> bool:
            return start_sync()

    apps_clients = AppsClients()
    mcp_endpoint = MCPEndpoint(
        build_server(StudyTools(settings, engine, settings.public_url(), sync=SyncControl()),
                     settings.version, apps_clients),
        engine,
        public_base,
        apps_clients,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        scheduler = start_scheduler(sync, settings.sync_interval_hours)
        if not sync.configured():
            logger.warning("Moodle is not connected yet: add it on the settings page")
        async with mcp_endpoint.running():
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
        cors = oauth_routes.wants_cors(request.url.path)
        if cors and request.method == "OPTIONS":
            return Response(status_code=204, headers=oauth_routes.cors_headers())
        response = await call_next(request)
        if cors:
            response.headers.update(oauth_routes.cors_headers())
        if request.url.path.startswith(("/assets/", "/pdfjs/")) and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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
        if index_html is not None:
            return FileResponse(index_html, media_type="text/html")
        return status_html()

    @app.get("/status", response_class=HTMLResponse)
    async def status_page(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        return status_html()

    def status_html() -> HTMLResponse:
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
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        if not _same_origin(request):
            return _forbidden()
        if sync.configured():
            start_sync()
        return RedirectResponse("/status" if index_html else "/", status_code=303)

    def render_settings(
        request: Request,
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
                mcp_url=f"{public_base(request)}/mcp",
                connections=oauth.connections(engine),
            ),
            status_code=status,
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_form(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        saved = request.query_params.get("saved")
        message = {
            "moodle": "Source site connection saved. A sync has started.",
            "password": "Password changed. Other devices have been signed out.",
            "forgot": "Token removed.",
            "connector": "Claude was disconnected. Add the connector again to reconnect.",
        }.get(saved or "", "")
        return render_settings(request, message=message)

    @app.post("/settings/moodle", response_class=HTMLResponse)
    async def save_moodle(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        if not _same_origin(request):
            return _forbidden()
        form = await _form(request)
        if form is None:
            return render_settings(request, error="Request too large.", status=413)
        current = accounts.get_moodle(engine, settings.secret_key)
        entered_url = form.get("url", "").strip()

        def failed(reason: str) -> HTMLResponse:
            # Keep what was typed (except secrets) and say plainly that nothing was saved.
            logger.warning("Moodle settings not saved: %s", reason)
            return render_settings(
                request,
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
                return failed("paste a token (or enter your username and password).")
            token_to_test = current.token
        else:
            token_to_test = token
        try:
            async with client_factory(url, token_to_test) as client:
                client.max_retries = 1  # someone is waiting on this page: fail fast
                if not token_to_test:
                    await client.login_with_password(username, password)
                    token = client.token
                site = await moodle_api.get_site_info(client)
        except MoodleAuthError as exc:
            return failed(f"the source site refused the token ({exc}).")
        except MoodleError as exc:
            return failed(f"could not reach the source site at {url} ({exc}).")
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
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        if not _same_origin(request):
            return _forbidden()
        accounts.forget_token(engine)
        return RedirectResponse("/settings?saved=forgot", status_code=303)

    @app.post("/settings/connector/disconnect")
    async def disconnect_connector(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        if not _same_origin(request):
            return _forbidden()
        oauth.revoke_all(engine, forget_clients=True)
        return RedirectResponse("/settings?saved=connector", status_code=303)

    @app.post("/settings/password", response_class=HTMLResponse)
    async def save_password(request: Request) -> Response:
        if not is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        if not _same_origin(request):
            return _forbidden()
        key = _client_key(request)
        if throttle.is_blocked(key):
            return render_settings(request, error="Too many failed attempts. Try again later.", status=429)
        form = await _form(request)
        if form is None:
            return render_settings(request, error="Request too large.", status=413)
        if not accounts.verify_password(engine, form.get("current", "")):
            throttle.record_failure(key)
            return render_settings(request, error="The current password is wrong.", status=400)
        new, confirm = form.get("new", ""), form.get("confirm", "")
        if new != confirm:
            return render_settings(request, error="The new passwords do not match.", status=400)
        try:
            accounts.change_password(engine, new)
        except ValueError as exc:
            return render_settings(request, error=str(exc), status=400)
        oauth.revoke_all(engine)  # connectors must sign in again with the new password
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
            return JSONResponse({"error": "The source site is not connected"}, status_code=409)
        if not start_sync():
            return JSONResponse({"status": "already running"}, status_code=409)
        return JSONResponse({"status": "started"}, status_code=202)

    @app.get("/api/courses")
    async def courses(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse({"courses": course_overview(engine)})

    routes.register(app, settings, engine, is_authenticated, _same_origin)
    prompt_routes.register(app, settings, engine, is_authenticated, _same_origin)
    study_routes.register(app, settings, engine, is_authenticated, _same_origin)
    oauth_routes.register(app, settings, engine, is_authenticated, _same_origin, throttle,
                          _client_key)
    # Claude's connector: OAuth bearer token required (checked in MCPEndpoint).
    app.router.routes.append(Route("/mcp", mcp_endpoint, methods=["GET", "POST", "DELETE"]))

    # ------------------------------------------------------------------ web UI build

    if index_html is not None and frontend is not None:
        assets = frontend / "assets"
        if assets.is_dir():
            # Hashed file names: safe to cache for a year.
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        pdfjs = frontend / "pdfjs"
        if pdfjs.is_dir():
            # pdf.js fonts, character maps and decoders (public library files).
            app.mount("/pdfjs", StaticFiles(directory=pdfjs), name="pdfjs")

        for name in PUBLIC_FILES:
            path = frontend / name
            if path.is_file():
                app.add_api_route(f"/{name}", _static_file(path), methods=["GET"],
                                  include_in_schema=False)

    return app


# Colours of the installed app's splash screen and system bars, per theme. Android (Chrome)
# takes the status and navigation bar colours from the manifest's theme_color, not from the
# page, so the manifest follows the theme picked in the UI (a ``theme`` cookie set next to
# localStorage). With the device theme, Chrome's dark-mode override applies instead.
MANIFEST_COLOURS = {
    "light": {"theme_color": "#ffffff", "background_color": "#ffffff"},
    "dark": {"theme_color": "#131C2E", "background_color": "#0B1220"},
}


def manifest_for_theme(raw: str, theme: str | None) -> str:
    try:
        manifest = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(manifest, dict):
        return raw
    colours = MANIFEST_COLOURS.get(theme or "")
    if colours:
        manifest.update(colours)
        manifest.pop("user_preferences", None)  # a forced theme wins over the device's
    return json.dumps(manifest)


def _manifest_file(path):
    async def serve(request: Request) -> Response:
        body = manifest_for_theme(path.read_text(encoding="utf-8"), request.cookies.get("theme"))
        # Short cache, varying on the cookie, so a theme switch reaches the next manifest check.
        return Response(body, media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache", "Vary": "Cookie"})

    return serve


def _static_file(path):
    if path.name == "manifest.webmanifest":
        return _manifest_file(path)

    async def serve() -> FileResponse:
        headers = {"Cache-Control": "no-cache"} if path.name == "sw.js" else {
            "Cache-Control": "public, max-age=86400"}
        return FileResponse(path, headers=headers)

    return serve


def get_app() -> FastAPI:
    """Factory for uvicorn: ``uvicorn app.main:get_app --factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
