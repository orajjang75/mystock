"""The two scheduled jobs: after-close daily work and per-bar intraday work (PRD 8장 작업, 10장).

Both follow the same order: collect data, record whether that worked, check freshness, and only
if the data is fresh evaluate holdings and save/send the alerts. A failed or late collection
therefore stops the signals and leaves a warning (a ``data_stale`` alert and /api/health). The
clock is injected, so tests can move time forward bar by bar.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import MarketDataAdapter
from app.core.config import Settings
from app.core.market import KST, MARKET_CLOSE, is_trading_day
from app.db.enums import BarLength
from app.db.models import Holding
from app.jobs.daily_scan import run_daily_scan
from app.jobs.ingest import ingest_intraday_30m
from app.services import ops, status
from app.services.alert_engine import AlertDraft, evaluate_all, process_expirations
from app.services.alerts import save_drafts
from app.services.freshness import FreshnessReport, evaluate_freshness
from app.services.notifier import build_notifiers
from app.services.settings import (
    load_alert_cooldown_bars,
    load_channels,
    load_signal_bar_length,
)
from app.services.universe import UniverseSpec

logger = logging.getLogger(__name__)

FIRST_BAR_END = time(9, 30)
LAST_RUN = (datetime.combine(datetime.min, MARKET_CLOSE) + timedelta(minutes=10)).time()
COLLECT_LOOKBACK_DAYS = 5  # re-fetch a few days so a missed run heals itself


def _real_clock() -> datetime:
    return datetime.now(KST)


@dataclass
class JobContext:
    session_factory: Callable[[], Session]
    adapter: MarketDataAdapter
    settings: Settings
    clock: Callable[[], datetime] = _real_clock
    http_client: httpx.Client | None = None  # for the notifiers; tests inject a mock transport
    spec: UniverseSpec | None = None


@dataclass(frozen=True, slots=True)
class JobResult:
    skipped: str | None = None  # why nothing ran
    collected: bool = False  # the data fetch succeeded
    stale: list[str] = field(default_factory=list)  # freshness warnings that stopped the signals
    saved: int = 0
    suppressed: int = 0  # alerts held back by the cooldown


def _stale_draft(report: FreshnessReport, now: datetime) -> AlertDraft:
    messages = [w.message for w in report.warnings if w.message]
    return AlertDraft(
        kind="data_stale",
        holding_id=None,
        code="",
        bar_time=now,
        evidence={"message": " / ".join(messages), "sources": [w.source for w in report.warnings]},
    )


def _finish(
    session: Session,
    ctx: JobContext,
    drafts: list[AlertDraft],
    *,
    collected: bool,
    stale: list[str],
) -> JobResult:
    """Save and send ``drafts`` (subject to the cooldown), then commit."""
    notifiers = build_notifiers(ctx.settings, load_channels(session), ctx.http_client)
    result = save_drafts(
        session,
        drafts,
        created_at=ctx.clock(),
        cooldown_bars=load_alert_cooldown_bars(session),
        signal_length=load_signal_bar_length(session),
        notifiers=notifiers,
    )
    session.commit()
    return JobResult(
        collected=collected, stale=stale, saved=len(result.saved), suppressed=result.suppressed
    )


def _record_failure(session: Session, source: str, now: datetime, error: BaseException) -> None:
    session.rollback()
    status.record_failure(session, source, now, f"{type(error).__name__}: {error}")
    session.commit()
    logger.error("%s collection failed: %s: %s", source, type(error).__name__, error)


# --- intraday ---------------------------------------------------------------------------------


def run_intraday_job(ctx: JobContext, now: datetime | None = None) -> JobResult:
    """At a 30-minute bar close: fetch holdings' bars, check freshness, evaluate, alert."""
    now = (now or ctx.clock()).astimezone(KST)
    if not is_trading_day(now.date()):
        return JobResult(skipped="not a trading day")
    if not (FIRST_BAR_END <= now.time() <= LAST_RUN):
        return JobResult(skipped="outside market hours")

    with ctx.session_factory() as session:
        if load_signal_bar_length(session) is BarLength.D1:
            return JobResult(skipped="signals use daily bars; the daily job evaluates them")
        codes = list(session.scalars(select(Holding.code).distinct()))
        collected = _collect_intraday(session, ctx, codes, now)
        report = evaluate_freshness(session, now, ctx.settings.daily_scan_time)
        if not report.ok:
            logger.warning("signals paused, stale data: %s", [w.message for w in report.warnings])
            stale = [w.source for w in report.warnings]
            return _finish(
                session, ctx, [_stale_draft(report, now)], collected=collected, stale=stale
            )

        drafts = process_expirations(session, now) + evaluate_all(session, now=now)
        return _finish(session, ctx, drafts, collected=collected, stale=[])


def _collect_intraday(session: Session, ctx: JobContext, codes: list[str], now: datetime) -> bool:
    try:
        if codes:
            ingest_intraday_30m(
                session,
                ctx.adapter,
                codes,
                start=now.date() - timedelta(days=COLLECT_LOOKBACK_DAYS),
                end=now.date(),
                now=now,
            )
        status.record_success(session, "intraday", now)
        session.commit()
        return True
    except Exception as error:
        _record_failure(session, "intraday", now, error)
        return False


# --- daily ------------------------------------------------------------------------------------


def run_daily_job(ctx: JobContext, now: datetime | None = None) -> JobResult:
    """After the close: ingest + scan, then the daily alerts (A-13 forced sale, expiry)."""
    now = (now or ctx.clock()).astimezone(KST)
    if not is_trading_day(now.date()):
        return JobResult(skipped="not a trading day")
    if now.time() < ctx.settings.daily_scan_time:
        return JobResult(skipped="before the scan time")

    with ctx.session_factory() as session:
        collected = _collect_daily(session, ctx, now)
        report = evaluate_freshness(session, now, ctx.settings.daily_scan_time)
        if not report.ok:
            logger.warning("signals paused, stale data: %s", [w.message for w in report.warnings])
            stale = [w.source for w in report.warnings]
            return _finish(
                session, ctx, [_stale_draft(report, now)], collected=collected, stale=stale
            )

        scope: Literal["all", "daily"] = (
            "all" if load_signal_bar_length(session) is BarLength.D1 else "daily"
        )
        drafts = process_expirations(session, now) + evaluate_all(session, now=now, scope=scope)
        return _finish(session, ctx, drafts, collected=collected, stale=[])


def _collect_daily(session: Session, ctx: JobContext, now: datetime) -> bool:
    try:
        result = run_daily_scan(
            session, ctx.adapter, now=now, spec=ctx.spec or UniverseSpec.from_settings()
        )
        if result.skipped:
            raise RuntimeError(result.skipped)
        status.record_success(session, "daily", now)
        session.commit()
        return True
    except Exception as error:
        _record_failure(session, "daily", now, error)
        return False


# --- the run log -------------------------------------------------------------------------------


def _outcome(result: JobResult) -> str:
    if result.skipped:
        return "skipped"
    return "stale" if result.stale or not result.collected else "ok"


def run_logged(
    ctx: JobContext, name: str, job: Callable[[JobContext], JobResult], now: datetime | None = None
) -> JobResult:
    """Run ``job`` and write what happened to ``job_runs``, for the 모의 운영 report.

    The scheduler calls this instead of the job itself. An exception is logged as a ``failed``
    run and raised again, so the scheduler's own handling is unchanged.
    """
    started = (now or ctx.clock()).astimezone(KST)
    scheduled = (
        ops.floor_30(started)
        if name == "intraday"
        else datetime.combine(started.date(), ctx.settings.daily_scan_time, tzinfo=KST)
    )
    try:
        result = job(ctx)
    except Exception as error:
        _log_run(
            ctx, name, scheduled, started, "failed", {"error": f"{type(error).__name__}: {error}"}
        )
        raise
    detail: dict[str, object] = {
        "collected": result.collected,
        "stale": result.stale,
        "saved": result.saved,
        "suppressed": result.suppressed,
        "skipped": result.skipped,
    }
    outcome = _outcome(result)
    if outcome == "stale":
        with ctx.session_factory() as session:
            detail["error"] = ops.last_error(session, name)
    _log_run(ctx, name, scheduled, started, outcome, detail)
    return result


def _log_run(
    ctx: JobContext,
    name: str,
    scheduled: datetime,
    started: datetime,
    outcome: str,
    detail: dict[str, object],
) -> None:
    try:
        with ctx.session_factory() as session:
            ops.record_run(
                session, name, scheduled, started, ctx.clock().astimezone(KST), outcome, detail
            )
    except Exception:  # the log must never be the reason a job fails
        logger.exception("could not write the %s run log", name)
