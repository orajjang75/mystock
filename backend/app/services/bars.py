"""Intraday bar helpers: 60-minute aggregation of 30-minute bars and DB loading.

Only 30-minute bars are stored (PRD 8장). A 60-minute bar is built at read time from the
30-minute bars that start inside the same clock hour of the regular session, so the last one
of the day (15:00-15:30) spans only 30 minutes.
"""

import math
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.market import INTRADAY_BAR_MINUTES, KST, MARKET_OPEN
from app.db.enums import BarLength
from app.db.models import InvestorFlowDaily, OhlcvDaily, OhlcvIntraday

_LAST_BAR_START = time(15, 0)


def aggregate_60m(bars_30m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate regular-session 30-minute bars (index = bar start, tz-aware KST) to 60 minutes.

    Returns open/high/low/close/volume plus ``n_bars``, ``span_minutes`` (30 or 60) and
    ``is_complete``: False for an hour whose second half has not been collected yet, so an
    in-progress bar is never mistaken for a closed one (CLAUDE.md 규칙 4).
    """
    session_bars = bars_30m.between_time(MARKET_OPEN, _LAST_BAR_START, inclusive="both")
    hours = pd.DatetimeIndex(session_bars.index).floor("60min")
    grouped = session_bars.groupby(hours)
    hourly = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        n_bars=("close", "size"),
    )
    hourly.index.name = "bar_time"
    hourly["span_minutes"] = hourly["n_bars"] * INTRADAY_BAR_MINUTES
    expected = np.where(pd.DatetimeIndex(hourly.index).hour == _LAST_BAR_START.hour, 1, 2)
    hourly["is_complete"] = hourly["n_bars"].to_numpy() == expected
    return hourly


def load_intraday(
    session: Session, code: str, bar_length: BarLength, start: date, end: date
) -> pd.DataFrame:
    """Stored 30-minute bars for ``start..end`` inclusive, or their 60-minute aggregation."""
    if bar_length is BarLength.D1:
        raise ValueError("Daily bars are not intraday bars.")
    lower = datetime.combine(start, time.min, tzinfo=KST)
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=KST)
    rows = session.execute(
        select(
            OhlcvIntraday.bar_time,
            OhlcvIntraday.open,
            OhlcvIntraday.high,
            OhlcvIntraday.low,
            OhlcvIntraday.close,
            OhlcvIntraday.volume,
        )
        .where(
            OhlcvIntraday.code == code,
            OhlcvIntraday.bar_length == BarLength.M30,
            OhlcvIntraday.bar_time >= lower,
            OhlcvIntraday.bar_time < upper,
        )
        .order_by(OhlcvIntraday.bar_time)
    ).all()
    frame = pd.DataFrame(rows, columns=["bar_time", "open", "high", "low", "close", "volume"])
    times = pd.to_datetime(frame["bar_time"])
    # SQLite hands back naive wall-clock values that were written as KST; PostgreSQL is aware.
    times = times.dt.tz_localize(KST) if times.dt.tz is None else times.dt.tz_convert(KST)
    frame = frame.assign(bar_time=times).set_index("bar_time")
    frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].astype(float)
    frame["volume"] = frame["volume"].astype("int64")
    return aggregate_60m(frame) if bar_length is BarLength.M60 else frame


_PRICE_COLUMNS = ["open", "high", "low", "close"]
_DAILY_FIELDS = [*_PRICE_COLUMNS, "volume", "trading_value"]
_FLOW_FIELDS = ["foreign_net_buy", "institution_net_buy"]


def load_daily_panel(
    session: Session, codes: Sequence[str], end: date, lookback_days: int = 420
) -> dict[str, pd.DataFrame]:
    """Daily bars and investor flow of ``codes`` as ``{field: frame(date x code)}``.

    Covers ``end - lookback_days .. end``. Flow fields are aligned to the price calendar, so a
    day without flow data is NaN. 420 calendar days hold the 252 trading days the 52-week
    drawdown needs plus indicator warm-up.
    """
    start = end - timedelta(days=lookback_days)
    bars = session.execute(
        select(
            OhlcvDaily.code,
            OhlcvDaily.trade_date,
            *(getattr(OhlcvDaily, c) for c in _DAILY_FIELDS),
        ).where(OhlcvDaily.code.in_(codes), OhlcvDaily.trade_date.between(start, end))
    ).all()
    flows = session.execute(
        select(
            InvestorFlowDaily.code,
            InvestorFlowDaily.trade_date,
            *(getattr(InvestorFlowDaily, c) for c in _FLOW_FIELDS),
        ).where(InvestorFlowDaily.code.in_(codes), InvestorFlowDaily.trade_date.between(start, end))
    ).all()
    bar_frame = pd.DataFrame(bars, columns=["code", "trade_date", *_DAILY_FIELDS])
    flow_frame = pd.DataFrame(flows, columns=["code", "trade_date", *_FLOW_FIELDS])

    if bar_frame.empty:
        empty = pd.DataFrame(
            columns=list(codes), index=pd.DatetimeIndex([], name="trade_date"), dtype="float64"
        )
        return {field: empty.copy() for field in [*_DAILY_FIELDS, *_FLOW_FIELDS]}

    def wide(frame: pd.DataFrame, field: str, calendar: pd.Index | None) -> pd.DataFrame:
        if frame.empty and calendar is not None:
            return pd.DataFrame(np.nan, index=calendar, columns=list(codes))
        table = frame.pivot(index="trade_date", columns="code", values=field)
        table.index = pd.DatetimeIndex(table.index, name="trade_date")
        table = table.reindex(columns=list(codes))
        if calendar is not None:
            table = table.reindex(calendar)
        # One float array per field: the engine is several times faster on single-block frames.
        return pd.DataFrame(
            table.to_numpy(dtype="float64"), index=table.index, columns=table.columns
        )

    panel = {field: wide(bar_frame, field, None) for field in _DAILY_FIELDS}
    calendar = panel["close"].index
    panel.update({field: wide(flow_frame, field, calendar) for field in _FLOW_FIELDS})
    return panel


def load_recent_bars(
    session: Session, code: str, bar_length: BarLength, limit: int
) -> pd.DataFrame:
    """The latest ``limit`` bars of one stock (oldest first), with columns open..volume.

    Daily bars come straight from ``ohlcv_daily``; 30/60-minute bars from the stored 30-minute
    bars (60-minute ones aggregated, carrying ``span_minutes`` and ``is_complete``).
    """
    if bar_length is BarLength.D1:
        rows = session.execute(
            select(OhlcvDaily.trade_date, *(getattr(OhlcvDaily, c) for c in _DAILY_FIELDS[:5]))
            .where(OhlcvDaily.code == code)
            .order_by(OhlcvDaily.trade_date.desc())
            .limit(limit)
        ).all()
        frame = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "volume"])
        frame["trade_date"] = pd.DatetimeIndex(frame["trade_date"])
        frame = frame.set_index("trade_date").sort_index()
        frame[_PRICE_COLUMNS] = frame[_PRICE_COLUMNS].astype("float64")
        return frame

    last = session.scalar(
        select(OhlcvIntraday.bar_time)
        .where(OhlcvIntraday.code == code, OhlcvIntraday.bar_length == BarLength.M30)
        .order_by(OhlcvIntraday.bar_time.desc())
        .limit(1)
    )
    if last is None:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    bars_per_day = 13 if bar_length is BarLength.M30 else 7
    days = math.ceil(limit / bars_per_day) + 1
    end_day = last.astimezone(KST).date() if last.tzinfo else last.date()
    start_day = end_day - timedelta(days=int(days * 7 / 5) + 4)  # weekends and holidays
    return load_intraday(session, code, bar_length, start_day, end_day).tail(limit)
