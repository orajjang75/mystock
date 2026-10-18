"""The data a backtest runs on, read from the same tables the app fills (PRD 10장 데이터).

- Prices are the adjusted prices the adapters deliver (``MarketDataAdapter`` contract: adjusted
  for splits and dividends). A day-to-day jump beyond the exchange's ±30 % price limit is
  reported in ``Dataset.notes`` as a sign that an unadjusted series slipped in.
- The universe of a date is the market-cap ranking stored for that date (``universe_snapshots``),
  not today's ranking. Without snapshots the current universe is used for every date and the
  notes say so.
- Delisted stocks stay in unless the option says otherwise; after their last bar they are
  simply not members.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.config import UniverseOptions
from app.db.enums import BarLength, Market
from app.db.models import IndexDaily, Instrument, UniverseSnapshot
from app.services.bars import load_daily_panel, load_intraday
from app.services.universe import load_universe

PRICE_LIMIT = 0.31  # KRX daily price limit is 30 %
DELIST_GAP_BARS = 5  # a stock whose bars stop this many sessions before the end is delisted
INDICATOR_WARMUP_BARS = 270  # 252 for the 52-week high plus a margin for the smoothing

BAR_FIELDS = ["open", "high", "low", "close", "volume"]


class BacktestDataError(RuntimeError):
    """There is not enough stored data to run the backtest."""


@dataclass
class Dataset:
    panel: dict[str, pd.DataFrame]  # field -> frame(date x code)
    index: pd.DataFrame  # KOSPI daily open..close
    members: pd.DataFrame  # bool frame(date x code): in the universe that day and has a bar
    names: dict[str, str]
    markets: dict[str, Market]
    first_bar: dict[str, pd.Timestamp]
    last_bar: dict[str, pd.Timestamp]
    delisted: set[str]
    eval_start: pd.Timestamp  # first day signals may be used (after the indicator warm-up)
    eval_end: pd.Timestamp
    notes: dict[str, Any] = field(default_factory=dict)
    _intraday: Callable[[str, BarLength], pd.DataFrame] | None = None
    _cache: dict[tuple[str, BarLength], pd.DataFrame] = field(default_factory=dict)

    @property
    def codes(self) -> list[str]:
        return list(self.panel["close"].columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.panel["close"].index)

    def daily_bars(self, code: str) -> pd.DataFrame:
        """One stock's own daily bars (open..volume), only the days it traded."""
        frame = pd.DataFrame({name: self.panel[name][code] for name in BAR_FIELDS})
        return frame.dropna(subset=["close"])

    def flow(self, code: str) -> tuple[pd.Series, pd.Series]:
        """Foreign and institution net buying aligned to the stock's own daily bars."""
        index = self.daily_bars(code).index
        return (
            self.panel["foreign_net_buy"][code].reindex(index),
            self.panel["institution_net_buy"][code].reindex(index),
        )

    def bars(self, code: str, length: BarLength) -> pd.DataFrame:
        """Signal bars of ``length``: daily bars, or the stored 30-minute bars (60 = aggregated)."""
        if length is BarLength.D1:
            return self.daily_bars(code)
        key = (code, length)
        if key not in self._cache:
            if self._intraday is None:
                raise BacktestDataError("this dataset has no intraday source")
            self._cache[key] = self._intraday(code, length)
        return self._cache[key]

    def intraday_span(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """First and last day with stored 30-minute bars of any stock, if there are any."""
        return self.notes.get("intraday_span")


def _latest_bar_date(session: Session) -> date:
    latest: date | None = session.scalar(select(func.max(IndexDaily.trade_date)))
    if latest is None:
        raise BacktestDataError("No daily bars are stored; run the ingest job first.")
    return latest


def _snapshots(session: Session, end: date) -> pd.DataFrame:
    rows = session.execute(
        select(UniverseSnapshot.as_of, UniverseSnapshot.code, UniverseSnapshot.market)
        .where(UniverseSnapshot.as_of <= end)
        .order_by(UniverseSnapshot.as_of, UniverseSnapshot.rank)
    ).all()
    return pd.DataFrame(rows, columns=["as_of", "code", "market"])


def suspected_unadjusted(close: pd.DataFrame) -> dict[str, int]:
    """Stocks with day-to-day moves beyond the price limit: a split or dividend left in the series
    shows up as exactly such a jump. ``{code: number of jumps}``."""
    jumps = (close.pct_change(fill_method=None).abs() > PRICE_LIMIT).sum()
    return {str(code): int(n) for code, n in jumps.items() if n}


def _member_mask(
    dates: pd.DatetimeIndex, codes: list[str], snapshots: pd.DataFrame, point_in_time: bool
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """date x code bool frame from the snapshots: each day uses the latest snapshot up to it."""
    mask = np.zeros((len(dates), len(codes)), dtype=bool)
    position = {code: i for i, code in enumerate(codes)}
    as_ofs = sorted(snapshots["as_of"].unique())
    notes: dict[str, Any] = {"snapshots": len(as_ofs)}
    if not point_in_time:
        latest = snapshots[snapshots["as_of"] == as_ofs[-1]]["code"]
        mask[:, [position[c] for c in latest if c in position]] = True
        notes["universe"] = f"고정: {as_ofs[-1]}의 순위를 모든 날에 사용"
        return pd.DataFrame(mask, index=dates, columns=codes), notes
    stamps = pd.DatetimeIndex(pd.to_datetime(as_ofs))
    which = np.clip(stamps.searchsorted(dates, side="right") - 1, 0, None)
    notes["before_first_snapshot_days"] = int((dates < stamps[0]).sum())  # filled from the first
    for k, as_of in enumerate(as_ofs):
        rows = np.flatnonzero(which == k)
        if len(rows) == 0:
            continue
        cols = [
            position[c] for c in snapshots[snapshots["as_of"] == as_of]["code"] if c in position
        ]
        mask[np.ix_(rows, cols)] = True
    notes["universe"] = "시점별: 각 날짜 이전에 저장된 가장 가까운 시가총액 순위"
    return pd.DataFrame(mask, index=dates, columns=codes), notes


def load_dataset(
    session: Session,
    options: UniverseOptions,
    start: date | None = None,
    end: date | None = None,
    *,
    min_history_bars: int = INDICATOR_WARMUP_BARS,
) -> Dataset:
    """Read the stored bars of every stock that was in the universe in ``start..end``."""
    end = min(end, _latest_bar_date(session)) if end else _latest_bar_date(session)
    snapshots = _snapshots(session, end)
    notes: dict[str, Any] = {"adjusted_prices": True}
    fallback = snapshots.empty
    if fallback:
        # Nothing stored yet: today's universe, for every day. Flagged so nobody reads it as
        # point in time.
        members = load_universe(session)
        if not members:
            raise BacktestDataError("The scan universe is empty; run the ingest job first.")
        snapshots = pd.DataFrame(
            [(end, m.code, m.market) for m in members], columns=["as_of", "code", "market"]
        )
        notes["universe_warning"] = (
            "저장된 시점별 유니버스가 없어 오늘의 유니버스를 모든 날에 썼습니다 "
            "(미래 정보가 섞입니다)."
        )
    codes = sorted(snapshots["code"].unique())

    lookback = ((end - start).days if start else 800) + int(min_history_bars * 1.5)
    panel = load_daily_panel(session, codes, end, lookback_days=lookback)
    close = panel["close"]
    if close.empty or close.shape[0] < 30:
        raise BacktestDataError("Too few daily bars are stored to run a backtest.")
    present = [c for c in codes if close[c].notna().any()]
    if len(present) < len(codes):
        notes["codes_without_bars"] = sorted(set(codes) - set(present))
        panel = {name: frame[present] for name, frame in panel.items()}
        codes = present
    dates = pd.DatetimeIndex(panel["close"].index)

    last_bar = {c: pd.Timestamp(panel["close"][c].last_valid_index()) for c in codes}
    first_bar = {c: pd.Timestamp(panel["close"][c].first_valid_index()) for c in codes}
    cutoff = dates[-1 - DELIST_GAP_BARS] if len(dates) > DELIST_GAP_BARS else dates[0]
    delisted = {c for c in codes if last_bar[c] < cutoff}
    if not options.include_delisted and delisted:
        keep = [c for c in codes if c not in delisted]
        panel = {name: frame[keep] for name, frame in panel.items()}
        codes = keep
    notes["delisted"] = sorted(delisted)
    notes["include_delisted"] = options.include_delisted

    mask, mask_notes = _member_mask(dates, codes, snapshots, options.point_in_time and not fallback)
    notes.update(mask_notes)
    if fallback:
        notes["snapshots"] = 0
    mask &= panel["close"].notna()

    suspicious = suspected_unadjusted(panel["close"])
    if suspicious:
        notes["suspected_unadjusted"] = suspicious

    index_rows = session.execute(
        select(
            IndexDaily.trade_date,
            IndexDaily.open,
            IndexDaily.high,
            IndexDaily.low,
            IndexDaily.close,
        )
        .where(IndexDaily.index_code == "KOSPI", IndexDaily.trade_date <= end)
        .order_by(IndexDaily.trade_date)
    ).all()
    index = pd.DataFrame(index_rows, columns=["trade_date", "open", "high", "low", "close"])
    index = index.set_index(pd.DatetimeIndex(index.pop("trade_date"))).astype("float64")
    index = index.reindex(dates)

    warm = dates[min(min_history_bars, len(dates) - 1)]
    eval_start = max(pd.Timestamp(start), warm) if start else warm
    if start and pd.Timestamp(start) < warm:
        notes["warmup_warning"] = (
            f"{end}까지 일봉이 {len(dates)}개뿐이라 "
            f"{warm.date()} 이전의 신호는 지표 준비 기간이 모자랍니다"
        )
        eval_start = max(pd.Timestamp(start), dates[0])
    names, markets = _instrument_info(session, codes)

    def intraday(code: str, length: BarLength) -> pd.DataFrame:
        return load_intraday(session, code, length, dates[0].date(), end)

    span = _intraday_span(session, codes)
    if span:
        notes["intraday_span"] = span
    return Dataset(
        panel=panel,
        index=index,
        members=mask,
        names=names,
        markets=markets,
        first_bar=first_bar,
        last_bar=last_bar,
        delisted=delisted,
        eval_start=eval_start,
        eval_end=dates[-1],
        notes=notes,
        _intraday=intraday,
    )


def _instrument_info(
    session: Session, codes: list[str]
) -> tuple[dict[str, str], dict[str, Market]]:
    rows = session.execute(
        select(Instrument.code, Instrument.name, Instrument.market).where(
            Instrument.code.in_(codes)
        )
    ).all()
    return {c: n for c, n, _ in rows}, {c: m for c, _, m in rows}


def _intraday_span(session: Session, codes: list[str]) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    from app.db.models import OhlcvIntraday

    first, last = session.execute(
        select(func.min(OhlcvIntraday.bar_time), func.max(OhlcvIntraday.bar_time)).where(
            OhlcvIntraday.code.in_(codes)
        )
    ).one()
    if first is None or last is None:
        return None
    return pd.Timestamp(first).tz_localize(None).normalize(), pd.Timestamp(last).tz_localize(
        None
    ).normalize()


def backfill_snapshots(
    session: Session,
    adapter: Any,
    start: date,
    end: date,
    *,
    step_days: int = 30,
    spec: Any = None,
) -> list[date]:
    """Store the universe as ranked on every ``step_days`` calendar days of ``start..end``.

    For history the scanner never ran on (a fresh database filled from a source that can answer
    "who was big on this date"). Returns the dates stored. Commits.
    """
    from app.services.universe import snapshot_universe

    stored: list[date] = []
    day = start
    while day <= end:
        snapshot_universe(session, adapter, day, spec)
        stored.append(day)
        day += timedelta(days=step_days)
    if stored[-1] != end:
        snapshot_universe(session, adapter, end, spec)
        stored.append(end)
    session.commit()
    return stored
