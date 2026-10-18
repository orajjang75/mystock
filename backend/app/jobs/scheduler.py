"""APScheduler registration (PRD 8장: 일봉 작업 장 마감 후, 분봉 작업 정규장 중 봉 마감마다).

Both jobs fire on weekdays only; holidays and times outside the session are skipped inside the
jobs themselves, which also log why. Run one scheduler per deployment (one API worker).
"""

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.market import KST
from app.jobs.monitor import JobContext, JobResult, run_daily_job, run_intraday_job

logger = logging.getLogger(__name__)

INTRADAY_JOB = "intraday"
DAILY_JOB = "daily"
# A bar closes on the hour and half hour; fetch ten seconds later, when the broker has it.
INTRADAY_SECOND = 10


def _guarded(name: str, job: Callable[[JobContext], JobResult], ctx: JobContext) -> None:
    """Run a job; whatever happens, the scheduler keeps going."""
    try:
        result = job(ctx)
        if result.skipped:
            logger.info("%s job skipped: %s", name, result.skipped)
        else:
            logger.info(
                "%s job done: collected=%s stale=%s saved=%d suppressed=%d",
                name,
                result.collected,
                result.stale,
                result.saved,
                result.suppressed,
            )
    except Exception:
        logger.exception("%s job crashed", name)


def run_intraday(ctx: JobContext) -> None:
    _guarded(INTRADAY_JOB, run_intraday_job, ctx)


def run_daily(ctx: JobContext) -> None:
    _guarded(DAILY_JOB, run_daily_job, ctx)


def build_scheduler(ctx: JobContext) -> BackgroundScheduler:
    """A scheduler with both jobs registered (not started)."""
    scan_time = ctx.settings.daily_scan_time
    scheduler = BackgroundScheduler(timezone=KST)
    scheduler.add_job(
        run_intraday,
        CronTrigger(
            day_of_week="mon-fri", hour="9-15", minute="0,30", second=INTRADAY_SECOND, timezone=KST
        ),
        args=[ctx],
        id=INTRADAY_JOB,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily,
        CronTrigger(
            day_of_week="mon-fri", hour=scan_time.hour, minute=scan_time.minute, timezone=KST
        ),
        args=[ctx],
        id=DAILY_JOB,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    return scheduler
