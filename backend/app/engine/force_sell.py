"""A-13 5일선 이탈 강제 매도 (PRD 6장 강제 매도 행). Confirmed daily closes only."""

from typing import TypeVar

import numpy as np
import pandas as pd

from app.engine.indicators import fields, sma
from app.engine.params import DEFAULT_PARAMS
from app.engine.screener_signals import ma_short_above_long

Frame = TypeVar("Frame", pd.Series, pd.DataFrame)

_F = DEFAULT_PARAMS.force_sell


def ma_breakdown(
    close: Frame, short: int = _F.ma_short_window, long: int = _F.ma_long_window
) -> Frame:
    """5일선 이탈: 직전 5일 이동평균 ≥ 20일 이동평균 이고 현재 5일 이동평균 < 20일 이동평균.

    One function for both table rows: pass a stock's daily closes for 보유 종목 5일선 이탈, or
    the KOSPI index's daily closes for KOSPI 지수 5일선 이탈.
    """
    short_ma, long_ma = sma(close, short), sma(close, long)
    return (short_ma.shift(1) >= long_ma.shift(1)) & (short_ma < long_ma)


def ma_recovered(
    close: Frame, short: int = _F.ma_short_window, long: int = _F.ma_long_window
) -> Frame:
    """A-13 재매수 알림 재개 조건: 5일선이 20일선 위로 회복 (= 5일선 우위)."""
    return ma_short_above_long(close, short, long)


def force_sell(
    stock_close: Frame,
    index_close: pd.Series,
    short: int = _F.ma_short_window,
    long: int = _F.ma_long_window,
) -> pd.DataFrame:
    """Columns ``stock``, ``index`` and ``force_sell`` (either one).

    A KOSPI breakdown applies to every stock; a stock breakdown only to that stock.
    ``index_close`` is aligned to the stock index (missing days count as no breakdown).
    """
    stock = ma_breakdown(stock_close, short, long)
    index = ma_breakdown(index_close, short, long).reindex(stock_close.index, fill_value=False)
    if isinstance(stock, pd.DataFrame):
        everywhere = np.broadcast_to(index.to_numpy()[:, None], stock.shape)
        index_frame = pd.DataFrame(everywhere, index=stock.index, columns=stock.columns)
    else:
        index_frame = index
    return fields({"stock": stock, "index": index_frame, "force_sell": stock | index_frame})
