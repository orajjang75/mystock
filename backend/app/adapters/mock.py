"""Reproducible fake market: the default source for development and tests.

Every stock gets one of four price scenarios (bottom-then-rebound, steady decline, sideways,
uptrend) so screener tests have known positives and negatives. All data derives from ``seed``
and the number of bars, so the same seed always produces the same series (dates only shift
with ``end_date``). Prices are whole-won floats; every 30-minute bar set adds up to its daily bar.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

import numpy as np
import pandas as pd

from app.adapters.base import (
    DAILY_COLUMNS,
    FLOW_COLUMNS,
    INDEX_COLUMNS,
    INTRADAY_COLUMNS,
    Listing,
    MarketDataAdapter,
)
from app.core.market import INTRADAY_BAR_MINUTES, KST, MARKET_OPEN, last_weekday
from app.db.enums import Market

BARS_PER_DAY = 13  # 09:00..15:00 start times, 30 minutes each


class Scenario(StrEnum):
    REBOUND = "rebound"  # 바닥 후 반등
    DOWNTREND = "downtrend"  # 계속 하락 (낙폭 -22%: 52주 낙폭 -30% 게이트에는 못 미친다)
    SIDEWAYS = "sideways"  # 횡보
    UPTREND = "uptrend"  # 상승


# (bars before the last bar, price level relative to the first bar). Linear in log price.
_KNOTS: dict[Scenario, list[tuple[int, float]]] = {
    Scenario.REBOUND: [
        (-499, 1.0),
        (-240, 1.30),  # 52주 고점
        (-60, 0.806),  # 고점 대비 -38%
        (-12, 0.79),
        (-8, 0.70),  # 마지막 급락: 볼린저 하단 이탈
        (0, 0.80),  # 반등
    ],
    Scenario.DOWNTREND: [(-499, 1.0), (-250, 1.05), (0, 0.82)],
    Scenario.SIDEWAYS: [(-499, 1.0), (0, 1.0)],
    Scenario.UPTREND: [(-499, 1.0), (0, 1.5)],
}
_SCENARIO_CYCLE = [
    Scenario.REBOUND,
    Scenario.DOWNTREND,
    Scenario.SIDEWAYS,
    Scenario.UPTREND,
    Scenario.SIDEWAYS,
    Scenario.DOWNTREND,
    Scenario.UPTREND,
    Scenario.SIDEWAYS,
    Scenario.REBOUND,
    Scenario.DOWNTREND,
]

# Zero-based positions (by market-cap rank) of stocks the universe filters must drop.
_FLAGS: dict[Market, dict[str, set[int]]] = {
    Market.KOSPI: {
        "admin": {7, 41, 77},
        "halted": {12, 58},
        "warning": {23, 66},
        "preferred": {4, 30, 55},
        "illiquid": {18, 90},
    },
    Market.KOSDAQ: {
        "admin": {3},
        "halted": {9},
        "warning": {14},
        "preferred": {6},
        "illiquid": {11},
    },
}
_CODE_PREFIX = {Market.KOSPI: "9", Market.KOSDAQ: "8"}
_TOP_MARKET_CAP = {Market.KOSPI: 4.0e14, Market.KOSDAQ: 2.0e13}
_CAP_DECAY = {Market.KOSPI: 0.96, Market.KOSDAQ: 0.93}
_TOP_TRADING_VALUE = {Market.KOSPI: 6.0e10, Market.KOSDAQ: 2.0e10}
_TRADING_VALUE_DECAY = {Market.KOSPI: 0.975, Market.KOSDAQ: 0.96}
_ILLIQUID_TRADING_VALUE = 3.0e8  # 3억 원: below the 10억 원 liquidity floor

INDEX_CODE = "KOSPI"


@dataclass(frozen=True, slots=True)
class MockStock:
    code: str
    name: str
    market: Market
    position: int  # 0-based market-cap rank at ``end_date``
    seed_index: int  # unique across markets; keys the random stream
    scenario: Scenario
    price0: float
    shares: int
    base_trading_value: float
    is_preferred: bool
    is_admin_issue: bool
    is_halted: bool
    is_warning: bool
    is_illiquid: bool


def _ar1_noise(
    rng: np.random.Generator, n: int, phi: float = 0.8, sigma: float = 0.02
) -> np.ndarray:
    """Stationary AR(1) noise (std ``sigma``) without a Python loop."""
    shocks = pd.Series(rng.standard_normal(n))
    smoothed = shocks.ewm(alpha=1 - phi, adjust=False).mean().to_numpy()
    return np.asarray(smoothed * sigma / np.sqrt((1 - phi) / (1 + phi)))


class MockAdapter(MarketDataAdapter):
    def __init__(
        self,
        seed: int = 42,
        end_date: date | None = None,
        *,
        n_kospi: int = 120,
        n_kosdaq: int = 30,
        daily_days: int = 500,
        intraday_days: int = 60,
        delistings: Mapping[str, int] | None = None,
    ) -> None:
        """``delistings`` maps a stock code to how many trading days before ``end_date`` it
        stopped trading: its bars end there (after a ten-bar slide to 60 % of the price) and it
        is no longer listed afterwards. Nothing is delisted by default, so existing data and
        tests are unchanged. Used to test the survivorship-bias option of the backtest.
        """
        self._seed = seed
        self._delistings = dict(delistings or {})
        self._end_date = end_date or last_weekday(datetime.now(KST).date())
        self._daily_days = daily_days
        self._intraday_days = min(intraday_days, daily_days)
        self.stocks = self._build_stocks(n_kospi, n_kosdaq)
        self._by_code = {s.code: s for s in self.stocks}
        self._daily_cache: dict[str, pd.DataFrame] = {}
        self._flow_cache: dict[str, pd.DataFrame] = {}
        self._intraday_cache: dict[str, pd.DataFrame] = {}

    # --- universe -----------------------------------------------------------------------

    def _build_stocks(self, n_kospi: int, n_kosdaq: int) -> list[MockStock]:
        stocks: list[MockStock] = []
        for market, count in ((Market.KOSPI, n_kospi), (Market.KOSDAQ, n_kosdaq)):
            flags = _FLAGS[market]
            for position in range(count):
                seed_index = len(stocks)
                rng = np.random.default_rng([self._seed, seed_index, 0])
                preferred = position in flags["preferred"]
                illiquid = position in flags["illiquid"]
                code = f"{_CODE_PREFIX[market]}{position + 1:04d}{5 if preferred else 0}"
                price0 = float(round(rng.uniform(5_000, 200_000), -2))
                end_close = price0 * _KNOTS[_SCENARIO_CYCLE[position % 10]][-1][1]
                cap_end = _TOP_MARKET_CAP[market] * _CAP_DECAY[market] ** position
                trading_value = (
                    _ILLIQUID_TRADING_VALUE
                    if illiquid
                    else (_TOP_TRADING_VALUE[market] * _TRADING_VALUE_DECAY[market] ** position)
                )
                stocks.append(
                    MockStock(
                        code=code,
                        name=f"모의{market.value}{position + 1:03d}{'우' if preferred else ''}",
                        market=market,
                        position=position,
                        seed_index=seed_index,
                        scenario=_SCENARIO_CYCLE[position % 10],
                        price0=price0,
                        shares=int(cap_end / end_close),
                        base_trading_value=trading_value,
                        is_preferred=preferred,
                        is_admin_issue=position in flags["admin"],
                        is_halted=position in flags["halted"],
                        is_warning=position in flags["warning"],
                        is_illiquid=illiquid,
                    )
                )
        return stocks

    def stock(self, code: str) -> MockStock:
        return self._by_code[code]

    def fetch_listings(self, as_of: date, *, limit_per_market: int | None = None) -> list[Listing]:
        as_of_ts = pd.Timestamp(as_of)
        listings: list[Listing] = []
        for market in (Market.KOSPI, Market.KOSDAQ):
            items: list[Listing] = []
            for stock in (s for s in self.stocks if s.market == market):
                closes = self._daily(stock)["close"]
                if stock.code in self._delistings and as_of_ts > closes.index[-1]:
                    continue  # no longer listed
                closes = closes[closes.index <= as_of_ts]
                if closes.empty:
                    continue
                items.append(
                    Listing(
                        code=stock.code,
                        name=stock.name,
                        market=market,
                        market_cap=int(stock.shares * closes.iloc[-1]),
                        is_preferred=stock.is_preferred,
                        is_admin_issue=stock.is_admin_issue,
                        is_halted=stock.is_halted,
                        is_warning=stock.is_warning,
                    )
                )
            items.sort(key=lambda item: (-item.market_cap, item.code))
            listings.extend(items[:limit_per_market] if limit_per_market else items)
        return listings

    # --- daily bars ---------------------------------------------------------------------

    def _dates(self) -> pd.DatetimeIndex:
        return pd.bdate_range(end=self._end_date, periods=self._daily_days, name="trade_date")

    def _daily(self, stock: MockStock) -> pd.DataFrame:
        if stock.code not in self._daily_cache:
            self._daily_cache[stock.code] = self._delisted(stock, self._make_daily(stock))
        return self._daily_cache[stock.code]

    def _delisted(self, stock: MockStock, frame: pd.DataFrame) -> pd.DataFrame:
        """Cut the bars of a delisted stock at its last trading day, after a slide to 60 %."""
        days = self._delistings.get(stock.code)
        if days is None:
            return frame
        frame = frame.iloc[: len(frame) - days].copy()
        slide = np.linspace(1.0, 0.6, 10)
        for column in ("open", "high", "low", "close"):
            values = frame[column].to_numpy(dtype="float64").copy()
            values[-10:] = np.maximum(np.round(values[-10:] * slide), 1)
            frame[column] = values
        frame["trading_value"] = (frame["volume"] * frame["close"]).astype("int64")
        return frame

    def last_trading_day(self, code: str) -> date:
        """The last day ``code`` has bars (the end date unless it was delisted)."""
        return pd.Timestamp(self._daily(self._by_code[code]).index[-1]).date()

    def _make_daily(self, stock: MockStock) -> pd.DataFrame:
        n = self._daily_days
        rng = np.random.default_rng([self._seed, stock.seed_index, 1])
        t = np.arange(n)
        knots = _KNOTS[stock.scenario]
        trend = np.log(
            np.interp(t, [n - 1 + back for back, _ in knots], [level for _, level in knots])
        )
        if stock.scenario is Scenario.SIDEWAYS:
            trend = trend + 0.05 * np.sin(2 * np.pi * t / 55 + rng.uniform(0, 2 * np.pi))
        close = np.maximum(np.round(stock.price0 * np.exp(trend + _ar1_noise(rng, n))), 100)

        if stock.scenario is Scenario.REBOUND:
            # The last three bars are clearly bullish so the volume signal (양봉) can fire.
            for k in (3, 2, 1):
                close[-k] = max(close[-k], round(close[-k - 1] * 1.008))

        open_ = np.round(close * 1.0)
        open_[1:] = np.round(close[:-1] * (1 + rng.normal(0, 0.004, n - 1)))
        open_[0] = close[0]
        if stock.scenario is Scenario.REBOUND:
            open_[-3:] = np.round(close[-4:-1] * 0.996)
        high = np.round(np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n))))
        low = np.round(np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n))))
        high = np.maximum(high, np.maximum(open_, close))
        low = np.minimum(low, np.minimum(open_, close))

        volume_factor = rng.lognormal(0, 0.35, n)
        if stock.scenario is Scenario.REBOUND:
            volume_factor[-3:] = [2.5, 2.5, 4.0]  # 거래량 급증 (잡음 없이 고정)
        volume = np.maximum(np.round(stock.base_trading_value * volume_factor / close), 1)
        return pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume.astype("int64"),
                "trading_value": (volume * close).astype("int64"),
            },
            index=self._dates(),
        )[DAILY_COLUMNS]

    def fetch_daily_ohlcv(self, code: str, start: date, end: date) -> pd.DataFrame:
        return self._daily(self._by_code[code]).loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()

    # --- investor flow ------------------------------------------------------------------

    def fetch_investor_flow(self, code: str, start: date, end: date) -> pd.DataFrame:
        stock = self._by_code[code]
        if code not in self._flow_cache:
            self._flow_cache[code] = self._make_flow(stock)
        return self._flow_cache[code].loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()

    def _make_flow(self, stock: MockStock) -> pd.DataFrame:
        daily = self._daily(stock)
        n = len(daily)
        rng = np.random.default_rng([self._seed, stock.seed_index, 3])
        ratio = rng.normal(0, 0.03, (n, 2))  # net buy as a share of the day's trading value
        if stock.scenario is Scenario.REBOUND:
            # Sellers give up, then both groups turn into net buyers: 순매수 전환.
            ratio[-10:-5] = -(0.03 + np.abs(rng.normal(0, 0.02, (5, 2))))
            ratio[-5:] = 0.03 + np.abs(rng.normal(0, 0.02, (5, 2)))
        elif stock.scenario is Scenario.DOWNTREND:
            ratio[-5:] = -(0.02 + np.abs(rng.normal(0, 0.02, (5, 2))))
        elif stock.scenario is Scenario.UPTREND:
            ratio += 0.01
        amounts = np.round(ratio * daily["trading_value"].to_numpy()[:, None]).astype("int64")
        return pd.DataFrame(amounts, index=daily.index, columns=FLOW_COLUMNS)

    # --- intraday bars ------------------------------------------------------------------

    def fetch_intraday_30m(self, code: str, start: date, end: date) -> pd.DataFrame:
        if code not in self._intraday_cache:
            self._intraday_cache[code] = self._make_intraday(self._by_code[code])
        frame = self._intraday_cache[code]
        lower = pd.Timestamp(start, tz=KST)
        upper = pd.Timestamp(end, tz=KST) + pd.Timedelta(days=1)
        return frame[(frame.index >= lower) & (frame.index < upper)].copy()

    def _make_intraday(self, stock: MockStock) -> pd.DataFrame:
        daily = self._daily(stock).iloc[-self._intraday_days :]
        days, bars = len(daily), BARS_PER_DAY
        rng = np.random.default_rng([self._seed, stock.seed_index, 2])
        day_open, day_high, day_low, day_close = (
            daily[c].to_numpy()[:, None] for c in ("open", "high", "low", "close")
        )

        # A noisy walk from the day's open to its close (a bridge, so both ends are pinned).
        frac = np.linspace(0, 1, bars + 1)[None, :]
        steps = rng.normal(0, 0.0025, (days, bars + 1))
        steps[:, 0] = 0  # the walk starts at the day's open
        walk = np.cumsum(steps, axis=1)
        bridge = walk - frac * walk[:, [-1]]
        path = np.exp(np.log(day_open) + (np.log(day_close) - np.log(day_open)) * frac + bridge)
        path = np.clip(np.round(path), day_low, day_high)
        bar_open, bar_close = path[:, :-1], path[:, 1:]

        wick_up = 1 + np.abs(rng.normal(0, 0.0015, (days, bars)))
        wick_down = 1 - np.abs(rng.normal(0, 0.0015, (days, bars)))
        bar_high = np.minimum(np.round(np.maximum(bar_open, bar_close) * wick_up), day_high)
        bar_low = np.maximum(np.round(np.minimum(bar_open, bar_close) * wick_down), day_low)
        rows = np.arange(days)
        bar_high[rows, bar_high.argmax(axis=1)] = day_high[:, 0]  # the day's extremes were traded
        bar_low[rows, bar_low.argmin(axis=1)] = day_low[:, 0]

        # U-shaped intraday volume that sums exactly to the daily volume.
        u_shape = 1 + 1.5 * ((np.arange(bars) - 6) / 6) ** 2
        weights = u_shape * rng.lognormal(0, 0.3, (days, bars))
        cumulative = np.round(
            np.cumsum(weights, axis=1)
            / weights.sum(axis=1, keepdims=True)
            * daily["volume"].to_numpy()[:, None]
        )
        cumulative[:, -1] = daily["volume"].to_numpy()
        volume = np.diff(cumulative, axis=1, prepend=0).astype("int64")

        offsets = pd.to_timedelta(
            MARKET_OPEN.hour * 60 + MARKET_OPEN.minute + INTRADAY_BAR_MINUTES * np.arange(bars),
            unit="m",
        )
        starts = (daily.index.to_numpy()[:, None] + offsets.to_numpy()[None, :]).ravel()
        index = pd.DatetimeIndex(starts, name="bar_time").tz_localize(KST)
        return pd.DataFrame(
            {
                "open": bar_open.ravel(),
                "high": bar_high.ravel(),
                "low": bar_low.ravel(),
                "close": bar_close.ravel(),
                "volume": volume.ravel(),
            },
            index=index,
        )[INTRADAY_COLUMNS]

    # --- index --------------------------------------------------------------------------

    def fetch_index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        if index_code != INDEX_CODE:
            raise KeyError(index_code)
        n = self._daily_days
        rng = np.random.default_rng([self._seed, 10_000, 4])
        trend = np.log(np.interp(np.arange(n), [0, n - 120, n - 1], [1.0, 1.15, 1.10]))
        close = np.round(2500 * np.exp(trend + _ar1_noise(rng, n, sigma=0.012)), 2)
        open_ = np.round(np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.002, n)), 2)
        high = np.round(np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n))), 2)
        low = np.round(np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n))), 2)
        frame = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close},
            index=self._dates(),
        )[INDEX_COLUMNS]
        return frame.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()
