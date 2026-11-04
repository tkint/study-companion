"""Prompt builder: Markdown templates in this folder turned into ready-to-paste prompts.

Each ``*.md`` file has a small front matter (title, description, order, topic: required,
optional or none) and a body with placeholders:

``{{courses}}``  course names with ids          ``{{period}}``    the chosen period
``{{steps}}``    numbered MCP tool calls          ``{{language}}``  language of the answers
``{{depth}}``    depth instruction                ``{{time}}``      time available ("" if none)
``{{topic}}``    the topic typed in the form      ``{{part}}``      "Part 2 of 3 ..." ("" if one)
``{{today}}``    today's date                     ``{{target}}``    your catch-up target, e.g. "60%"

``{{#name}}...{{/name}}`` keeps its content only when ``name`` is set (``time``, ``topic``,
``deadlines``, ``completion``, ``save``: save results back to the app with the write tools); ``{{^name}}...{{/name}}`` only when it is not. Tool names in
templates and in ``{{steps}}`` must be real MCP tools (``app.mcp_tools.TOOL_NAMES``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import Engine

from app.catchup import target_percent
from app.config import Settings
from app.materials import (
    CourseMaterials,
    SectionInfo,
    bounds,
    enrolled_courses,
    load_course,
    parse_date,
)
from app.api.ui import deadlines as deadline_rows

TEMPLATE_DIR = Path(__file__).parent
LANGUAGES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch",
}
DEPTHS = {
    "quick": ("Quick overview", 300,
              "Keep it short: the key ideas only. Skim the files (headings, first pages, "
              "summaries) instead of reading everything."),
    "standard": ("Standard", 150,
                 "Cover the main ideas with enough detail to understand them; read the "
                 "important files, a few pages at a time."),
    "deep": ("Deep dive", 80,
             "Go in depth: read the files thoroughly and include definitions, worked "
             "examples and the reasoning behind each idea."),
}
MAX_SECTIONS_PER_PROMPT = 6
MAX_TOPIC_CHARS = 200

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_SECTION = re.compile(r"\{\{([#^])(\w+)\}\}(.*?)\{\{/\2\}\}", re.DOTALL)
_VAR = re.compile(r"\{\{(\w+)\}\}")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Template:
    id: str
    title: str
    description: str
    order: int
    topic: str  # required, optional, none
    body: str


def parse_template(template_id: str, raw: str) -> Template:
    """One template from its Markdown text (front matter + body)."""
    raw = raw.replace("\r\n", "\n")
    meta: dict[str, str] = {}
    m = _FRONT.match(raw)
    if m:
        for line in m.group(1).splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        raw = raw[m.end():]
    try:
        order = int(meta.get("order", "99"))
    except ValueError:
        order = 99
    return Template(
        id=template_id,
        title=meta.get("title") or template_id.replace("_", " ").capitalize(),
        description=meta.get("description", ""),
        order=order,
        topic=meta.get("topic", "optional") if meta.get("topic") in {"required", "optional", "none"} else "optional",
        body=raw.strip() + "\n",
    )


def default_sources(directory: Path = TEMPLATE_DIR) -> dict[str, str]:
    """The built-in templates' Markdown text, by id (file stem)."""
    out = {}
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith(("_", ".")) or path.name.lower() == "readme.md":
            continue
        out[path.stem] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return out


def load_templates(directory: Path = TEMPLATE_DIR,
                   overrides: dict[str, str] | None = None) -> dict[str, Template]:
    """Built-in templates, with your edits (``overrides``: id -> Markdown) in their place."""
    sources = default_sources(directory)
    for tid, raw in (overrides or {}).items():
        if tid in sources:  # an edit of a template that no longer exists is ignored
            sources[tid] = raw
    out = {tid: parse_template(tid, raw) for tid, raw in sources.items()}
    return dict(sorted(out.items(), key=lambda kv: (kv[1].order, kv[0])))


def render(body: str, values: dict[str, str]) -> str:
    def section(m: re.Match) -> str:
        on = bool(values.get(m.group(2)))
        return m.group(3) if on == (m.group(1) == "#") else ""

    previous = None
    while previous != body:  # nested sections
        previous, body = body, _SECTION.sub(section, body)
    body = _VAR.sub(lambda m: str(values.get(m.group(1), "")), body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"


# ---------------------------------------------------------------------- request


@dataclass
class Request:
    course_ids: list[int]
    goal: str
    from_date: date | None = None
    to_date: date | None = None
    section_from: int | None = None
    section_to: int | None = None
    depth: str = "standard"
    language: str = "course"
    topic: str = ""
    hours_total: float | None = None
    hours_per_day: float | None = None
    days: int | None = None
    include_deadlines: bool = True
    include_completion: bool = True
    save_results: bool = True

    @classmethod
    def from_json(cls, data: object) -> "Request":
        if not isinstance(data, dict):
            raise PromptError("send a JSON object")
        ids = data.get("course_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
            raise PromptError("choose at least one course")

        def num(name: str, kind=float, low=0.0, high=1e6):
            v = data.get(name)
            if v is None or v == "":
                return None
            try:
                v = kind(v)
            except (TypeError, ValueError):
                raise PromptError(f"{name} must be a number") from None
            if not (low < v <= high):
                raise PromptError(f"{name} is out of range")
            return v

        def section_no(name: str):
            v = data.get(name)
            if v is None or v == "":
                return None
            if not isinstance(v, int) or v < 0:
                raise PromptError(f"{name} must be a section number")
            return v

        try:
            start = parse_date(data.get("from"), "from")
            end = parse_date(data.get("to"), "to")
        except ValueError as exc:
            raise PromptError(str(exc)) from None
        if start and end and end < start:
            raise PromptError("the end date is before the start date")
        depth = data.get("depth") or "standard"
        if depth not in DEPTHS:
            raise PromptError("unknown depth")
        language = data.get("language") or "course"
        if language != "course" and language not in LANGUAGES:
            raise PromptError("unknown language")
        topic = data.get("topic") or ""
        if not isinstance(topic, str):
            raise PromptError("topic must be text")
        req = cls(
            course_ids=list(dict.fromkeys(ids))[:10],
            goal=str(data.get("goal") or ""),
            from_date=start,
            to_date=end,
            section_from=section_no("section_from"),
            section_to=section_no("section_to"),
            depth=depth,
            language=language,
            topic=" ".join(topic.split())[:MAX_TOPIC_CHARS],
            hours_total=num("hours_total", float, 0, 1000),
            hours_per_day=num("hours_per_day", float, 0, 24),
            days=num("days", int, 0, 365),
            include_deadlines=bool(data.get("include_deadlines", True)),
            include_completion=bool(data.get("include_completion", True)),
            save_results=bool(data.get("save_results", True)),
        )
        if (req.section_from is not None and req.section_to is not None
                and req.section_to < req.section_from):
            raise PromptError("the last section is before the first one")
        return req


def _hours(h: float) -> str:
    h = round(h, 1)
    text = f"{h:g}"
    return f"{text} hour" + ("" if h == 1 else "s")


def time_text(req: Request) -> str:
    if req.hours_per_day and req.days:
        return f"{_hours(req.hours_per_day)} per day for {req.days} day{'s' if req.days != 1 else ''}"
    if req.hours_total:
        return f"{_hours(req.hours_total)} in total"
    return ""


# ---------------------------------------------------------------------- building


@dataclass
class Unit:
    """Part of one course that goes into one prompt."""

    cm: CourseMaterials
    sections: list[SectionInfo]

    @property
    def numbers(self) -> tuple[int, int]:
        nums = [s.row.number for s in self.sections]
        return min(nums), max(nums)

    @property
    def pages(self) -> int:
        return sum(s.pages for s in self.sections)


def _q(value: str) -> str:
    return '"' + value.replace("\\", "").replace('"', "'") + '"'


class Builder:
    def __init__(self, settings: Settings, engine: Engine, now: float | None = None) -> None:
        self.settings = settings
        self.engine = engine
        self.tz = settings.tz
        self.now = int(now if now is not None else datetime.now().timestamp())
        self.today = datetime.fromtimestamp(self.now, self.tz).date()
        from app.prompts.store import overrides

        self.templates = load_templates(overrides=overrides(engine))

    def options(self) -> dict:
        upcoming: dict[int, int] = {}
        for d in deadline_rows(self.engine, start=self.now, end=self.now + 365 * 86400, now=self.now):
            if d["course_id"] and not d["done"]:
                upcoming.setdefault(d["course_id"], d["due_at"])
        courses = []
        for c in enrolled_courses(self.engine):
            cm = load_course(self.engine, c.id)
            courses.append({
                "id": c.id,
                "fullname": c.fullname,
                "shortname": c.shortname,
                "lang": c.lang,
                "next_deadline": upcoming.get(c.id),
                "sections": [
                    {"id": s.row.id, "number": s.row.number, "name": s.row.name}
                    for s in (cm.sections if cm else []) if not s.empty
                ],
            })
        return {
            "today": self.today.isoformat(),
            "timezone": self.settings.timezone,
            "courses": courses,
            "goals": [
                {"id": t.id, "title": t.title, "description": t.description, "topic": t.topic}
                for t in self.templates.values()
            ],
            "depths": [{"id": k, "title": v[0]} for k, v in DEPTHS.items()],
            "languages": [{"id": k, "title": v} for k, v in LANGUAGES.items()],
        }

    def build(self, req: Request) -> dict:
        template = self.templates.get(req.goal)
        if template is None:
            raise PromptError("choose a goal")
        if template.topic == "required" and not req.topic:
            raise PromptError("type the topic to explain")
        start, end = bounds(req.from_date, req.to_date, self.tz)
        single = len(req.course_ids) == 1
        units: list[Unit] = []
        previews = []
        for cid in req.course_ids:
            cm = load_course(self.engine, cid)
            if cm is None:
                raise PromptError(f"unknown course {cid}")
            sections, note = cm.select(
                start, end,
                req.section_from if single else None,
                req.section_to if single else None,
            )
            previews.append({
                "id": cm.course.id,
                "fullname": cm.course.fullname,
                "lang": cm.course.lang,
                "sections": len(sections),
                "files": sum(len(s.files) for s in sections),
                "readable_files": sum(1 for s in sections for f in s.files if f.readable),
                "pages": sum(s.pages for s in sections),
                "note": note,
            })
            if sections:
                units += self._split(cm, sections, DEPTHS[req.depth][1])
        if not units:
            raise PromptError("nothing matches: the chosen courses have no material in that "
                              "range. Try another period or section range, or sync first.")
        prompts = self._pack(units, DEPTHS[req.depth][1])
        rendered = [
            {"title": self._title(template, chunk, i, len(prompts)),
             "text": self._render(template, req, chunk, i, len(prompts))}
            for i, chunk in enumerate(prompts, start=1)
        ]
        return {
            "summary": {
                "sections": sum(p["sections"] for p in previews),
                "files": sum(p["files"] for p in previews),
                "readable_files": sum(p["readable_files"] for p in previews),
                "pages": sum(p["pages"] for p in previews),
                "prompts": len(rendered),
            },
            "courses": previews,
            "prompts": rendered,
        }

    # -- splitting

    def _split(self, cm: CourseMaterials, sections: list[SectionInfo], budget: int) -> list[Unit]:
        """Cut one course's sections into consecutive runs within the page budget."""
        units, current, pages = [], [], 0
        for sec in sections:
            if current and (pages + sec.pages > budget or len(current) >= MAX_SECTIONS_PER_PROMPT):
                units.append(Unit(cm, current))
                current, pages = [], 0
            current.append(sec)
            pages += sec.pages
        if current:
            units.append(Unit(cm, current))
        return units

    def _pack(self, units: list[Unit], budget: int) -> list[list[Unit]]:
        """Put small units (whole small courses) together in one prompt."""
        prompts: list[list[Unit]] = []
        for unit in units:
            last = prompts[-1] if prompts else None
            if (last and sum(u.pages for u in last) + unit.pages <= budget
                    and sum(len(u.sections) for u in last) + len(unit.sections) <= MAX_SECTIONS_PER_PROMPT
                    and all(u.cm.course.id != unit.cm.course.id for u in last)):
                last.append(unit)
            else:
                prompts.append([unit])
        return prompts

    # -- rendering

    def _split_course(self, cm: CourseMaterials, units: list[Unit]) -> bool:
        return sum(1 for u in units if u.cm is cm) > 1

    def _title(self, template: Template, chunk: list[Unit], i: int, n: int) -> str:
        names = ", ".join(u.cm.course.shortname or u.cm.course.fullname for u in chunk)
        if n == 1:
            return f"{template.title}: {names}"
        lo, hi = chunk[0].numbers
        sections = f", sections {lo}-{hi}" if len(chunk) == 1 else ""
        return f"Part {i} of {n}: {names}{sections}"

    def _period(self, req: Request) -> str:
        if req.from_date or req.to_date:
            start = req.from_date.isoformat() if req.from_date else "the start of the course"
            end = req.to_date.isoformat() if req.to_date else str(self.today)
            text = f"{start} to {end}"
        else:
            text = "the whole course"
        if len(req.course_ids) == 1 and (req.section_from is not None or req.section_to is not None):
            lo = req.section_from if req.section_from is not None else 0
            hi = req.section_to if req.section_to is not None else "the end"
            text = (f"sections {lo} to {hi}" if text == "the whole course"
                    else f"{text}, sections {lo} to {hi}")
        return text

    def _steps(self, req: Request, chunk: list[Unit], whole: dict[int, bool]) -> str:
        steps: list[str] = []
        for u in chunk:
            c = u.cm.course
            args = [f"course_id={c.id}"]
            if req.from_date:
                args.append(f'from_date="{req.from_date.isoformat()}"')
            if req.to_date:
                args.append(f'to_date="{req.to_date.isoformat()}"')
            lo, hi = u.numbers
            ranged = len(req.course_ids) == 1 and (req.section_from is not None or req.section_to is not None)
            if not whole[c.id] or ranged:
                args += [f"section_from={lo}", f"section_to={hi}"]
            steps.append(f"get_materials({', '.join(args)}) to list the sections and files"
                         f" of {c.fullname}")
        steps.append("read_file(file_id, pages) for the files that matter, a few pages at a "
                     "time; use get_section(section_id) when a section's activities need detail")
        if req.goal in ("study_plan", "catch_up", "study_session"):
            hours = f", hours_per_day={req.hours_per_day:g}" if req.hours_per_day else ""
            days = f", days={req.days}" if req.days else ""
            for u in chunk:
                steps.append(f"get_catch_up_plan(course_id={u.cm.course.id}{hours}{days}) for the "
                             "app's rule-based plan as a starting point: the mandatory work left, "
                             "its deadlines, and what is beyond my catch-up target")
        if req.goal == "review" or (req.save_results and req.goal == "quiz"):
            for u in chunk:
                steps.append(f"get_questions(course_id={u.cm.course.id}, due_only=true) for the "
                             "saved questions due for review (with their question_id)")
        if req.goal == "weak_spots":
            for u in chunk:
                steps.append(f"get_questions(course_id={u.cm.course.id}) for all saved questions, "
                             "with the ones I missed (misses) and the ones due")
        if req.topic:
            for u in chunk:
                steps.append(f"search_materials(query={_q(req.topic)}, course_id={u.cm.course.id}) "
                             f"to find where the topic is covered")
        if req.include_deadlines:
            until = self.today + timedelta(days=max(30, (req.days or 0)))
            for u in chunk:
                extra = ", include_done=false" if req.goal == "assignment" else ""
                steps.append(f'get_deadlines(course_id={u.cm.course.id}, from_date="{self.today}", '
                             f'to_date="{until}"{extra}) for what is due next')
        return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))

    def _language(self, req: Request, chunk: list[Unit]) -> str:
        if req.language != "course":
            return LANGUAGES[req.language]
        langs = {u.cm.course.lang for u in chunk if u.cm.course.lang}
        if len(langs) == 1:
            code = langs.pop()
            return LANGUAGES.get(code, code)
        return "the language of each course's material" if langs else "the language of the course material"

    def _render(self, template: Template, req: Request, chunk: list[Unit], i: int, n: int) -> str:
        whole = {}
        for u in chunk:
            whole[u.cm.course.id] = True
        # A course is "whole" in this prompt unless its sections were split across prompts.
        for u in chunk:
            cid = u.cm.course.id
            total = len(u.cm.select(*bounds(req.from_date, req.to_date, self.tz))[0])
            whole[cid] = len(u.sections) == total
        courses = ", ".join(f'"{u.cm.course.fullname}" (course_id {u.cm.course.id})' for u in chunk)
        part = ""
        if n > 1:
            covered = "; ".join(
                f"{u.cm.course.fullname} sections {u.numbers[0]} to {u.numbers[1]}" for u in chunk)
            part = (f"This is part {i} of {n} (to stay within your limits): cover only "
                    f"{covered}. I will paste the next part afterwards.")
        values = {
            "courses": courses,
            "period": self._period(req),
            "steps": self._steps(req, chunk, whole),
            "language": self._language(req, chunk),
            "depth": DEPTHS[req.depth][2],
            "time": time_text(req),
            "topic": req.topic,
            "part": part,
            "today": self.today.isoformat(),
            "target": f"{target_percent(self.engine):g}%",
            "deadlines": "yes" if req.include_deadlines else "",
            "completion": "yes" if req.include_completion else "",
            "save": "yes" if req.save_results else "",
        }
        return render(template.body, values)
