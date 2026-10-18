"""The whole sell/rebuy cycle, simulated bar by bar (PRD 5장, 10장 수량 늘리기).

The signal frames are the app's: ``engine.cycle_signals`` for the sell candidates and rebuy
confirmations (the live alert engine reads the last row of the same frames),
``engine.holding_rules`` for the A-6 trend filter, ``engine.force_sell`` for A-13. The state of
every holding and its cycles is kept by the app's own state machine, ``services.holdings``
(``record_fill``, ``expire_due_cycles``, ``retry_cycle``, ``abandon_cycle``, ``cycle_views``), in a
throw-away in-memory database, so a transition that is illegal in the app is illegal here.

What is simulated is a user who follows every alert: the decision is made on the confirmed bar
and the order is filled at the **next bar's open** (룩어헤드 방지), with slippage against the
trader, the configured fee and the sell tax. Cooldowns are not needed (the order follows the alert
at once) and the ATR stop only warns, so neither changes a position.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session

from app.backtest.config import CycleOptions
from app.backtest.dataset import Dataset
from app.core.market import KST, MARKET_CLOSE, MARKET_OPEN, trading_days_between
from app.db.base import Base
from app.db.enums import BarLength, CycleState, FillSide, Market
from app.db.models import Alert, Cycle, Fill, Holding, Instrument, Setting
from app.engine.alert_signals import previous_confirmed_daily
from app.engine.cycle_signals import flow_for_bars, rebuy_confirmations, rebuy_signals, sell_signals
from app.engine.force_sell import force_sell, ma_recovered
from app.engine.holding_rules import daily_downtrend
from app.engine.params import SignalParams
from app.services import holdings as machine
from app.services import quantities as q
from app.services.alert_engine import cycle_proceeds
from app.services.settings import save_signal_params

logger = logging.getLogger(__name__)

_TABLES = [
    Instrument.__table__,
    Holding.__table__,
    Cycle.__table__,
    Fill.__table__,
    Alert.__table__,
    Setting.__table__,
]
POST_FORCED_HORIZONS = (5, 10, 20)


def aware(stamp: datetime) -> datetime:
    """SQLite hands datetimes back without their zone; every time in a simulation is KST."""
    return stamp.replace(tzinfo=KST) if stamp.tzinfo is None else stamp.astimezone(KST)


# --- per-stock signal arrays -----------------------------------------------------------------


@dataclass
class StockSignals:
    """Everything the loop reads, as plain arrays aligned to the stock's signal bars."""

    code: str
    index: pd.DatetimeIndex  # the bars as stored (daily: midnight of the date), ascending
    starts: pd.DatetimeIndex  # when each bar opens, KST-aware: orders are filled at this time
    ends: pd.DatetimeIndex  # when each bar is confirmed, KST-aware
    open: np.ndarray
    close: np.ndarray
    sell_alert: np.ndarray  # bool
    confirmations: pd.DataFrame  # the cycle-independent rebuy parts (see cycle_signals)
    down: np.ndarray  # A-6 daily downtrend as known at each bar
    force: np.ndarray  # A-13 breakdown, set on the last bar of the day it is confirmed
    recovered: np.ndarray  # A-13 re-entry allowed
    delisted_at: int | None = None  # index of the last bar if the stock stopped trading early
    daily_close: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))


def bar_starts(index: pd.DatetimeIndex, length: BarLength) -> pd.DatetimeIndex:
    if length is not BarLength.D1:
        return pd.DatetimeIndex(index)
    return pd.DatetimeIndex(
        [pd.Timestamp(datetime.combine(ts.date(), MARKET_OPEN, tzinfo=KST)) for ts in index]
    )


def bar_ends(index: pd.DatetimeIndex, length: BarLength, bars: pd.DataFrame) -> pd.DatetimeIndex:
    if length is BarLength.D1:
        return pd.DatetimeIndex(
            [pd.Timestamp(datetime.combine(ts.date(), MARKET_CLOSE, tzinfo=KST)) for ts in index]
        )
    span = bars.get("span_minutes", 30)
    return pd.DatetimeIndex(index + pd.to_timedelta(span, unit="min"))


def stock_signals(
    data: Dataset, code: str, length: BarLength, params: SignalParams
) -> StockSignals | None:
    """Compute every signal for one stock over all the bars stored for it (None: no bars)."""
    bars = data.bars(code, length)
    if length is not BarLength.D1 and "is_complete" in bars:
        bars = bars[bars["is_complete"].to_numpy(dtype=bool)]  # never a half-collected hour
    if len(bars) < 40:
        return None
    daily = data.daily_bars(code)
    foreign, institution = data.flow(code)
    is_daily = length is BarLength.D1
    times = pd.DatetimeIndex(bars.index)
    flow = flow_for_bars(
        foreign, institution, times, daily=is_daily, days=params.sell.flow_exit_days
    )
    sell = sell_signals(bars, flow, params)
    confirmations = rebuy_confirmations(bars, flow, params)

    dclose = daily["close"]
    index_close = data.index["close"].reindex(daily.index)
    trend = params.trend
    down_d = daily_downtrend(dclose, trend.ma_window, trend.slope_bars).fillna(False)
    fs = params.force_sell
    forced_d = force_sell(dclose, index_close, fs.ma_short_window, fs.ma_long_window)["force_sell"]
    recovered_d = ma_recovered(dclose, fs.ma_short_window, fs.ma_long_window) & ma_recovered(
        index_close, fs.ma_short_window, fs.ma_long_window
    ).fillna(False)

    if is_daily:
        down = down_d.reindex(times).fillna(False).to_numpy(dtype=bool)
        recovered = recovered_d.reindex(times).fillna(False).to_numpy(dtype=bool)
        force = forced_d.reindex(times).fillna(False).to_numpy(dtype=bool)
    else:
        # an intraday bar of day D knows the daily bars through D-1
        down = (
            previous_confirmed_daily(down_d.to_frame("down"), times)["down"]
            .fillna(False)
            .to_numpy(dtype=bool)
        )
        recovered = (
            previous_confirmed_daily(recovered_d.to_frame("rec"), times)["rec"]
            .fillna(False)
            .to_numpy(dtype=bool)
        )
        # the breakdown of day D is confirmed at D's close: on D's last bar
        day = times.tz_localize(None).normalize() if times.tz is not None else times.normalize()
        last_of_day = pd.Series(day).ne(pd.Series(day).shift(-1)).to_numpy()
        flag = forced_d.reindex(day).fillna(False).to_numpy(dtype=bool)
        force = flag & last_of_day

    delisted_at: int | None = None
    if code in data.delisted:
        delisted_at = len(bars) - 1
    return StockSignals(
        code=code,
        index=times,
        starts=bar_starts(times, length),
        ends=bar_ends(times, length, bars),
        open=bars["open"].to_numpy(dtype="float64"),
        close=bars["close"].to_numpy(dtype="float64"),
        sell_alert=sell["alert"].to_numpy(dtype=bool),
        confirmations=confirmations,
        down=down,
        force=force,
        recovered=recovered,
        delisted_at=delisted_at,
        daily_close=dclose,
    )


# --- the book: the app's state machine in memory ---------------------------------------------


class Book:
    """A throw-away database holding every simulated holding, driven by ``services.holdings``."""

    def __init__(self, params: SignalParams) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=_TABLES)  # type: ignore[arg-type]
        self.engine = engine
        self.session = Session(engine, expire_on_commit=False)
        save_signal_params(self.session, params)  # retry_cycle reads the expiry window from here
        self.params = params

    def add_stock(self, code: str, name: str, market: Market) -> None:
        self.session.add(Instrument(code=code, name=name, market=market))
        self.session.flush()

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()


# --- one stock -------------------------------------------------------------------------------


@dataclass
class StockRun:
    code: str
    name: str
    holding_id: int
    start_quantity: int
    start_price: float
    times: pd.DatetimeIndex  # the bars traded on
    equity: np.ndarray  # shares x close + cash after each bar
    hold_value: np.ndarray  # the same position never traded
    quantity: np.ndarray  # shares held after each bar
    cash: float = 0.0
    expired: list[dict[str, Any]] = field(default_factory=list)
    forced: list[dict[str, Any]] = field(default_factory=list)
    delisted_exit: bool = False
    holds_warnings: int = 0  # bars on which a rebuy was held back or turned into a warning


def simulate_stock(
    book: Book,
    sig: StockSignals,
    name: str,
    params: SignalParams,
    options: CycleOptions,
    first: int,
    last: int,
    trade_from: int,
    slippage: float,
) -> StockRun:
    """Run one stock from bar ``first`` to ``last``; trading is allowed from ``trade_from``."""
    session, rebuy = book.session, params.rebuy
    market = Market.KOSPI
    if session.get(Instrument, sig.code) is None:
        book.add_stock(sig.code, name, market)
    price0 = float(sig.open[first])
    start_qty = int(options.initial_value // price0)
    if start_qty < 2:
        raise ValueError(f"{sig.code}: the starting stake buys fewer than 2 shares")
    holding = machine.register(session, sig.code, start_qty, Decimal(str(price0)))
    quantity, cash = start_qty, 0.0
    n = last - first + 1
    equity = np.zeros(n)
    quantity_after = np.zeros(n, dtype="int64")
    hold_value = sig.close[first : last + 1] * start_qty
    run = StockRun(
        sig.code,
        name,
        holding.id,
        start_qty,
        price0,
        sig.ends[first : last + 1],
        equity,
        hold_value,
        quantity_after,
    )
    retries: dict[int, int] = {}
    cache: dict[int, pd.DataFrame] = {}  # rebuy frames by cycle id

    def fill(side: FillSide, i: int, quantity_: int, *, forced: bool = False) -> Any:
        """Fill at the open of the bar after ``i`` with slippage against the trader."""
        nonlocal quantity, cash
        j = i + 1
        base = float(sig.open[j])
        price = base * (1 - slippage) if side is FillSide.SELL else base * (1 + slippage)
        result = machine.record_fill(
            session,
            holding.id,
            side,
            Decimal(str(round(price, 4))),
            quantity_,
            filled_at=sig.starts[j].to_pydatetime(),
            forced=forced,
            params=rebuy,
        )
        f = result.fill
        gross = f.price * f.quantity
        cash += float(gross - f.fee - f.tax) if side is FillSide.SELL else -float(gross + f.fee)
        quantity = result.holding.quantity
        return result

    for i in range(first, last + 1):
        pos = i - first
        now = aware(sig.ends[i].to_pydatetime())
        can_trade = i >= trade_from and i < last  # an order needs a next bar to fill on
        cycle = machine.open_cycle(session, holding.id)

        # A-7: the wait ran out; the user's choice follows at once
        if (
            cycle is not None
            and cycle.state is CycleState.REBUY_WAIT
            and aware(cycle.expires_at or now) <= now
        ):
            expired = machine.expire_due_cycles(session, now)
            if expired:
                loss = (float(sig.close[i]) / float(cycle.sell_price) - 1) * 100
                run.expired.append(
                    {
                        "cycle_id": cycle.id,
                        "sell_price": float(cycle.sell_price),
                        "sell_quantity": cycle.sell_quantity,
                        "close_at_expiry": float(sig.close[i]),
                        "missed_pct": loss,
                        "missed_value": max(0.0, float(sig.close[i]) - float(cycle.sell_price))
                        * cycle.sell_quantity,
                        "expired_at": now.isoformat(),
                    }
                )
                tries = retries.get(cycle.id, 0)
                if options.on_expiry == "retry" and tries < options.max_retries:
                    retries[cycle.id] = tries + 1
                    machine.retry_cycle(session, holding.id, cycle.id, now=now)
                else:
                    machine.abandon_cycle(session, holding.id, cycle.id)
                cycle = machine.open_cycle(session, holding.id)

        if can_trade and quantity > 0 and sig.force[i]:
            # A-13: sell everything, whatever the state, filled at the next open
            result = fill(FillSide.SELL, i, quantity, forced=True)
            run.forced.append(
                {
                    "at": sig.starts[i + 1].isoformat(),
                    "price": float(result.fill.price),
                    "quantity": result.fill.quantity,
                    "date": pd.Timestamp(sig.starts[i + 1]).tz_localize(None).normalize(),
                }
            )
        elif can_trade:
            _decide(book, sig, i, params, holding, cycle, cache, fill, run)

        equity[pos] = quantity * float(sig.close[i]) + cash
        quantity_after[pos] = quantity

    if sig.delisted_at is not None and last == sig.delisted_at and quantity > 0:
        # the stock stopped trading: whatever is left is sold at its last price
        j = last
        price = float(sig.close[j]) * (1 - slippage)
        result = machine.record_fill(
            session, holding.id, FillSide.SELL, Decimal(str(round(price, 4))), quantity,
            filled_at=aware(sig.ends[j].to_pydatetime()), forced=True, params=rebuy,
        )  # fmt: skip
        f = result.fill
        cash += float(f.price * f.quantity - f.fee - f.tax)
        quantity = 0
        equity[-1] = cash
        quantity_after[-1] = 0
        run.delisted_exit = True
    run.cash = cash
    return run


def _decide(
    book: Book,
    sig: StockSignals,
    i: int,
    params: SignalParams,
    holding: Holding,
    cycle: Cycle | None,
    cache: dict[int, pd.DataFrame],
    fill: Any,
    run: StockRun,
) -> None:
    """The A-2 / A-5 / A-6 decision of the live alert engine, acted on at the next open."""
    session = book.session
    down = bool(sig.down[i])

    def rebuy_frame(target_cycle: Cycle) -> pd.DataFrame:
        if target_cycle.id not in cache:
            cache[target_cycle.id] = rebuy_signals(
                pd.Series(sig.close, index=sig.index),
                sig.confirmations,
                float(target_cycle.rebuy_target_price),
                params,
            )
        return cache[target_cycle.id]

    def try_rebuy(target_cycle: Cycle) -> bool:
        frame = rebuy_frame(target_cycle)
        if bool(frame["held_by_flow_filter"].iloc[i]):
            run.holds_warnings += 1  # the alert is held back (a warning only)
            return False
        if not bool(frame["alert"].iloc[i]):
            return False
        proceeds, _ = cycle_proceeds(session, holding.id, target_cycle)
        shares = q.suggested_rebuy_quantity(
            proceeds, Decimal(str(float(sig.close[i]))), params.rebuy
        )
        if shares <= 0:
            return False
        fill(FillSide.REBUY, i, shares)
        return True

    if cycle is None:
        reentry = machine.reentry_cycle(session, holding.id)
        if reentry is not None and bool(sig.recovered[i]):
            if down:
                run.holds_warnings += 1  # 비중 축소 경고 instead of a rebuy
            elif try_rebuy(reentry):
                return
        if not down and holding.quantity > 0 and bool(sig.sell_alert[i]):
            quantity = q.suggested_sell_quantity(holding.quantity, params.sell.sell_fraction)
            if quantity is not None:
                fill(FillSide.SELL, i, quantity)
    elif cycle.state is CycleState.REBUY_WAIT:
        if down:
            run.holds_warnings += 1
        else:
            try_rebuy(cycle)


# --- all stocks ------------------------------------------------------------------------------


@dataclass
class CycleResult:
    length: BarLength
    metrics: dict[str, Any]
    cycles: list[dict[str, Any]]
    curves: dict[str, list[Any]]
    notes: dict[str, Any]


def _trading_days(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return trading_days_between(a.date(), b.date())


def _holdings_at(data: Dataset, start: pd.Timestamp, limit: int) -> list[str]:
    """The stocks held: members on the first day, the most traded first."""
    day = data.dates[int(data.dates.searchsorted(start))]
    members = data.members.loc[day]
    codes = list(members.index[members.to_numpy()])
    traded = data.panel["trading_value"].loc[:day].tail(20).mean()
    codes.sort(key=lambda c: -float(traded.get(c, 0.0) or 0.0))
    return codes[:limit]


def simulate_cycles(
    data: Dataset,
    params: SignalParams,
    length: BarLength,
    options: CycleOptions,
    period: tuple[pd.Timestamp, pd.Timestamp],
    *,
    slippage: float | None = None,
    codes: list[str] | None = None,
) -> CycleResult:
    """Simulate the sell/rebuy cycle of ``codes`` (default: the biggest members) over ``period``."""
    slippage = options.slippage if slippage is None else slippage
    start, end = period
    chosen = codes or _holdings_at(data, start, options.max_stocks)
    book = Book(params)
    runs: list[StockRun] = []
    skipped: list[str] = []
    try:
        for code in chosen:
            sig = stock_signals(data, code, length, params)
            if sig is None:
                skipped.append(code)
                continue
            day = (
                sig.index.tz_localize(None).normalize()
                if sig.index.tz is not None
                else sig.index.normalize()
            )
            inside = np.flatnonzero((day >= start) & (day <= end))
            if len(inside) < 20:
                skipped.append(code)
                continue
            first, last = int(inside[0]), int(inside[-1])
            warm_day = _nth_session(day[first : last + 1], options.warmup_days)
            trade_from = first + int(np.searchsorted(day[first : last + 1], warm_day))
            sig.delisted_at = (
                last
                if (code in data.delisted and last == len(sig.index) - 1 and day[last] < end)
                else None
            )
            try:
                runs.append(
                    simulate_stock(
                        book, sig, data.names.get(code, code), params, options,
                        first, last, trade_from, slippage,
                    )
                )  # fmt: skip
            except ValueError as error:
                logger.info("skipped %s: %s", code, error)
                skipped.append(code)
        return _collect(book, data, runs, length, options, slippage, skipped)
    finally:
        book.close()


def _nth_session(days: pd.DatetimeIndex, n: int) -> pd.Timestamp:
    unique = pd.DatetimeIndex(days.unique())
    return pd.Timestamp(unique[min(n, len(unique) - 1)])


def _collect(
    book: Book,
    data: Dataset,
    runs: list[StockRun],
    length: BarLength,
    options: CycleOptions,
    slippage: float,
    skipped: list[str],
) -> CycleResult:
    session = book.session
    rows: list[dict[str, Any]] = []
    totals = {"fees": 0.0, "taxes": 0.0}
    for run in runs:
        views, _ = machine.cycle_views(session, run.holding_id)
        fills = session.query(Fill).filter(Fill.holding_id == run.holding_id).all()
        for view in views:
            sold_at, rebought_at = view.sold_at, view.rebought_at
            if sold_at is None:
                continue
            rows.append(_cycle_row(run, view, data, sold_at, rebought_at))
        for f in fills:
            totals["fees"] += float(f.fee)
            totals["taxes"] += float(f.tax)
    rows.sort(key=lambda r: (r["sold_at"], r["code"]))
    metrics = _metrics(runs, rows, data, length, totals, slippage)
    curves = _curves(runs)
    return CycleResult(
        length=length,
        metrics=metrics,
        cycles=rows,
        curves=curves,
        notes={
            "stocks": len(runs),
            "skipped": skipped,
            "delisted_exits": [r.code for r in runs if r.delisted_exit],
            "slippage": slippage,
        },
    )


# --- results ---------------------------------------------------------------------------------

_STATE_LABEL = {
    CycleState.REBUY_WAIT: "open",
    CycleState.REBUY_DONE: "done",
    CycleState.EXPIRED: "expired",
    CycleState.ABANDONED: "abandoned",
    CycleState.FORCE_CLOSED: "forced",
}


def _cycle_row(
    run: StockRun,
    view: machine.CycleView,
    data: Dataset,
    sold_at: datetime,
    rebought_at: datetime | None,
) -> dict[str, Any]:
    cycle = view.cycle
    sell_qty = cycle.sell_quantity
    increase = view.quantity_increase
    waited = None
    if rebought_at is not None:
        waited = _trading_days(pd.Timestamp(sold_at), pd.Timestamp(rebought_at))
    missed = next((e for e in run.expired if e["cycle_id"] == cycle.id), None)
    return {
        "code": run.code,
        "name": run.name,
        "state": _STATE_LABEL[cycle.state],
        "forced": view.forced,
        "sold_at": aware(sold_at).isoformat(),
        "sell_price": float(cycle.sell_price),
        "sell_quantity": sell_qty,
        "rebuy_target_price": float(cycle.rebuy_target_price),
        "rebought_at": aware(rebought_at).isoformat() if rebought_at else None,
        "rebuy_price": None if cycle.rebuy_price is None else float(cycle.rebuy_price),
        "rebuy_quantity": cycle.rebuy_quantity,
        "quantity_increase": increase,
        "increase_rate": None if increase is None else increase / sell_qty,
        "net_cash": None if view.net_cash is None else float(view.net_cash),
        "costs": float(view.sell_fee + view.sell_tax + (view.rebuy_fee or 0)),
        "wait_sessions": waited,
        "expired": missed is not None,
        "missed_pct": None if missed is None else missed["missed_pct"],
        "missed_value": None if missed is None else missed["missed_value"],
    }


def _stat(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None}
    arr = np.asarray(values, dtype="float64")
    return {"mean": float(arr.mean()), "median": float(np.median(arr))}


def _max_drawdown(curve: np.ndarray) -> float:
    if curve.size == 0:
        return 0.0
    peak = np.maximum.accumulate(curve)
    return float(np.min(curve / peak - 1))


def _union_curve(runs: list[StockRun], attr: str) -> pd.Series:
    """Sum of the per-stock series over the union of bar times; a series that ended is carried."""
    frames = [pd.Series(getattr(r, attr), index=r.times) for r in runs]
    wide = pd.concat(frames, axis=1).sort_index().ffill()
    return wide.sum(axis=1)


def _metrics(
    runs: list[StockRun],
    rows: list[dict[str, Any]],
    data: Dataset,
    length: BarLength,
    totals: dict[str, float],
    slippage: float,
) -> dict[str, Any]:
    own = [r for r in rows if not r["forced"]]  # the sales the strategy chose to make
    finished = [r for r in own if r["state"] in ("done", "expired", "abandoned")]
    done = [r for r in own if r["state"] == "done"]
    gained = [r for r in done if (r["quantity_increase"] or 0) > 0]
    expired = [r for r in own if r["expired"]]
    start_total = sum(run.start_quantity for run in runs)
    total_increase = sum(r["quantity_increase"] or 0 for r in done)
    sold_dates = {r["sold_at"][:10] for r in own}

    equity = _union_curve(runs, "equity") if runs else pd.Series(dtype="float64")
    hold = _union_curve(runs, "hold_value") if runs else pd.Series(dtype="float64")
    ret = float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) > 1 else 0.0
    hold_ret = float(hold.iloc[-1] / hold.iloc[0] - 1) if len(hold) > 1 else 0.0

    forced_after: dict[str, Any] = {}
    for horizon in POST_FORCED_HORIZONS:
        moves = []
        for run in runs:
            close = data.panel["close"][run.code].dropna()
            for event in run.forced:
                later = close[close.index > event["date"]]
                if len(later) >= horizon and event["price"] > 0:
                    moves.append(float(later.iloc[horizon - 1] / event["price"] - 1))
        forced_after[str(horizon)] = {"n": len(moves), **_stat(moves)}

    return {
        "bar_length": length.value,
        "stocks": len(runs),
        "sells": len(own),
        "finished": len(finished),
        "open_at_end": len([r for r in own if r["state"] == "open"]),
        "completed": len(done),
        "completion_rate": len(done) / len(finished) if finished else None,
        "gain_rate": len(gained) / len(finished) if finished else None,
        "increase_rate": _stat([r["increase_rate"] for r in done]),
        "cumulative_increase": total_increase,
        "cumulative_increase_pct": 100 * total_increase / start_total if start_total else None,
        "signal_dates": len(sold_dates),
        "expired": len(expired),
        "expired_share": len(expired) / len(finished) if finished else None,
        "missed_pct": _stat([r["missed_pct"] for r in expired]),
        "missed_value": float(sum(r["missed_value"] for r in expired)),
        "wait_sessions": _stat(
            [r["wait_sessions"] for r in done if r["wait_sessions"] is not None]
        ),
        "forced": {
            "count": sum(len(run.forced) for run in runs),
            "stocks": sum(1 for run in runs if run.forced),
            "after": forced_after,
        },
        "delisted_exits": sum(1 for run in runs if run.delisted_exit),
        "held_back": sum(run.holds_warnings for run in runs),
        "costs": totals["fees"] + totals["taxes"],
        "total_return": ret,
        "hold_return": hold_ret,
        "excess_return": ret - hold_ret,
        "max_drawdown": _max_drawdown(equity.to_numpy()),
        "hold_max_drawdown": _max_drawdown(hold.to_numpy()),
        "slippage": slippage,
    }


def _curves(runs: list[StockRun]) -> dict[str, list[Any]]:
    """Account value and share count over time, with the never-trade position as the yardstick."""
    if not runs:
        return {"times": [], "strategy": [], "hold": [], "quantity_gain_pct": []}
    equity = _union_curve(runs, "equity")
    hold = _union_curve(runs, "hold_value")
    gain = _union_curve(runs, "quantity")
    start_total = sum(run.start_quantity for run in runs)
    step = max(1, len(equity) // 400)
    pick = np.arange(0, len(equity), step)
    if pick[-1] != len(equity) - 1:
        pick = np.append(pick, len(equity) - 1)
    base = float(equity.iloc[0]) or 1.0
    return {
        "times": [pd.Timestamp(equity.index[int(i)]).isoformat() for i in pick],
        "strategy": [round(100 * float(equity.iloc[i]) / base, 4) for i in pick],
        "hold": [round(100 * float(hold.iloc[i]) / base, 4) for i in pick],
        "quantity_gain_pct": [
            round(100 * (float(gain.iloc[i]) / start_total - 1), 4) for i in pick
        ],
    }
