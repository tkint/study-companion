"""OAuth 2.1 authorization server for the MCP connector (single user).

What claude.ai custom connectors need: protected resource metadata (RFC 9728), server
metadata discovery (RFC 8414), dynamic client registration (RFC 7591), the authorization
code flow with PKCE S256 only, refresh token rotation and revocation (RFC 7009).

Sign-in uses the web UI password (or an existing web UI session). Codes and tokens are
random, stored only as SHA-256 hashes, and short-lived (access tokens one hour by default).
Redirect URIs must use a host from OAUTH_REDIRECT_HOSTS (claude.ai, claude.com and
localhost by default), so nobody can register a client that sends codes elsewhere.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.engine import Engine
from sqlmodel import col, delete, select

from app.db import session
from app.models import OAuthClient, OAuthCode, OAuthToken

SCOPE = "study"
CODE_TTL = 300
MAX_CLIENTS = 50
MAX_REDIRECT_URIS = 10
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
AUTH_METHODS = {"none", "client_secret_post", "client_secret_basic"}


class OAuthError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400) -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description
        self.status = status

    def body(self) -> dict:
        out = {"error": self.error}
        if self.description:
            out["error_description"] = self.description
        return out


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now(now: int | None) -> int:
    return int(now if now is not None else time.time())


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def redirect_allowed(uri: str, allowed_hosts: tuple[str, ...]) -> bool:
    try:
        parts = urlsplit(uri)
        host = (parts.hostname or "").lower()
        port = parts.port  # raises ValueError for a bad port
    except ValueError:
        return False
    del port
    if parts.fragment or parts.username or parts.password or not host:
        return False
    if host not in allowed_hosts:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and host in LOCAL_HOSTS


def metadata(base: str) -> dict:
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": sorted(AUTH_METHODS),
        "revocation_endpoint_auth_methods_supported": sorted(AUTH_METHODS),
        "scopes_supported": [SCOPE],
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": "https://github.com/tkint/study-companion/blob/main/docs/connector.md",
    }


def resource_metadata(base: str) -> dict:
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Study Companion",
        "resource_documentation": "https://github.com/tkint/study-companion/blob/main/docs/connector.md",
    }


def resource_ok(resource: str, base: str) -> bool:
    """RFC 8707 resource indicator: this server's MCP endpoint (or its origin)."""
    return not resource or resource.rstrip("/") in {base, f"{base}/mcp"}


# ---------------------------------------------------------------------- clients


def register_client(engine: Engine, data: object, allowed_hosts: tuple[str, ...],
                    now: int | None = None) -> dict:
    if not isinstance(data, dict):
        raise OAuthError("invalid_client_metadata", "send the client metadata as a JSON object")
    uris = data.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECT_URIS or not all(
        isinstance(u, str) and len(u) <= 2000 for u in uris
    ):
        raise OAuthError("invalid_redirect_uri", "redirect_uris must be a list of URLs")
    for uri in uris:
        if not redirect_allowed(uri, allowed_hosts):
            raise OAuthError(
                "invalid_redirect_uri",
                f"redirect URI not allowed: hosts allowed are {', '.join(allowed_hosts)} "
                "(set OAUTH_REDIRECT_HOSTS on the server to change this)",
            )
    method = data.get("token_endpoint_auth_method") or "none"
    if method not in AUTH_METHODS:
        raise OAuthError("invalid_client_metadata",
                         f"token_endpoint_auth_method must be one of {', '.join(sorted(AUTH_METHODS))}")
    grants = data.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grants, list) or "authorization_code" not in grants or not set(grants) <= {
        "authorization_code", "refresh_token"
    }:
        raise OAuthError("invalid_client_metadata",
                         "grant_types must include authorization_code (and optionally refresh_token)")
    responses = data.get("response_types") or ["code"]
    if responses != ["code"]:
        raise OAuthError("invalid_client_metadata", 'response_types must be ["code"]')
    name = data.get("client_name")
    name = " ".join(name.split())[:100] if isinstance(name, str) else ""
    now = _now(now)
    client = OAuthClient(
        id=secrets.token_urlsafe(18),
        name=name,
        redirect_uris="\n".join(uris),
        auth_method=method,
        created_at=now,
    )
    secret = ""
    if method != "none":
        secret = secrets.token_urlsafe(32)
        client.secret_hash = _hash(secret)
    with session(engine) as s:
        _prune_clients(s)
        s.add(client)
        s.commit()
    out = {
        "client_id": client.id,
        "client_id_issued_at": now,
        "client_name": name,
        "redirect_uris": uris,
        "token_endpoint_auth_method": method,
        "grant_types": grants,
        "response_types": ["code"],
        "scope": SCOPE,
    }
    if secret:
        out["client_secret"] = secret
        out["client_secret_expires_at"] = 0
    return out


def _prune_clients(s) -> None:
    """Keep at most MAX_CLIENTS: drop the oldest clients that hold no tokens."""
    clients = s.exec(select(OAuthClient).order_by(OAuthClient.created_at)).all()
    excess = len(clients) - MAX_CLIENTS + 1
    if excess <= 0:
        return
    active = {t.client_id for t in s.exec(select(OAuthToken)).all()}
    for c in clients:
        if excess <= 0:
            break
        if c.id not in active:
            s.delete(c)
            excess -= 1


def get_client(engine: Engine, client_id: str | None) -> OAuthClient | None:
    if not client_id or len(client_id) > 100:
        return None
    with session(engine) as s:
        return s.get(OAuthClient, client_id)


def client_redirects(client: OAuthClient) -> list[str]:
    return [u for u in client.redirect_uris.split("\n") if u]


def pick_redirect(client: OAuthClient, redirect_uri: str | None) -> str | None:
    uris = client_redirects(client)
    if not redirect_uri:
        return uris[0] if len(uris) == 1 else None
    return redirect_uri if redirect_uri in uris else None


def authenticate_client(client: OAuthClient | None, secret: str | None) -> None:
    if client is None:
        raise OAuthError("invalid_client", "unknown client", 401)
    if client.auth_method == "none":
        return
    if not secret or not hmac.compare_digest(_hash(secret), client.secret_hash):
        raise OAuthError("invalid_client", "client authentication failed", 401)


# ---------------------------------------------------------------------- codes and tokens


@dataclass(frozen=True)
class AuthRequest:
    client: OAuthClient
    redirect_uri: str
    code_challenge: str
    state: str
    scope: str
    resource: str


def create_code(engine: Engine, req: AuthRequest, now: int | None = None) -> str:
    code = secrets.token_urlsafe(32)
    with session(engine) as s:
        s.add(OAuthCode(
            code_hash=_hash(code), client_id=req.client.id, redirect_uri=req.redirect_uri,
            code_challenge=req.code_challenge, scope=SCOPE, resource=req.resource,
            expires_at=_now(now) + CODE_TTL,
        ))
        s.commit()
    return code


def _issue(s, client_id: str, scope: str, resource: str, access_ttl: int, refresh_ttl: int,
           now: int) -> dict:
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    s.add(OAuthToken(token_hash=_hash(access), kind="access", client_id=client_id, scope=scope,
                     resource=resource, expires_at=now + access_ttl, created_at=now))
    s.add(OAuthToken(token_hash=_hash(refresh), kind="refresh", client_id=client_id, scope=scope,
                     resource=resource, expires_at=now + refresh_ttl, created_at=now))
    client = s.get(OAuthClient, client_id)
    if client is not None:
        client.last_used_at = now
        s.add(client)
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": access_ttl,
        "refresh_token": refresh,
        "scope": scope,
    }


def _prune(s, now: int) -> None:
    s.exec(delete(OAuthCode).where(OAuthCode.expires_at < now))
    s.exec(delete(OAuthToken).where(OAuthToken.expires_at < now))


def exchange_code(engine: Engine, client: OAuthClient, code: str, redirect_uri: str | None,
                  verifier: str, access_ttl: int, refresh_ttl: int,
                  now: int | None = None) -> dict:
    now = _now(now)
    if not code:
        raise OAuthError("invalid_request", "code is required")
    if not verifier or not (43 <= len(verifier) <= 128):
        raise OAuthError("invalid_request", "code_verifier is required (PKCE)")
    with session(engine) as s:
        row = s.get(OAuthCode, _hash(code))
        if row is None or row.expires_at < now or row.client_id != client.id:
            raise OAuthError("invalid_grant", "the code is invalid, used or expired")
        s.delete(row)  # one use only, whatever happens next
        s.commit()
        if (redirect_uri or row.redirect_uri) != row.redirect_uri:
            raise OAuthError("invalid_grant", "redirect_uri does not match")
        try:
            challenge = pkce_s256(verifier)
        except UnicodeEncodeError:
            raise OAuthError("invalid_grant", "PKCE verification failed") from None
        if not hmac.compare_digest(challenge, row.code_challenge):
            raise OAuthError("invalid_grant", "PKCE verification failed")
        _prune(s, now)
        out = _issue(s, client.id, row.scope, row.resource, access_ttl, refresh_ttl, now)
        s.commit()
    return out


def refresh_tokens(engine: Engine, client: OAuthClient, refresh_token: str, access_ttl: int,
                   refresh_ttl: int, now: int | None = None) -> dict:
    now = _now(now)
    if not refresh_token:
        raise OAuthError("invalid_request", "refresh_token is required")
    with session(engine) as s:
        row = s.get(OAuthToken, _hash(refresh_token))
        if (row is None or row.kind != "refresh" or row.expires_at < now
                or row.client_id != client.id):
            raise OAuthError("invalid_grant", "the refresh token is invalid or expired")
        s.delete(row)  # rotation: a refresh token works once
        _prune(s, now)
        out = _issue(s, client.id, row.scope, row.resource, access_ttl, refresh_ttl, now)
        s.commit()
    return out


def verify_access(engine: Engine, token: str | None, now: int | None = None) -> OAuthToken | None:
    if not token or len(token) > 200:
        return None
    with session(engine) as s:
        row = s.get(OAuthToken, _hash(token))
    if row is None or row.kind != "access" or row.expires_at < _now(now):
        return None
    return row


def revoke(engine: Engine, token: str, client: OAuthClient) -> None:
    with session(engine) as s:
        row = s.get(OAuthToken, _hash(token or ""))
        if row is not None and row.client_id == client.id:
            s.delete(row)
            s.commit()


def revoke_all(engine: Engine, forget_clients: bool = False) -> int:
    """Sign every connector out (password change, or "Disconnect" in settings)."""
    with session(engine) as s:
        clients = {t.client_id for t in s.exec(select(OAuthToken)).all()}
        s.exec(delete(OAuthToken))
        s.exec(delete(OAuthCode))
        if forget_clients:
            s.exec(delete(OAuthClient))
        s.commit()
    return len(clients)


def connections(engine: Engine, now: int | None = None) -> list[dict]:
    """Clients that currently hold a valid refresh or access token."""
    now = _now(now)
    with session(engine) as s:
        tokens = s.exec(select(OAuthToken).where(OAuthToken.expires_at >= now)).all()
        ids = {t.client_id for t in tokens}
        clients = s.exec(select(OAuthClient).where(col(OAuthClient.id).in_(ids))).all() if ids else []
    return [
        {"name": c.name or "Unnamed client",
         "hosts": sorted({urlsplit(u).hostname or "" for u in client_redirects(c)}),
         "last_used_at": c.last_used_at}
        for c in sorted(clients, key=lambda c: -(c.last_used_at or 0))
    ]
