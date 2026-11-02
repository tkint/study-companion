"""In-process schedule for the Moodle sync (APScheduler, no extra container)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.moodle.sync import SyncAlreadyRunning, SyncService

logger = logging.getLogger("app.moodle.scheduler")

FIRST_RUN_DELAY = timedelta(minutes=2)


async def _scheduled_sync(service: SyncService) -> None:
    if not service.configured():
        logger.info("Scheduled sync skipped: no Moodle site/token saved yet")
        return
    try:
        await service.run("schedule")
    except SyncAlreadyRunning:
        logger.info("Scheduled sync skipped: a sync is already running")


def start_scheduler(service: SyncService, interval_hours: float) -> AsyncIOScheduler | None:
    if interval_hours <= 0:
        logger.info("Scheduled Moodle sync is off (SYNC_INTERVAL_HOURS=0)")
        return None
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
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
    scheduler.start()
    logger.info("Moodle sync scheduled every %g hours", interval_hours)
    return scheduler
