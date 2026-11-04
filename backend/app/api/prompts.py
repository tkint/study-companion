"""JSON routes for the prompt builder page and the template editor (session cookie required)."""

from __future__ import annotations

import json
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from app import prompts
from app.config import Settings
from app.mcp_tools import TOOL_NAMES
from app.prompts import store

MAX_BODY = 8192
MAX_TEMPLATE_BODY = 4 * store.MAX_CHARS + 1024  # JSON escaping can grow the text


def register(
    app: FastAPI,
    settings: Settings,
    engine: Engine,
    is_authenticated: Callable[[Request], bool],
    same_origin: Callable[[Request], bool],
) -> None:
    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "not signed in"}, status_code=401)

    @app.get("/api/prompt/options")
    async def prompt_options(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse(prompts.Builder(settings, engine).options())

    @app.post("/api/prompt/build")
    async def prompt_build(request: Request) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        body = await request.body()
        if len(body) > MAX_BODY:
            return JSONResponse({"error": "request too large"}, status_code=413)
        try:
            data = json.loads(body or b"null")
        except ValueError:
            data = None
        try:
            req = prompts.Request.from_json(data)
            return JSONResponse(prompts.Builder(settings, engine).build(req))
        except prompts.PromptError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    # -- template editor

    @app.get("/api/prompt/templates")
    async def template_list(request: Request) -> JSONResponse:
        if not is_authenticated(request):
            return unauthorized()
        return JSONResponse({
            "templates": store.listing(engine),
            "variables": list(store.VARIABLES),
            "flags": list(store.FLAGS),
            "tools": list(TOOL_NAMES),
        })

    async def template_text(request: Request) -> str | JSONResponse:
        body = await request.body()
        if len(body) > MAX_TEMPLATE_BODY:
            return JSONResponse({"error": "the template is too long"}, status_code=413)
        try:
            data = json.loads(body or b"null")
        except ValueError:
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            return JSONResponse({"error": "send {\"text\": ...}"}, status_code=400)
        return data["text"]

    @app.post("/api/prompt/templates/{template_id}/check")
    async def template_check(template_id: str, request: Request) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        text = await template_text(request)
        if isinstance(text, JSONResponse):
            return text
        return JSONResponse({"problems": store.validate(template_id, text)})

    @app.put("/api/prompt/templates/{template_id}")
    async def template_save(template_id: str, request: Request) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        text = await template_text(request)
        if isinstance(text, JSONResponse):
            return text
        try:
            store.save(engine, template_id, text)
        except store.TemplateError as exc:
            status = 404 if str(exc) == "unknown template" else 400
            return JSONResponse({"error": str(exc)}, status_code=status)
        return JSONResponse(_one(template_id))

    @app.delete("/api/prompt/templates/{template_id}")
    async def template_reset(template_id: str, request: Request) -> JSONResponse:
        if not is_authenticated(request) or not same_origin(request):
            return unauthorized()
        if template_id not in prompts.default_sources():
            return JSONResponse({"error": "unknown template"}, status_code=404)
        store.reset(engine, template_id)
        return JSONResponse(_one(template_id))

    def _one(template_id: str) -> dict:
        return next(t for t in store.listing(engine) if t["id"] == template_id)
