"""OAuth 2.1 for the connector (discovery, registration, PKCE, refresh) and /mcp."""

import dataclasses
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.auth.oauth import pkce_s256, redirect_allowed
from app.db import make_engine
from app.extract.index import extract_files, index_structure
from app.main import create_app

from .conftest import PASSWORD
from .m3_seed import seed

CALLBACK = "https://claude.ai/api/mcp/auth_callback"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18"}


@pytest.fixture
def app(settings):
    engine = make_engine(settings.data_dir)
    seed(engine, settings.data_dir)
    extract_files(engine, settings.data_dir)
    index_structure(engine)
    return create_app(settings)


@pytest.fixture
def c(app):
    with TestClient(app, follow_redirects=False) as client:
        yield client


def register(c, **extra) -> dict:
    body = {"client_name": "Claude", "redirect_uris": [CALLBACK], **extra}
    r = c.post("/oauth/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def auth_params(client_id: str, verifier: str, **extra) -> dict:
    return {"response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK,
            "code_challenge": pkce_s256(verifier), "code_challenge_method": "S256",
            "state": "st4te", "scope": "study", "resource": "http://testserver/mcp", **extra}


def get_code(c, client_id: str, verifier: str) -> str:
    r = c.post("/oauth/authorize", headers=SAME_ORIGIN,
               data={**auth_params(client_id, verifier), "password": PASSWORD, "decision": "allow"})
    assert r.status_code == 303, r.text
    query = parse_qs(urlsplit(r.headers["location"]).query)
    assert r.headers["location"].startswith(CALLBACK)
    assert query["state"] == ["st4te"] and query["iss"] == ["http://testserver"]
    return query["code"][0]


def tokens(c) -> dict:
    client = register(c)
    verifier = secrets.token_urlsafe(48)
    code = get_code(c, client["client_id"], verifier)
    r = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                     "redirect_uri": CALLBACK, "client_id": client["client_id"],
                                     "code_verifier": verifier})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return {**r.json(), "client_id": client["client_id"]}


def rpc(c, token: str, method: str, params: dict | None = None, id_: int = 1):
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return c.post("/mcp", json=body, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"})


# -------------------------------------------------------------------- discovery


def test_discovery(c):
    meta = c.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"] == "http://testserver"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["registration_endpoint"] == "http://testserver/oauth/register"
    resource = c.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == "http://testserver/mcp"
    assert resource["authorization_servers"] == ["http://testserver"]


def test_discovery_uses_the_public_domain(settings):
    from dataclasses import replace

    app = create_app(replace(settings, domain="study.example.ch"))
    with TestClient(app) as c:
        assert c.get("/.well-known/oauth-authorization-server").json()["issuer"] == \
            "https://study.example.ch"
        r = c.post("/mcp", json={})
    assert 'resource_metadata="https://study.example.ch/.well-known/oauth-protected-resource/mcp"' \
        in r.headers["www-authenticate"]


def test_cors_preflight_for_claude(c):
    r = c.options("/oauth/token", headers={"Origin": "https://claude.ai",
                                           "Access-Control-Request-Method": "POST"})
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == "*"
    assert c.get("/.well-known/oauth-protected-resource").headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-origin" not in c.get("/oauth/authorize").headers


# -------------------------------------------------------------------- registration


def test_redirect_allowed():
    hosts = ("claude.ai", "localhost")
    assert redirect_allowed(CALLBACK, hosts)
    assert redirect_allowed("http://localhost:6274/cb", hosts)
    assert not redirect_allowed("http://claude.ai/cb", hosts)  # plain http only on localhost
    assert not redirect_allowed("https://evil.example/cb", hosts)
    assert not redirect_allowed("https://claude.ai.evil.example/cb", hosts)
    assert not redirect_allowed("https://claude.ai/cb#frag", hosts)
    assert not redirect_allowed("https://user@claude.ai/cb", hosts)


@pytest.mark.parametrize("body", [
    {"redirect_uris": ["https://evil.example/cb"]},
    {"redirect_uris": []},
    {"redirect_uris": "https://claude.ai/cb"},
    {"redirect_uris": [CALLBACK], "token_endpoint_auth_method": "private_key_jwt"},
    {"redirect_uris": [CALLBACK], "grant_types": ["client_credentials"]},
    {"redirect_uris": [CALLBACK], "response_types": ["token"]},
])
def test_registration_rejects_bad_metadata(c, body):
    r = c.post("/oauth/register", json=body)
    assert r.status_code == 400
    assert r.json()["error"] in {"invalid_redirect_uri", "invalid_client_metadata"}


def test_registration_rejects_non_json(c):
    r = c.post("/oauth/register", content=b"nope", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_confidential_client_gets_a_secret(c):
    client = register(c, token_endpoint_auth_method="client_secret_post")
    assert client["client_secret"] and client["client_secret_expires_at"] == 0
    assert "client_secret" not in register(c)


# -------------------------------------------------------------------- authorization


def test_consent_page_and_errors(c):
    client = register(c)
    verifier = secrets.token_urlsafe(48)
    r = c.get("/oauth/authorize", params=auth_params(client["client_id"], verifier))
    assert r.status_code == 200
    assert "Claude" in r.text and "claude.ai" in r.text and 'name="password"' in r.text
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"

    # Unknown client or redirect: shown here, never redirected.
    assert c.get("/oauth/authorize", params=auth_params("nope", verifier)).status_code == 400
    bad = auth_params(client["client_id"], verifier, redirect_uri="https://claude.ai/other")
    assert c.get("/oauth/authorize", params=bad).status_code == 400

    # PKCE missing or plain: redirected back with an error.
    params = auth_params(client["client_id"], verifier, code_challenge_method="plain")
    r = c.get("/oauth/authorize", params=params)
    assert r.status_code == 303 and "error=invalid_request" in r.headers["location"]
    params = auth_params(client["client_id"], verifier, resource="https://other.example/mcp")
    assert "error=invalid_target" in c.get("/oauth/authorize", params=params).headers["location"]


def test_consent_post_checks(c):
    client = register(c)
    verifier = secrets.token_urlsafe(48)
    data = {**auth_params(client["client_id"], verifier), "password": PASSWORD, "decision": "allow"}
    r = c.post("/oauth/authorize", data=data, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/oauth/authorize", data={**data, "password": "wrong"}, headers=SAME_ORIGIN)
    assert r.status_code == 401 and "Wrong password" in r.text
    r = c.post("/oauth/authorize", data={**data, "decision": "deny"}, headers=SAME_ORIGIN)
    assert r.status_code == 303 and "error=access_denied" in r.headers["location"]


def test_signed_in_user_only_clicks_allow(c):
    c.post("/login", data={"password": PASSWORD})
    client = register(c)
    verifier = secrets.token_urlsafe(48)
    page = c.get("/oauth/authorize", params=auth_params(client["client_id"], verifier))
    assert 'name="password"' not in page.text
    r = c.post("/oauth/authorize", headers=SAME_ORIGIN,
               data={**auth_params(client["client_id"], verifier), "decision": "allow"})
    assert r.status_code == 303 and "code=" in r.headers["location"]


def test_consent_password_is_throttled(c):
    client = register(c)
    data = {**auth_params(client["client_id"], secrets.token_urlsafe(48)),
            "password": "wrong", "decision": "allow"}
    for _ in range(3):
        c.post("/oauth/authorize", data=data, headers=SAME_ORIGIN)
    r = c.post("/oauth/authorize", data={**data, "password": PASSWORD}, headers=SAME_ORIGIN)
    assert r.status_code == 429


# -------------------------------------------------------------------- tokens


def test_code_exchange_rules(c):
    client = register(c)
    cid = client["client_id"]
    verifier = secrets.token_urlsafe(48)

    code = get_code(c, cid, verifier)
    r = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                     "client_id": cid, "code_verifier": "x" * 50})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    # The code was used up by the failed attempt.
    r = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                     "client_id": cid, "code_verifier": verifier})
    assert r.json()["error"] == "invalid_grant"

    code = get_code(c, cid, verifier)
    r = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                     "client_id": cid, "code_verifier": verifier,
                                     "redirect_uri": "https://claude.ai/elsewhere"})
    assert r.json()["error"] == "invalid_grant"

    r = c.post("/oauth/token", data={"grant_type": "password", "client_id": cid})
    assert r.json()["error"] == "unsupported_grant_type"
    r = c.post("/oauth/token", data={"grant_type": "authorization_code", "client_id": "nope"})
    assert r.status_code == 401 and r.json()["error"] == "invalid_client"


def test_confidential_client_must_authenticate(c):
    client = register(c, token_endpoint_auth_method="client_secret_basic")
    verifier = secrets.token_urlsafe(48)
    code = get_code(c, client["client_id"], verifier)
    data = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "client_id": client["client_id"]}
    assert c.post("/oauth/token", data=data).status_code == 401
    code = get_code(c, client["client_id"], verifier)
    r = c.post("/oauth/token", data={**data, "code": code},
               auth=(client["client_id"], client["client_secret"]))
    assert r.status_code == 200 and r.json()["token_type"] == "Bearer"


GEMINI_CALLBACK = ("https://oauth-redirect.googleusercontent.com/r/"
                   "user_bound_custom-mcp-1234567890-study_companion_ch")


GEMINI_HOSTS = ("oauth-redirect.googleusercontent.com",
                "oauth-redirect-sandbox.googleusercontent.com",
                "oauth-redirect-test.googleusercontent.com")
CHATGPT_CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"


def test_gemini_and_chatgpt_are_refused_by_default(c):
    for uri in (GEMINI_CALLBACK, CHATGPT_CALLBACK):
        r = c.post("/oauth/register", json={"redirect_uris": [uri]})
        assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"


@pytest.fixture
def c_more(settings):
    """OAUTH_REDIRECT_HOSTS with Gemini and ChatGPT added by the owner."""
    hosts = (*settings.oauth_redirect_hosts, *GEMINI_HOSTS, "chatgpt.com")
    app = create_app(dataclasses.replace(settings, oauth_redirect_hosts=hosts))
    with TestClient(app, follow_redirects=False) as client:
        yield client


def test_gemini_connector_flow(c_more):
    """What Gemini's custom MCP connector sends: no client_name, client_secret_basic, a
    callback on Google's OAuth relay, scope offline_access, client_id only in the Basic
    header at the token endpoint."""
    r = c_more.post("/oauth/register", json={"redirect_uris": [GEMINI_CALLBACK],
                                        "token_endpoint_auth_method": "client_secret_basic",
                                        "grant_types": ["authorization_code", "refresh_token"],
                                        "response_types": ["code"]})
    assert r.status_code == 201, r.text
    client = r.json()
    verifier = secrets.token_urlsafe(48)
    params = {**auth_params(client["client_id"], verifier), "redirect_uri": GEMINI_CALLBACK,
              "scope": "offline_access"}
    page = c_more.get("/oauth/authorize", params=params)
    assert page.status_code == 200 and "oauth-redirect.googleusercontent.com" in page.text
    r = c_more.post("/oauth/authorize", headers=SAME_ORIGIN,
               data={**params, "password": PASSWORD, "decision": "allow"})
    assert r.status_code == 303 and r.headers["location"].startswith(GEMINI_CALLBACK)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    r = c_more.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                     "redirect_uri": GEMINI_CALLBACK, "code_verifier": verifier},
               auth=(client["client_id"], client["client_secret"]))
    assert r.status_code == 200, r.text
    token = r.json()
    assert token["refresh_token"]
    assert rpc(c_more, token["access_token"], "tools/list").status_code == 200
    # ChatGPT's stable callback registers too; other Google hosts stay refused.
    assert register(c_more, redirect_uris=[CHATGPT_CALLBACK])

    r = c_more.post("/oauth/register", json={"redirect_uris": ["https://evil.googleusercontent.com/r/x"]})
    assert r.status_code == 400


def test_gemini_registers_on_all_three_relays(c_more, settings):
    """Gemini sends one callback per Google relay; every host must be allowed."""
    uris = [f"https://{h}/r/user_bound_custom-mcp-1234567890-study_companion_ch"
            for h in GEMINI_HOSTS]
    r = c_more.post("/oauth/register", json={"redirect_uris": uris,
                                             "token_endpoint_auth_method": "client_secret_basic"})
    assert r.status_code == 201, r.text
    # With only the main relay allowed, the error names the missing hosts.
    hosts = (*settings.oauth_redirect_hosts, GEMINI_HOSTS[0])
    app = create_app(dataclasses.replace(settings, oauth_redirect_hosts=hosts))
    with TestClient(app) as client:
        r = client.post("/oauth/register", json={"redirect_uris": uris})
    assert r.status_code == 400
    desc = r.json()["error_description"]
    assert GEMINI_HOSTS[1] in desc and GEMINI_HOSTS[2] in desc


def test_refused_registration_logs_hosts_not_uris(c, caplog):
    with caplog.at_level("WARNING"):
        r = c.post("/oauth/register",
                   json={"redirect_uris": ["https://new-client.example/cb?token=s3cret"]})
    assert r.status_code == 400
    assert "new-client.example" in caplog.text and "s3cret" not in caplog.text


def test_refresh_rotation_and_revocation(c):
    t = tokens(c)
    r = c.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": t["client_id"],
                                     "refresh_token": t["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    assert new["access_token"] != t["access_token"]
    # The old refresh token works once only.
    r = c.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": t["client_id"],
                                     "refresh_token": t["refresh_token"]})
    assert r.json()["error"] == "invalid_grant"

    assert rpc(c, new["access_token"], "ping").status_code == 200
    c.post("/oauth/revoke", data={"token": new["access_token"], "client_id": t["client_id"]})
    assert rpc(c, new["access_token"], "ping").status_code == 401


def test_password_change_and_disconnect_sign_claude_out(c):
    t = tokens(c)
    c.post("/login", data={"password": PASSWORD})
    page = c.get("/settings")
    assert "Claude connector" in page.text and "http://testserver/mcp" in page.text
    assert "Claude (claude.ai)" in page.text
    r = c.post("/settings/connector/disconnect", headers=SAME_ORIGIN)
    assert r.status_code == 303
    assert rpc(c, t["access_token"], "ping").status_code == 401
    assert "Not connected yet" in c.get("/settings").text

    t = tokens(c)
    new = "another long password!"
    c.post("/settings/password", headers=SAME_ORIGIN,
           data={"current": PASSWORD, "new": new, "confirm": new})
    assert rpc(c, t["access_token"], "ping").status_code == 401


# -------------------------------------------------------------------- MCP


def test_mcp_requires_a_token(c):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith(
        'Bearer resource_metadata="http://testserver/.well-known/oauth-protected-resource/mcp"')
    r = rpc(c, "not-a-token", "ping")
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_mcp_session(c):
    token = tokens(c)["access_token"]
    r = rpc(c, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1"}})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["serverInfo"]["name"] == "study-companion"
    assert "list_courses" in result["instructions"]

    listed = rpc(c, token, "tools/list", id_=2).json()["result"]["tools"]
    by_name = {t["name"]: t for t in listed}
    from app.mcp_tools import TOOL_NAMES

    assert set(by_name) == set(TOOL_NAMES)
    assert by_name["read_file"]["annotations"]["readOnlyHint"] is True
    assert by_name["save_summary"]["annotations"]["readOnlyHint"] is False
    item_schema = by_name["save_questions"]["inputSchema"]
    assert "items" in item_schema["properties"] and "QuestionItem" in str(item_schema)
    assert "pages" in by_name["read_file"]["inputSchema"]["properties"]

    r = rpc(c, token, "tools/call", {"name": "read_file",
                                     "arguments": {"file_id": 1, "pages": "3"}}, id_=3)
    result = r.json()["result"]
    assert result["isError"] is False
    assert "Valeurs propres" in result["content"][0]["text"]

    r = rpc(c, token, "tools/call", {"name": "get_section", "arguments": {"section_id": 1}}, id_=4)
    result = r.json()["result"]
    assert result["isError"] is True and "no section with id 1" in result["content"][0]["text"]


def test_mcp_write_tools_show_up_in_the_web_ui(c):
    token = tokens(c)["access_token"]

    def call(name, args, id_=1):
        r = rpc(c, token, "tools/call", {"name": name, "arguments": args}, id_=id_)
        return r.json()["result"]

    r = call("save_summary", {"section_id": 102, "markdown": "# Matrices\n- **inverse** (td.docx p. 1)"})
    assert r["isError"] is False and "Saved a summary of section 102" in r["content"][0]["text"]
    r = call("save_questions", {"section_id": 102, "items": [
        {"question": "Inverse of I?", "answer": "I", "source": "td.docx p. 1"},
        {"question": "det(AB)?", "answer": "det(A)det(B)", "kind": "mcq",
         "choices": ["det(A)+det(B)", "det(A)det(B)"]},
    ]})
    text = r["content"][0]["text"]
    assert r["isError"] is False and "saved 2 new question(s)" in text
    ids = [int(x) for x in text.split("question_id: ")[1].split(".")[0].split(", ")]
    r = call("record_quiz_result", {"score": 1, "total": 2, "section_id": 102, "topic": "Matrices",
                                    "items": [{"question_id": ids[0], "correct": True},
                                              {"question_id": ids[1], "correct": False}]})
    assert r["isError"] is False and "Recorded 1/2 (50%)" in r["content"][0]["text"]
    r = call("save_questions", {"section_id": 102, "items": [{"question": "only a question"}]})
    assert r["isError"] is True
    r = call("trigger_sync", {})
    assert "not connected" in r["content"][0]["text"]
    r = call("get_catch_up_plan", {"hours_per_day": 1, "days": 3})
    assert r["isError"] is False and "Catch-up plan" in r["content"][0]["text"]

    c.post("/login", data={"password": PASSWORD})
    page = c.get("/api/courses/10/study").json()
    assert page["notes"][0]["markdown"].startswith("# Matrices")
    assert page["questions"]["102"]["questions"] == 2
    assert page["results"][0]["percent"] == 50 and page["results"][0]["source"] == "claude"


APPS_CAPS = {"extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}}


def test_ask_question_is_an_mcp_app(c):
    token = tokens(c)["access_token"]
    init = {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "1"}}
    call = {"name": "ask_question",
            "arguments": {"question": "2 + 2?", "choices": ["3", "4", "5"]}}

    # A client without MCP Apps gets the question to write in its reply.
    assert rpc(c, token, "initialize", {**init, "capabilities": {}}).status_code == 200
    text = rpc(c, token, "tools/call", call, id_=2).json()["result"]["content"][0]["text"]
    assert "Present it your own way" in text and "2 + 2?\n\nA) 3\nB) 4\nC) 5" in text

    # The client's capabilities at initialize are remembered for its OAuth client.
    assert rpc(c, token, "initialize", {**init, "capabilities": APPS_CAPS}, id_=3).status_code == 200
    tool = {t["name"]: t for t in rpc(c, token, "tools/list", id_=4).json()["result"]["tools"]}["ask_question"]
    uri = tool["_meta"]["ui"]["resourceUri"]
    assert uri.startswith("ui://")
    resource = rpc(c, token, "resources/read", {"uri": uri}, id_=5).json()["result"]["contents"][0]
    assert resource["mimeType"] == "text/html;profile=mcp-app"
    html = resource["text"]
    assert "ui/initialize" in html and '"ui/message"' in html and ".innerHTML" not in html
    text = rpc(c, token, "tools/call", call, id_=6).json()["result"]["content"][0]["text"]
    assert text.startswith("Shown to the student as a card with clickable choices A to C")

    bad = rpc(c, token, "tools/call", {"name": "ask_question",
                                       "arguments": {"question": "Q", "choices": ["a", "a"]}}, id_=7)
    assert bad.json()["result"]["isError"] is True
