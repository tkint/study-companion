"""JSON routes for the React UI, file downloads and the ICS feed.

All routes need the session cookie, except ``/calendar.ics`` which also accepts the secret
feed token (calendar apps can't sign in). State-changing routes also check that the
request came from this site.
"""

from __future__ import annotations

import json
import mimetypes
import time
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.engine import Engine

from app import reminders, stats, study, teacher_pages
from app.api import ics, ui
from app.config import Settings
from app.db import session
from app.models import CourseImage, File
from app.moodle.names import UnsafePathError, safe_join
from app.planner import Planner, published

# Shown in the browser. Everything else downloads: Moodle HTML or SVG served inline from
# this origin could run scripts with your session.
INLINE_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
}
MAX_RANGE_DAYS = 400


def _int_param(request: Request, name: str) -> int | None:
    value = request.query_params.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def register(
    app: FastAPI,
    settings: Settings,
    engine: Engine,
    is_authenticated: Callable[[Request], bool],
    same_origin: Callable[[Request], bool],
) -> None:
    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "not signed in"}, status_code=401)

    def not_found() -> JSONResponse:
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/api/dashboard")
    async def dashboard(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        sync = app.state.sync
        run = sync.last_run()
        data = ui.dashboard(engine)
        data["sync"] = {
            "configured": sync.configured(),
            "running": sync.running,
            "last_run": run.model_dump() if run else None,
        }
        data["version"] = settings.version
        data["study"] = study.overview(engine)
        data["stats"] = stats.stats(engine, settings.tz)
        plan = Planner(settings, engine).plan(days=7).to_dict()
        data["plan"] = {k: plan[k] for k in ("hours_per_day", "total_minutes", "sections_left",
                                             "sections_done", "late", "target_percent",
                                             "projected_percent", "optional_left_out", "ignored")}
        data["catch_up"] = plan["progress"]
        data["plan"]["today"] = plan["days"][0] if plan["days"] and plan["days"][0]["date"] == plan["today"] else None
        return JSONResponse(data)

    @app.get("/api/courses/{course_id}")
    async def course(request: Request, course_id: int) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        data = ui.course_detail(engine, course_id)
        return JSONResponse(data) if data else not_found()

    @app.get("/api/deadlines")
    async def deadlines(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        start, end = _int_param(request, "from"), _int_param(request, "to")
        if start is None or end is None or end <= start or end - start > MAX_RANGE_DAYS * 86400:
            return JSONResponse(
                {"error": f"from and to (Unix seconds) are required, at most {MAX_RANGE_DAYS} days apart"},
                status_code=400,
            )
        return JSONResponse({"deadlines": ui.deadlines(engine, start, end)})

    @app.post("/api/deadlines/{deadline_id}/done")
    async def mark_done(request: Request, deadline_id: int) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("done"), bool):
            return JSONResponse({"error": 'send {"done": true|false}'}, status_code=400)
        if not ui.set_done(engine, deadline_id, body["done"]):
            return not_found()
        return JSONResponse({"id": deadline_id, "done": body["done"]})

    # ------------------------------------------------------------------ files

    @app.get("/api/files/{file_id}")
    async def file_info(request: Request, file_id: int) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        with session(engine) as s:
            f = s.get(File, file_id)
        if f is None:
            return not_found()
        title = teacher_pages.titles(engine, [f]).get(f.id)
        return JSONResponse({**ui.file_dict(f, title), "course_id": f.course_id,
                             "module_id": f.module_id})

    @app.get("/api/files/{file_id}/page")
    async def file_page(request: Request, file_id: int) -> JSONResponse:
        """A teacher page (Moodle page or book chapter) as sanitised HTML for the viewer."""
        if not is_authenticated(request):
            return unauthorized()
        data = teacher_pages.render(engine, settings.data_dir, file_id)
        return JSONResponse(data) if data else not_found()

    @app.get("/files/{file_id}/{name:path}")
    @app.get("/files/{file_id}")
    async def get_file(request: Request, file_id: int, name: str = "") -> Response:
        if not is_authenticated(request):
            return unauthorized()
        with session(engine) as s:
            f = s.get(File, file_id)
        if f is None or f.status != "ok" or not f.local_path:
            return not_found()
        try:
            path = safe_join(settings.data_dir, f.local_path)
        except UnsafePathError:
            return not_found()
        if not path.is_file():
            return not_found()
        media_type = (f.mimetype or mimetypes.guess_type(f.filename)[0] or "").lower()
        inline = media_type in INLINE_TYPES and request.query_params.get("download") != "1"
        headers = {
            # Defence in depth: even if a browser renders the file, no scripts, no plugins.
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        }
        return FileResponse(
            path,
            media_type=media_type if inline else "application/octet-stream",
            filename=f.filename,
            content_disposition_type="inline" if inline else "attachment",
            headers=headers,
        )

    @app.get("/course-images/{course_id}")
    async def course_image(request: Request, course_id: int) -> Response:
        if not is_authenticated(request):
            return unauthorized()
        with session(engine) as s:
            img = s.get(CourseImage, course_id)
        # Only raster types checked from the bytes at sync time (never SVG or HTML).
        if img is None or img.status != "ok" or img.mimetype not in INLINE_TYPES or not img.local_path:
            return not_found()
        try:
            path = safe_join(settings.data_dir, img.local_path)
        except UnsafePathError:
            return not_found()
        if not path.is_file():
            return not_found()
        return FileResponse(
            path,
            media_type=img.mimetype,
            headers={
                "Content-Security-Policy": "sandbox; default-src 'none'",
                "X-Content-Type-Options": "nosniff",
                # The URL carries a version (?v=), so it can be cached for long.
                "Cache-Control": "private, max-age=604800",
            },
        )

    # ------------------------------------------------------------------ calendar

    def feed_urls(request: Request) -> dict:
        token = ics.feed_token(engine, settings.secret_key)
        base = str(request.base_url).rstrip("/")
        url = f"{base}/calendar.ics?token={token}"
        return {"url": url, "webcal": "webcal://" + url.split("://", 1)[1]}

    @app.get("/api/calendar/feed")
    async def calendar_feed(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse(feed_urls(request))

    @app.post("/api/calendar/feed")
    async def calendar_feed_rotate(request: Request) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        ics.rotate_feed(engine)
        return JSONResponse(feed_urls(request))

    @app.get("/api/reminders")
    async def reminders_today(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse(reminders.today(engine, settings))

    @app.post("/api/reminders/settings")
    async def reminders_settings(request: Request) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        raw = await request.body()
        try:
            data = json.loads(raw) if len(raw) <= 4096 else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return JSONResponse({"error": "send a JSON object"}, status_code=400)
        try:
            return JSONResponse(reminders.set_prefs(engine, data))
        except reminders.ReminderError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/calendar.ics")
    async def calendar_ics(request: Request) -> Response:
        token = request.query_params.get("token")
        if not (is_authenticated(request) or ics.check_feed_token(engine, settings.secret_key, token)):
            return Response("Not found", status_code=404, media_type="text/plain")
        now = int(time.time())
        items = ui.deadlines(engine, start=now - ui.OVERDUE_DAYS * 86400, now=now,
                             include_ignored=False)
        prefs = reminders.prefs(engine)
        plan = published.current(settings, engine, now=now)
        headers = {"Cache-Control": "private, max-age=900"}
        if request.query_params.get("download") == "1":
            headers["Content-Disposition"] = (
                f'attachment; filename="study-calendar-{plan["today"]}.ics"')
        return Response(
            ics.build_ics(items, now=now, alarms=prefs["deadline_alarms"], plan=plan,
                          base_url=str(request.base_url),
                          day_alarm=prefs["daily_enabled"], tz=settings.tz),
            media_type="text/calendar; charset=utf-8",
            headers=headers,
        )
