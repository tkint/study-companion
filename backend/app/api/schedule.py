"""JSON routes of the timed study schedule (``app.planner.schedule``): the published
schedule, a preview of unsaved settings, and saving them (which publishes a new schedule,
so the calendar feed ``/calendar.ics`` follows). Session cookie required; writes also
check the origin."""

from __future__ import annotations

import json
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from app.config import Settings
from app.planner import published, schedule

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
        return JSONResponse(published.current(settings, engine))

    @app.post("/api/schedule/preview")
    async def schedule_preview(request: Request) -> JSONResponse:
        """The schedule unsaved settings would give; nothing is saved."""
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request)
        if data is None:
            return JSONResponse({"error": "send a JSON object"}, status_code=400)
        try:
            return JSONResponse(published.preview(settings, engine, data))
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
        return JSONResponse(published.publish(settings, engine))
