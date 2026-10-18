"""Screener signals (PRD 6장, 스크리너 행). Pure vectorized pandas functions, no loops.

Inputs are Series (one stock) or DataFrames with one column per stock; outputs have the same
shape. Callers pass **confirmed** bars only (see ``engine.confirmed``): "직전" is the bar just
before, "현재" is the latest confirmed bar, and every "최근 N거래일" window includes the current
bar. Boolean signals are False wherever their inputs are NaN (e.g. during indicator warm-up).

Functions ending in ``_pct``/``_ratio``/``avg_`` return the number behind a signal, which is
what gets stored as the evidence of a scan result. Ratio-based comparisons are rounded to
8 decimals first so that a value exactly on a threshold is not lost to float noise.
"""

from typing import TypeVar

import pandas as pd

from app.engine.indicators import sma
from app.engine.params import DEFAULT_PARAMS
from app.engine.swings import (
    last_swing_high,
    last_two_swings,
    swing_low_confirmed,
)

Frame = TypeVar("Frame", pd.Series, pd.DataFrame)

_S = DEFAULT_PARAMS.screener
_DECIMALS = 8


def _at_least(value: Frame, threshold: float) -> Frame:
    return value.round(_DECIMALS) >= threshold


def _at_most(value: Frame, threshold: float) -> Frame:
    return value.round(_DECIMALS) <= threshold


# --- 안전 필터 -------------------------------------------------------------------------


def avg_trading_value(trading_value: Frame, window: int = _S.liquidity_window) -> Frame:
    """최근 ``window``거래일 일평균 거래대금. NaN until ``window`` bars exist."""
    return trading_value.rolling(window, min_periods=window).mean()


def liquidity_ok(
    trading_value: Frame,
    min_avg: float = _S.min_avg_trading_value,
    window: int = _S.liquidity_window,
) -> Frame:
    """거래대금: 최근 20거래일 일평균 거래대금 ≥ 기준 (10억 원)."""
    return avg_trading_value(trading_value, window) >= min_avg


# --- 바닥 게이트 -----------------------------------------------------------------------


def drawdown_52w_pct(high: Frame, close: Frame, window: int = _S.drawdown_window) -> Frame:
    """100 × (현재 종가 / 최근 252거래일 최고가 − 1). NaN until 252 bars exist."""
    return 100 * (close / high.rolling(window, min_periods=window).max() - 1)


def drawdown_52w_ok(
    high: Frame,
    close: Frame,
    threshold_pct: float = _S.drawdown_threshold_pct,
    window: int = _S.drawdown_window,
) -> Frame:
    """52주 고점 대비 낙폭 ≤ 기준 (-30%; 후보가 적으면 ``drawdown_relaxed_threshold_pct``)."""
    return _at_most(drawdown_52w_pct(high, close, window), threshold_pct)


def disparity_pct(close: Frame, window: int = _S.disparity_window) -> Frame:
    """100 × (종가 / 20일 이동평균 − 1)."""
    return 100 * (close / sma(close, window) - 1)


def disparity_oversold(
    close: Frame,
    threshold_pct: float = _S.disparity_threshold_pct,
    window: int = _S.disparity_window,
) -> Frame:
    """이격도 ≤ 과열 임계값 (-8%)."""
    return _at_most(disparity_pct(close, window), threshold_pct)


def bollinger_break_history(pct_b: Frame, lookback: int = _S.bollinger_break_lookback) -> Frame:
    """볼린저 하단 이탈 이력: 최근 10거래일 중 %B < 0 인 날이 있음."""
    return (pct_b < 0).astype("float64").rolling(lookback, min_periods=1).max() > 0


# --- 반전 ------------------------------------------------------------------------------


def rsi_cross_up(rsi: Frame, level: float = _S.rsi_cross_level) -> Frame:
    """RSI 상향 돌파: 직전 RSI < 30 이고 현재 RSI ≥ 30."""
    return (rsi.shift(1) < level) & (rsi >= level)


def bullish_divergence(
    low: Frame,
    rsi: Frame,
    k: int = _S.swing_confirm_bars,
    lookback: int = _S.divergence_lookback,
) -> Frame:
    """강세 다이버전스: 확정된 두 스윙 저점에서 가격은 하락하고 RSI는 상승.

    Looks at the latest two confirmed swing lows; both must lie within the last ``lookback``
    bars. A swing low is confirmed ``k`` bars after it happens. True from the confirmation of
    the second swing until it, or its predecessor, leaves the window or a newer swing appears.
    """
    pair = last_two_swings(low, rsi, swing_low_confirmed(low, k), k)
    return (
        (pair.previous_age < lookback)
        & (pair.latest_price < pair.previous_price)
        & (pair.latest_value > pair.previous_value)
    )


def bollinger_reentry(pct_b: Frame) -> Frame:
    """볼린저 복귀: 직전 %B < 0 이고 현재 %B ≥ 0."""
    return (pct_b.shift(1) < 0) & (pct_b >= 0)


# --- 확인 ------------------------------------------------------------------------------


def macd_golden_cross(
    macd_line: Frame,
    signal_line: Frame,
    below_zero_only: bool = _S.macd_cross_below_zero_only,
) -> Frame:
    """MACD 골든크로스: 직전 MACD ≤ 시그널 이고 현재 MACD > 시그널.

    With ``below_zero_only`` only a cross while the MACD line is below zero counts. The same
    function is the 재매수 MACD 골든크로스.
    """
    cross = (macd_line.shift(1) <= signal_line.shift(1)) & (macd_line > signal_line)
    return cross & (macd_line < 0) if below_zero_only else cross


def close_above_ma(close: Frame, window: int = _S.ma_long_window) -> Frame:
    """종가의 20일선 회복: 종가 > 20일 이동평균."""
    return close > sma(close, window)


def ma_short_above_long(
    close: Frame, short: int = _S.ma_short_window, long: int = _S.ma_long_window
) -> Frame:
    """5일선 우위: 5일 이동평균 > 20일 이동평균."""
    return sma(close, short) > sma(close, long)


def downwave_high_breakout(close: Frame, high: Frame, k: int = _S.swing_confirm_bars) -> Frame:
    """하락 파동 고점 돌파: 종가 > 최근 확정 스윙 고점 (상태 판정, 돌파 당일에 한정하지 않음)."""
    return close > last_swing_high(high, k)


def obv_turn_up(obv_value: Frame, window: int = _S.obv_ma_window) -> Frame:
    """OBV 전환: OBV가 자기 20일 평균 위로 올라선 첫 봉 (직전 OBV ≤ 평균, 현재 OBV > 평균)."""
    average = sma(obv_value, window)
    return (obv_value.shift(1) <= average.shift(1)) & (obv_value > average)


# --- 거래량 ----------------------------------------------------------------------------


def volume_ratio(volume: Frame, window: int = _S.volume_window) -> Frame:
    """당일 거래량 / 최근 20거래일 평균 거래량 (당일 포함)."""
    return volume / volume.rolling(window, min_periods=window).mean()


def volume_surge(
    volume: Frame,
    open_: Frame,
    close: Frame,
    multiple: float = _S.volume_multiple,
    window: int = _S.volume_window,
) -> Frame:
    """평균 대비 거래량: 거래량 ≥ 평균 × ``multiple`` 이고 양봉. 2배 기본, 3배는 가산용."""
    return _at_least(volume_ratio(volume, window), multiple) & (close > open_)


# --- 수급 ------------------------------------------------------------------------------


def consecutive_net_buy(net_buy: Frame, days: int = _S.flow_consecutive_days) -> Frame:
    """외국인(기관) 연속 순매수: 일별 순매수 금액 > 0 인 날이 최근 N거래일 연속.

    Pass the foreign column for 외국인 연속 순매수 and the institution column for 기관.
    """
    return net_buy.rolling(days, min_periods=days).min() > 0


def net_buy_strength_pct(
    foreign: Frame,
    institution: Frame,
    trading_value: Frame,
    window: int = _S.flow_strength_window,
) -> Frame:
    """100 × 최근 5거래일 (외국인 + 기관) 순매수 금액 합 / 최근 5거래일 거래대금 합."""
    net = (foreign + institution).rolling(window, min_periods=window).sum()
    return 100 * net / trading_value.rolling(window, min_periods=window).sum()


def net_buy_strength(
    foreign: Frame,
    institution: Frame,
    trading_value: Frame,
    threshold_pct: float = _S.flow_strength_threshold_pct,
    window: int = _S.flow_strength_window,
) -> Frame:
    """외국인·기관 순매수 강도 ≥ 기준 (2%)."""
    return _at_least(
        net_buy_strength_pct(foreign, institution, trading_value, window), threshold_pct
    )


def net_buy_turnaround(
    foreign: Frame, institution: Frame, window: int = _S.flow_turnaround_window
) -> Frame:
    """순매수 전환: 최근 5거래일 (외국인 + 기관) 합 > 0 이고 그 이전 5거래일 합 ≤ 0."""
    recent = (foreign + institution).rolling(window, min_periods=window).sum()
    return (recent > 0) & (recent.shift(window) <= 0)


def flow_missing(foreign: Frame, institution: Frame, lookback: int) -> Frame:
    """'수급 미반영': 최근 ``lookback``거래일에 외국인·기관 값이 빈 날이 있거나 이력이 모자람.

    Flow signals are False in that case; the scorer drops the 수급 구간 and rescales to 100.
    """
    missing = foreign.isna() | institution.isna()
    window = missing.astype("float64").rolling(lookback, min_periods=lookback).max()
    return window.fillna(1.0) > 0
