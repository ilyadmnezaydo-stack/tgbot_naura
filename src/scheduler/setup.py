"""
Scheduler setup using python-telegram-bot's JobQueue.
"""
import logging
from datetime import time

import pytz
from telegram.ext import Application

from src.config import settings
from src.scheduler.jobs import (
    evening_reminder_job,
    morning_reminder_job,
    weekly_stats_job,
)

logger = logging.getLogger(__name__)


def setup_scheduler(application: Application) -> None:
    """
    Configure scheduled jobs using PTB's JobQueue.

    Jobs:
    - Morning reminder: Daily at 11:00 MSK
    - Evening reminder: Daily at 19:00 MSK
    - Weekly stats: Sunday at 10:00 MSK
    """
    job_queue = application.job_queue
    tz = pytz.timezone(settings.TIMEZONE)

    # Morning reminder at 11:00 MSK
    job_queue.run_daily(
        callback=morning_reminder_job,
        time=time(hour=settings.REMINDER_MORNING_HOUR, minute=0, tzinfo=tz),
        name="morning_reminder",
    )
    logger.info(f"Scheduled morning reminder at {settings.REMINDER_MORNING_HOUR}:00 {settings.TIMEZONE}")

    # Evening reminder at 19:00 MSK
    job_queue.run_daily(
        callback=evening_reminder_job,
        time=time(hour=settings.REMINDER_EVENING_HOUR, minute=0, tzinfo=tz),
        name="evening_reminder",
    )
    logger.info(f"Scheduled evening reminder at {settings.REMINDER_EVENING_HOUR}:00 {settings.TIMEZONE}")

    # Weekly stats on Sunday at 10:00 MSK
    job_queue.run_daily(
        callback=weekly_stats_job,
        time=time(hour=10, minute=0, tzinfo=tz),
        days=(6,),  # Sunday = 6 (0 = Monday in python-telegram-bot)
        name="weekly_stats",
    )
    logger.info("Scheduled weekly stats for Sunday at 10:00")
