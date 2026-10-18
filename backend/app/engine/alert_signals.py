"""Alert signals for holdings (PRD 6장 매도·재매수 행). Pure vectorized pandas functions.

Same conventions as ``screener_signals``: inputs are confirmed bars of the chosen length
(30m/60m/daily), "직전" is the previous bar, "현재" the latest confirmed bar. The 수급 신호
(수급 이탈, 수급 필터) use the previous confirmed *daily* bars, never intraday data; align them
to intraday bars with ``flow_exit_at_bars``.
"""

from collections.abc import Sequence
from typing import TypeVar

import pandas as pd

from app.engine.indicators import fields, price_pct_b, sma
from app.engine.params import DEFAULT_PARAMS
from app.engine.screener_signals import flow_missing, macd_golden_cross
from app.engine.swings import last_two_swings, swing_high_confirmed

Frame = TypeVar("Frame", pd.Series, pd.DataFrame)
Price = TypeVar("Price", float, pd.Series, pd.DataFrame)

_SELL = DEFAULT_PARAMS.sell
_REBUY = DEFAULT_PARAMS.rebuy
_DECIMALS = 8

__all__ = [
    "atr_disparity",
    "atr_disparity_overheat",
    "bearish_divergence",
    "bollinger_support",
    "bollinger_upper_reentry",
    "flow_exit",
    "flow_exit_at_bars",
    "macd_golden_cross",
    "macd_weakening",
    "previous_confirmed_daily",
    "price_condition",
    "rebuy_decision",
    "rebuy_target_price",
    "rsi_overbought_exit",
    "rsi_rebound",
    "sell_decision",
]


# --- 매도 ------------------------------------------------------------------------------


def rsi_overbought_exit(rsi: Frame, level: float = _SELL.rsi_overbought) -> Frame:
    """RSI 과열 이탈: 직전 RSI ≥ 70 이고 현재 RSI < 70."""
    return (rsi.shift(1) >= level) & (rsi < level)


def bollinger_upper_reentry(pct_b: Frame, level: float = _SELL.bollinger_upper_level) -> Frame:
    """볼린저 상단 복귀: 직전 %B > 1 이고 현재 %B ≤ 1."""
    return (pct_b.shift(1) > level) & (pct_b <= level)


def macd_weakening(macd_line: Frame, signal_line: Frame, bars: int = _SELL.macd_weak_bars) -> Frame:
    """MACD 약화: 데드크로스, 또는 히스토그램이 양수인 채로 N봉 연속 감소 (N = 2).

    Dead cross: 직전 MACD ≥ 시그널 이고 현재 MACD < 시그널.
    """
    dead_cross = (macd_line.shift(1) >= signal_line.shift(1)) & (macd_line < signal_line)
    hist = macd_line - signal_line
    shrinking = (hist.diff() < 0).astype("float64").rolling(bars, min_periods=bars).min() > 0
    return dead_cross | (shrinking & (hist > 0))


def bearish_divergence(
    high: Frame,
    rsi: Frame,
    macd_hist: Frame,
    k: int = _SELL.swing_confirm_bars,
    lookback: int = _SELL.divergence_lookback,
) -> Frame:
    """약세 다이버전스: 확정된 두 스윙 고점에서 가격은 상승하고 RSI 또는 MACD 히스토그램은 하락.

    Mirror of ``bullish_divergence``: latest two confirmed swing highs within ``lookback`` bars.
    """
    confirmed = swing_high_confirmed(high, k)
    on_rsi = last_two_swings(high, rsi, confirmed, k)
    on_hist = last_two_swings(high, macd_hist, confirmed, k)
    return (
        (on_rsi.previous_age < lookback)
        & (on_rsi.latest_price > on_rsi.previous_price)
        & (
            (on_rsi.latest_value < on_rsi.previous_value)
            | (on_hist.latest_value < on_hist.previous_value)
        )
    )


def atr_disparity(
    close: Frame, atr_value: Frame, window: int = _SELL.atr_disparity_window
) -> Frame:
    """(종가 − 20봉 이동평균) / ATR(14)."""
    return (close - sma(close, window)) / atr_value


def atr_disparity_overheat(
    close: Frame,
    atr_value: Frame,
    window: int = _SELL.atr_disparity_window,
    multiple: float = _SELL.atr_disparity_multiple,
) -> Frame:
    """ATR 기반 이격도 과열: (종가 − 20봉 이동평균) / ATR(14) ≥ 3."""
    return atr_disparity(close, atr_value, window).round(_DECIMALS) >= multiple


def flow_exit(foreign: Frame, institution: Frame, days: int = _SELL.flow_exit_days) -> pd.DataFrame:
    """수급 이탈 (= 재매수 수급 필터의 조건), on **daily** data.

    ``signal``: (외국인 + 기관) 일별 순매수 금액이 최근 N거래일 연속 0 미만. Skipped (False)
    when any of the last N days has no data, in which case ``unreflected`` ('수급 미반영') is True.
    """
    unreflected = flow_missing(foreign, institution, days)
    net = foreign + institution
    signal = (net.rolling(days, min_periods=days).max() < 0) & ~unreflected
    return fields({"signal": signal, "unreflected": unreflected})


def previous_confirmed_daily(daily: pd.DataFrame, bar_times: pd.DatetimeIndex) -> pd.DataFrame:
    """For each intraday bar, the last daily row of a strictly earlier date (NaN if none).

    A bar on day D therefore sees daily data through D-1 only, never the unfinished day D.
    """
    available = daily.copy()
    available.index = pd.DatetimeIndex(daily.index).normalize() + pd.Timedelta(days=1)
    bar_days = bar_times.tz_localize(None).normalize() if bar_times.tz is not None else bar_times
    aligned = available.reindex(bar_days.normalize(), method="ffill")
    aligned.index = bar_times
    return aligned


def flow_exit_at_bars(
    foreign_daily: Frame,
    institution_daily: Frame,
    bar_times: pd.DatetimeIndex,
    days: int = _SELL.flow_exit_days,
) -> pd.DataFrame:
    """``flow_exit`` of the previous confirmed daily bar, aligned to intraday ``bar_times``.

    Bars with no earlier daily bar at all get no signal and are flagged as unreflected.
    """
    aligned = previous_confirmed_daily(flow_exit(foreign_daily, institution_daily, days), bar_times)
    return fields(
        {
            "signal": aligned["signal"].fillna(False).astype(bool),
            "unreflected": aligned["unreflected"].fillna(True).astype(bool),
        }
    )


def count_true(signals: Sequence[Frame]) -> Frame:
    """Number of signals that are True at each bar."""
    return sum((s.astype("int64") for s in signals[1:]), start=signals[0].astype("int64"))


def sell_decision(
    candidates: Sequence[Frame], min_overlap: int = _SELL.min_overlap
) -> pd.DataFrame:
    """A-2: a sell alert needs ``min_overlap`` (2) of the six sell candidates at the same bar.

    Pass the candidates in any order, 수급 이탈 ``signal`` included.
    Columns: ``alert``, ``overlap``.
    """
    overlap = count_true(candidates)
    return fields({"alert": overlap >= min_overlap, "overlap": overlap})


# --- 재매수 ----------------------------------------------------------------------------


def rsi_rebound(
    rsi: Frame, low: float = _REBUY.rsi_rebound_low, high: float = _REBUY.rsi_rebound_high
) -> Frame:
    """RSI 반등: 직전 RSI < 현재 RSI 이고 현재 RSI가 30 이상 50 미만."""
    return (rsi.shift(1) < rsi) & (rsi >= low) & (rsi < high)


def bollinger_support(
    low: Frame, bands: pd.DataFrame, level: float = _REBUY.bollinger_support_level
) -> Frame:
    """볼린저 지지: 직전 봉 저가의 %B ≤ 기준선 이고 현재 종가의 %B > 같은 기준선.

    ``bands`` is the output of ``indicators.bollinger``; 0 = 하단 지지, 0.5 = 중심선 지지.
    """
    return (price_pct_b(low, bands).shift(1) <= level) & (bands["pct_b"] > level)


def price_condition(price: Frame, target_price: Frame | float) -> Frame:
    """가격 조건: 현재가 ≤ 재매수 목표가. Never a signal on its own (see ``rebuy_decision``)."""
    return price <= target_price


def rebuy_target_price(
    sell_price: Price,
    cost: float = _REBUY.cost,
    target_gain: float = _REBUY.target_gain,
) -> Price:
    """재매수 목표가 = 직전 매도가 × (1 − 비용 − 목표 이득).

    ``cost`` = 왕복 수수료 + 매도 거래세, ``target_gain`` 기본 1%.
    """
    return sell_price * (1 - cost - target_gain)


def rebuy_decision(
    price_ok: Frame,
    rsi_rebound_: Frame,
    bollinger_support_: Frame,
    macd_cross: Frame,
    flow_exit_signal: Frame,
    min_confirmations: int = _REBUY.min_confirmations,
) -> pd.DataFrame:
    """재매수 알림 판정.

    Needs 가격 조건 AND ``min_confirmations`` (2) of the three reversal confirmations; the
    수급 필터 is not counted as a confirmation. If 수급 이탈 holds, the alert is held back and
    only a warning remains (``held_by_flow_filter``). Pass ``flow_exit_signal`` False where flow
    data is missing: the filter is then not applied.
    """
    confirmations = count_true([rsi_rebound_, bollinger_support_, macd_cross])
    ready = price_ok & (confirmations >= min_confirmations)
    held = ready & flow_exit_signal
    return fields(
        {
            "alert": ready & ~held,
            "held_by_flow_filter": held,
            "confirmations": confirmations,
        }
    )
