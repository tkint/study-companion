"""SQLModel tables. Moodle ids are kept as primary keys where Moodle provides stable ones.

Timestamps are Unix seconds (UTC) like Moodle's, ``None`` when Moodle has none (e.g. no due
date). Later milestones add notes, questions and FTS5 tables. New tables (rather than new
columns) keep existing databases working, since `create_all` only adds missing tables.
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class Account(SQLModel, table=True):
    """The app's user. Single-user for now (id 1); the table is ready for more."""

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = ""
    password_hash: str = Field(default="", repr=False)
    # Bumped on password change: invalidates every existing session cookie.
    session_epoch: int = 0
    created_at: int = 0
    updated_at: int = 0


class MoodleAccount(SQLModel, table=True):
    """A user's Moodle site and web service token (encrypted with SECRET_KEY)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="account.id", unique=True, index=True)
    url: str = ""
    token_encrypted: str = Field(default="", repr=False)
    token_updated_at: Optional[int] = None
    checked_at: Optional[int] = None
    check_ok: Optional[bool] = None
    check_message: str = ""


class Site(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)  # single row
    url: str = ""
    sitename: str = ""
    release: str = ""
    userid: int = 0
    fullname: str = ""
    lang: str = ""  # user's language on the site (base code)
    updated_at: int = 0


class Course(SQLModel, table=True):
    id: int = Field(primary_key=True)  # Moodle course id
    shortname: str = ""
    fullname: str = ""
    summary: str = ""
    category: Optional[int] = None
    # Language of the course material: base ISO code (en, fr, es) and where it came from:
    # "course" (forced in Moodle), "detected" (from names/summaries) or "site" (your
    # Moodle language, used as a fallback).
    lang: str = ""
    lang_source: str = ""
    moodle_lang: str = ""  # the raw course lang field, e.g. "fr_ch"
    startdate: Optional[int] = None
    enddate: Optional[int] = None
    visible: bool = True
    progress: Optional[float] = None
    folder: str = ""  # relative to DATA_DIR/courses
    enrolled: bool = True  # False once you are no longer enrolled (data kept)
    synced_at: Optional[int] = None


class Section(SQLModel, table=True):
    id: int = Field(primary_key=True)  # Moodle section id
    course_id: int = Field(index=True, foreign_key="course.id")
    number: int = 0
    name: str = ""
    summary: str = ""
    visible: bool = True
    folder: str = ""


class Module(SQLModel, table=True):
    id: int = Field(primary_key=True)  # course module id (cmid)
    course_id: int = Field(index=True, foreign_key="course.id")
    section_id: Optional[int] = Field(default=None, index=True)
    modname: str = ""  # resource, folder, page, url, assign, quiz, forum, ...
    instance: Optional[int] = None
    name: str = ""
    description: str = ""
    url: str = ""
    visible: bool = True
    position: int = 0
    completion_state: Optional[int] = None  # 0 incomplete, 1 complete, 2 pass, 3 fail
    completion_time: Optional[int] = None
    removed: bool = False


class File(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("module_id", "filepath", "filename"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: int = Field(index=True, foreign_key="module.id")
    course_id: int = Field(index=True, foreign_key="course.id")
    section_id: Optional[int] = None
    filename: str = ""
    filepath: str = "/"
    mimetype: str = ""
    filesize: int = 0
    timemodified: int = 0
    fileurl: str = Field(default="", repr=False)  # never contains the token
    local_path: str = ""  # relative to DATA_DIR
    downloaded_size: Optional[int] = None
    downloaded_timemodified: Optional[int] = None
    downloaded_at: Optional[int] = None
    status: str = "pending"  # pending, ok, skipped_size, external, error, removed
    error: str = ""


class Deadline(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str  # assign, quiz, event
    source_id: int
    course_id: Optional[int] = Field(default=None, index=True)
    module_id: Optional[int] = None
    name: str = ""
    kind: str = ""  # due, close, action (calendar)
    due_at: Optional[int] = Field(default=None, index=True)
    open_at: Optional[int] = None
    cutoff_at: Optional[int] = None
    url: str = ""
    grade: Optional[float] = None
    description: str = ""
    removed: bool = False


class SyncRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: int
    finished_at: Optional[int] = None
    trigger: str = ""  # schedule, manual, cli
    status: str = "running"  # running, ok, partial, error
    courses: int = 0
    files_downloaded: int = 0
    files_unchanged: int = 0
    files_failed: int = 0
    bytes_downloaded: int = 0
    deadlines: int = 0
    message: str = ""


class DeadlineMark(SQLModel, table=True):
    """A deadline you marked done in the web UI (Moodle has no completion for it, or you
    handed it in another way). Kept apart from Deadline so a resync never overwrites it."""

    deadline_id: int = Field(primary_key=True, foreign_key="deadline.id")
    done_at: int = 0


class CalendarFeed(SQLModel, table=True):
    """Secret ICS feed URL per user. The token is an HMAC of SECRET_KEY and ``epoch``, so it
    can be shown again at any time and a new link (epoch + 1) revokes the old one."""

    user_id: int = Field(primary_key=True, foreign_key="account.id")
    epoch: int = 0
    created_at: int = 0
