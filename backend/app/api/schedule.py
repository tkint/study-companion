"""JSON routes of the timed study schedule (``app.planner.schedule``) and its ``.ics``
download. Session cookie required; writes also check the origin."""

from __future__ import annotations

import json
import time
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.engine import Engine

from app.api import ics
from app.config import Settings
from app.planner import schedule

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

    @app.get("/api/schedule")
    async def get_schedule(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse(schedule.Generator(settings, engine).generate().to_dict())

    @app.post("/api/schedule/settings")
    async def schedule_settings(request: Request) -> JSONResponse:
        """Any subset of the settings (``schedule.DEFAULTS`` plus ``daily_hours``)."""
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        raw = await request.body()
        try:
            data = json.loads(raw) if len(raw) <= MAX_BODY else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return JSONResponse({"error": "send a JSON object"}, status_code=400)
        try:
            return JSONResponse(schedule.save(engine, data))
        except schedule.ScheduleError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/schedule.ics")
    async def schedule_ics(request: Request) -> Response:
        if not is_authenticated(request):
            return unauthorized()
        now = int(time.time())
        plan = schedule.Generator(settings, engine, now=now).generate()
        body = ics.build_schedule_ics([b.to_dict() for b in plan.blocks],
                                      str(request.base_url), now=now)
        return Response(body, media_type="text/calendar; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="study-schedule-{plan.today}.ics"',
            "Cache-Control": "private, no-store",
        })
