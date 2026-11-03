"""The MCP read tools as plain functions that return compact text.

Kept free of the MCP SDK so they are easy to test and reuse; ``app.mcp_server`` registers
them as tools. Output is short Markdown with ids (course_id, section_id, file_id) and page
numbers, and long results are paginated with the exact call for the next page, so Claude
can stay within its context window. Dates are in the configured TIMEZONE.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from app.api.ui import deadlines as deadline_rows
from app.config import Settings
from app.db import session
from app.extract import index
from app.materials import (
    CourseMaterials,
    FileInfo,
    SectionInfo,
    bounds,
    enrolled_courses,
    file_kind,
    fmt_date,
    fmt_datetime,
    load_course,
    parse_date,
)
from app.models import Course, Deadline, File, FilePage, FileText, Module, Section

SECTIONS_PER_PAGE = 8
DEADLINES_PER_PAGE = 30
HITS_PER_PAGE = 10
MAX_PAGES_PER_READ = 20
MAX_CHARS_PER_READ = 40_000
DEFAULT_READ_PAGES = 10
SUMMARY_CHARS = 300
DESCRIPTION_CHARS = 1500

# Tool names, used by the prompt templates (and checked by tests).
TOOL_NAMES = (
    "list_courses",
    "get_deadlines",
    "get_materials",
    "get_section",
    "read_file",
    "search_materials",
)


class ToolInputError(ValueError):
    """Bad arguments: the message is shown to Claude so it can retry."""


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _block(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _page_count(n: int, per_page: int) -> int:
    return max(1, -(-n // per_page))


def _check_page(page: int, pages: int) -> None:
    if page < 1 or page > pages:
        raise ToolInputError(f"page must be between 1 and {pages}")


def _call(name: str, **kwargs) -> str:
    args = ", ".join(
        f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
        for k, v in kwargs.items() if v is not None
    )
    return f"{name}({args})"


def parse_pages(spec: str | int | None, total: int) -> list[int]:
    """``"3"``, ``"1-5"``, ``"2,4,7-9"`` or ``"10-"`` to sorted page numbers within 1..total."""
    if spec is None or str(spec).strip() == "":
        return list(range(1, min(total, DEFAULT_READ_PAGES) + 1))
    pages: set[int] = set()
    for part in str(spec).replace(" ", "").split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d*))?", part)
        if not m:
            raise ToolInputError('pages must look like "3", "1-5" or "2,4,7-9"')
        first = int(m.group(1))
        last = first if m.group(2) is None else (int(m.group(2)) if m.group(2) else total)
        if last < first:
            raise ToolInputError(f"bad page range {part!r}")
        pages.update(range(max(first, 1), min(last, total) + 1))
    if not pages:
        raise ToolInputError(f"no such page: the file has {total} page(s)")
    return sorted(pages)


def _ranges(pages: list[int]) -> str:
    out, start, prev = [], None, None
    for p in pages + [None]:
        if start is None:
            start = prev = p
        elif p is not None and p == prev + 1:
            prev = p
        else:
            out.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = p
    return ",".join(out)


class StudyTools:
    def __init__(self, settings: Settings, engine: Engine, base_url: str = "",
                 clock=time.time) -> None:
        self.settings = settings
        self.engine = engine
        self.base_url = base_url.rstrip("/")
        self.clock = clock
        self.tz = settings.tz

    # ---------------------------------------------------------------- helpers

    def _course(self, course_id: int) -> CourseMaterials:
        cm = load_course(self.engine, int(course_id))
        if cm is None:
            raise ToolInputError(
                f"no course with id {course_id}; call list_courses for the course ids"
            )
        return cm

    def _today(self):
        return datetime.fromtimestamp(self.clock(), self.tz).date()

    def _file_line(self, f: FileInfo) -> str:
        bits = [f'"{f.row.filename}" file_id {f.id}']
        unit = f.unit
        if f.readable:
            bits.append(f"{f.text.pages} {unit}{'s' if f.text.pages != 1 else ''} of text")
        elif f.text is not None:
            bits.append({
                "empty": "no text (scanned or image-only)",
                "unsupported": "no text (file type not supported)",
                "too_large": "not extracted (too large)",
                "error": "text could not be extracted",
            }.get(f.text.status, "no text"))
        elif f.row.status == "ok":
            bits.append("text not extracted yet")
        else:
            bits.append({"skipped_size": "too large to download", "external": "external link",
                         "error": "download failed"}.get(f.row.status, "not downloaded yet"))
        if f.row.timemodified:
            bits.append(f"updated {fmt_date(f.row.timemodified, self.tz)}")
        return " · ".join(bits)

    def _section_text(self, sec: SectionInfo, full: bool) -> list[str]:
        r = sec.row
        lines = [f"## Section {r.number}: {r.name} (section_id {r.id})"]
        if r.summary:
            summary = _block(r.summary, 4000) if full else _short(r.summary, SUMMARY_CHARS)
            lines.append(f"Summary: {summary}")
        for m in sec.modules:
            row = m.row
            head = f"- {m.label}: {row.name or '(untitled)'}"
            if row.completion_state is not None:
                head += " ✓ done" if m.done else " (not done)"
            for d in m.deadlines:
                if d.due_at:
                    head += f" · {'due' if d.kind == 'due' else 'closes'} {fmt_datetime(d.due_at, self.tz)}"
            lines.append(head)
            if row.description and (full or row.modname in {"label", "assign"}):
                limit = DESCRIPTION_CHARS if full else SUMMARY_CHARS
                desc = _block(row.description, limit) if full else _short(row.description, limit)
                lines.append("  " + desc.replace("\n", "\n  "))
            if row.modname == "url" and row.url and full:
                lines.append(f"  Link: {row.url}")
            for f in m.files:
                lines.append(f"  - {self._file_line(f)}")
        return lines

    # ---------------------------------------------------------------- tools

    def list_courses(self, include_past: bool = False) -> str:
        courses = enrolled_courses(self.engine, include_past)
        if not courses:
            return ("No courses yet. The server syncs from Moodle every few hours; the student "
                    "can start a sync in the web UI.")
        now = int(self.clock())
        upcoming: dict[int, int] = {}
        overdue: dict[int, int] = {}
        for d in deadline_rows(self.engine, start=now - 120 * 86400, now=now):
            if d["course_id"] is None or d["done"]:
                continue
            target = upcoming if d["due_at"] >= now else overdue
            target[d["course_id"]] = target.get(d["course_id"], 0) + 1
        with session(self.engine) as s:
            counts: dict[int, list[int]] = {}
            for f, t in s.exec(
                select(File, FileText).join(FileText, FileText.file_id == File.id, isouter=True)
                .where(File.status != "removed")
            ).all():
                c = counts.setdefault(f.course_id, [0, 0])
                c[0] += 1
                if t is not None and t.status == "ok":
                    c[1] += t.pages
            sections: dict[int, int] = {}
            for sec in s.exec(select(Section)).all():
                sections[sec.course_id] = sections.get(sec.course_id, 0) + 1
        lines = [f"{len(courses)} course(s). Use course_id with the other tools."]
        for c in courses:
            files, pages = counts.get(c.id, [0, 0])
            bits = [f"- [{c.id}] {c.fullname or c.shortname}"]
            if c.shortname and c.shortname != c.fullname:
                bits[0] += f" ({c.shortname})"
            if c.lang:
                bits.append(f"language {c.lang}")
            bits.append(f"{sections.get(c.id, 0)} sections, {files} files, {pages} pages of text")
            bits.append(f"{upcoming.get(c.id, 0)} upcoming / {overdue.get(c.id, 0)} overdue deadlines")
            if c.progress is not None:
                bits.append(f"progress {round(c.progress)}%")
            if not c.enrolled:
                bits.append("no longer enrolled")
            lines.append(" · ".join(bits))
        return "\n".join(lines)

    def get_deadlines(
        self,
        course_id: int | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        include_done: bool = True,
        page: int = 1,
    ) -> str:
        try:
            start_d = parse_date(from_date, "from_date") or self._today() - timedelta(days=14)
            end_d = parse_date(to_date, "to_date") or self._today() + timedelta(days=60)
        except ValueError as exc:
            raise ToolInputError(str(exc)) from None
        if end_d < start_d:
            raise ToolInputError("to_date must not be before from_date")
        if course_id is not None:
            self._course(course_id)
        start, end = bounds(start_d, end_d, self.tz)
        now = int(self.clock())
        items = deadline_rows(self.engine, start, end, course_id=course_id, now=now)
        if not include_done:
            items = [d for d in items if not d["done"]]
        pages = _page_count(len(items), DEADLINES_PER_PAGE)
        _check_page(page, pages)
        scope = f" in course {course_id}" if course_id is not None else ""
        head = (f"{len(items)} deadline(s){scope} from {start_d} to {end_d} "
                f"(times in {self.settings.timezone}, today is {self._today()}).")
        if not items:
            return head
        lines = [head]
        with session(self.engine) as s:
            descriptions = {}
            ids = [d["id"] for d in items]
            for row in s.exec(select(Deadline).where(col(Deadline.id).in_(ids))).all():
                descriptions[row.id] = row.description
        kinds = {"assign": "Assignment", "quiz": "Quiz", "event": "Event"}
        for d in items[(page - 1) * DEADLINES_PER_PAGE: page * DEADLINES_PER_PAGE]:
            state = "done" if d["done"] else ("OVERDUE" if d["due_at"] < now else "to do")
            line = (f"- {fmt_datetime(d['due_at'], self.tz)} · {d['course_name'] or 'no course'}"
                    f" · {kinds.get(d['source'], d['source'])}: {d['name']} · {state}")
            if d["grade"]:
                line += f" · max grade {d['grade']:g}"
            if d["module_id"]:
                line += f" · module {d['module_id']}"
            lines.append(line)
            desc = descriptions.get(d["id"])
            if desc:
                lines.append(f"  {_short(desc, 400)}")
        if page < pages:
            lines.append(f"Page {page} of {pages}. Next: " + _call(
                "get_deadlines", course_id=course_id, from_date=str(start_d), to_date=str(end_d),
                include_done=None if include_done else False, page=page + 1))
        return "\n".join(lines)

    def get_materials(
        self,
        course_id: int,
        from_date: str | None = None,
        to_date: str | None = None,
        section_from: int | None = None,
        section_to: int | None = None,
        page: int = 1,
    ) -> str:
        cm = self._course(course_id)
        try:
            start_d = parse_date(from_date, "from_date")
            end_d = parse_date(to_date, "to_date")
        except ValueError as exc:
            raise ToolInputError(str(exc)) from None
        start, end = bounds(start_d, end_d, self.tz)
        sections, note = cm.select(start, end, section_from, section_to)
        pages = _page_count(len(sections), SECTIONS_PER_PAGE)
        _check_page(page, pages)
        c = cm.course
        files = sum(len(s.files) for s in sections)
        text_pages = sum(f.text.pages for s in sections for f in s.files if f.readable)
        period = ""
        if start_d or end_d:
            period = f" for {start_d or 'the start'} to {end_d or 'today'}"
        if section_from is not None or section_to is not None:
            period += f", sections {section_from if section_from is not None else 0}" \
                      f"-{section_to if section_to is not None else 'end'}"
        lines = [
            f"# {c.fullname} (course_id {c.id}){period}",
            f"{len(sections)} section(s), {files} file(s), {text_pages} pages of extracted text."
            + (f" Course language: {c.lang}." if c.lang else ""),
            "Read files with read_file(file_id, pages); open a section in full with "
            "get_section(section_id).",
        ]
        if note:
            lines.append(f"Note: {note}")
        for sec in sections[(page - 1) * SECTIONS_PER_PAGE: page * SECTIONS_PER_PAGE]:
            lines.append("")
            lines += self._section_text(sec, full=False)
        if page < pages:
            lines.append("")
            lines.append(f"Page {page} of {pages}. Next: " + _call(
                "get_materials", course_id=c.id, from_date=from_date or None,
                to_date=to_date or None, section_from=section_from, section_to=section_to,
                page=page + 1))
        return "\n".join(lines)

    def get_section(self, section_id: int) -> str:
        with session(self.engine) as s:
            row = s.get(Section, int(section_id))
        if row is None:
            raise ToolInputError(
                f"no section with id {section_id}; get_materials lists the section ids"
            )
        cm = self._course(row.course_id)
        sec = cm.section(row.id)
        assert sec is not None
        lines = [f"# {cm.course.fullname} (course_id {cm.course.id})"]
        lines += self._section_text(sec, full=True)
        if not sec.modules:
            lines.append("(no activities in this section)")
        return "\n".join(lines)

    def read_file(self, file_id: int, pages: str | None = None) -> str:
        with session(self.engine) as s:
            f = s.get(File, int(file_id))
            state = s.get(FileText, int(file_id)) if f else None
            course = s.get(Course, f.course_id) if f else None
            section = s.get(Section, f.section_id) if f and f.section_id else None
            module = s.get(Module, f.module_id) if f else None
        if f is None or f.status == "removed":
            raise ToolInputError(f"no file with id {file_id}; get_materials lists the file ids")
        where = " › ".join(x for x in [
            course.fullname if course else "", section.name if section else "",
            module.name if module and module.name != f.filename else "",
        ] if x)
        head = f'File {f.id} "{f.filename}" ({where})'
        if state is None or state.status != "ok" or not state.pages:
            reason = {
                None: "its text has not been extracted yet (it is extracted after each sync)",
                "empty": "it has no text layer (probably scanned or images only)",
                "unsupported": "this file type is not supported for text extraction",
                "too_large": "it is too large to extract",
                "error": "its text could not be extracted",
            }.get(state.status if state else None, "it has no text")
            if state is None and f.status != "ok":
                reason = {"skipped_size": "it is too large to download (usually a video)",
                          "external": "it is an external link",
                          "error": "it could not be downloaded"}.get(f.status, "it is not downloaded yet")
            elif state is None and not file_kind(f):
                reason = "this file type is not supported for text extraction"
            link = (f" The student can open it at {self.base_url}/#/file/{f.id}."
                    if self.base_url and f.status == "ok" else "")
            return f"{head}: no text available because {reason}.{link}"
        wanted = parse_pages(pages, state.pages)
        unit = state.unit
        with session(self.engine) as s:
            rows = {
                p.page: p.text for p in s.exec(
                    select(FilePage).where(FilePage.file_id == f.id,
                                           col(FilePage.page).in_(wanted[:MAX_PAGES_PER_READ]))
                ).all()
            }
        out, used, shown = [], 0, []
        for n in wanted[:MAX_PAGES_PER_READ]:
            body = rows.get(n, "").strip() or "(no text on this page)"
            if shown and used + len(body) > MAX_CHARS_PER_READ:
                break
            out.append(f"--- {unit} {n} ---\n{body}")
            used += len(body)
            shown.append(n)
        rest = [p for p in wanted if p not in shown]
        lines = [f"{head}, {unit}s {_ranges(shown)} of {state.pages}:", *out]
        if rest:
            lines.append("(stopped to keep this short) Next: "
                         + _call("read_file", file_id=f.id, pages=_ranges(rest)))
        elif shown[-1] < state.pages and not pages:
            lines.append("More: " + _call("read_file", file_id=f.id,
                                           pages=f"{shown[-1] + 1}-{min(state.pages, shown[-1] + DEFAULT_READ_PAGES)}"))
        return "\n\n".join(lines)

    def search_materials(self, query: str, course_id: int | None = None, page: int = 1) -> str:
        if not index.fts_query(query):
            raise ToolInputError("query must contain at least one word")
        if course_id is not None:
            self._course(course_id)
        if page < 1:
            raise ToolInputError("page must be 1 or more")
        hits, total = index.search(self.engine, query, course_id, HITS_PER_PAGE,
                                   (page - 1) * HITS_PER_PAGE)
        if total == 0:
            return (f'No matches for "{query}". Try fewer or different words (the course may be '
                    f"in another language), or browse with get_materials.")
        pages = _page_count(total, HITS_PER_PAGE)
        _check_page(page, pages)
        with session(self.engine) as s:
            courses = {c.id: c.fullname for c in s.exec(select(Course)).all()}
            section_ids = {h.section_id for h in hits if h.section_id}
            sections = {
                sec.id: sec.name for sec in s.exec(
                    select(Section).where(col(Section.id).in_(section_ids))).all()
            } if section_ids else {}
            states = {
                t.file_id: t.unit for t in s.exec(select(FileText).where(
                    col(FileText.file_id).in_([h.ref_id for h in hits if h.kind == "file"]))).all()
            }
        lines = [f'{total} match(es) for "{query}" (best first, page {page} of {pages}):']
        for i, h in enumerate(hits, start=(page - 1) * HITS_PER_PAGE + 1):
            where = " › ".join(x for x in [courses.get(h.course_id, ""),
                                           sections.get(h.section_id, "")] if x)
            if h.kind == "file":
                what = f'"{h.title}" {states.get(h.ref_id, "page")} {h.page}'
                call = _call("read_file", file_id=h.ref_id, pages=str(h.page))
            elif h.kind == "section":
                what = f'section "{h.title}"'
                call = _call("get_section", section_id=h.ref_id)
            else:
                what = f'activity "{h.title}"'
                call = _call("get_section", section_id=h.section_id) if h.section_id else ""
            lines.append(f"{i}. {what} · {where} · {call}")
            if h.snippet:
                lines.append(f"   {_short(h.snippet, 300)}")
        if page < pages:
            lines.append("Next: " + _call("search_materials", query=query,
                                          course_id=course_id, page=page + 1))
        return "\n".join(lines)
