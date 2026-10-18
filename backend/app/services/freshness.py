"""Data freshness check (PRD 10장 데이터 신선도).

If a collection failed, or the last successful one is too old for the time of day, signals are
not produced and /api/health shows a warning. "Too old" is relative to when the job should have
succeeded by: the latest closed 30-minute bar during the session, or the daily scan time after
the close.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.core.market import KST, MARKET_CLOSE, is_trading_day
from app.services.status import SourceStatus, load_status

FIRST_BAR_END = time(9, 30)


@dataclass(frozen=True, slots=True)
class FreshnessSpec:
    intraday_grace: timedelta = timedelta(minutes=5)  # time allowed after a bar closes
    daily_grace: timedelta = timedelta(minutes=60)  # time allowed after the daily scan time
    intraday_window_end: time = time(16, 0)  # the last bar's collection may still be late


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    source: str
    stale: bool
    expected_since: datetime | None  # the collection that should have succeeded by now
    last_success: datetime | None
    last_error: str | None
    message: str | None


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    sources: dict[str, SourceFreshness] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(s.stale for s in self.sources.values())

    @property
    def warnings(self) -> list[SourceFreshness]:
        return [s for s in self.sources.values() if s.stale]


def expected_intraday_run(now: datetime, spec: FreshnessSpec) -> datetime | None:
    """The close of the latest 30-minute bar that should have been collected, if any."""
    local = now.astimezone(KST)
    if not is_trading_day(local.date()):
        return None
    if not (FIRST_BAR_END <= local.time() < spec.intraday_window_end):
        return None
    minutes = local.hour * 60 + local.minute
    end = datetime.combine(local.date(), time(minutes // 60, minutes // 30 % 2 * 30), tzinfo=KST)
    close = datetime.combine(local.date(), MARKET_CLOSE, tzinfo=KST)
    return min(end, close)


def expected_daily_run(now: datetime, scan_time: time) -> datetime:
    """When the latest daily collection was due: today's scan time, or the last trading day's."""
    local = now.astimezone(KST)
    day = local.date()
    for _ in range(14):
        due = datetime.combine(day, scan_time, tzinfo=KST)
        if is_trading_day(day) and due <= local:
            return due
        day -= timedelta(days=1)
    return datetime.combine(day, scan_time, tzinfo=KST)


def _judge(
    source: str,
    expected: datetime | None,
    grace: timedelta,
    status: SourceStatus,
    now: datetime,
    label: str,
) -> SourceFreshness:
    missed = status.last_success is None or (
        expected is not None and status.last_success < expected
    )
    # Late: nothing succeeded by the end of the grace period. Failed: the attempt for the
    # expected run is known to have failed, so there is no reason to wait for the grace.
    failed = (
        expected is not None
        and status.last_error is not None
        and status.last_attempt is not None
        and status.last_attempt >= expected
    )
    stale = expected is not None and missed and (now > expected + grace or failed)
    message = None
    if stale and expected is not None:
        since = (
            status.last_success.astimezone(KST).strftime("%m-%d %H:%M")
            if status.last_success
            else "없음"
        )
        due = expected.astimezone(KST).strftime("%H:%M")
        message = f"{label} 수집이 {due} 이후 갱신되지 않았습니다 (마지막 성공: {since})"
        if status.last_error:
            message += f" - {status.last_error}"
    return SourceFreshness(source, stale, expected, status.last_success, status.last_error, message)


def evaluate_freshness(
    session: Session, now: datetime, scan_time: time, spec: FreshnessSpec | None = None
) -> FreshnessReport:
    """Is the market data fresh enough at ``now`` to produce signals?"""
    spec = spec or FreshnessSpec()
    status = load_status(session)
    return FreshnessReport(
        {
            "intraday": _judge(
                "intraday",
                expected_intraday_run(now, spec),
                spec.intraday_grace,
                status["intraday"],
                now,
                "분봉 시세",
            ),
            "daily": _judge(
                "daily",
                expected_daily_run(now, scan_time),
                spec.daily_grace,
                status["daily"],
                now,
                "일봉 시세",
            ),
        }
    )
