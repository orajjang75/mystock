"""Swing highs/lows, confirmed without look-ahead.

A bar is a swing low when its low is the lowest of the ``k`` bars on each side and itself, so it
can only be known ``k`` bars later. Every function here reports a swing at the bar where it
becomes *confirmed*, never earlier.
"""

from typing import Generic, NamedTuple, TypeVar

import numpy as np
import pandas as pd

Frame = TypeVar("Frame", pd.Series, pd.DataFrame)


def _confirmed(is_swing: Frame, k: int) -> Frame:
    return is_swing.shift(k, fill_value=False)


def swing_low_confirmed(low: Frame, k: int) -> Frame:
    """True at bar t when bar t-k is a swing low (confirmed at t)."""
    window = low.rolling(2 * k + 1, center=True, min_periods=2 * k + 1)
    return _confirmed(low == window.min(), k)


def swing_high_confirmed(high: Frame, k: int) -> Frame:
    """True at bar t when bar t-k is a swing high (confirmed at t)."""
    window = high.rolling(2 * k + 1, center=True, min_periods=2 * k + 1)
    return _confirmed(high == window.max(), k)


def last_swing_high(high: Frame, k: int) -> Frame:
    """Price of the most recent confirmed swing high, carried forward (NaN before the first)."""
    return high.shift(k).where(swing_high_confirmed(high, k)).ffill()


class SwingPair(NamedTuple, Generic[Frame]):
    """The two most recent confirmed swings as seen at each bar."""

    latest_price: Frame
    previous_price: Frame
    latest_value: Frame
    previous_value: Frame
    previous_age: Frame  # bars from the previous swing bar to this bar


def _positions(like: Frame) -> Frame:
    count = np.arange(len(like), dtype="float64")
    if isinstance(like, pd.DataFrame):
        grid = np.broadcast_to(count[:, None], like.shape).copy()
        return pd.DataFrame(grid, index=like.index, columns=like.columns)
    return pd.Series(count, index=like.index)


def last_two_swings(price: Frame, value: Frame, confirmed: Frame, k: int) -> SwingPair[Frame]:
    """Price and an indicator ``value`` at the latest two confirmed swings.

    ``confirmed`` is the output of ``swing_low_confirmed``/``swing_high_confirmed`` for
    ``price``. The indicator is read at the swing bar itself (t-k), not at the confirming bar.
    """
    position = _positions(price)

    def pair(series: Frame) -> tuple[Frame, Frame]:
        at_swing = series.where(confirmed).ffill()
        return at_swing, at_swing.shift(1).where(confirmed).ffill()

    latest_price, previous_price = pair(price.shift(k))
    latest_value, previous_value = pair(value.shift(k))
    _, previous_position = pair(position - k)
    return SwingPair(
        latest_price, previous_price, latest_value, previous_value, position - previous_position
    )
