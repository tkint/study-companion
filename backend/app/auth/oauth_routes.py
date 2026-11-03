"""HTTP endpoints of the OAuth server (see ``app.auth.oauth``).

Discovery, registration, token and revocation endpoints are called by Claude's servers (or
a browser-based client), so they accept cross-site requests and send CORS headers. Only the
consent form, which lives on this site, gets the same-origin check.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Callable
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.engine import Engine

from app import accounts
from app.auth import oauth
from app.auth.pages import consent_page, oauth_error_page
from app.auth.session import LoginThrottle
from app.config import Settings

logger = logging.getLogger("app.oauth")

MAX_BODY = 16384
CORS_PREFIXES = ("/.well-known/oauth-", "/oauth/token", "/oauth/register", "/oauth/revoke", "/mcp")
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
AUTHORIZE_FIELDS = ("response_type", "client_id", "redirect_uri", "code_challenge",
                    "code_challenge_method", "state", "scope", "resource")


def cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, mcp-protocol-version, "
                                        "mcp-session-id, last-event-id",
        "Access-Control-Expose-Headers": "WWW-Authenticate, mcp-session-id, mcp-protocol-version",
        "Access-Control-Max-Age": "86400",
    }


def wants_cors(path: str) -> bool:
    return path.startswith(CORS_PREFIXES)


def _error(exc: oauth.OAuthError) -> JSONResponse:
    headers = dict(NO_STORE)
    if exc.status == 401:
        headers["WWW-Authenticate"] = 'Basic realm="oauth"'
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


def _redirect_hosts(data: object) -> str:
    """The hosts of the redirect URIs a client sent, for the log: hosts only, never full
    URIs, so the owner can see what to add to OAUTH_REDIRECT_HOSTS."""
    uris = data.get("redirect_uris") if isinstance(data, dict) else None
    hosts: set[str] = set()
    for uri in uris if isinstance(uris, list) else []:
        try:
            hosts.add((urlsplit(uri).hostname or "?")[:100] if isinstance(uri, str) else "?")
        except ValueError:
            hosts.add("?")
    return ", ".join(sorted(hosts)[:10]) or "none"


def _with_query(uri: str, params: dict[str, str]) -> str:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(params.items())
    return urlunsplit(parts._replace(query=urlencode(query)))


async def _form(request: Request) -> dict[str, str] | None:
    body = await request.body()
    if len(body) > MAX_BODY:
        return None
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace"), max_num_fields=30).items()}


def _basic_auth(request: Request) -> tuple[str | None, str | None]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None, None
    try:
        raw = base64.b64decode(header[6:].strip()).decode()
    except (ValueError, UnicodeDecodeError):
        return None, None
    user, _, password = raw.partition(":")
    return unquote(user), unquote(password)


def register(
    app: FastAPI,
    settings: Settings,
    engine: Engine,
    is_authenticated: Callable[[Request], bool],
    same_origin: Callable[[Request], bool],
    throttle: LoginThrottle,
    client_key: Callable[[Request], str],
) -> None:
    registrations = LoginThrottle(20, 3600)

    def base(request: Request) -> str:
        return settings.public_url(str(request.base_url))

    # ------------------------------------------------------------------ discovery

    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_resource(request: Request) -> JSONResponse:
        return JSONResponse(oauth.resource_metadata(base(request)))

    @app.get("/.well-known/oauth-authorization-server")
    @app.get("/.well-known/oauth-authorization-server/mcp")
    async def authorization_server(request: Request) -> JSONResponse:
        return JSONResponse(oauth.metadata(base(request)))

    # ------------------------------------------------------------------ registration

    @app.post("/oauth/register")
    async def register_client(request: Request) -> JSONResponse:
        key = client_key(request)
        if registrations.is_blocked(key):
            return _error(oauth.OAuthError("slow_down", "too many registrations", 429))
        body = await request.body()
        if len(body) > MAX_BODY:
            return _error(oauth.OAuthError("invalid_client_metadata", "request too large"))
        try:
            data = json.loads(body or b"null")
        except ValueError:
            data = None
        try:
            out = oauth.register_client(engine, data, settings.oauth_redirect_hosts)
        except oauth.OAuthError as exc:
            logger.warning("Client registration refused: %s (redirect hosts: %s)",
                           exc.description, _redirect_hosts(data))
            return _error(exc)
        registrations.record_failure(key)  # counts registrations per client IP
        logger.info("OAuth client registered: %r", out["client_name"])
        return JSONResponse(out, status_code=201, headers=NO_STORE)

    # ------------------------------------------------------------------ authorization

    def check_request(params: dict[str, str], request: Request):
        """Validate an authorization request. Returns (AuthRequest, None) or (None, response):
        errors about the client or redirect URI are shown here, never redirected."""
        client = oauth.get_client(engine, params.get("client_id"))
        if client is None:
            return None, HTMLResponse(oauth_error_page(
                "This connection is not registered (unknown client). The server may have been "
                "reset."), status_code=400)
        redirect_uri = oauth.pick_redirect(client, params.get("redirect_uri"))
        if redirect_uri is None:
            return None, HTMLResponse(oauth_error_page("The redirect address does not match the "
                                                       "registered one."), status_code=400)
        state = params.get("state", "")

        def fail(error: str, description: str):
            return None, RedirectResponse(_with_query(redirect_uri, {
                "error": error, "error_description": description, "state": state,
                "iss": base(request)}), status_code=303)

        if params.get("response_type") != "code":
            return fail("unsupported_response_type", "only response_type=code is supported")
        challenge = params.get("code_challenge", "")
        if not challenge or params.get("code_challenge_method") != "S256":
            return fail("invalid_request", "PKCE with code_challenge_method=S256 is required")
        if not (43 <= len(challenge) <= 128):
            return fail("invalid_request", "invalid code_challenge")
        resource = params.get("resource", "")
        if not oauth.resource_ok(resource, base(request)):
            return fail("invalid_target", "unknown resource")
        return oauth.AuthRequest(client, redirect_uri, challenge, state,
                                 params.get("scope", ""), resource), None

    def consent(req: oauth.AuthRequest, params: dict[str, str], request: Request,
                error: str = "", status: int = 200) -> HTMLResponse:
        hidden = {k: params[k] for k in AUTHORIZE_FIELDS if params.get(k)}
        return HTMLResponse(
            consent_page(
                client_name=req.client.name,
                redirect_host=urlsplit(req.redirect_uri).hostname or req.redirect_uri,
                hidden=hidden,
                signed_in=is_authenticated(request),
                error=error,
            ),
            status_code=status,
            headers={"Content-Security-Policy": "frame-ancestors 'none'", **NO_STORE},
        )

    @app.get("/oauth/authorize")
    async def authorize(request: Request) -> Response:
        params = {k: v for k, v in request.query_params.items() if k in AUTHORIZE_FIELDS}
        req, problem = check_request(params, request)
        if problem is not None:
            return problem
        return consent(req, params, request)

    @app.post("/oauth/authorize")
    async def authorize_decision(request: Request) -> Response:
        if not same_origin(request):
            return HTMLResponse(oauth_error_page("Blocked a request that did not come from this "
                                                 "site."), status_code=403)
        form = await _form(request)
        if form is None:
            return HTMLResponse(oauth_error_page("Request too large."), status_code=413)
        params = {k: v for k, v in form.items() if k in AUTHORIZE_FIELDS}
        req, problem = check_request(params, request)
        if problem is not None:
            return problem
        if form.get("decision") != "allow":
            return RedirectResponse(_with_query(req.redirect_uri, {
                "error": "access_denied", "error_description": "the user cancelled",
                "state": req.state, "iss": base(request)}), status_code=303)
        if not is_authenticated(request):
            key = client_key(request)
            if throttle.is_blocked(key):
                return consent(req, params, request,
                               "Too many failed attempts. Try again in a few minutes.", 429)
            if not accounts.verify_password(engine, form.get("password", "")):
                throttle.record_failure(key)
                logger.warning("Failed connector sign-in from %s", key)
                return consent(req, params, request, "Wrong password.", 401)
            throttle.reset(key)
        code = oauth.create_code(engine, req)
        logger.info("Connector authorized for client %r", req.client.name)
        return RedirectResponse(_with_query(req.redirect_uri, {
            "code": code, "state": req.state, "iss": base(request)}), status_code=303)

    # ------------------------------------------------------------------ tokens

    @app.post("/oauth/token")
    async def token(request: Request) -> JSONResponse:
        form = await _form(request)
        if form is None:
            return _error(oauth.OAuthError("invalid_request", "request too large"))
        basic_id, basic_secret = _basic_auth(request)
        client_id = basic_id or form.get("client_id")
        client = oauth.get_client(engine, client_id)
        try:
            oauth.authenticate_client(client, basic_secret or form.get("client_secret"))
            grant = form.get("grant_type")
            if grant == "authorization_code":
                out = oauth.exchange_code(
                    engine, client, form.get("code", ""), form.get("redirect_uri"),
                    form.get("code_verifier", ""), settings.oauth_access_ttl,
                    settings.oauth_refresh_ttl,
                )
            elif grant == "refresh_token":
                out = oauth.refresh_tokens(
                    engine, client, form.get("refresh_token", ""), settings.oauth_access_ttl,
                    settings.oauth_refresh_ttl,
                )
            else:
                raise oauth.OAuthError("unsupported_grant_type",
                                       "use authorization_code or refresh_token")
        except oauth.OAuthError as exc:
            if exc.error != "invalid_grant" or form.get("grant_type") != "refresh_token":
                logger.warning("Token request refused: %s", exc.error)
            return _error(exc)
        return JSONResponse(out, headers=NO_STORE)

    @app.post("/oauth/revoke")
    async def revoke(request: Request) -> Response:
        form = await _form(request) or {}
        basic_id, basic_secret = _basic_auth(request)
        client = oauth.get_client(engine, basic_id or form.get("client_id"))
        try:
            oauth.authenticate_client(client, basic_secret or form.get("client_secret"))
        except oauth.OAuthError as exc:
            return _error(exc)
        oauth.revoke(engine, form.get("token", ""), client)
        return Response(status_code=200, headers=NO_STORE)
