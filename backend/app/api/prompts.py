"""JSON routes for the prompt builder page (session cookie required)."""

from __future__ import annotations

import json
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from app import prompts
from app.config import Settings

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
