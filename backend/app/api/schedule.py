"""JSON routes of the timed study schedule (``app.planner.schedule``): the published
schedule, a preview of unsaved settings, and saving them (which publishes a new schedule,
so the calendar feed ``/calendar.ics`` follows). Session cookie required; writes also
check the origin."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.engine import Engine

from app.config import Settings
from app.db import session
from app.models import Site
from app.api import ui
from app.planner import print_week, published, schedule

MAX_BODY = 32768  # room for 50 weekly and 100 dated unavailabilities


def register(
    app: FastAPI,
    settings: Settings,
    engine: Engine,
    is_authenticated: Callable[[Request], bool],
    same_origin: Callable[[Request], bool],
) -> None:
    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "not signed in"}, status_code=401)

    def with_owner(data: dict) -> dict:
        """Your name on Moodle, for the header of the printed weeks."""
        with session(engine) as s:
            site = s.get(Site, 1)
        return {**data, "owner": site.fullname if site else ""}

    async def body(request: Request) -> dict | None:
        raw = await request.body()
        try:
            data = json.loads(raw) if len(raw) <= MAX_BODY else None
        except ValueError:
            data = None
        return data if isinstance(data, dict) else None

    @app.get("/api/schedule")
    async def get_schedule(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse(with_owner(published.current(settings, engine)))

    @app.post("/api/schedule/preview")
    async def schedule_preview(request: Request) -> JSONResponse:
        """The schedule unsaved settings would give; nothing is saved."""
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request)
        if data is None:
            return JSONResponse({"error": "send a JSON object"}, status_code=400)
        try:
            return JSONResponse(with_owner(published.preview(settings, engine, data)))
        except schedule.ScheduleError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/schedule/settings")
    async def schedule_settings(request: Request) -> JSONResponse:
        """Save any subset of the settings (``schedule.DEFAULTS`` plus ``daily_hours``) and
        publish the schedule they give. Returns the published schedule."""
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request)
        if data is None:
            return JSONResponse({"error": "send a JSON object"}, status_code=400)
        try:
            schedule.save(engine, data)
        except schedule.ScheduleError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(with_owner(published.publish(settings, engine)))

    @app.get("/api/schedule.pdf")
    async def schedule_pdf(request: Request) -> Response:
        """The saved schedule as a PDF, one page per week: ``from`` (a date in the first week,
        default this week), ``weeks`` (1-8), ``deadlines`` and ``busy`` (0 to leave out)."""
        if not is_authenticated(request):
            return unauthorized()
        q = request.query_params
        now = int(time.time())
        today = datetime.fromtimestamp(now, settings.tz).date()
        try:
            first = date.fromisoformat(q.get("from") or today.isoformat())
            weeks = int(q.get("weeks") or 1)
        except ValueError:
            return JSONResponse({"error": "from is YYYY-MM-DD, weeks 1 to 8"}, status_code=400)
        if not 1 <= weeks <= print_week.MAX_WEEKS:
            return JSONResponse({"error": "weeks must be 1 to 8"}, status_code=400)
        monday = first - timedelta(days=first.weekday())
        start = int(datetime(monday.year, monday.month, monday.day, tzinfo=settings.tz).timestamp())
        end = start + weeks * 7 * 86400 + 3600
        plan = with_owner(published.current(settings, engine, now=now))
        deadlines = ui.deadlines(engine, start=start - 86400, end=end + 86400, now=now,
                                 include_ignored=False)
        body = print_week.render(plan, deadlines, monday, weeks, settings.tz, owner=plan["owner"],
                                 printed=today, with_deadlines=q.get("deadlines") != "0",
                                 with_busy=q.get("busy") != "0")
        return Response(body, media_type="application/pdf", headers={
            "Content-Disposition": f'inline; filename="study-plan-{monday.isoformat()}.pdf"',
            "Cache-Control": "private, no-store",
        })
