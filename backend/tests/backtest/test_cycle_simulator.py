"""The cycle simulator: scripted scenarios with known outcomes, then the no-lookahead checks."""

from datetime import datetime, time
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.backtest.config import CycleOptions
from app.backtest.cycle_simulator import (
    Book,
    StockRun,
    StockSignals,
    simulate_stock,
)
from app.core.market import KST, MARKET_CLOSE, MARKET_OPEN
from app.db.enums import CycleState, HoldingState
from app.services import holdings as machine
from tests.legacy_rates import HAND_PARAMS

PARAMS = HAND_PARAMS


def at(day: pd.Timestamp, clock: time) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(day.date(), clock, tzinfo=KST))


def flags(n: int, positions: tuple[int, ...]) -> np.ndarray:
    return np.isin(np.arange(n), positions)


def make(
    opens: list[float],
    *,
    closes: list[float] | None = None,
    sell_at: tuple[int, ...] = (),
    rebuy_at: tuple[int, ...] = (),  # bars on which two reversal confirmations hold
    held_at: tuple[int, ...] = (),  # bars on which 수급 이탈 holds
    force_at: tuple[int, ...] = (),
    down_at: tuple[int, ...] = (),
    recovered: bool = True,
    start: str = "2026-09-01",
) -> StockSignals:
    """Daily bars with the signals set by hand (the signal maths has its own tests)."""
    n = len(opens)
    days = pd.bdate_range(start, periods=n)
    closes = closes or opens
    conf = pd.DataFrame(
        {
            "rsi_rebound": flags(n, rebuy_at),
            "bollinger_support": flags(n, rebuy_at),
            "macd_golden_cross": np.zeros(n, dtype=bool),
            "flow_exit": flags(n, held_at),
            "flow_unreflected": np.zeros(n, dtype=bool),
        },
        index=days,
    )
    return StockSignals(
        code="900001",
        index=days,
        starts=pd.DatetimeIndex([at(d, MARKET_OPEN) for d in days]),
        ends=pd.DatetimeIndex([at(d, MARKET_CLOSE) for d in days]),
        open=np.array(opens, dtype=float),
        close=np.array(closes, dtype=float),
        sell_alert=flags(n, sell_at),
        confirmations=conf,
        down=flags(n, down_at),
        force=flags(n, force_at),
        recovered=np.full(n, recovered),
    )  # fmt: skip


class Sim:
    def __init__(self, sig: StockSignals, *, slippage: float = 0.0, **options: Any) -> None:
        self.book = Book(PARAMS)
        self.sig = sig
        opts = CycleOptions(initial_value=1_000_000, warmup_days=0, **options)
        self.run: StockRun = simulate_stock(
            self.book, sig, "모의", PARAMS, opts, 0, len(sig.open) - 1, 0, slippage
        )
        self.session = self.book.session
        self.holding = machine.get_holding(self.session, self.run.holding_id)

    def cycles(self) -> list[Any]:
        return machine.cycle_views(self.session, self.holding.id)[0]


FLAT = [100.0] * 30


def test_a_sell_is_filled_at_the_next_open_and_a_rebuy_below_target_adds_shares() -> None:
    opens = [100.0] * 30
    opens[4] = 100.0  # the sell signal is on bar 3; the fill is bar 4's open
    opens[8:] = [98.0] * 22  # a dip: the rebuy signal on bar 8 (close 98) is filled at bar 9's open
    closes = list(opens)
    closes[3] = 101.0  # the signal bar's own close is not the fill price
    sim = Sim(make(opens, closes=closes, sell_at=(3,), rebuy_at=(8,)))

    (view,) = sim.cycles()
    cycle = view.cycle

    assert float(cycle.sell_price) == 100.0  # bar 4's open, not bar 3's close of 101
    assert cycle.sell_quantity == 3333  # a third of 10 000 shares
    assert view.sold_at.date().isoformat() == "2026-09-07"  # bar 4 of bdate_range(2026-09-01)
    assert float(cycle.rebuy_price) == 98.0  # bar 9's open
    assert cycle.state is CycleState.REBUY_DONE
    assert view.quantity_increase == cycle.rebuy_quantity - 3333 > 0
    assert sim.holding.quantity == 10_000 + view.quantity_increase
    assert sim.holding.state is HoldingState.HOLDING
    assert sim.run.quantity[-1] == sim.holding.quantity


def test_nothing_is_done_before_the_signal_bar_closes() -> None:
    """A signal on the very last bar has no next bar to fill on: no order."""
    sim = Sim(make(FLAT, sell_at=(len(FLAT) - 1,)))

    assert sim.cycles() == []
    assert sim.holding.quantity == 10_000


def test_the_equity_counts_cash_and_costs() -> None:
    sim = Sim(make(FLAT, sell_at=(3,)))  # sell a third and never rebuy at a price below the target

    (view,) = sim.cycles()

    cost = float(view.sell_fee + view.sell_tax)
    assert cost == pytest.approx(3333 * 100 * (0.0003 / 2 + 0.0018), rel=1e-6)
    assert sim.run.equity[-1] == pytest.approx(
        1_000_000 - cost, abs=1
    )  # flat prices: only the costs
    assert sim.run.cash == pytest.approx(3333 * 100 - cost, abs=1)


def test_slippage_goes_against_the_trader_on_both_sides() -> None:
    opens = [100.0] * 30
    opens[8:] = [95.0] * 22
    sim = Sim(make(opens, sell_at=(3,), rebuy_at=(8,)), slippage=0.01)

    (view,) = sim.cycles()

    assert float(view.cycle.sell_price) == pytest.approx(99.0)  # sold 1 % lower
    assert float(view.cycle.rebuy_price) == pytest.approx(95.0 * 1.01)  # bought 1 % higher


def test_no_rebuy_without_the_price_condition() -> None:
    """The reversal signals fire, but the price is still above the target: no rebuy."""
    sim = Sim(make(FLAT, sell_at=(3,), rebuy_at=(8, 9, 10)))

    (view,) = sim.cycles()

    assert view.cycle.rebuy_price is None  # price 100 > target ~99.2


def test_a_wait_that_runs_out_is_abandoned_by_default_and_counts_the_missed_gain() -> None:
    opens = [100.0] * 30
    opens[9:] = [110.0] * 21  # the price runs away while we wait; the window ends on bar 9
    sim = Sim(make(opens, sell_at=(3,)))

    (view,) = sim.cycles()

    assert view.cycle.state is CycleState.ABANDONED
    assert sim.holding.state is HoldingState.HOLDING
    (expired,) = sim.run.expired
    assert expired["missed_pct"] == pytest.approx(10.0, abs=0.01)
    assert expired["missed_value"] == pytest.approx(10.0 * 3333, abs=1)


def test_retry_waits_for_a_new_window_up_to_the_limit() -> None:
    sim = Sim(make([100.0] * 60, sell_at=(3,)), on_expiry="retry", max_retries=1)

    (view,) = sim.cycles()

    assert len(sim.run.expired) == 2  # the first window, then the retry's window
    assert view.cycle.state is CycleState.ABANDONED  # the limit of one retry was reached
    assert sim.holding.state is HoldingState.HOLDING


def test_a_second_sale_waits_for_the_cycle_to_end() -> None:
    sim = Sim(make(FLAT, sell_at=(3, 4, 5, 6)))

    assert len(sim.cycles()) == 1  # one sale per cycle (A-2)


def test_a_downtrend_stops_the_cycle_and_a_warning_is_counted_instead() -> None:
    sim = Sim(make(FLAT, sell_at=(3,), down_at=(3,)))
    assert sim.cycles() == []  # no sale in a daily downtrend (A-6)

    opens = [100.0] * 30
    opens[8:] = [98.0] * 22
    waiting = Sim(make(opens, sell_at=(3,), rebuy_at=(8,), down_at=(8,)))
    (view,) = waiting.cycles()
    assert view.cycle.rebuy_price is None  # a 비중 축소 경고 replaces the rebuy
    assert waiting.run.holds_warnings >= 1


def test_the_flow_filter_holds_the_rebuy_back() -> None:
    opens = [100.0] * 30
    opens[8:] = [98.0] * 22
    sim = Sim(make(opens, sell_at=(3,), rebuy_at=(8,), held_at=(8,)))

    (view,) = sim.cycles()

    assert view.cycle.rebuy_price is None
    assert sim.run.holds_warnings == 1


def test_a_forced_sale_sells_everything_ends_the_cycle_and_waits_for_the_recovery() -> None:
    opens = [100.0] * 40
    sim = Sim(make(opens, sell_at=(3,), force_at=(6,), rebuy_at=(10,), recovered=False))

    (cycle_view,) = sim.cycles()

    assert cycle_view.cycle.state is CycleState.FORCE_CLOSED
    assert sim.holding.quantity == 0
    assert len(sim.run.forced) == 1
    assert sim.run.forced[0]["quantity"] == 10_000 - 3333  # what was left
    assert sim.holding.state is HoldingState.HOLDING  # waiting for the recovery before a re-entry


def test_the_reentry_after_a_forced_sale_needs_the_recovery_and_a_rebuy_signal() -> None:
    opens = [100.0] * 20 + [95.0] * 20
    held = Sim(make(opens, force_at=(3,), rebuy_at=(25,), recovered=False))
    assert held.holding.quantity == 0  # never recovered: no re-entry

    back = Sim(make(opens, force_at=(3,), rebuy_at=(25,), recovered=True))
    assert back.holding.quantity > 0  # re-entered at the first rebuy signal under the target
    (view,) = back.cycles()
    assert view.cycle.rebuy_quantity == back.holding.quantity


def test_a_delisted_stock_is_closed_at_its_last_price() -> None:
    sig = make(FLAT)
    sig.delisted_at = len(FLAT) - 1
    sim = Sim(sig)

    assert sim.holding.quantity == 0
    assert sim.run.delisted_exit
    assert sim.run.equity[-1] == pytest.approx(sim.run.cash)
    assert sim.run.quantity[-1] == 0


def test_a_stake_too_small_to_split_is_refused() -> None:
    with pytest.raises(ValueError, match="fewer than 2 shares"):
        Sim(make([600_000.0] * 30))


def test_trading_waits_for_the_warmup() -> None:
    sig = make(FLAT, sell_at=(2,))
    book = Book(PARAMS)
    options = CycleOptions(initial_value=1_000_000, warmup_days=0)

    run = simulate_stock(
        book, sig, "모의", PARAMS, options, 0, len(FLAT) - 1, trade_from=5, slippage=0.0
    )

    assert machine.cycle_views(book.session, run.holding_id)[0] == []  # the signal came too early


# --- on the mock market: no look-ahead, whatever the bar length ------------------------------

from collections.abc import Iterator  # noqa: E402

from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.backtest.config import UniverseOptions  # noqa: E402
from app.backtest.cycle_simulator import simulate_cycles, stock_signals  # noqa: E402
from app.backtest.dataset import Dataset, load_dataset  # noqa: E402
from app.db.enums import BarLength  # noqa: E402
from app.engine.cycle_signals import rebuy_signals  # noqa: E402

SLIPPAGE = 0.002


@pytest.fixture(scope="module")
def data(bt_engine: Engine) -> Iterator[Dataset]:
    with sessionmaker(bind=bt_engine, expire_on_commit=False)() as session:
        yield load_dataset(session, UniverseOptions())


def period_of(data: Dataset, length: BarLength) -> tuple[pd.Timestamp, pd.Timestamp]:
    span = data.intraday_span()
    assert span is not None
    return (
        (span[0], span[1])
        if length is not BarLength.D1
        else (max(data.eval_start, span[0]), span[1])
    )


def truncated(data: Dataset, last: pd.Timestamp) -> Dataset:
    """The dataset as it was at the close of ``last``: nothing later exists."""
    keep = data.dates <= last

    def intraday(code: str, length: BarLength) -> pd.DataFrame:
        bars = data.bars(code, length)
        span = bars.get("span_minutes", 30)
        ends = pd.DatetimeIndex(bars.index) + pd.to_timedelta(span, unit="min")
        return bars[ends <= pd.Timestamp(datetime.combine(last.date(), MARKET_CLOSE, tzinfo=KST))]

    return Dataset(
        panel={k: v.loc[keep] for k, v in data.panel.items()},
        index=data.index.loc[keep],
        members=data.members.loc[keep],
        names=data.names,
        markets=data.markets,
        first_bar=data.first_bar,
        last_bar=data.last_bar,
        delisted=data.delisted,
        eval_start=data.eval_start,
        eval_end=last,
        notes=data.notes,
        _intraday=intraday,
    )


@pytest.mark.parametrize("length", [BarLength.D1, BarLength.M60, BarLength.M30])
def test_every_fill_is_at_the_open_of_the_bar_after_the_signal(
    data: Dataset, length: BarLength
) -> None:
    options = CycleOptions(max_stocks=10, slippage=SLIPPAGE)
    result = simulate_cycles(data, PARAMS, length, options, period_of(data, length))
    assert result.cycles, "the mock run should trade at least once"

    checked = {"sell": 0, "rebuy": 0}
    for row in result.cycles:
        sig = stock_signals(data, row["code"], length, PARAMS)
        assert sig is not None
        starts = list(sig.starts)

        j = starts.index(pd.Timestamp(row["sold_at"]))
        assert j >= 1  # there was a bar before the fill: the one that gave the signal
        assert row["sell_price"] == pytest.approx(round(sig.open[j] * (1 - SLIPPAGE), 4))
        assert sig.sell_alert[j - 1] or sig.force[j - 1]  # the decision was made one bar earlier
        checked["sell"] += 1

        if row["rebought_at"]:
            k = starts.index(pd.Timestamp(row["rebought_at"]))
            assert k > j
            assert row["rebuy_price"] == pytest.approx(round(sig.open[k] * (1 + SLIPPAGE), 4))
            frame = rebuy_signals(
                pd.Series(sig.close, index=sig.index),
                sig.confirmations,
                row["rebuy_target_price"],
                PARAMS,
            )
            assert frame["alert"].iloc[k - 1]  # the rebuy alert of the previous bar, filled now
            assert sig.close[k - 1] <= row["rebuy_target_price"]  # the price condition held then
            checked["rebuy"] += 1
    assert checked["sell"] > 0


@pytest.mark.parametrize("length", [BarLength.D1, BarLength.M60])
def test_cutting_the_data_does_not_change_what_was_done_before_the_cut(
    data: Dataset, length: BarLength
) -> None:
    """A later bar leaking into a decision would change earlier trades once it is cut away."""
    options = CycleOptions(max_stocks=10, slippage=SLIPPAGE)
    start, end = period_of(data, length)
    sessions = data.dates[(data.dates >= start) & (data.dates <= end)]
    cut = sessions[len(sessions) * 2 // 3]
    full = simulate_cycles(data, PARAMS, length, options, (start, end))
    early = simulate_cycles(truncated(data, cut), PARAMS, length, options, (start, cut))

    assert early.cycles
    by_key = {(r["code"], r["sold_at"]): r for r in full.cycles}
    for row in early.cycles:
        twin = by_key[(row["code"], row["sold_at"])]  # the same sale was made in the full run
        for field in ("sell_price", "sell_quantity", "rebuy_target_price", "forced"):
            assert row[field] == twin[field], field
        if row["rebought_at"]:  # a rebuy that already happened before the cut is the same one
            for field in ("rebought_at", "rebuy_price", "rebuy_quantity", "quantity_increase"):
                assert row[field] == twin[field], field


def test_the_same_run_twice_gives_the_same_result(data: Dataset) -> None:
    options = CycleOptions(max_stocks=6)
    period = period_of(data, BarLength.D1)

    first = simulate_cycles(data, PARAMS, BarLength.D1, options, period)
    second = simulate_cycles(data, PARAMS, BarLength.D1, options, period)

    assert first.cycles == second.cycles
    assert first.metrics == second.metrics


def test_the_metrics_follow_their_definitions(data: Dataset) -> None:
    options = CycleOptions(max_stocks=12)
    result = simulate_cycles(data, PARAMS, BarLength.M60, options, period_of(data, BarLength.M60))
    m, rows = result.metrics, result.cycles

    own = [r for r in rows if not r["forced"]]
    finished = [r for r in own if r["state"] in ("done", "expired", "abandoned")]
    done = [r for r in own if r["state"] == "done"]
    assert m["sells"] == len(own) and m["finished"] == len(finished) and m["completed"] == len(done)
    if finished:
        assert m["completion_rate"] == pytest.approx(len(done) / len(finished))
        assert m["gain_rate"] == pytest.approx(
            sum(1 for r in done if r["quantity_increase"] > 0) / len(finished)
        )
    for r in done:
        assert r["quantity_increase"] == r["rebuy_quantity"] - r["sell_quantity"]
        assert r["increase_rate"] == pytest.approx(r["quantity_increase"] / r["sell_quantity"])
    assert m["cumulative_increase"] == sum(r["quantity_increase"] for r in done)
    assert m["excess_return"] == pytest.approx(m["total_return"] - m["hold_return"])
    assert -1 < m["max_drawdown"] <= 0
    assert m["expired"] == sum(1 for r in own if r["expired"])


def test_a_delisted_stock_ends_flat_and_its_slide_counts(data: Dataset) -> None:
    """Whether A-13 sells it on the way down or the delisting closes it, nothing is left held."""
    delisted = sorted(data.delisted)
    assert delisted
    start = data.dates[len(data.dates) - 200]
    result = simulate_cycles(
        data,
        PARAMS,
        BarLength.D1,
        CycleOptions(max_stocks=5),
        (start, data.eval_end),
        codes=delisted,
    )

    exits = result.metrics["forced"]["stocks"] + result.metrics["delisted_exits"]
    assert exits >= len(delisted)  # every one of them was closed out one way or the other
    assert result.metrics["total_return"] < 0  # a slide to 60 % is paid for
    assert result.curves["quantity_gain_pct"][-1] == pytest.approx(-100)  # no shares left
