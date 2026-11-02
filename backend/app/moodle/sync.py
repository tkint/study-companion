"""Moodle -> SQLite + files sync.

One run: site info, enrolled courses, each course's sections/modules/files and completion,
deadlines (assignments, quizzes, calendar action events), then file downloads. Files are
stored under ``DATA_DIR/courses/<course>/<NN section>/[<module>/]<file>`` and skipped when
their Moodle ``timemodified`` and size are unchanged. Errors in one course or one file do
not stop the run; the run is then marked ``partial``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import select

from app import accounts
from app.config import Settings
from app.db import session as db_session
from app.models import Course, Deadline, File, Module, Section, Site, SyncRun
from app.moodle import api
from app.moodle.client import MoodleAuthError, MoodleClient, MoodleError, strip_secrets
from app.moodle.names import safe_join, safe_name, safe_relpath
from app.moodle.text import clean_text, detect_lang, normalise_lang

logger = logging.getLogger("app.moodle.sync")

COURSES_DIR = "courses"
EVENTS_PAST_DAYS = 120
EVENTS_FUTURE_DAYS = 365
# Modules whose files go straight into the section folder (one file per module, usually).
FLAT_MODULES = {"resource"}

ClientFactory = Callable[[str, str], MoodleClient]  # (site url, token) -> client


def default_client_factory(settings: Settings) -> ClientFactory:
    def factory(url: str, token: str) -> MoodleClient:
        return MoodleClient(
            url,
            token,
            rate_limit=settings.moodle_rate_limit,
            timeout=settings.moodle_timeout,
            service=settings.moodle_service,
        )

    return factory


class SyncAlreadyRunning(RuntimeError):
    pass


class SyncService:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        client_factory: ClientFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.client_factory = client_factory or default_client_factory(settings)
        self.clock = clock
        self.base_url = ""
        self._lock = asyncio.Lock()

    def configured(self) -> bool:
        return accounts.get_moodle(self.engine, self.settings.secret_key).configured

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def last_run(self) -> SyncRun | None:
        with db_session(self.engine) as s:
            return s.exec(select(SyncRun).order_by(SyncRun.id.desc()).limit(1)).first()

    async def run(self, trigger: str = "manual") -> SyncRun:
        if self._lock.locked():
            raise SyncAlreadyRunning("A sync is already running")
        async with self._lock:
            return await self._run(trigger)

    # ---------------------------------------------------------------- orchestration

    async def _run(self, trigger: str) -> SyncRun:
        now = int(self.clock())
        with db_session(self.engine) as s:
            run = SyncRun(started_at=now, trigger=trigger)
            s.add(run)
            s.commit()
            s.refresh(run)
        problems: list[str] = []
        creds = accounts.get_moodle(self.engine, self.settings.secret_key)
        self.base_url = creds.url
        try:
            if not creds.url:
                raise MoodleError("No Moodle site set: add it on the settings page")
            if not creds.token:
                raise MoodleAuthError(
                    "The saved token can no longer be read (SECRET_KEY changed)"
                    if creds.token_unreadable
                    else "No Moodle token saved"
                )
            async with self.client_factory(creds.url, creds.token) as client:
                site = await api.get_site_info(client)
                self._save_site(site)
                courses = await api.get_user_courses(client, site["userid"])
                run.courses = len(courses)
                self._save_courses(courses)
                for course in courses:
                    try:
                        await self._sync_course(client, course, site, problems)
                    except MoodleAuthError:
                        raise
                    except MoodleError as exc:
                        problems.append(f"{course['shortname']}: {exc}")
                        logger.warning("Course %s failed: %s", course["id"], exc)
                run.deadlines = await self._sync_deadlines(
                    client, [c["id"] for c in courses], site, problems
                )
                await self._download_files(client, run, problems)
            run.status = "partial" if problems else "ok"
            run.message = "; ".join(problems[:20])
        except MoodleAuthError as exc:
            run.status = "error"
            run.message = (
                f"{exc}. The Moodle token is missing, invalid or expired: get a new one and "
                "paste it on the settings page (docs/moodle-token.md)."
            )
            accounts.record_check(self.engine, False, run.message)
            logger.error("Sync stopped: Moodle token rejected")
        except MoodleError as exc:
            run.status = "error"
            run.message = str(exc)
            logger.error("Sync failed: %s", exc)
        except Exception as exc:  # keep the scheduler alive, record what happened
            run.status = "error"
            run.message = f"Unexpected error: {type(exc).__name__}"
            logger.exception("Sync crashed")
        run.finished_at = int(self.clock())
        with db_session(self.engine) as s:
            s.add(run)
            s.commit()
            s.refresh(run)
        logger.info(
            "Sync %s: %d courses, %d files downloaded, %d unchanged, %d failed, %d deadlines",
            run.status, run.courses, run.files_downloaded, run.files_unchanged,
            run.files_failed, run.deadlines,
        )
        return run

    # ---------------------------------------------------------------- site and courses

    def _save_site(self, site: dict) -> None:
        with db_session(self.engine) as s:
            row = s.get(Site, 1) or Site(id=1)
            row.url = self.base_url
            row.sitename = clean_text(site["sitename"])
            row.release = site["release"]
            row.userid = site["userid"]
            row.fullname = clean_text(site["fullname"])
            row.lang = normalise_lang(site["lang"])
            row.updated_at = int(self.clock())
            s.add(row)
            s.commit()

    def _save_courses(self, courses: list[dict]) -> None:
        with db_session(self.engine) as s:
            existing = {c.id: c for c in s.exec(select(Course)).all()}
            used_folders = {c.folder for c in existing.values() if c.folder}
            seen = set()
            for data in courses:
                seen.add(data["id"])
                row = existing.get(data["id"]) or Course(id=data["id"])
                forced = normalise_lang(data["lang"])
                row.moodle_lang = data["lang"]
                lang = forced or row.lang
                row.shortname = clean_text(data["shortname"], lang, keep_lines=False)
                row.fullname = clean_text(data["fullname"], lang, keep_lines=False)
                row.summary = clean_text(data["summary"], lang)
                row.category = data["category"]
                row.startdate, row.enddate = data["startdate"], data["enddate"]
                row.visible = data["visible"]
                row.progress = data["progress"]
                row.enrolled = True
                if forced:
                    row.lang, row.lang_source = forced, "course"
                if not row.folder:
                    folder = safe_name(row.shortname, f"course-{row.id}")
                    if folder in used_folders:
                        folder = safe_name(f"{folder} ({row.id})")
                    row.folder = folder
                    used_folders.add(folder)
                s.add(row)
            for cid, row in existing.items():
                if cid not in seen and row.enrolled:
                    row.enrolled = False
                    s.add(row)
            s.commit()

    async def _sync_course(
        self, client: MoodleClient, course: dict, site: dict, problems: list[str]
    ) -> None:
        sections = await api.get_course_contents(client, course["id"])
        completion: dict[int, dict] = {}
        if _available(site, "core_completion_get_activities_completion_status"):
            try:
                completion = await api.get_completion(client, course["id"], site["userid"])
            except MoodleAuthError:
                raise
            except MoodleError as exc:
                # Usually "completion not enabled for this course": not a problem.
                logger.info("No completion data for course %s (%s)", course["id"], exc.errorcode)

        with db_session(self.engine) as s:
            row = s.get(Course, course["id"])
            assert row is not None
            lang = self._course_lang(row, course, sections, site)
            course_dir = Path(COURSES_DIR) / row.folder

            seen_sections, seen_modules, seen_files = set(), set(), set()
            claimed: dict[str, tuple] = {}
            files = {
                (f.module_id, f.filepath, f.filename): f
                for f in s.exec(select(File).where(File.course_id == row.id)).all()
            }
            for sec in sections:
                seen_sections.add(sec["id"])
                srow = s.get(Section, sec["id"]) or Section(id=sec["id"], course_id=row.id)
                srow.course_id = row.id
                srow.number = sec["number"]
                srow.name = clean_text(sec["name"], lang, keep_lines=False) or (
                    "General" if sec["number"] == 0 else f"Section {sec['number']}"
                )
                srow.summary = clean_text(sec["summary"], lang)
                srow.visible = sec["visible"]
                srow.folder = safe_name(f"{srow.number:02d} {srow.name}")
                s.add(srow)
                for mod in sec["modules"]:
                    seen_modules.add(mod["id"])
                    mrow = s.get(Module, mod["id"]) or Module(id=mod["id"], course_id=row.id)
                    mrow.course_id, mrow.section_id = row.id, srow.id
                    mrow.modname, mrow.instance = mod["modname"], mod["instance"]
                    mrow.name = clean_text(mod["name"], lang, keep_lines=False)
                    mrow.description = clean_text(mod["description"], lang)
                    mrow.url = mod["url"]
                    mrow.visible, mrow.position = mod["visible"], mod["position"]
                    mrow.removed = False
                    done = completion.get(mod["id"])
                    if done is not None:
                        mrow.completion_state = done["state"]
                        mrow.completion_time = done["timecompleted"]
                    s.add(mrow)
                    s.flush()

                    for f in mod["files"]:
                        key = (mod["id"], f["filepath"], f["filename"])
                        seen_files.add(key)
                        frow = files.get(key) or File(
                            module_id=mod["id"], course_id=row.id,
                            filepath=f["filepath"], filename=f["filename"],
                        )
                        frow.section_id = srow.id
                        frow.mimetype = f["mimetype"]
                        frow.filesize = f["filesize"]
                        frow.timemodified = f["timemodified"]
                        frow.fileurl = strip_secrets(f["fileurl"])
                        parts = [srow.folder]
                        if mod["modname"] not in FLAT_MODULES or len(mod["files"]) > 1:
                            parts.append(safe_name(mrow.name, f"module-{mod['id']}"))
                        parts += safe_relpath(f["filepath"])
                        name = safe_name(f["filename"], f"file-{mod['id']}")
                        rel = _unique(course_dir.joinpath(*parts), name, mod["id"], key, claimed)
                        self._move_if_renamed(frow, rel)
                        frow.local_path = rel
                        if frow.status == "removed":
                            frow.status = "pending"
                        s.add(frow)

            for key, frow in files.items():
                if key not in seen_files and frow.status != "removed":
                    frow.status = "removed"  # keep the local copy
                    s.add(frow)
            for mrow in s.exec(select(Module).where(Module.course_id == row.id)).all():
                if mrow.id not in seen_modules and not mrow.removed:
                    mrow.removed = True
                    s.add(mrow)
            for srow in s.exec(select(Section).where(Section.course_id == row.id)).all():
                if srow.id not in seen_sections:
                    s.delete(srow)
            row.synced_at = int(self.clock())
            s.add(row)
            s.commit()

    def _course_lang(self, row: Course, course: dict, sections: list[dict], site: dict) -> str:
        forced = normalise_lang(course["lang"])
        if forced:
            row.lang, row.lang_source = forced, "course"
            return forced
        site_lang = normalise_lang(site["lang"])
        sample = [row.fullname, row.summary]
        for sec in sections:
            sample += [clean_text(sec["name"], site_lang), clean_text(sec["summary"], site_lang)]
            sample += [clean_text(m["name"], site_lang) for m in sec["modules"]]
            sample += [clean_text(m["description"], site_lang) for m in sec["modules"]]
        detected = detect_lang(" ".join(sample))
        if detected:
            row.lang, row.lang_source = detected, "detected"
        elif site_lang:
            row.lang, row.lang_source = site_lang, "site"
        return row.lang

    def _move_if_renamed(self, frow: File, new_rel: str) -> None:
        if not frow.local_path or frow.local_path == new_rel:
            return
        data_dir = self.settings.data_dir
        try:
            old = safe_join(data_dir, frow.local_path)
            new = safe_join(data_dir, new_rel)
        except ValueError:
            return
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            old.replace(new)

    # ---------------------------------------------------------------- deadlines

    async def _sync_deadlines(
        self, client: MoodleClient, course_ids: list[int], site: dict, problems: list[str]
    ) -> int:
        if not course_ids:
            return 0
        now = int(self.clock())
        rows: dict[str, list[dict]] = {}

        async def fetch(source: str, wsfunction: str, coro) -> None:
            if not _available(site, wsfunction):
                return
            try:
                rows[source] = await coro
            except MoodleAuthError:
                raise
            except MoodleError as exc:
                problems.append(f"deadlines ({source}): {exc}")

        await fetch("assign", "mod_assign_get_assignments", api.get_assignments(client, course_ids))
        await fetch("quiz", "mod_quiz_get_quizzes_by_courses", api.get_quizzes(client, course_ids))
        await fetch(
            "event",
            "core_calendar_get_action_events_by_timesort",
            api.get_action_events(
                client, now - EVENTS_PAST_DAYS * 86400, now + EVENTS_FUTURE_DAYS * 86400
            ),
        )

        langs = {}
        with db_session(self.engine) as s:
            langs = {c.id: c.lang for c in s.exec(select(Course)).all()}
            covered = {("assign", a["id"]) for a in rows.get("assign", [])}
            covered |= {("quiz", q["id"]) for q in rows.get("quiz", [])}
            items: dict[str, list[dict]] = {}
            for a in rows.get("assign", []):
                items.setdefault("assign", []).append({
                    "source_id": a["id"], "course_id": a["course_id"], "module_id": a["cmid"],
                    "name": a["name"], "kind": "due", "due_at": a["duedate"],
                    "open_at": a["opendate"], "cutoff_at": a["cutoffdate"],
                    "grade": a["grade"], "description": a["intro"],
                    "url": _view_url(self.base_url, "assign", a["cmid"]),
                })
            for q in rows.get("quiz", []):
                items.setdefault("quiz", []).append({
                    "source_id": q["id"], "course_id": q["course_id"], "module_id": q["cmid"],
                    "name": q["name"], "kind": "close", "due_at": q["timeclose"],
                    "open_at": q["timeopen"], "cutoff_at": None,
                    "grade": q["grade"], "description": q["intro"],
                    "url": _view_url(self.base_url, "quiz", q["cmid"]),
                })
            for e in rows.get("event", []):
                if (e["modulename"], e["instance"]) in covered:
                    continue  # already recorded from the assignment/quiz itself
                items.setdefault("event", []).append({
                    "source_id": e["id"], "course_id": e["course_id"], "module_id": e["cmid"],
                    "name": e["name"], "kind": "action", "due_at": e["timesort"],
                    "open_at": None, "cutoff_at": None, "grade": None,
                    "description": e["description"], "url": e["url"],
                })

            count = 0
            for source in rows:
                existing = {
                    d.source_id: d
                    for d in s.exec(select(Deadline).where(Deadline.source == source)).all()
                }
                seen = set()
                for item in items.get(source, []):
                    seen.add(item["source_id"])
                    d = existing.get(item["source_id"]) or Deadline(
                        source=source, source_id=item["source_id"]
                    )
                    lang = langs.get(item["course_id"] or 0, "")
                    for k, v in item.items():
                        if k in {"name", "description"}:
                            v = clean_text(v, lang, keep_lines=(k == "description"))
                        setattr(d, k, v)
                    d.removed = False
                    s.add(d)
                    count += 1
                for sid, d in existing.items():
                    if sid not in seen and not d.removed:
                        d.removed = True
                        s.add(d)
            s.commit()
        return count

    # ---------------------------------------------------------------- downloads

    async def _download_files(self, client: MoodleClient, run: SyncRun, problems: list[str]) -> None:
        data_dir = self.settings.data_dir
        max_bytes = self.settings.moodle_max_file_mb * 1024 * 1024
        with db_session(self.engine) as s:
            pending = s.exec(
                select(File).where(File.status != "removed").order_by(File.id)
            ).all()
        failures = 0
        for frow in pending:
            try:
                dest = safe_join(data_dir, frow.local_path)
            except ValueError:
                frow.status, frow.error = "error", "unsafe path"
                self._save(frow)
                continue
            if not client.is_moodle_url(frow.fileurl):
                frow.status, frow.error = "external", ""
                self._save(frow)
                continue
            if frow.filesize and frow.filesize > max_bytes:
                frow.status, frow.error = "skipped_size", ""
                self._save(frow)
                continue
            unchanged = (
                dest.exists()
                and frow.downloaded_timemodified == frow.timemodified
                and (not frow.filesize or frow.downloaded_size == frow.filesize)
            )
            if unchanged:
                if frow.status != "ok":
                    frow.status, frow.error = "ok", ""
                    self._save(frow)
                run.files_unchanged += 1
                continue
            try:
                size = await client.download(frow.fileurl, dest, max_bytes=max_bytes)
            except MoodleAuthError:
                raise
            except MoodleError as exc:
                run.files_failed += 1
                failures += 1
                frow.status, frow.error = "error", str(exc)[:300]
                self._save(frow)
                logger.warning("Download failed for file %s: %s", frow.id, exc)
                continue
            frow.downloaded_size = frow.filesize or size
            frow.downloaded_timemodified = frow.timemodified
            frow.downloaded_at = int(self.clock())
            frow.status, frow.error = "ok", ""
            self._save(frow)
            run.files_downloaded += 1
            run.bytes_downloaded += size
        if failures:
            problems.append(f"{failures} file(s) failed to download")

    def _save(self, row) -> None:
        with db_session(self.engine) as s:
            s.add(row)
            s.commit()


# -------------------------------------------------------------------- helpers


def _available(site: dict, wsfunction: str) -> bool:
    functions = site.get("functions") or set()
    return not functions or wsfunction in functions


def _view_url(base: str, modname: str, cmid: int | None) -> str:
    return f"{base}/mod/{modname}/view.php?id={cmid}" if cmid else ""


def _unique(folder: Path, name: str, module_id: int, key: tuple, claimed: dict) -> str:
    rel = (folder / name).as_posix()
    if claimed.get(rel, key) != key:
        stem, dot, ext = name.rpartition(".")
        alt = f"{stem} ({module_id}).{ext}" if dot and stem else f"{name} ({module_id})"
        rel = (folder / safe_name(alt)).as_posix()
    claimed[rel] = key
    return rel
