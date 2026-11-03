"""Remote MCP server at ``/mcp`` (official MCP Python SDK, streamable HTTP).

Stateless with plain JSON responses: every POST carries one JSON-RPC message and needs a
valid OAuth access token (``app.auth.oauth``). Without one, the endpoint answers 401 with
a ``WWW-Authenticate`` header pointing at the protected resource metadata, which is how
claude.ai discovers the sign-in. The tools themselves live in ``app.mcp_tools``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Callable

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
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
get_deadlines lists what is due. Read only what the task needs: prefer a few targeted
read_file calls over reading every file. Answer in the language the student asks for."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                            openWorldHint=False)


def build_server(tools: StudyTools, version: str) -> MCPServer:
    mcp = MCPServer(
        name="study-companion",
        title="Study Companion",
        version=version,
        instructions=INSTRUCTIONS,
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
        from_date: Annotated[str | None, Field(description="First day, YYYY-MM-DD (default: 14 days ago)")] = None,
        to_date: Annotated[str | None, Field(description="Last day, YYYY-MM-DD (default: in 60 days)")] = None,
        include_done: Annotated[bool, Field(description="Include deadlines already done")] = True,
        page: Annotated[int, Field(ge=1, description="Result page")] = 1,
    ) -> str:
        """List assignment, quiz and calendar deadlines in a date range, with done/overdue status."""
        return await run(tools.get_deadlines, course_id, from_date, to_date, include_done, page)

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

    return mcp


class MCPEndpoint:
    """ASGI app for ``/mcp``: checks the bearer token, then hands over to the SDK."""

    def __init__(self, server: MCPServer, engine, base_url: Callable[[Request], str]) -> None:
        self.engine = engine
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
        if oauth.verify_access(self.engine, token) is None:
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
        await self.manager.handle_request(scope, receive, send)
