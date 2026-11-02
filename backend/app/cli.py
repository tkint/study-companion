"""Command line helpers, run inside the container:

    docker compose exec app python -m app.cli check        # test the Moodle token
    docker compose exec app python -m app.cli sync         # run a full sync now
    docker compose exec app python -m app.cli snapshot-db  # consistent DB copy for backups
    docker compose exec app python -m app.cli reset-password  # forgot the UI password

No command prints the token.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app import accounts
from app.config import ConfigError, Settings
from app.db import make_engine, snapshot
from app.moodle import api
from app.moodle.client import MoodleError
from app.moodle.sync import SyncService, default_client_factory

SNAPSHOT_PATH = "backup/app.db"


async def _check(settings: Settings) -> int:
    creds = accounts.get_moodle(make_engine(settings.data_dir), settings.secret_key)
    if not creds.configured:
        print("No Moodle site/token saved yet: add them on the settings page.", file=sys.stderr)
        return 1
    async with default_client_factory(settings)(creds.url, creds.token) as client:
        site = await api.get_site_info(client)
        courses = await api.get_user_courses(client, site["userid"])
    print(f"OK: signed in to {site['sitename']!r} (Moodle {site['release']}) as {site['fullname']}")
    print(f"{len(courses)} enrolled course(s):")
    for c in courses:
        print(f"  [{c['id']}] {c['shortname']}: {c['fullname']} (lang: {c['lang'] or 'not set'})")
    return 0


async def _sync(settings: Settings) -> int:
    run = await SyncService(settings, make_engine(settings.data_dir)).run("cli")
    print(
        f"{run.status}: {run.courses} courses, {run.files_downloaded} files downloaded "
        f"({run.bytes_downloaded / 1e6:.1f} MB), {run.files_unchanged} unchanged, "
        f"{run.files_failed} failed, {run.deadlines} deadlines"
    )
    if run.message:
        print(run.message)
    return 0 if run.status in {"ok", "partial"} else 1


def _reset_password(settings: Settings) -> int:
    import getpass

    engine = make_engine(settings.data_dir)
    new = getpass.getpass("New web UI password (12+ characters): ")
    if new != getpass.getpass("Repeat: "):
        print("The passwords do not match.", file=sys.stderr)
        return 1
    try:
        if not accounts.verify_password(engine, new):  # make sure the account exists
            accounts.bootstrap(engine, Settings(**{**settings.__dict__, "app_password": new}))
        accounts.change_password(engine, new)
    except (ValueError, ConfigError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Password changed; every device has been signed out.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["check", "sync", "snapshot-db", "reset-password"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "check":
            return asyncio.run(_check(settings))
        if args.command == "sync":
            return asyncio.run(_sync(settings))
        if args.command == "reset-password":
            return _reset_password(settings)
        make_engine(settings.data_dir)  # make sure the database exists
        dest = snapshot(settings.data_dir, settings.data_dir / SNAPSHOT_PATH)
        print(f"Database snapshot written to {dest}")
        return 0
    except MoodleError as exc:
        print(f"Moodle error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
