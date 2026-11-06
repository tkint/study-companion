"""Extracted text storage and the FTS5 search index.

``search_index`` is an FTS5 table (created in ``app.db``) over file pages, section
summaries and activity descriptions. Rows have a ``kind`` (file, section, module), the id
they point to, the page (files only) and the course/section, so search hits can be turned
into ``read_file``/``get_section`` calls.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import delete, select

from app.db import session
from app.extract.formats import ExtractError, extract, kind_of
from app.models import Course, File, FilePage, FileText, Module, Section
from app.moodle.names import UnsafePathError, safe_join

logger = logging.getLogger("app.extract")

MAX_EXTRACT_MB = 100

FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5("
    "title, body, kind UNINDEXED, ref_id UNINDEXED, page UNINDEXED, "
    "course_id UNINDEXED, section_id UNINDEXED, "
    "tokenize = 'unicode61 remove_diacritics 2')"
)


@dataclass
class ExtractStats:
    extracted: int = 0
    unchanged: int = 0
    failed: int = 0
    removed: int = 0

    def __str__(self) -> str:
        return (f"{self.extracted} extracted, {self.unchanged} unchanged, "
                f"{self.failed} without text, {self.removed} removed")


def _insert_rows(conn, rows: list[dict]) -> None:
    if rows:
        conn.execute(
            text("INSERT INTO search_index (title, body, kind, ref_id, page, course_id, section_id) "
                 "VALUES (:title, :body, :kind, :ref_id, :page, :course_id, :section_id)"),
            rows,
        )


def _drop_file(conn, file_id: int) -> None:
    conn.execute(text("DELETE FROM search_index WHERE kind = 'file' AND ref_id = :id"),
                 {"id": file_id})


def extract_files(engine: Engine, data_dir: Path, clock=time.time,
                  force: bool = False) -> ExtractStats:
    """Extract text from downloaded files that are new or changed since the last run, and
    forget the text of files that are gone from Moodle. Synchronous (CPU bound): run it in
    a thread from async code."""
    stats = ExtractStats()
    with session(engine) as s:
        files = s.exec(select(File)).all()
        states = {t.file_id: t for t in s.exec(select(FileText)).all()}
    max_bytes = MAX_EXTRACT_MB * 1024 * 1024
    for f in files:
        state = states.get(f.id)
        if f.status == "removed":
            if state is not None:
                _forget(engine, f.id)
                stats.removed += 1
            continue
        if f.status != "ok" or not f.local_path:
            continue
        version = (f.downloaded_timemodified, f.downloaded_size)
        if (not force and state is not None
                and (state.source_timemodified, state.source_size) == version):
            stats.unchanged += 1
            continue
        kind = kind_of(f.mimetype, f.filename)
        new = FileText(file_id=f.id, source_timemodified=version[0], source_size=version[1],
                       extracted_at=int(clock()))
        pages: list[str] = []
        if kind is None:
            new.status = "unsupported"
        else:
            try:
                path = safe_join(data_dir, f.local_path)
                if not path.is_file():
                    raise ExtractError("file missing on the server")
                if path.stat().st_size > max_bytes:
                    new.status = "too_large"
                else:
                    result = extract(path, kind)
                    pages, new.unit = result.pages, result.unit
                    new.chars = sum(len(p) for p in pages)
                    new.status = "ok" if new.chars else "empty"
            except (ExtractError, UnsafePathError) as exc:
                new.status, new.error = "error", str(exc)[:300]
            except Exception as exc:  # a library bug on one file must not stop the run
                new.status, new.error = "error", f"unexpected {type(exc).__name__}"
                logger.warning("Extraction of file %s crashed: %s", f.id, type(exc).__name__)
        new.pages = len(pages)
        if new.status in {"ok", "empty"} and kind:
            stats.extracted += 1
        elif kind:
            stats.failed += 1
        _store(engine, f, new, pages)
    return stats


def _forget(engine: Engine, file_id: int) -> None:
    with session(engine) as s:
        s.exec(delete(FilePage).where(FilePage.file_id == file_id))
        state = s.get(FileText, file_id)
        if state is not None:
            s.delete(state)
        _drop_file(s.connection(), file_id)
        s.commit()


def _title(s, f: File, pages: list[str]) -> str:
    """Search title: teacher pages come from Moodle as ``index.html``; use the activity
    name (plus the chapter heading for a book chapter) so search hits are readable."""
    if f.filename.lower() not in {"index.html", "index.htm"}:
        return f.filename
    module = s.get(Module, f.module_id)
    name = module.name if module and module.name else f.filename
    first = (pages[0] if pages else "").strip().split("\n", 1)[0].strip()
    if module is not None and module.modname == "book" and first and len(first) <= 120:
        return f"{name}: {first}"
    return name


def _store(engine: Engine, f: File, state: FileText, pages: list[str]) -> None:
    with session(engine) as s:
        title = _title(s, f, pages)
        s.exec(delete(FilePage).where(FilePage.file_id == f.id))
        conn = s.connection()
        _drop_file(conn, f.id)
        s.merge(state)
        for i, body in enumerate(pages, start=1):
            s.add(FilePage(file_id=f.id, page=i, text=body))
        _insert_rows(conn, [
            {"title": title, "body": body, "kind": "file", "ref_id": f.id, "page": i,
             "course_id": f.course_id, "section_id": f.section_id}
            for i, body in enumerate(pages, start=1) if body
        ])
        s.commit()


def index_structure(engine: Engine) -> None:
    """Rebuild the index rows for section summaries and activity names/descriptions."""
    with session(engine) as s:
        sections = s.exec(select(Section)).all()
        modules = s.exec(select(Module).where(Module.removed == False)).all()  # noqa: E712
        conn = s.connection()
        conn.execute(text("DELETE FROM search_index WHERE kind IN ('section', 'module')"))
        rows = [
            {"title": sec.name, "body": sec.summary, "kind": "section", "ref_id": sec.id,
             "page": None, "course_id": sec.course_id, "section_id": sec.id}
            for sec in sections
        ]
        rows += [
            {"title": m.name, "body": m.description, "kind": "module", "ref_id": m.id,
             "page": None, "course_id": m.course_id, "section_id": m.section_id}
            for m in modules if m.name or m.description
        ]
        _insert_rows(conn, rows)
        s.commit()


_WORD = re.compile(r"\w+", re.UNICODE)


def fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 query: every word must match (prefix match on the
    last one); FTS syntax characters in the input are ignored."""
    words = _WORD.findall(query or "")[:12]
    if not words:
        return ""
    quoted = [f'"{w}"' for w in words]
    quoted[-1] += "*"
    return " ".join(quoted)


@dataclass
class Hit:
    kind: str
    ref_id: int
    page: int | None
    course_id: int | None
    section_id: int | None
    title: str
    snippet: str


def search(engine: Engine, query: str, course_id: int | None = None,
           limit: int = 10, offset: int = 0) -> tuple[list[Hit], int]:
    """Best matches first, plus the total number of matches. Only enrolled courses."""
    match = fts_query(query)
    if not match:
        return [], 0
    with session(engine) as s:
        enrolled = [c.id for c in s.exec(select(Course).where(Course.enrolled == True)).all()]  # noqa: E712
        if course_id is not None:
            enrolled = [c for c in enrolled if c == course_id]
        if not enrolled:
            return [], 0
        ids = ",".join(str(int(c)) for c in enrolled)
        where = f"search_index MATCH :q AND course_id IN ({ids})"
        conn = s.connection()
        try:
            total = conn.execute(text(f"SELECT count(*) FROM search_index WHERE {where}"),
                                 {"q": match}).scalar_one()
            rows = conn.execute(
                text(f"SELECT kind, ref_id, page, course_id, section_id, title, "
                     f"snippet(search_index, -1, '**', '**', ' … ', 24) "
                     f"FROM search_index WHERE {where} ORDER BY bm25(search_index, 4.0, 1.0) "
                     f"LIMIT :limit OFFSET :offset"),
                {"q": match, "limit": limit, "offset": offset},
            ).all()
        except Exception as exc:  # malformed query despite quoting: treat as no match
            logger.info("Search failed: %s", type(exc).__name__)
            return [], 0
    hits = [Hit(r[0], int(r[1]), int(r[2]) if r[2] is not None else None,
                r[3], r[4], r[5] or "", (r[6] or "").replace("\n", " ")) for r in rows]
    return hits, int(total)
