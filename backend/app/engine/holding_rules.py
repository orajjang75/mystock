"""Holding rules that are not rows of the PRD 6장 table: A-6 trend filter and A-8 ATR stop.

Both definitions were confirmed with the product owner (see docs/signal-map.md). Pure vectorized
pandas functions on confirmed daily bars, like the rest of the engine.
"""

from typing import TypeVar

import pandas as pd

from app.engine.indicators import sma
from app.engine.params import DEFAULT_PARAMS

Frame = TypeVar("Frame", pd.Series, pd.DataFrame)

_TREND = DEFAULT_PARAMS.trend
_STOP = DEFAULT_PARAMS.stop


def daily_downtrend(
    close: Frame, ma_window: int = _TREND.ma_window, slope_bars: int = _TREND.slope_bars
) -> Frame:
    """A-6 일봉 하락 추세: 종가 < 60일선 이고 60일선이 5거래일 전보다 낮음 (기울기 < 0).

    Anything that is not a downtrend (including a sideways market) lets the sell/rebuy cycle run.
    """
    average = sma(close, ma_window)
    return (close < average) & (average < average.shift(slope_bars))


def atr_stop_price(
    avg_price: Frame | float, daily_atr: Frame, multiple: float = _STOP.atr_multiple
) -> Frame:
    """A-8 ATR 기반 손절선 = 평균단가 − 2 × 일봉 ATR(14)."""
    return avg_price - multiple * daily_atr


def stop_breached(price: Frame, stop: Frame) -> Frame:
    """A-8 이탈: 현재가가 손절선보다 낮음 (같으면 이탈이 아니다)."""
    return price < stop
