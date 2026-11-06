"""Course material read model shared by the MCP tools and the prompt builder.

Moodle does not date sections, so a *period* selects the sections with something dated in
it: a file uploaded or changed in the period, or an activity with a deadline in it. Courses
copied from an earlier year often keep old file dates; when nothing matches, callers fall
back to the whole course (or a section range) and say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from app import teacher_pages
from app.db import session
from app.models import Course, Deadline, File, FileText, Module, Section

# Rough pages for files whose text is not extracted yet (for previews only).
BYTES_PER_PAGE = {"pdf": 60_000, "pptx": 150_000, "docx": 20_000}
DONE_STATES = {1, 2}
MODULE_LABELS = {
    "resource": "File", "folder": "Folder", "page": "Page", "url": "Link", "assign": "Assignment",
    "quiz": "Quiz", "forum": "Forum", "label": "Text", "book": "Book", "lesson": "Lesson",
    "h5pactivity": "H5P", "scorm": "SCORM", "feedback": "Feedback", "choice": "Choice",
    "workshop": "Workshop", "glossary": "Glossary", "wiki": "Wiki", "lti": "External tool",
}


def parse_date(value: str | None, name: str = "date") -> date | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ValueError(f"{name} must be a date like 2026-09-01") from None


def day_start(d: date, tz: ZoneInfo) -> int:
    return int(datetime.combine(d, time.min, tzinfo=tz).timestamp())


def bounds(start: date | None, end: date | None, tz: ZoneInfo) -> tuple[int | None, int | None]:
    """Unix seconds for [start 00:00, end + 1 day 00:00) in ``tz``."""
    return (
        day_start(start, tz) if start else None,
        day_start(end + timedelta(days=1), tz) if end else None,
    )


def fmt_date(ts: int | None, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d") if ts else ""


def fmt_datetime(ts: int | None, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M") if ts else ""


def file_kind(f: File) -> str:
    from app.extract.formats import kind_of

    return kind_of(f.mimetype, f.filename) or ""


@dataclass
class FileInfo:
    row: File
    text: FileText | None
    title: str = ""  # readable name of a teacher page (Moodle exports them as index.html)

    @property
    def name(self) -> str:
        return self.title or self.row.filename

    @property
    def id(self) -> int:
        return int(self.row.id or 0)

    @property
    def readable(self) -> bool:
        return bool(self.text and self.text.status == "ok" and self.text.pages)

    @property
    def pages(self) -> int:
        """Extracted pages, else an estimate from the file size (0 for media files)."""
        if self.text is not None and self.text.status in {"ok", "empty"}:
            return self.text.pages
        per_page = BYTES_PER_PAGE.get(file_kind(self.row))
        if per_page and self.row.filesize:
            return max(1, self.row.filesize // per_page)
        return 1 if file_kind(self.row) in {"html", "text"} else 0

    @property
    def unit(self) -> str:
        return self.text.unit if self.text else "page"


@dataclass
class ModuleInfo:
    row: Module
    files: list[FileInfo] = field(default_factory=list)
    deadlines: list[Deadline] = field(default_factory=list)

    @property
    def label(self) -> str:
        return MODULE_LABELS.get(self.row.modname, self.row.modname.capitalize() or "Activity")

    @property
    def done(self) -> bool:
        return self.row.completion_state in DONE_STATES


@dataclass
class SectionInfo:
    row: Section
    modules: list[ModuleInfo] = field(default_factory=list)

    def dates(self) -> list[int]:
        out = []
        for m in self.modules:
            out += [f.row.timemodified for f in m.files if f.row.timemodified]
            out += [d.due_at for d in m.deadlines if d.due_at]
        return out

    def in_period(self, start: int | None, end: int | None) -> bool:
        return any((start is None or t >= start) and (end is None or t < end)
                   for t in self.dates())

    @property
    def files(self) -> list[FileInfo]:
        return [f for m in self.modules for f in m.files]

    @property
    def pages(self) -> int:
        return sum(f.pages for f in self.files)

    @property
    def empty(self) -> bool:
        return not self.modules and not self.row.summary


@dataclass
class CourseMaterials:
    course: Course
    sections: list[SectionInfo]

    def section(self, section_id: int) -> SectionInfo | None:
        return next((s for s in self.sections if s.row.id == section_id), None)

    def select(
        self,
        start: int | None = None,
        end: int | None = None,
        section_from: int | None = None,
        section_to: int | None = None,
    ) -> tuple[list[SectionInfo], str]:
        """Sections for a period and/or section number range, with a note when the period
        matched nothing and the whole range is returned instead."""
        chosen = [
            s for s in self.sections
            if (section_from is None or s.row.number >= section_from)
            and (section_to is None or s.row.number <= section_to)
            and not s.empty
        ]
        if start is None and end is None:
            return chosen, ""
        dated = [s for s in chosen if s.in_period(start, end)]
        if dated:
            return dated, ""
        return chosen, (
            "Nothing in this course is dated in that period (the source site only dates file uploads "
            "and deadlines, and copied courses keep old dates), so all sections"
            + (" in the section range" if section_from is not None or section_to is not None else "")
            + " are listed. Ask the student which sections they missed if unsure."
        )


def load_course(engine: Engine, course_id: int) -> CourseMaterials | None:
    with session(engine) as s:
        course = s.get(Course, course_id)
        if course is None:
            return None
        sections = s.exec(
            select(Section).where(Section.course_id == course_id).order_by(Section.number)
        ).all()
        modules = s.exec(
            select(Module)
            .where(Module.course_id == course_id, Module.removed == False)  # noqa: E712
            .order_by(Module.position, Module.id)
        ).all()
        files = s.exec(
            select(File)
            .where(File.course_id == course_id, File.status != "removed")
            .order_by(File.filepath, File.filename)
        ).all()
        file_ids = [f.id for f in files]
        texts = {
            t.file_id: t
            for t in s.exec(select(FileText).where(col(FileText.file_id).in_(file_ids))).all()
        } if file_ids else {}
        deadlines = s.exec(
            select(Deadline).where(Deadline.course_id == course_id,
                                   Deadline.removed == False)  # noqa: E712
        ).all()
    names = teacher_pages.titles(engine, list(files))
    files_by_module: dict[int, list[FileInfo]] = {}
    for f in files:
        files_by_module.setdefault(f.module_id, []).append(
            FileInfo(f, texts.get(f.id), names.get(f.id, ""))
        )
    deadlines_by_module: dict[int, list[Deadline]] = {}
    for d in deadlines:
        if d.module_id:
            deadlines_by_module.setdefault(d.module_id, []).append(d)
    mods_by_section: dict[int | None, list[ModuleInfo]] = {}
    for m in modules:
        mods_by_section.setdefault(m.section_id, []).append(
            ModuleInfo(m, files_by_module.get(m.id, []), deadlines_by_module.get(m.id, []))
        )
    return CourseMaterials(
        course, [SectionInfo(sec, mods_by_section.get(sec.id, [])) for sec in sections]
    )


def enrolled_courses(engine: Engine, include_past: bool = False) -> list[Course]:
    with session(engine) as s:
        q = select(Course).order_by(Course.fullname)
        if not include_past:
            q = q.where(Course.enrolled == True)  # noqa: E712
        return list(s.exec(q).all())
