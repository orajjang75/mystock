"""Indicators (PRD 6장 공통 지표). Vectorized pure functions, no Python loops.

Every function accepts either one stock (a Series) or many stocks at once (a DataFrame with
one column per stock, indexed by bar time); pandas applies the same math column by column.
Multi-output functions return one DataFrame: flat columns for a Series input and
``(field, stock)`` MultiIndex columns for a DataFrame input, so ``result["pct_b"]`` has the
shape of the input in both cases.

Smoothing is seeded with the simple average of the first window (Wilder / TA-Lib convention),
so values are NaN until a full window exists.
"""

from typing import TypeVar

import pandas as pd

from app.engine.params import DEFAULT_PARAMS

Frame = TypeVar("Frame", pd.Series, pd.DataFrame)

_IND = DEFAULT_PARAMS.indicators


def sma(x: Frame, window: int) -> Frame:
    """Simple moving average over the last ``window`` bars (current bar included)."""
    return x.rolling(window, min_periods=window).mean()


def _seeded_ewm(x: Frame, length: int, alpha: float) -> Frame:
    seed = sma(x, length)
    valid = seed.notna()
    first = valid & ~valid.shift(1, fill_value=False)
    start = x.where(valid & ~first, seed.where(first))
    return start.ewm(alpha=alpha, adjust=False).mean()


def ema(x: Frame, length: int) -> Frame:
    """Exponential moving average, alpha = 2 / (length + 1)."""
    return _seeded_ewm(x, length, 2 / (length + 1))


def wilder(x: Frame, length: int) -> Frame:
    """Wilder's smoothing (RMA), alpha = 1 / length."""
    return _seeded_ewm(x, length, 1 / length)


def fields(columns: dict[str, Frame]) -> pd.DataFrame:
    return pd.concat(columns, axis=1)


def rsi(close: Frame, length: int = _IND.rsi_period) -> Frame:
    """Relative strength index. 100 when there were no losses in the smoothed window."""
    delta = close.diff()
    avg_gain = wilder(delta.clip(lower=0), length)
    avg_loss = wilder((-delta).clip(lower=0), length)
    value = 100 - 100 / (1 + avg_gain / avg_loss)
    return value.where(avg_loss != 0, 100.0)


def macd(
    close: Frame,
    fast: int = _IND.macd_fast,
    slow: int = _IND.macd_slow,
    signal: int = _IND.macd_signal,
) -> pd.DataFrame:
    """Columns ``macd``, ``signal`` and ``hist`` (macd - signal)."""
    line = ema(close, fast) - ema(close, slow)
    signal_line = ema(line, signal)
    return fields({"macd": line, "signal": signal_line, "hist": line - signal_line})


def true_range(high: Frame, low: Frame, close: Frame) -> Frame:
    previous_close = close.shift(1)
    # clip(lower=...) is an element-wise max that ignores NaN bounds (no previous close at bar 0).
    return (
        (high - low)
        .clip(lower=(high - previous_close).abs())
        .clip(lower=(low - previous_close).abs())
    )


def atr(high: Frame, low: Frame, close: Frame, length: int = _IND.atr_period) -> Frame:
    """Average true range (Wilder)."""
    return wilder(true_range(high, low, close), length)


def obv(close: Frame, volume: Frame) -> Frame:
    """On-balance volume; the first bar counts as 0."""
    change = close.diff()
    direction = (change > 0).astype("float64") - (change < 0).astype("float64")
    return (direction * volume).cumsum()


def bollinger(
    close: Frame,
    window: int = _IND.bollinger_window,
    k: float = _IND.bollinger_k,
    ddof: int = 0,
) -> pd.DataFrame:
    """Columns ``lower``, ``mid``, ``upper``, ``pct_b`` and ``bandwidth`` from one calculation.

    %B = (close - lower) / (upper - lower); bandwidth = (upper - lower) / mid. Population
    standard deviation (``ddof=0``) as in TA-Lib and charting platforms. %B is NaN when the
    bands have zero width.
    """
    mid = sma(close, window)
    deviation = k * close.rolling(window, min_periods=window).std(ddof=ddof)
    lower, upper = mid - deviation, mid + deviation
    width = upper - lower
    return fields(
        {
            "lower": lower,
            "mid": mid,
            "upper": upper,
            "pct_b": (close - lower) / width.where(width != 0),
            "bandwidth": width / mid,
        }
    )


def price_pct_b(price: Frame, bands: pd.DataFrame) -> Frame:
    """%B of any price (e.g. a bar's low) against that bar's own Bollinger bands."""
    lower, upper = bands["lower"], bands["upper"]
    width = upper - lower
    return (price - lower) / width.where(width != 0)
