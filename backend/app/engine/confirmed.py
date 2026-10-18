"""Drop bars that are not final yet, before any signal is computed (CLAUDE.md 규칙 4)."""

from datetime import datetime

import pandas as pd

from app.core.market import INTRADAY_BAR_MINUTES, is_daily_bar_confirmed


def confirmed_daily(bars: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Keep daily bars whose session has closed by ``now``."""
    keep = [is_daily_bar_confirmed(ts.date(), now) for ts in bars.index]
    return bars.loc[keep]


def confirmed_intraday(
    bars: pd.DataFrame, now: datetime, bar_minutes: int = INTRADAY_BAR_MINUTES
) -> pd.DataFrame:
    """Keep intraday bars (index = bar start, tz-aware) that have ended by ``now``.

    A ``span_minutes`` column (from ``services.bars.aggregate_60m``) overrides ``bar_minutes``,
    so the 30-minute last 60-minute bar of the day is final at 15:30. An ``is_complete`` column
    that is False (a 60-minute bar with only its first half collected) is never confirmed.
    """
    span = bars.get("span_minutes", bar_minutes)
    ends = pd.DatetimeIndex(bars.index) + pd.to_timedelta(span, unit="min")
    keep = ends <= pd.Timestamp(now)
    if "is_complete" in bars:
        keep = keep & bars["is_complete"].to_numpy(dtype=bool)
    return bars.loc[keep]
