"""Typed, defensive wrappers around the Moodle web service functions we use.

Each wrapper returns plain dicts with every field present (missing or malformed values get
defaults), because responses differ between Moodle versions and site settings.
Reference: https://docs.moodle.org/dev/Web_service_API_functions
"""

from __future__ import annotations

from typing import Any

from app.moodle.client import MoodleClient

ACTION_EVENTS_PAGE = 50
ACTION_EVENTS_MAX_PAGES = 20


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_str(value: Any) -> str:
    return "" if value is None else str(value)


def as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", ""}
    return bool(value)


def ts(value: Any) -> int | None:
    """Moodle uses 0 for 'no date'."""
    v = as_int(value)
    return v if v and v > 0 else None


def _list(value: Any) -> list[dict]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


async def get_site_info(client: MoodleClient) -> dict:
    data = await client.call("core_webservice_get_site_info")
    data = data if isinstance(data, dict) else {}
    return {
        "sitename": as_str(data.get("sitename")),
        "userid": as_int(data.get("userid"), 0),
        "fullname": as_str(data.get("fullname")),
        "release": as_str(data.get("release")),
        "lang": as_str(data.get("lang")),
        "siteurl": as_str(data.get("siteurl")),
        # Empty set means "unknown" (older sites); callers then just try the call.
        "functions": {
            as_str(f.get("name")) for f in _list(data.get("functions")) if f.get("name")
        },
    }


async def get_user_courses(client: MoodleClient, userid: int) -> list[dict]:
    data = await client.call("core_enrol_get_users_courses", userid=userid)
    courses = []
    for c in _list(data):
        cid = as_int(c.get("id"))
        if cid is None or cid == 1:  # 1 is the site front page
            continue
        courses.append(
            {
                "id": cid,
                "shortname": as_str(c.get("shortname")) or f"course-{cid}",
                "fullname": as_str(c.get("fullname") or c.get("displayname")),
                "summary": as_str(c.get("summary")),
                "category": as_int(c.get("category")),
                "lang": as_str(c.get("lang")),  # empty unless the course forces a language
                "startdate": ts(c.get("startdate")),
                "enddate": ts(c.get("enddate")),
                "visible": as_bool(c.get("visible")),
                "progress": as_float(c.get("progress")),
                # None: this Moodle didn't say (older versions); {} : no image.
                "image": course_image(c),
            }
        )
    return courses


IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def course_image(c: dict) -> dict | None:
    """The course's header image from a course record of ``core_enrol_get_users_courses``
    or ``core_course_get_courses_by_field``.

    Prefers ``overviewfiles`` (Moodle 3.2+, with size and timemodified) over ``courseimage``
    (newer sites: a URL, or a generated ``data:`` SVG pattern when the course has none, which
    we ignore and draw our own fallback). Returns ``None`` when the record has neither field
    (the site didn't say), ``{}`` when it has no usable image.
    """
    has_overview = isinstance(c.get("overviewfiles"), list)
    has_image = "courseimage" in c
    if not has_overview and not has_image:
        return None
    for item in _list(c.get("overviewfiles")):
        f = _parse_file(item)
        if not f:
            continue
        mimetype = f["mimetype"].lower()
        if mimetype in IMAGE_TYPES or (
            not mimetype and f["filename"].lower().endswith(_IMAGE_EXTS)
        ):
            return {k: f[k] for k in ("fileurl", "filename", "timemodified", "filesize")}
    url = as_str(c.get("courseimage")).strip()
    if url.lower().startswith(("https://", "http://")):
        name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        return {"fileurl": url, "filename": name, "timemodified": 0, "filesize": 0}
    return {}


async def get_course_images(client: MoodleClient, courseids: list[int]) -> dict[int, dict]:
    """Header images via ``core_course_get_courses_by_field`` (Moodle 3.3+), for sites whose
    enrolment call doesn't include them. Courses without one map to ``{}``."""
    if not courseids:
        return {}
    data = await client.call(
        "core_course_get_courses_by_field", field="ids", value=",".join(map(str, courseids))
    )
    courses = _list((data or {}).get("courses") if isinstance(data, dict) else None)
    out: dict[int, dict] = {}
    for c in courses:
        cid = as_int(c.get("id"))
        if cid is not None:
            out[cid] = course_image(c) or {}
    return out


def _parse_file(item: dict) -> dict | None:
    if as_str(item.get("type") or "file") != "file":
        return None
    filename = as_str(item.get("filename"))
    fileurl = as_str(item.get("fileurl"))
    if not filename or not fileurl:
        return None
    return {
        "filename": filename,
        "filepath": as_str(item.get("filepath")) or "/",
        "filesize": as_int(item.get("filesize"), 0) or 0,
        "fileurl": fileurl,
        "timemodified": as_int(item.get("timemodified"), 0) or 0,
        "mimetype": as_str(item.get("mimetype")),
    }


async def get_course_contents(client: MoodleClient, courseid: int) -> list[dict]:
    data = await client.call("core_course_get_contents", courseid=courseid)
    sections = []
    for index, s in enumerate(_list(data)):
        sid = as_int(s.get("id"))
        if sid is None:
            continue
        modules = []
        for pos, m in enumerate(_list(s.get("modules"))):
            mid = as_int(m.get("id"))
            if mid is None:
                continue
            contents = _list(m.get("contents"))
            url = as_str(m.get("url"))
            if as_str(m.get("modname")) == "url":
                # For URL modules the external link is the content's fileurl.
                url = next((as_str(c.get("fileurl")) for c in contents if c.get("type") == "url"), url)
            modules.append(
                {
                    "id": mid,
                    "name": as_str(m.get("name")),
                    "modname": as_str(m.get("modname")),
                    "instance": as_int(m.get("instance")),
                    "url": url,
                    "description": as_str(m.get("description")),
                    "visible": as_bool(m.get("visible")) and as_bool(m.get("uservisible")),
                    "position": pos,
                    "files": [f for f in map(_parse_file, contents) if f],
                }
            )
        sections.append(
            {
                "id": sid,
                "number": as_int(s.get("section"), index) or 0,
                "name": as_str(s.get("name")),
                "summary": as_str(s.get("summary")),
                "visible": as_bool(s.get("visible")) and as_bool(s.get("uservisible")),
                "modules": modules,
            }
        )
    return sections


async def get_assignments(client: MoodleClient, courseids: list[int]) -> list[dict]:
    data = await client.call("mod_assign_get_assignments", courseids=courseids)
    out = []
    for course in _list((data or {}).get("courses") if isinstance(data, dict) else None):
        cid = as_int(course.get("id"))
        for a in _list(course.get("assignments")):
            aid = as_int(a.get("id"))
            if aid is None:
                continue
            out.append(
                {
                    "id": aid,
                    "course_id": as_int(a.get("course"), cid),
                    "cmid": as_int(a.get("cmid")),
                    "name": as_str(a.get("name")),
                    "duedate": ts(a.get("duedate")),
                    "cutoffdate": ts(a.get("cutoffdate")),
                    "opendate": ts(a.get("allowsubmissionsfromdate")),
                    "grade": as_float(a.get("grade")),
                    "intro": as_str(a.get("intro")),
                }
            )
    return out


async def get_quizzes(client: MoodleClient, courseids: list[int]) -> list[dict]:
    data = await client.call("mod_quiz_get_quizzes_by_courses", courseids=courseids)
    out = []
    for q in _list((data or {}).get("quizzes") if isinstance(data, dict) else None):
        qid = as_int(q.get("id"))
        if qid is None:
            continue
        out.append(
            {
                "id": qid,
                "course_id": as_int(q.get("course")),
                "cmid": as_int(q.get("coursemodule")),
                "name": as_str(q.get("name")),
                "timeopen": ts(q.get("timeopen")),
                "timeclose": ts(q.get("timeclose")),
                "grade": as_float(q.get("grade")),
                "intro": as_str(q.get("intro")),
            }
        )
    return out


async def get_action_events(client: MoodleClient, timefrom: int, timeto: int) -> list[dict]:
    """Calendar items that need action (submit, attempt...), paginated by ``aftereventid``."""
    out: list[dict] = []
    after: int | None = None
    for _ in range(ACTION_EVENTS_MAX_PAGES):
        params: dict[str, Any] = {
            "timesortfrom": timefrom,
            "timesortto": timeto,
            "limitnum": ACTION_EVENTS_PAGE,
        }
        if after:
            params["aftereventid"] = after
        data = await client.call("core_calendar_get_action_events_by_timesort", **params)
        events = _list((data or {}).get("events") if isinstance(data, dict) else None)
        for e in events:
            eid = as_int(e.get("id"))
            if eid is None:
                continue
            course = e.get("course") if isinstance(e.get("course"), dict) else {}
            out.append(
                {
                    "id": eid,
                    "name": as_str(e.get("activityname") or e.get("name")),
                    "course_id": as_int(course.get("id"), as_int(e.get("courseid"))),
                    "modulename": as_str(e.get("modulename")),
                    "instance": as_int(e.get("instance")),
                    "cmid": as_int(e.get("coursemoduleid")),
                    "timesort": ts(e.get("timesort")) or ts(e.get("timestart")),
                    "url": as_str(e.get("url")),
                    "description": as_str(e.get("description")),
                }
            )
        last = as_int((data or {}).get("lastid")) if isinstance(data, dict) else None
        if len(events) < ACTION_EVENTS_PAGE:
            break
        last = last or (out[-1]["id"] if out else None)
        if not last or last == after:
            break
        after = last
    return out


async def get_completion(client: MoodleClient, courseid: int, userid: int) -> dict[int, dict]:
    data = await client.call(
        "core_completion_get_activities_completion_status", courseid=courseid, userid=userid
    )
    out = {}
    for s in _list((data or {}).get("statuses") if isinstance(data, dict) else None):
        cmid = as_int(s.get("cmid"))
        if cmid is None:
            continue
        out[cmid] = {"state": as_int(s.get("state"), 0), "timecompleted": ts(s.get("timecompleted"))}
    return out
