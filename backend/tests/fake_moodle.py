"""An in-memory Moodle for tests: routes REST calls to recorded JSON fixtures and serves
files from pluginfile URLs. Nothing ever leaves the process."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from app.moodle.client import MoodleClient

FIXTURES = Path(__file__).parent / "fixtures" / "moodle"
BASE = "https://moodle.example.ch"
TOKEN = "0123456789abcdef0123456789abcdef"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 4
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 8


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeMoodle:
    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.calls: list[tuple[str, dict]] = []  # (wsfunction, params)
        self.downloads: list[str] = []  # file paths requested
        self.requests: list[httpx.Request] = []
        self.responses = {
            "core_webservice_get_site_info": load("site_info.json"),
            "core_enrol_get_users_courses": load("users_courses.json"),
            "mod_assign_get_assignments": load("assignments.json"),
            "mod_quiz_get_quizzes_by_courses": load("quizzes.json"),
            "core_calendar_get_action_events_by_timesort": load("action_events.json"),
            "core_course_get_courses_by_field": load("courses_by_field.json"),
        }
        self.contents = {101: load("contents_101.json"), 202: load("contents_202.json"),
                         303: load("contents_303.json")}
        self.completion = {101: load("completion_101.json")}
        self.files: dict[str, bytes] = {
            "/webservice/pluginfile.php/900/mod_resource/content/1/plan_du_cours.pdf": b"%PDF-plan-1",
            "/webservice/pluginfile.php/901/mod_folder/content/0/cours1.pptx": b"pptx-01",
            "/webservice/pluginfile.php/901/mod_folder/content/0/evil": b"evil",
            "/webservice/pluginfile.php/1200/mod_resource/content/3/notes.pdf": b"%PDF-note",
            "/webservice/pluginfile.php/1201/mod_page/content/index.html": b"<h1>Sorting</h1>",
            "/webservice/pluginfile.php/1300/mod_resource/content/1/lectura.pdf": b"%PDF-",
        }
        # Course header images, kept apart from course files (they aren't counted as files).
        self.images: dict[str, bytes] = {
            "/webservice/pluginfile.php/500/course/overviewfiles/banniere.png": PNG,
            "/webservice/pluginfile.php/530/course/overviewfiles/mapa.jpg": JPEG,
        }
        self.fail_next: dict[str, list[int]] = {}  # path or wsfunction -> status codes to return

    def contents_copy(self, courseid: int):
        return copy.deepcopy(self.contents[courseid])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/webservice/rest/server.php":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            fn = form.get("wsfunction", "")
            self.calls.append((fn, form))
            if fn in self.fail_next and self.fail_next[fn]:
                return httpx.Response(self.fail_next[fn].pop(0))
            if form.get("wstoken") != self.token:
                return httpx.Response(200, json=load("error_invalidtoken.json"))
            if fn == "core_course_get_contents":
                return httpx.Response(200, json=self.contents.get(int(form["courseid"]), []))
            if fn == "core_completion_get_activities_completion_status":
                cid = int(form["courseid"])
                if cid in self.completion:
                    return httpx.Response(200, json=self.completion[cid])
                return httpx.Response(200, json=load("error_completion_disabled.json"))
            if fn in self.responses:
                return httpx.Response(200, json=self.responses[fn])
            return httpx.Response(
                200, json={"exception": "x", "errorcode": "invalidrecord", "message": fn}
            )
        if path == "/login/token.php":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            ok = form.get("username") == "jdoe" and form.get("password") == "pw"
            return httpx.Response(200, json=load("token_ok.json" if ok else "token_bad.json"))
        if path.startswith("/webservice/pluginfile.php"):
            self.downloads.append(path)
            if path in self.fail_next and self.fail_next[path]:
                return httpx.Response(self.fail_next[path].pop(0))
            if request.url.params.get("token") != self.token:
                return httpx.Response(200, json=load("error_invalidtoken.json"))
            body = self.files.get(path, self.images.get(path))
            if body is None:
                return httpx.Response(404)
            return httpx.Response(
                200, content=body, headers={"content-type": "application/octet-stream"}
            )
        return httpx.Response(404)

    def client(self, url: str | None = None, token: str | None = None, **kwargs) -> MoodleClient:
        """Usable as a sync ClientFactory: ``client(url, token)``."""
        async def no_sleep(_s: float) -> None:
            return None

        kwargs.setdefault("sleep", no_sleep)
        return MoodleClient(
            url or BASE,
            self.token if token is None else token,
            transport=httpx.MockTransport(self.handler),
            **kwargs,
        )
