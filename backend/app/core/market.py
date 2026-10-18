"""Korean regular-session constants and bar-confirmation rules (PRD 6장, CLAUDE.md 규칙 4)."""

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays

from app.db.enums import BarLength

KST = ZoneInfo("Asia/Seoul")

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)
INTRADAY_BAR_MINUTES = 30


@lru_cache
def _closed_days(year: int) -> frozenset[date]:
    """Statutory Korean holidays plus the KRX year-end closing (Dec 31)."""
    return frozenset(holidays.country_holidays("KR", years=year)) | {date(year, 12, 31)}


def is_trading_day(day: date) -> bool:
    """Weekday and not a Korean market holiday.

    Built from the ``holidays`` package, so check it against the KRX holiday notice each year
    (e.g. it lists 제헌절). The scan job also refuses to run when no bars exist for the day.
    """
    return day.weekday() < 5 and day not in _closed_days(day.year)


def add_trading_days(day: date, count: int) -> date:
    """The ``count``-th trading day after ``day`` (``day`` itself does not count)."""
    current = day
    remaining = count
    while remaining > 0:
        current += timedelta(days=1)
        if is_trading_day(current):
            remaining -= 1
    return current


def rebuy_expiry(sold_at: datetime, trading_days: int) -> datetime:
    """A-7: the close of the ``trading_days``-th trading day after the sale."""
    last_day = add_trading_days(sold_at.astimezone(KST).date(), trading_days)
    return datetime.combine(last_day, MARKET_CLOSE, tzinfo=KST)


def last_weekday(today: date) -> date:
    """The most recent Monday-Friday on or before ``today`` (holidays are not considered yet)."""
    return today - timedelta(days=max(today.weekday() - 4, 0))


def last_confirmed_weekday(now: datetime) -> date:
    """The latest weekday whose daily bar is final at ``now``."""
    local_now = now.astimezone(KST)
    day = last_weekday(local_now.date())
    if not is_daily_bar_confirmed(day, now):
        day = last_weekday(day - timedelta(days=1))
    return day


def is_daily_bar_confirmed(trade_date: date, now: datetime) -> bool:
    """A daily bar is final only after that day's regular session has closed."""
    local_now = now.astimezone(KST)
    if trade_date < local_now.date():
        return True
    return trade_date == local_now.date() and local_now.time() >= MARKET_CLOSE


def is_intraday_bar_confirmed(
    bar_start: datetime, now: datetime, bar_minutes: int = INTRADAY_BAR_MINUTES
) -> bool:
    """A bar labelled by its start time is final once its end time has passed."""
    return bar_start + timedelta(minutes=bar_minutes) <= now


BARS_PER_DAY = {BarLength.M30: 13, BarLength.M60: 7, BarLength.D1: 1}
_BAR_MINUTES = {BarLength.M30: 30, BarLength.M60: 60}


def _local(stamp: datetime) -> datetime:
    """``stamp`` in KST; a naive value is taken to be KST already."""
    return stamp.replace(tzinfo=KST) if stamp.tzinfo is None else stamp.astimezone(KST)


def trading_days_between(earlier: date, later: date) -> int:
    """Trading days in ``(earlier, later]``; negative if ``later`` is before ``earlier``."""
    if later < earlier:
        return -trading_days_between(later, earlier)
    return sum(
        1
        for n in range(1, (later - earlier).days + 1)
        if is_trading_day(earlier + timedelta(days=n))
    )


def bars_between(earlier: datetime, later: datetime, length: BarLength) -> int:
    """How many regular-session bars of ``length`` lie between two bar start times.

    Overnight, weekends and holidays are skipped, so "6 bars" of 60 minutes is one trading day.
    """
    days = trading_days_between(_local(earlier).date(), _local(later).date())

    def slot(stamp: datetime) -> int:
        if length is BarLength.D1:
            return 0
        local = _local(stamp)
        minutes = local.hour * 60 + local.minute - (MARKET_OPEN.hour * 60 + MARKET_OPEN.minute)
        return minutes // _BAR_MINUTES[length]

    return days * BARS_PER_DAY[length] + slot(later) - slot(earlier)
