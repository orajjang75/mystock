"""Alerts for holdings (PRD 5장 A-2~A-8, A-13). Computes what to tell the user; stores nothing.

For each holding the engine reads the latest **confirmed** bars of the configured signal length
(A-11) plus confirmed daily bars (trend filter, investor flow, ATR stop, A-13), runs the signal
functions of ``app.engine`` and returns ``AlertDraft``s. Saving them, the cooldown (A-10), the
freshness check and the delivery channels belong to the alerts service (step 6): evaluating the
same bar twice returns the same drafts with the same ``dedupe_key``.

Rules by state:

- plain holding: a sell alert needs ``min_overlap`` (2) of the six sell candidates, only if the
  daily trend is not down (A-6). Never while a cycle is waiting for a rebuy (A-2).
- rebuy wait: a rebuy alert needs price <= target and 2 of 3 reversal signals; if the daily
  trend is down a 비중 축소 경고 replaces it; if 수급 이탈 holds the alert is held back as a
  warning. An expired cycle gets no more alerts (its 만료 알림 comes from ``process_expirations``).
- after a forced sale: rebuy alerts wait until the stock and KOSPI have both recovered (A-13).
- any state: ATR stop breach (A-8) and the A-13 forced sale ignore all of the above.
"""

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.market import KST, MARKET_CLOSE
from app.db.enums import BarLength, CycleState, FillSide
from app.db.models import Cycle, Fill, Holding, IndexDaily, InvestorFlowDaily
from app.engine import alert_signals as alert
from app.engine.confirmed import confirmed_daily, confirmed_intraday
from app.engine.cycle_signals import (
    REBUY_PARTS,
    SELL_CANDIDATES,
    flow_for_bars,
    rebuy_confirmations,
    rebuy_signals,
    sell_signals,
)
from app.engine.force_sell import force_sell, ma_recovered
from app.engine.holding_rules import atr_stop_price, daily_downtrend, stop_breached
from app.engine.indicators import atr
from app.engine.params import SignalParams
from app.services import holdings as holdings_service
from app.services import quantities as q
from app.services.bars import load_recent_bars
from app.services.settings import load_signal_bar_length, load_signal_params

logger = logging.getLogger(__name__)

# A signal bar older than this at evaluation time is not "the bar that just closed" (a feed that
# lags, or the next morning before the first bar): no signal-bar alert is made from it.
MAX_SIGNAL_BAR_AGE = timedelta(minutes=45)
DAILY_BARS = 400  # enough for the 60-day average and a few ATR cycles
SIGNAL_BARS = 300


@dataclass(frozen=True, slots=True)
class AlertDraft:
    """One alert to be saved and sent. ``kind`` is one of: sell, rebuy, rebuy_held (수급 이탈
    보류 경고), reduce_position (비중 축소 경고), stop_loss, expired, force_sell."""

    kind: str
    holding_id: int | None
    code: str
    bar_time: datetime | None
    bar_length: BarLength | None = None  # set for alerts tied to an intraday or daily signal bar
    bar_end: datetime | None = None  # when that bar closed, for the 1-minute latency target
    suggested_quantity: int | None = None
    price: float | None = None
    rebuy_target_price: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        stamp = self.bar_time.isoformat() if self.bar_time else ""
        return f"{self.kind}:{self.holding_id}:{stamp}"


@dataclass(frozen=True, slots=True)
class DailyContext:
    bars: pd.DataFrame  # confirmed daily open..volume
    foreign: pd.Series  # 순매수 금액, NaN where missing, aligned to ``bars``
    institution: pd.Series
    index_close: pd.Series  # KOSPI, aligned to ``bars``


def load_daily_context(session: Session, code: str, now: datetime) -> DailyContext:
    """Confirmed daily bars of ``code`` with its investor flow and the KOSPI close."""
    bars = confirmed_daily(load_recent_bars(session, code, BarLength.D1, DAILY_BARS), now)
    if bars.empty:
        empty = pd.Series(dtype="float64")
        return DailyContext(bars, empty, empty, empty)
    first = pd.Timestamp(bars.index[0]).date()
    flows = session.execute(
        select(
            InvestorFlowDaily.trade_date,
            InvestorFlowDaily.foreign_net_buy,
            InvestorFlowDaily.institution_net_buy,
        ).where(InvestorFlowDaily.code == code, InvestorFlowDaily.trade_date >= first)
    ).all()
    flow = pd.DataFrame(flows, columns=["trade_date", "foreign", "institution"])
    flow = flow.set_index(pd.DatetimeIndex(flow["trade_date"])).drop(columns="trade_date")
    flow = flow.reindex(bars.index).astype("float64")
    index_rows = session.execute(
        select(IndexDaily.trade_date, IndexDaily.close).where(
            IndexDaily.index_code == "KOSPI", IndexDaily.trade_date >= first
        )
    ).all()
    index_close = pd.Series(
        [float(close) for _, close in index_rows],
        index=pd.DatetimeIndex([day for day, _ in index_rows]),
        dtype="float64",
    ).reindex(bars.index)
    return DailyContext(bars, flow["foreign"], flow["institution"], index_close)


def _signal_bars(
    session: Session, code: str, length: BarLength, now: datetime, daily: DailyContext
) -> pd.DataFrame:
    if length is BarLength.D1:
        return daily.bars
    frame = load_recent_bars(session, code, length, SIGNAL_BARS)
    return frame if frame.empty else confirmed_intraday(frame, now)


def _number(value: Any) -> float | None:
    number = float(value)
    return number if np.isfinite(number) else None


def _stamp(index_value: Any) -> datetime:
    return pd.Timestamp(index_value).to_pydatetime()


def _last(series: pd.Series) -> bool:
    return bool(series.iloc[-1])


# --- sell, rebuy ----------------------------------------------------------------------------


def _flow_exit(
    daily: DailyContext, bars: pd.DataFrame, length: BarLength, days: int
) -> pd.DataFrame:
    """수급 이탈 for each signal bar: daily flow through the previous confirmed daily bar."""
    return flow_for_bars(
        daily.foreign,
        daily.institution,
        pd.DatetimeIndex(bars.index),
        daily=length is BarLength.D1,
        days=days,
    )


def _sell_alert(
    holding: Holding,
    bars: pd.DataFrame,
    daily: DailyContext,
    params: SignalParams,
    length: BarLength,
) -> AlertDraft | None:
    suggestion = q.suggested_sell_quantity(holding.quantity, params.sell.sell_fraction)
    if suggestion is None:
        return None  # a single share cannot be sold in part
    flow = _flow_exit(daily, bars, length, params.sell.flow_exit_days)
    frame = sell_signals(bars, flow, params)
    if not _last(frame["alert"]):
        return None
    close = bars["close"]
    price = float(close.iloc[-1])
    return AlertDraft(
        kind="sell",
        holding_id=holding.id,
        code=holding.code,
        bar_time=_stamp(bars.index[-1]),
        suggested_quantity=suggestion,
        price=price,
        rebuy_target_price=float(
            alert.rebuy_target_price(price, params.rebuy.cost, params.rebuy.target_gain)
        ),
        evidence={
            "signals": [name for name in SELL_CANDIDATES if _last(frame[name])],
            "overlap": int(frame["overlap"].iloc[-1]),
            "bar_length": length.value,
            "rsi": _number(frame["rsi"].iloc[-1]),
            "pct_b": _number(frame["pct_b"].iloc[-1]),
            "flow_unreflected": _last(flow["unreflected"]),
        },
        params=params.model_dump(mode="json"),
    )


def cycle_proceeds(session: Session, holding_id: int, cycle: Cycle) -> tuple[Decimal, int]:
    """Net cash and shares of the sales behind a cycle (all its sales for a re-entry)."""
    fills = session.scalars(
        select(Fill).where(
            Fill.holding_id == holding_id, Fill.cycle_id == cycle.id, Fill.side == FillSide.SELL
        )
    ).all()
    own = [f for f in fills if not f.forced]
    used = fills if cycle.state is CycleState.FORCE_CLOSED else (own or fills)
    proceeds = sum(
        (q.net_sell_proceeds(f.price, f.quantity, f.fee, f.tax) for f in used), Decimal(0)
    )
    return proceeds, sum(f.quantity for f in used)


def _rebuy_alerts(
    session: Session,
    holding: Holding,
    cycle: Cycle,
    bars: pd.DataFrame,
    daily: DailyContext,
    params: SignalParams,
    length: BarLength,
) -> list[AlertDraft]:
    close = bars["close"]
    flow = _flow_exit(daily, bars, length, params.sell.flow_exit_days)
    target = float(cycle.rebuy_target_price)
    frame = rebuy_signals(close, rebuy_confirmations(bars, flow, params), target, params)
    held, ready = _last(frame["held_by_flow_filter"]), _last(frame["alert"])
    if not (held or ready):
        return []
    price = float(close.iloc[-1])
    proceeds, sold = cycle_proceeds(session, holding.id, cycle)
    shares = q.suggested_rebuy_quantity(proceeds, Decimal(str(price)), params.rebuy)
    return [
        AlertDraft(
            kind="rebuy_held" if held else "rebuy",
            holding_id=holding.id,
            code=holding.code,
            bar_time=_stamp(bars.index[-1]),
            suggested_quantity=shares,
            price=price,
            rebuy_target_price=target,
            evidence={
                "signals": [name for name in REBUY_PARTS if _last(frame[name])],
                "confirmations": int(frame["confirmations"].iloc[-1]),
                "quantity_increase": q.quantity_increase(sold, shares),
                "sold_quantity": sold,
                "held_by_flow_filter": held,
                "flow_unreflected": _last(flow["unreflected"]),
                "bar_length": length.value,
            },
            params=params.model_dump(mode="json"),
        )
    ]


# --- evaluation -----------------------------------------------------------------------------


SIGNAL_BAR_KINDS = {"sell", "rebuy", "rebuy_held", "reduce_position", "stop_loss"}


def _bar_end(bars: pd.DataFrame, length: BarLength) -> datetime:
    """When the latest bar closed: its start plus its span (the market close for a daily bar)."""
    start = pd.Timestamp(bars.index[-1]).to_pydatetime()
    if length is BarLength.D1:
        return datetime.combine(start.date(), MARKET_CLOSE, tzinfo=KST)
    minutes = int(bars["span_minutes"].iloc[-1]) if "span_minutes" in bars else 30
    return start + timedelta(minutes=minutes)


def evaluate_holding(
    session: Session,
    holding: Holding,
    *,
    now: datetime,
    params: SignalParams | None = None,
    bar_length: BarLength | None = None,
    scope: Literal["all", "daily"] = "all",
) -> list[AlertDraft]:
    """Every alert due for ``holding`` at the latest confirmed bars as of ``now``.

    ``scope="daily"`` only looks at the confirmed daily bars (the A-13 forced sale), which is
    what the after-close job needs; ``"all"`` adds the signal-bar rules.
    """
    params = params or load_signal_params(session)
    length = bar_length or load_signal_bar_length(session)
    daily = load_daily_context(session, holding.code, now)
    if daily.bars.empty:
        return []
    dump = params.model_dump(mode="json")
    drafts: list[AlertDraft] = []
    day = _stamp(daily.bars.index[-1])
    close_daily = daily.bars["close"]

    # A-13 forced sale: whatever the state, trend or cycle.
    if holding.quantity > 0:
        forced = force_sell(
            close_daily,
            daily.index_close,
            params.force_sell.ma_short_window,
            params.force_sell.ma_long_window,
        )
        if _last(forced["force_sell"]):
            drafts.append(
                AlertDraft(
                    "force_sell",
                    holding.id,
                    holding.code,
                    day,
                    suggested_quantity=holding.quantity,
                    price=float(close_daily.iloc[-1]),
                    evidence={
                        "stock_ma_breakdown": _last(forced["stock"]),
                        "kospi_ma_breakdown": _last(forced["index"]),
                    },
                    params=dump,
                )
            )

    if scope == "daily":
        return drafts

    bars = _signal_bars(session, holding.code, length, now, daily)
    if (
        not bars.empty
        and length is not BarLength.D1
        and now - _bar_end(bars, length) > MAX_SIGNAL_BAR_AGE
    ):
        bars = bars.iloc[:0]
    price = float((bars if not bars.empty else daily.bars)["close"].iloc[-1])

    # A-8 ATR stop: the line is fixed by the average cost and the latest daily ATR.
    if holding.quantity > 0:
        ind = params.indicators
        daily_atr = atr(daily.bars["high"], daily.bars["low"], close_daily, ind.atr_period)
        stop = atr_stop_price(float(holding.avg_price), daily_atr, params.stop.atr_multiple)
        if bool(stop_breached(pd.Series([price]), pd.Series([stop.iloc[-1]])).iloc[0]):
            drafts.append(
                AlertDraft(
                    "stop_loss",
                    holding.id,
                    holding.code,
                    _stamp(bars.index[-1]) if not bars.empty else day,
                    suggested_quantity=holding.quantity,
                    price=price,
                    evidence={
                        "stop_price": float(stop.iloc[-1]),
                        "avg_price": float(holding.avg_price),
                        "daily_atr": float(daily_atr.iloc[-1]),
                    },
                    params=dump,
                )
            )

    if bars.empty:
        return drafts
    return _stamped(
        _signal_drafts(session, holding, bars, daily, params, length, drafts, price), bars, length
    )


def _stamped(drafts: list[AlertDraft], bars: pd.DataFrame, length: BarLength) -> list[AlertDraft]:
    """Add the signal bar's length and closing time to the alerts that depend on it."""
    end = _bar_end(bars, length)
    return [
        replace(d, bar_length=length, bar_end=end) if d.kind in SIGNAL_BAR_KINDS else d
        for d in drafts
    ]


def _signal_drafts(
    session: Session,
    holding: Holding,
    bars: pd.DataFrame,
    daily: DailyContext,
    params: SignalParams,
    length: BarLength,
    drafts: list[AlertDraft],
    price: float,
) -> list[AlertDraft]:
    close_daily = daily.bars["close"]
    down = _last(daily_downtrend(close_daily, params.trend.ma_window, params.trend.slope_bars))
    cycle = holdings_service.open_cycle(session, holding.id)

    if cycle is None:
        reentry = holdings_service.reentry_cycle(session, holding.id)
        if reentry is not None and _recovered(daily, params):
            if down:
                drafts.append(_reduce_position(holding, bars, price, params))
            else:
                drafts += _rebuy_alerts(session, holding, reentry, bars, daily, params, length)
        if not down and holding.quantity > 0:
            sell = _sell_alert(holding, bars, daily, params, length)
            if sell is not None:
                drafts.append(sell)
    elif cycle.state is CycleState.REBUY_WAIT:
        if down:
            drafts.append(_reduce_position(holding, bars, price, params))
        else:
            drafts += _rebuy_alerts(session, holding, cycle, bars, daily, params, length)
    return drafts


def _recovered(daily: DailyContext, params: SignalParams) -> bool:
    """A-13: the stock's and KOSPI's 5-day average are back above the 20-day average."""
    short, long = params.force_sell.ma_short_window, params.force_sell.ma_long_window
    stock_ok = _last(ma_recovered(daily.bars["close"], short, long))
    index_ok = _last(ma_recovered(daily.index_close, short, long))
    return stock_ok and index_ok


def _reduce_position(
    holding: Holding, bars: pd.DataFrame, price: float, params: SignalParams
) -> AlertDraft:
    """A-6: the daily trend turned down, so a 비중 축소 경고 replaces the rebuy alert."""
    return AlertDraft(
        "reduce_position",
        holding.id,
        holding.code,
        _stamp(bars.index[-1]),
        price=price,
        evidence={"daily_downtrend": True},
        params=params.model_dump(mode="json"),
    )


def evaluate_all(
    session: Session,
    *,
    now: datetime | None = None,
    params: SignalParams | None = None,
    bar_length: BarLength | None = None,
    scope: Literal["all", "daily"] = "all",
) -> list[AlertDraft]:
    """Alerts due for every holding. One holding failing does not stop the others."""
    now = (now or datetime.now(KST)).astimezone(KST)
    params = params or load_signal_params(session)
    bar_length = bar_length or load_signal_bar_length(session)
    drafts: list[AlertDraft] = []
    for holding in session.scalars(select(Holding).order_by(Holding.id)):
        try:
            drafts += evaluate_holding(
                session, holding, now=now, params=params, bar_length=bar_length, scope=scope
            )
        except Exception:
            logger.exception(
                "alert evaluation failed for holding %s (%s)", holding.id, holding.code
            )
    return drafts


def process_expirations(session: Session, now: datetime) -> list[AlertDraft]:
    """A-7: expire cycles whose window has passed and return their 만료 알림 drafts."""
    drafts = []
    for cycle in holdings_service.expire_due_cycles(session, now):
        holding = holdings_service.get_holding(session, cycle.holding_id)
        drafts.append(
            AlertDraft(
                "expired",
                holding.id,
                holding.code,
                cycle.expires_at,
                price=None,
                rebuy_target_price=float(cycle.rebuy_target_price),
                evidence={"cycle_id": cycle.id, "choices": ["retry", "abandon"]},
            )
        )
    return drafts
