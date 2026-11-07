"""In-process jobs (APScheduler, no extra container): the Moodle sync, and the nightly
update of the published study schedule (``app.planner.published.nightly``)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.moodle.sync import SyncAlreadyRunning, SyncService

logger = logging.getLogger("app.moodle.scheduler")

FIRST_RUN_DELAY = timedelta(minutes=2)
NIGHTLY_HOUR = 3  # local time: after the evening's study, before the morning's


def _nightly(job: Callable[[], object]) -> None:
    try:
        job()
    except Exception:  # noqa: BLE001 - a failed re-plan must not stop the scheduler
        logger.exception("Nightly study schedule update failed")


async def _scheduled_sync(service: SyncService) -> None:
    if not service.configured():
        logger.info("Scheduled sync skipped: no Moodle site/token saved yet")
        return
    try:
        await service.run("schedule")
    except SyncAlreadyRunning:
        logger.info("Scheduled sync skipped: a sync is already running")


def start_scheduler(service: SyncService, interval_hours: float,
                    nightly: Callable[[], object] | None = None,
                    tz: tzinfo | None = None) -> AsyncIOScheduler | None:
    if interval_hours <= 0 and nightly is None:
        logger.info("Scheduled Moodle sync is off (SYNC_INTERVAL_HOURS=0)")
        return None
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    if interval_hours > 0:
        scheduler.add_job(
            _scheduled_sync,
            IntervalTrigger(hours=interval_hours),
            args=[service],
            id="moodle-sync",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
            # Sync soon after start-up, so a fresh install fills up without waiting 6 hours.
            next_run_time=datetime.now(timezone.utc) + FIRST_RUN_DELAY,
        )
        logger.info("Moodle sync scheduled every %g hours", interval_hours)
    else:
        logger.info("Scheduled Moodle sync is off (SYNC_INTERVAL_HOURS=0)")
    if nightly is not None:
        scheduler.add_job(
            _nightly,
            CronTrigger(hour=NIGHTLY_HOUR, minute=30, timezone=tz or timezone.utc),
            args=[nightly],
            id="schedule-nightly",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=6 * 3600,
        )
    scheduler.start()
    return scheduler
