"""
Task scheduler for periodic jobs.

Uses APScheduler to run scheduled tasks like weekly summaries.
"""

import logging
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore
from pytz import timezone  # type: ignore
from services.weekly_summary import generate_and_save_weekly_summary
from config import get_config

logger = logging.getLogger(__name__)
config = get_config()

# Global scheduler instance
_scheduler: BackgroundScheduler | None = None


def init_scheduler() -> None:
    """
    Initialize and start the background scheduler.

    Sets up periodic jobs like weekly summary generation.
    """
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already initialized")
        return

    try:
        # Create scheduler with Pacific timezone
        pacific = timezone("America/Los_Angeles")
        _scheduler = BackgroundScheduler(timezone=pacific)

        # Add weekly summary job (every Friday at 11pm Pacific)
        if config.weekly_summary_enabled:
            _scheduler.add_job(
                func=generate_and_save_weekly_summary,
                trigger=CronTrigger(
                    day_of_week="fri",  # Friday
                    hour=23,  # 11pm
                    minute=0,  # On the hour
                    timezone=pacific,
                ),
                id="weekly_summary",
                name="Weekly Audiobook Summary",
                replace_existing=True,
                misfire_grace_time=3600,  # Allow 1 hour grace for missed jobs
            )
            logger.info("Added weekly summary job: Every Friday at 11:00 PM Pacific")
        else:
            logger.info("Weekly summary feature is disabled")

        # Start the scheduler
        _scheduler.start()
        logger.info("Scheduler started successfully")

    except Exception as e:
        logger.error(f"Error initializing scheduler: {e}", exc_info=True)
        _scheduler = None


def shutdown_scheduler() -> None:
    """
    Shut down the scheduler gracefully.
    """
    global _scheduler

    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=True)
            logger.info("Scheduler shut down successfully")
            _scheduler = None
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")


def get_scheduler() -> BackgroundScheduler | None:
    """
    Get the global scheduler instance.

    Returns:
        Scheduler instance or None if not initialized
    """
    return _scheduler


def trigger_weekly_summary_now(target_date: Optional[datetime] = None) -> None:
    """
    Manually trigger the weekly summary job immediately.

    Useful for testing or manual runs.

    Args:
        target_date: Optional datetime to generate summary for.
                     If None, uses current date.
    """
    try:
        if target_date:
            logger.info(f"Manually triggering weekly summary for date: {target_date}")
        else:
            logger.info("Manually triggering weekly summary for current week")
        result = generate_and_save_weekly_summary(target_date)

        if result:
            logger.info(f"Weekly summary created: {result['url']}")
        else:
            logger.warning("Weekly summary generation returned None")

    except Exception as e:
        logger.error(f"Error triggering weekly summary: {e}", exc_info=True)


def get_next_run_time() -> str | None:
    """
    Get the next scheduled run time for the weekly summary job.

    Returns:
        Formatted datetime string or None
    """
    if _scheduler is None:
        return None

    try:
        job = _scheduler.get_job("weekly_summary")
        if job and job.next_run_time:
            return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z")
        return None
    except Exception:
        return None
