"""JSON routes for the study loop: notes, questions (flashcards), quiz results, the
catch-up plan and its settings. Session cookie required; writes also check the origin."""

from __future__ import annotations

import json
import time
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from app import catchup, study
from app.config import Settings
from app.db import session
from app.models import Course
from app.planner import Planner

MAX_BODY = 8192


def register(
    app: FastAPI,
    settings: Settings,
    engine: Engine,
    is_authenticated: Callable[[Request], bool],
    same_origin: Callable[[Request], bool],
) -> None:
    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "not signed in"}, status_code=401)

    def bad(message: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    def not_found() -> JSONResponse:
        return bad("not found", 404)

    async def body(request: Request) -> dict | None:
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return None
        try:
            data = json.loads(raw or b"null")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def int_param(request: Request, name: str) -> int | None:
        value = request.query_params.get(name, "")
        return int(value) if value.isdigit() else None

    @app.get("/api/courses/{course_id}/study")
    async def course_study(request: Request, course_id: int) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        with session(engine) as s:
            if s.get(Course, course_id) is None:
                return not_found()
        return JSONResponse(study.course_study(engine, course_id))

    @app.get("/api/study")
    async def study_cards(request: Request) -> JSONResponse:
        """Cards to review: due ones (default) or all with ``all=1``, for a course/section."""
        if not is_authenticated(request):
            return unauthorized()
        now = int(time.time())
        course_id, section_id = int_param(request, "course"), int_param(request, "section")
        rows = study.questions(engine, course_id, section_id,
                               due_only=request.query_params.get("all") != "1", now=now)
        return JSONResponse({
            "now": now,
            "questions": [study.question_dict(q, now) for q in rows[:200]],
            "overview": study.overview(engine, now),
        })

    @app.post("/api/study/questions/{question_id}/review")
    async def review(request: Request, question_id: int) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request)
        if data is None or not isinstance(data.get("grade"), int):
            return bad('send {"grade": 0-3}')
        try:
            q = study.review(engine, question_id, data["grade"])
        except study.StudyError as exc:
            return bad(str(exc), 404 if "no question" in str(exc) else 400)
        return JSONResponse(study.question_dict(q, int(time.time())))

    @app.delete("/api/study/questions/{question_id}")
    async def delete_question(request: Request, question_id: int) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        return JSONResponse({"deleted": question_id}) if study.delete_question(engine, question_id) else not_found()

    @app.delete("/api/study/notes/{note_id}")
    async def delete_note(request: Request, note_id: int) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        return JSONResponse({"deleted": note_id}) if study.delete_note(engine, note_id) else not_found()

    @app.post("/api/study/results")
    async def save_result(request: Request) -> JSONResponse:
        """A finished flashcard session in the web UI."""
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request)
        if data is None:
            return bad("send a JSON object")
        try:
            result, _ = study.record_result(
                engine, data.get("score"), data.get("total"), data.get("course_id"),
                data.get("section_id"), data.get("topic") or "", source="web")
        except study.StudyError as exc:
            return bad(str(exc))
        return JSONResponse(study.result_dict(result), status_code=201)

    @app.delete("/api/study/results/{result_id}")
    async def delete_result(request: Request, result_id: int) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        return JSONResponse({"deleted": result_id}) if study.delete_result(engine, result_id) else not_found()

    @app.post("/api/sections/{section_id}/studied")
    async def studied(request: Request, section_id: int) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request)
        if data is None or not isinstance(data.get("studied"), bool):
            return bad('send {"studied": true|false}')
        if not study.set_studied(engine, section_id, data["studied"]):
            return not_found()
        return JSONResponse({"id": section_id, "studied": data["studied"]})

    @app.get("/api/plan")
    async def plan(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        days = int_param(request, "days") or 14
        flag = lambda name: request.query_params.get(name) == "1"  # noqa: E731
        return JSONResponse(Planner(settings, engine).plan(
            int_param(request, "course"), days=min(max(days, 1), 90),
            include_optional=flag("optional"), beyond_target=flag("beyond")).to_dict())

    @app.post("/api/plan/settings")
    async def plan_settings(request: Request) -> JSONResponse:
        """``{"hours_per_day": 2}`` and/or ``{"target_percent": 60}``."""
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request) or {}
        hours, target = data.get("hours_per_day"), data.get("target_percent")
        if hours is None and target is None:
            return bad('send {"hours_per_day": 2} or {"target_percent": 60}')
        out: dict = {}
        try:
            if hours is not None:
                if not isinstance(hours, (int, float)) or isinstance(hours, bool):
                    return bad('send {"hours_per_day": 2}')
                out["hours_per_day"] = study.set_hours_per_day(engine, float(hours))
            if target is not None:
                out["target_percent"] = catchup.set_target_percent(engine, target)
        except (study.StudyError, catchup.PrefError) as exc:
            return bad(str(exc))
        return JSONResponse(out)

    async def set_pref(request: Request, kind: str, item_id: int) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        data = await body(request)
        if not data or not ({"ignored", "criticality"} & data.keys()):
            return bad('send {"ignored": true|false} and/or '
                       '{"criticality": "mandatory"|"optional"|null}')
        try:
            pref = catchup.set_pref(engine, kind, item_id,
                                    ignored=data.get("ignored", catchup.UNSET),
                                    criticality=data.get("criticality", catchup.UNSET))
        except catchup.PrefError as exc:
            return bad(str(exc))
        if pref is None:
            return not_found()
        return JSONResponse({"id": item_id, "ignored": pref.ignored_at is not None,
                             "criticality": pref.criticality or None})

    @app.post("/api/deadlines/{deadline_id}/prefs")
    async def deadline_prefs(request: Request, deadline_id: int) -> JSONResponse:
        """Ignore a deadline or set it mandatory / optional (null: automatic)."""
        return await set_pref(request, "deadline", deadline_id)

    @app.post("/api/sections/{section_id}/prefs")
    async def section_prefs(request: Request, section_id: int) -> JSONResponse:
        return await set_pref(request, "section", section_id)
