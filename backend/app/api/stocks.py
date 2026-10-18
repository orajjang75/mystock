from typing import Annotated

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, require_user
from app.db.enums import BarLength
from app.db.models import Instrument, InvestorFlowDaily
from app.engine.indicators import atr, bollinger, macd, obv, rsi
from app.services.bars import load_recent_bars
from app.services.settings import load_signal_params

router = APIRouter(prefix="/stocks", tags=["stocks"], dependencies=[Depends(require_user)])

Bar = Annotated[BarLength, Query(description="1d, 30m or 60m")]
Limit = Annotated[int, Query(ge=1, le=1000)]
WARMUP_BARS = 150  # history for the slowest indicator to settle before the returned range


class Candle(BaseModel):
    time: str  # YYYY-MM-DD for daily bars, an ISO-8601 timestamp (KST) for intraday bars
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_complete: bool = True  # False for a 60-minute bar whose second half is not stored yet


class IndicatorPoint(BaseModel):
    time: str
    rsi: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    bb_lower: float | None
    bb_mid: float | None
    bb_upper: float | None
    pct_b: float | None
    bandwidth: float | None
    obv: float | None
    atr: float | None


class FlowPoint(BaseModel):
    date: str
    foreign_net_buy: int
    institution_net_buy: int


class IndicatorsResponse(BaseModel):
    code: str
    bar: BarLength
    points: list[IndicatorPoint]
    flow: list[FlowPoint]  # daily 순매수 금액 over the days the points cover


def _time_label(stamp: object, bar: BarLength) -> str:
    moment = pd.Timestamp(str(stamp)) if not isinstance(stamp, pd.Timestamp) else stamp
    return moment.date().isoformat() if bar is BarLength.D1 else moment.isoformat()


def _bars(db: DbSession, code: str, bar: BarLength, count: int) -> pd.DataFrame:
    if db.get(Instrument, code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown stock {code}")
    return load_recent_bars(db, code, bar, count)


def _numbers(series: pd.Series) -> list[float | None]:
    return [None if not np.isfinite(v) else float(v) for v in series.to_numpy(dtype="float64")]


@router.get("/{code}/candles")
def candles(code: str, db: DbSession, bar: Bar = BarLength.D1, limit: Limit = 200) -> list[Candle]:
    """The latest ``limit`` confirmed bars, oldest first."""
    frame = _bars(db, code, bar, limit)
    complete = (
        frame["is_complete"] if "is_complete" in frame else pd.Series(True, index=frame.index)
    )
    return [
        Candle(
            time=_time_label(stamp, bar),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=int(row.volume),
            is_complete=bool(done),
        )
        for (stamp, row), done in zip(frame.iterrows(), complete, strict=True)
    ]


@router.get("/{code}/indicators")
def indicators(
    code: str, db: DbSession, bar: Bar = BarLength.D1, limit: Limit = 200
) -> IndicatorsResponse:
    """RSI, MACD, Bollinger, OBV and ATR over the same bars as ``/candles``, plus daily flow."""
    frame = _bars(db, code, bar, limit + WARMUP_BARS)
    ind = load_signal_params(db).indicators
    close = frame["close"]
    bands = bollinger(close, ind.bollinger_window, ind.bollinger_k)
    lines = macd(close, ind.macd_fast, ind.macd_slow, ind.macd_signal)
    table = pd.DataFrame(
        {
            "rsi": rsi(close, ind.rsi_period),
            "macd": lines["macd"],
            "macd_signal": lines["signal"],
            "macd_hist": lines["hist"],
            "bb_lower": bands["lower"],
            "bb_mid": bands["mid"],
            "bb_upper": bands["upper"],
            "pct_b": bands["pct_b"],
            "bandwidth": bands["bandwidth"],
            "obv": obv(close, frame["volume"]),
            "atr": atr(frame["high"], frame["low"], close, ind.atr_period),
        }
    ).tail(limit)
    columns = {name: _numbers(table[name]) for name in table.columns}
    points = [
        IndicatorPoint(
            time=_time_label(stamp, bar), **{name: values[i] for name, values in columns.items()}
        )
        for i, stamp in enumerate(table.index)
    ]

    flow: list[FlowPoint] = []
    if len(table):
        first = pd.Timestamp(table.index[0]).date()
        last = pd.Timestamp(table.index[-1]).date()
        rows = db.execute(
            select(InvestorFlowDaily)
            .where(
                InvestorFlowDaily.code == code,
                InvestorFlowDaily.trade_date.between(first, last),
            )
            .order_by(InvestorFlowDaily.trade_date)
        ).scalars()
        flow = [
            FlowPoint(
                date=row.trade_date.isoformat(),
                foreign_net_buy=row.foreign_net_buy,
                institution_net_buy=row.institution_net_buy,
            )
            for row in rows
        ]
    return IndicatorsResponse(code=code, bar=bar, points=points, flow=flow)
