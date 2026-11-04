"""Remote MCP server at ``/mcp`` (official MCP Python SDK, streamable HTTP).

Stateless with plain JSON responses: every POST carries one JSON-RPC message and needs a
valid OAuth access token (``app.auth.oauth``). Without one, the endpoint answers 401 with
a ``WWW-Authenticate`` header pointing at the protected resource metadata, which is how
claude.ai discovers the sign-in. The tools themselves live in ``app.mcp_tools``.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Callable, Literal

import anyio
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, Apps, client_supports_apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.auth import oauth
from app.mcp_tools import StudyTools, ToolInputError

logger = logging.getLogger("app.mcp")
# The SDK logs every stateless request at INFO ("Terminating session: None").
for _name in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
    logging.getLogger(_name).setLevel(logging.WARNING)

INSTRUCTIONS = """\
Study Companion holds the student's Moodle courses: sections, activities, deadlines and the
text of course files (PDF, slides, documents, pages). Start with list_courses for course ids.
get_materials lists what a course covers in a period (with file ids and page counts);
read_file reads a few pages at a time; search_materials finds a topic across files;
get_deadlines lists what is due; get_catch_up_plan gives a day-by-day plan. Read only what
the task needs: prefer a few targeted read_file calls over reading every file. Answer in the
language the student asks for. Save your work back to the app so the student finds it in the
web UI: save_summary for a section summary, save_questions for practice questions and
flashcards, record_quiz_result after a quiz (get_questions lists saved questions and their
ids), log_study_time when a study session ends. When quizzing, ask each multiple-choice question with ask_question(question, choices):
the student answers by clicking a choice."""

QUESTION_UI = "ui://study-companion/ask-question.html"
QUESTION_HTML = (Path(__file__).parent / "mcp_ui" / "ask_question.html").read_text("utf-8")
# Request state key set by MCPEndpoint: the OAuth client id of the caller.
CLIENT_KEY = "study_companion_client"


class AppsClients:
    """Remembers which connector clients show MCP Apps.

    The server is stateless, so a tool call carries no record of the client's
    ``initialize`` capabilities; the endpoint notes them here per OAuth client instead.
    """

    def __init__(self) -> None:
        self._by_client: dict[str, bool] = {}

    def note_initialize(self, client_id: str, body: bytes) -> None:
        try:
            message = json.loads(body)
        except ValueError:
            return
        if not isinstance(message, dict) or message.get("method") != "initialize":
            return
        params = message.get("params")
        caps = params.get("capabilities") if isinstance(params, dict) else None
        ext = caps.get("extensions") if isinstance(caps, dict) else None
        ui = ext.get(EXTENSION_ID) if isinstance(ext, dict) else None
        mimes = ui.get("mimeTypes") if isinstance(ui, dict) else None
        self._by_client[client_id] = isinstance(mimes, list) and APP_MIME_TYPE in mimes

    def supports(self, client_id: str | None) -> bool:
        return bool(client_id) and self._by_client.get(client_id, False)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                            openWorldHint=False)
# Writes only add to or replace Claude's own notes in the app; nothing is sent to Moodle.
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                        openWorldHint=False)
APPEND = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                         openWorldHint=False)


class QuestionItem(BaseModel):
    question: str = Field(description="The question, or the front of a flashcard (Markdown)")
    answer: str = Field(description="The correct answer, or the back of the card (Markdown)")
    kind: Literal["short", "mcq", "flashcard"] | None = Field(
        default=None, description="short answer (default), mcq (needs choices) or flashcard")
    choices: list[str] | None = Field(default=None, description="2 to 8 options for mcq")
    explanation: str | None = Field(default=None, description="Why the answer is right")
    source: str | None = Field(default=None, description='Where it comes from, e.g. "cours.pdf p. 3"')


class QuizItem(BaseModel):
    question_id: int = Field(description="Id from save_questions or get_questions")
    correct: bool = Field(description="Whether the student answered it correctly")


def build_server(tools: StudyTools, version: str,
                 apps_clients: AppsClients | None = None) -> MCPServer:
    apps = Apps()
    apps_clients = apps_clients or AppsClients()

    def shows_apps(ctx: Context) -> bool:
        try:
            if client_supports_apps(ctx):
                return True
            request = ctx.request_context.request
        except (ValueError, AttributeError):
            return False
        state = getattr(request, "scope", {}).get("state") or {}
        return apps_clients.supports(state.get(CLIENT_KEY))

    @apps.tool(resource_uri=QUESTION_UI, name="ask_question", annotations=READ_ONLY,
               structured_output=False)
    async def ask_question(
        question: Annotated[str, Field(description="The question, without the choices (plain text; **bold** and `code` allowed)")],
        choices: Annotated[list[str], Field(description="2 to 8 answer options, without letters (A, B, ... are added)", min_length=2, max_length=8)],
        ctx: Context,
    ) -> str:
        """Ask the student one multiple-choice question as clickable choices, instead of
        writing the choices in your reply. Their pick comes back as their next message
        ("B) ..."). Do not reveal the answer before they pick."""
        try:
            return tools.ask_question(question, choices, shows_apps(ctx))
        except ToolInputError as exc:
            raise ToolError(str(exc)) from None

    apps.add_html_resource(QUESTION_UI, QUESTION_HTML, name="ask-question",
                           title="Multiple-choice question", prefers_border=True)

    mcp = MCPServer(
        name="study-companion",
        title="Study Companion",
        version=version,
        instructions=INSTRUCTIONS,
        extensions=[apps],
    )

    async def run(fn: Callable[..., str], *args, **kwargs) -> str:
        try:
            return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
        except ToolInputError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def list_courses(
        include_past: Annotated[bool, Field(description="Also list courses you are no longer enrolled in")] = False,
    ) -> str:
        """List the student's courses with their ids, language, size and deadline counts."""
        return await run(tools.list_courses, include_past)

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def get_deadlines(
        course_id: Annotated[int | None, Field(description="Course id; omit for all courses")] = None,
        from_date: Annotated[str | None, Field(description="First day, YYYY-MM-DD (default: today; give an earlier day for past work)")] = None,
        to_date: Annotated[str | None, Field(description="Last day, YYYY-MM-DD (default: in 60 days)")] = None,
        include_done: Annotated[bool, Field(description="Include deadlines already done")] = True,
        page: Annotated[int, Field(ge=1, description="Result page")] = 1,
        mandatory_only: Annotated[bool, Field(description="Only mandatory deadlines (leave out optional ones)")] = False,
        include_ignored: Annotated[bool, Field(description="Also list deadlines the student chose to ignore")] = False,
    ) -> str:
        """List assignment, quiz and calendar deadlines in a date range, with done/overdue
        status and whether each is mandatory or optional (focus on mandatory work)."""
        return await run(tools.get_deadlines, course_id, from_date, to_date, include_done, page,
                         mandatory_only, include_ignored)

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def get_materials(
        course_id: Annotated[int, Field(description="Course id from list_courses")],
        from_date: Annotated[str | None, Field(description="First day of the period, YYYY-MM-DD")] = None,
        to_date: Annotated[str | None, Field(description="Last day of the period, YYYY-MM-DD")] = None,
        section_from: Annotated[int | None, Field(description="First section number to include")] = None,
        section_to: Annotated[int | None, Field(description="Last section number to include")] = None,
        page: Annotated[int, Field(ge=1, description="Result page (8 sections per page)")] = 1,
    ) -> str:
        """List a course's sections, activities and files for a period or section range,
        with section ids, file ids and page counts to use with get_section and read_file."""
        return await run(tools.get_materials, course_id, from_date, to_date, section_from,
                         section_to, page)

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def get_section(
        section_id: Annotated[int, Field(description="Section id from get_materials")],
    ) -> str:
        """Show one section in full: summary, every activity with its description, files and deadlines."""
        return await run(tools.get_section, section_id)

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def read_file(
        file_id: Annotated[int, Field(description="File id from get_materials, get_section or search_materials")],
        pages: Annotated[str | None, Field(description='Pages to read, e.g. "1-5" or "2,4,7-9" (default: the first 10; at most 20 per call)')] = None,
    ) -> str:
        """Read the extracted text of a course file, page by page (slides for presentations)."""
        return await run(tools.read_file, file_id, pages)

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def search_materials(
        query: Annotated[str, Field(description="Words to find (all must match; accents ignored)")],
        course_id: Annotated[int | None, Field(description="Limit to one course")] = None,
        page: Annotated[int, Field(ge=1, description="Result page")] = 1,
    ) -> str:
        """Full-text search across course files, section summaries and activity descriptions.
        Returns file ids and pages to open with read_file."""
        return await run(tools.search_materials, query, course_id, page)

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def get_catch_up_plan(
        course_id: Annotated[int | None, Field(description="Course id; omit for all courses")] = None,
        hours_per_day: Annotated[float | None, Field(description="Study hours per day (default: the student's setting in the app)")] = None,
        days: Annotated[int, Field(ge=1, le=90, description="Days to plan")] = 14,
        from_date: Annotated[str | None, Field(description="Only sections with material dated since this day, YYYY-MM-DD")] = None,
        include_optional: Annotated[bool, Field(description="Also plan optional work (default: mandatory only)")] = False,
        beyond_target: Annotated[bool, Field(description="Also plan the backlog beyond the student's catch-up target")] = False,
    ) -> str:
        """Rule-based catch-up plan for the mandatory work: what upcoming deadlines need plus
        enough of the backlog to reach the student's catch-up target (e.g. 60%), ordered by
        urgency and laid out day by day with time estimates and file ids."""
        return await run(tools.get_catch_up_plan, course_id, hours_per_day, days, from_date,
                         include_optional, beyond_target)

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    async def get_questions(
        course_id: Annotated[int | None, Field(description="Course id")] = None,
        section_id: Annotated[int | None, Field(description="Section id")] = None,
        due_only: Annotated[bool, Field(description="Only questions due for review")] = False,
        page: Annotated[int, Field(ge=1, description="Result page")] = 1,
    ) -> str:
        """List saved practice questions with their ids, answers and review state (due ones
        first). Use it to quiz the student on what they should review."""
        return await run(tools.get_questions, course_id, section_id, due_only, page)

    @mcp.tool(annotations=WRITE, structured_output=False)
    async def save_summary(
        section_id: Annotated[int, Field(description="Section id from get_materials")],
        markdown: Annotated[str, Field(description="The summary in Markdown (headings, bullet points; cite file and page)")],
        title: Annotated[str | None, Field(description="Short title (default: the section name)")] = None,
    ) -> str:
        """Save a section summary to the app; it replaces the section's previous summary
        and shows in the course page of the web UI."""
        return await run(tools.save_summary, section_id, markdown, title)

    @mcp.tool(annotations=WRITE, structured_output=False)
    async def save_questions(
        section_id: Annotated[int, Field(description="Section id the questions are about")],
        items: Annotated[list[QuestionItem], Field(description="Up to 50 questions", min_length=1, max_length=50)],
    ) -> str:
        """Save practice questions or flashcards for a section. The student reviews them in
        the app's study mode (spaced repetition). A question saved again is updated, not
        duplicated. Returns the question ids."""
        return await run(tools.save_questions, section_id,
                         [i.model_dump(exclude_none=True) for i in items])

    @mcp.tool(annotations=APPEND, structured_output=False)
    async def record_quiz_result(
        score: Annotated[float, Field(ge=0, description="Points or correct answers")],
        total: Annotated[float, Field(gt=0, description="Maximum points or number of questions")],
        course_id: Annotated[int | None, Field(description="Course id (or give section_id)")] = None,
        section_id: Annotated[int | None, Field(description="Section the quiz was about")] = None,
        topic: Annotated[str | None, Field(description="What the quiz covered")] = None,
        items: Annotated[list[QuizItem] | None, Field(description="Per saved question: was it right? Updates their review schedule")] = None,
        notes: Annotated[str | None, Field(description="Short feedback: what to review")] = None,
    ) -> str:
        """Record the result of a quiz you gave the student, so their progress is tracked
        in the app."""
        return await run(tools.record_quiz_result, score, total, course_id, section_id, topic,
                         [i.model_dump() for i in items] if items else None, notes)

    @mcp.tool(annotations=APPEND, structured_output=False)
    async def log_study_time(
        minutes: Annotated[int, Field(ge=1, le=720, description="Length of the study session in minutes")],
        course_id: Annotated[int | None, Field(description="Course the session was about")] = None,
        note: Annotated[str | None, Field(description="What was studied, a few words")] = None,
    ) -> str:
        """Log the study session that just ended (when the student says how long it took,
        or at the end of a long session). It counts toward their daily goal and streak in
        the app."""
        return await run(tools.log_study_time, minutes, course_id, note)

    @mcp.tool(annotations=APPEND, structured_output=False)
    async def trigger_sync() -> str:
        """Start a sync with Moodle now (new files, deadlines and completion). Takes a few
        minutes; it runs in the background."""
        # Runs in the event loop (not a thread): starting the sync schedules a task.
        return tools.trigger_sync()

    return mcp


class MCPEndpoint:
    """ASGI app for ``/mcp``: checks the bearer token, then hands over to the SDK."""

    def __init__(self, server: MCPServer, engine, base_url: Callable[[Request], str],
                 apps_clients: AppsClients | None = None) -> None:
        self.engine = engine
        self.apps_clients = apps_clients
        self.base_url = base_url
        # Builds the SDK's session manager; we route to it ourselves after the token check.
        self.server = server
        self.manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def running(self):
        """Run the SDK's session manager for the app's lifetime (a fresh one per start:
        a manager can only run once)."""
        # DNS rebinding protection is off: it guards unauthenticated local servers, while
        # every request here needs a bearer token and Caddy only serves DOMAIN.
        self.server.streamable_http_app(
            json_response=True,
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        manager = self.server.session_manager
        async with manager.run():
            self.manager = manager
            try:
                yield
            finally:
                self.manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope)
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else None
        access = oauth.verify_access(self.engine, token)
        if access is None:
            base = self.base_url(request)
            error = ', error="invalid_token"' if token else ""
            response = JSONResponse(
                {"error": "invalid_token" if token else "unauthorized",
                 "error_description": "Sign in through the Study Companion connector (OAuth)."},
                status_code=401,
                headers={"WWW-Authenticate": (
                    f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"'
                    f', scope="{oauth.SCOPE}"{error}')},
            )
            await response(scope, receive, send)
            return
        if self.manager is None:
            await JSONResponse({"error": "starting up"}, status_code=503)(scope, receive, send)
            return
        scope.setdefault("state", {})[CLIENT_KEY] = access.client_id
        if self.apps_clients is not None and scope.get("method") == "POST":
            receive = await self._peek_body(scope, receive, access.client_id)
        await self.manager.handle_request(scope, receive, send)

    async def _peek_body(self, scope: Scope, receive: Receive, client_id: str) -> Receive:
        """Read the request body to note an ``initialize``, then replay it to the SDK."""
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if not message.get("more_body", False) or size > 4_000_000:
                break
        body = b"".join(chunks)
        if size <= 4_000_000:
            self.apps_clients.note_initialize(client_id, body)
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return replay
