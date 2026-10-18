"""Alert rules on the shared mock market, with the engine signals pinned to chosen values.

The signal maths is tested in tests/engine. Here the signals are forced True/False so that each
test isolates one rule: overlap counts, the state a holding is in, the daily trend filter, the
수급 이탈 hold, the forced sale and the ATR stop.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.adapters.mock import MockAdapter, Scenario
from app.core.market import KST
from app.db.enums import BarLength, FillSide
from app.db.models import Holding
from app.engine.holding_rules import daily_downtrend
from app.services import alert_engine as engine
from app.services import holdings as svc
from app.services.settings import save_signal_bar_length
from app.services.universe import load_universe
from tests.alert_helpers import REBUY_FUNCTIONS, SELL_FUNCTIONS, force_sell_frame, pin
from tests.conftest import AFTER_CLOSE

D = Decimal


@pytest.fixture(autouse=True)
def no_forced_sale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep A-13 quiet unless a test asks for it."""
    monkeypatch.setattr(engine, "force_sell", force_sell_frame())


def stock_where(
    adapter: MockAdapter, session: Session, scenario: Scenario, now: datetime, *, down: bool
) -> str:
    """A universe stock of ``scenario`` whose daily trend at ``now`` is (not) down."""
    for member in load_universe(session):
        if adapter.stock(member.code).scenario is not scenario:
            continue
        close = engine.load_daily_context(session, member.code, now).bars["close"]
        if bool(daily_downtrend(close).iloc[-1]) is down:
            return member.code
    raise AssertionError(f"no {scenario.value} stock with downtrend={down}")


@pytest.fixture
def code(market: Session, mock_adapter: MockAdapter) -> str:
    """A stock that is not in a downtrend."""
    return stock_where(mock_adapter, market, Scenario.UPTREND, AFTER_CLOSE, down=False)


def hold(session: Session, code: str, quantity: int = 100, avg_price: int = 1) -> Holding:
    return svc.register(session, code, quantity, D(avg_price))


def evaluate(
    session: Session, holding: Holding, now: datetime = AFTER_CLOSE, **kwargs: Any
) -> list[engine.AlertDraft]:
    return engine.evaluate_holding(session, holding, now=now, **kwargs)


def kinds(drafts: list[engine.AlertDraft]) -> list[str]:
    return [draft.kind for draft in drafts]


def last_close(session: Session, code: str, now: datetime = AFTER_CLOSE) -> float:
    return float(engine.load_daily_context(session, code, now).bars["close"].iloc[-1])


def sell_then_wait(
    session: Session, holding: Holding, sell_price: float | None = None, *, quantity: int = 30
) -> None:
    """Record a sale high enough that today's price is below the rebuy target."""
    price = sell_price if sell_price is not None else last_close(session, holding.code) * 2
    svc.record_fill(
        session,
        holding.id,
        FillSide.SELL,
        D(str(round(price, 2))),
        quantity,
        filled_at=AFTER_CLOSE - timedelta(days=1),
    )


# --- sell alerts (A-2, A-3, A-4) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("true", "flow", "expected"),
    [
        (set(), "off", False),
        ({"rsi_overbought_exit"}, "off", False),  # one candidate is not enough
        ({"rsi_overbought_exit", "macd_weakening"}, "off", True),
        (set(SELL_FUNCTIONS), "off", True),
        (set(), "exit", False),  # 수급 이탈 alone is one candidate
        ({"bollinger_upper_reentry"}, "exit", True),  # 수급 이탈 counts as the second one
        ({"bearish_divergence"}, "missing", False),  # missing flow data: skipped, not counted
    ],
)
def test_a_sell_alert_needs_two_overlapping_candidates(
    market: Session,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    true: set[str],
    flow: str,
    expected: bool,
) -> None:
    pin(monkeypatch, true=true, flow=flow)

    drafts = evaluate(market, hold(market, code))

    assert ("sell" in kinds(drafts)) is expected


def test_the_sell_alert_suggests_a_third_and_shows_the_rebuy_target(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})

    (draft,) = [d for d in evaluate(market, hold(market, code, 100)) if d.kind == "sell"]

    assert draft.suggested_quantity == 33  # a third of 100, never everything
    assert draft.price is not None
    assert draft.rebuy_target_price == pytest.approx(draft.price * (1 - 0.0021 - 0.01))
    assert draft.evidence["signals"] == ["rsi_overbought_exit", "macd_weakening"]
    assert draft.evidence["overlap"] == 2
    assert draft.params["sell"]["min_overlap"] == 2


@pytest.mark.parametrize(("held", "suggested"), [(100, 33), (3, 1), (2, 1)])
def test_the_suggested_quantity_follows_the_position(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str, held: int, suggested: int
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})

    (draft,) = [d for d in evaluate(market, hold(market, code, held)) if d.kind == "sell"]

    assert draft.suggested_quantity == suggested


def test_a_single_share_cannot_be_sold_in_part_so_there_is_no_sell_alert(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS))

    assert "sell" not in kinds(evaluate(market, hold(market, code, 1)))


@pytest.mark.parametrize("expire", [False, True])
def test_no_sell_alert_while_a_cycle_is_waiting_for_a_rebuy(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str, expire: bool
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS), flow="exit")
    holding = hold(market, code)
    sell_then_wait(market, holding)
    if expire:
        svc.expire_due_cycles(market, AFTER_CLOSE + timedelta(days=30))

    assert "sell" not in kinds(evaluate(market, holding))


def test_the_cycle_runs_again_after_the_rebuy(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS))
    holding = hold(market, code)
    sell_then_wait(market, holding)
    svc.record_fill(market, holding.id, FillSide.REBUY, D(1), 40, filled_at=AFTER_CLOSE)

    assert "sell" in kinds(evaluate(market, holding))


# --- the daily trend filter (A-6) -------------------------------------------------------------


def test_no_sell_alert_in_a_daily_downtrend(
    market: Session, monkeypatch: pytest.MonkeyPatch, mock_adapter: MockAdapter
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS))
    falling = stock_where(mock_adapter, market, Scenario.DOWNTREND, AFTER_CLOSE, down=True)

    drafts = evaluate(market, hold(market, falling))

    assert "sell" not in kinds(drafts)


def test_a_sideways_market_is_not_a_downtrend_so_the_cycle_runs(
    market: Session, monkeypatch: pytest.MonkeyPatch, mock_adapter: MockAdapter
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS))
    sideways = stock_where(mock_adapter, market, Scenario.SIDEWAYS, AFTER_CLOSE, down=False)

    assert "sell" in kinds(evaluate(market, hold(market, sideways)))


def test_a_downtrend_replaces_the_rebuy_alert_with_a_reduce_position_warning(
    market: Session, monkeypatch: pytest.MonkeyPatch, mock_adapter: MockAdapter
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS))
    falling = stock_where(mock_adapter, market, Scenario.DOWNTREND, AFTER_CLOSE, down=True)
    holding = hold(market, falling)
    sell_then_wait(market, holding)

    drafts = evaluate(market, holding)

    assert kinds(drafts) == ["reduce_position"]
    assert drafts[0].evidence == {"daily_downtrend": True}


# --- rebuy alerts (A-4, A-5) ------------------------------------------------------------------


def waiting_holding(market: Session, code: str, sell_price: float | None = None) -> Holding:
    holding = hold(market, code)
    sell_then_wait(market, holding, sell_price)
    return holding


@pytest.mark.parametrize(
    ("true", "expected"),
    [
        (set(), False),
        ({"rsi_rebound"}, False),
        ({"rsi_rebound", "bollinger_support"}, True),
        ({"bollinger_support", "macd_golden_cross"}, True),
        (set(REBUY_FUNCTIONS), True),
    ],
)
def test_a_rebuy_alert_needs_two_of_the_three_reversal_signals(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str, true: set[str], expected: bool
) -> None:
    pin(monkeypatch, true=true)

    drafts = evaluate(market, waiting_holding(market, code))

    assert ("rebuy" in kinds(drafts)) is expected


def test_the_price_must_be_at_or_below_the_target(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS))
    price = last_close(market, code)
    holding = hold(market, code)
    # the target is 98.79% of the sale price: sold at today's price the target is below it
    sell_then_wait(market, holding, price)

    assert evaluate(market, holding) == []


def test_the_rebuy_alert_suggests_the_quantity_the_proceeds_buy(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true={"rsi_rebound", "macd_golden_cross"})
    price = last_close(market, code)
    holding = waiting_holding(market, code, price * 2)  # sold 30 shares at twice today's price
    sold_at = Decimal(str(round(price * 2, 2)))

    (draft,) = evaluate(market, holding)

    proceeds = sold_at * 30 - sold_at * 30 * D("0.00015") - sold_at * 30 * D("0.0018")
    expected = int(proceeds / (Decimal(str(price)) * D("1.00015")))
    assert draft.kind == "rebuy"
    assert draft.suggested_quantity == expected
    assert draft.evidence["quantity_increase"] == expected - 30
    assert draft.evidence["confirmations"] == 2
    assert draft.rebuy_target_price == pytest.approx(float(sold_at) * (1 - 0.0021 - 0.01), rel=1e-6)


def test_a_flow_exit_holds_the_rebuy_alert_back_as_a_warning(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS), flow="exit")

    drafts = evaluate(market, waiting_holding(market, code))

    assert kinds(drafts) == ["rebuy_held"]
    assert drafts[0].evidence["held_by_flow_filter"] is True
    assert drafts[0].suggested_quantity is not None  # what the rebuy would have been


def test_the_flow_filter_is_not_applied_without_flow_data(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS), flow="missing")

    drafts = evaluate(market, waiting_holding(market, code))

    assert kinds(drafts) == ["rebuy"]
    assert drafts[0].evidence["flow_unreflected"] is True


def test_an_expired_cycle_gets_no_rebuy_alerts(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS))
    holding = waiting_holding(market, code)
    svc.expire_due_cycles(market, AFTER_CLOSE + timedelta(days=30))

    assert evaluate(market, holding) == []


def test_a_plain_holding_gets_no_rebuy_alert(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS))

    assert "rebuy" not in kinds(evaluate(market, hold(market, code)))


# --- forced sale (A-13) -----------------------------------------------------------------------


def force_signal(
    monkeypatch: pytest.MonkeyPatch, *, stock: bool = False, index: bool = False
) -> None:
    monkeypatch.setattr(
        engine,
        "force_sell",
        lambda close, index_close, short=5, long=20: pd.DataFrame(
            {"stock": stock, "index": index, "force_sell": stock or index}, index=close.index
        ),
    )


@pytest.mark.parametrize(("stock", "index"), [(True, False), (False, True), (True, True)])
@pytest.mark.parametrize("waiting", [False, True])
def test_a_forced_sale_ignores_every_other_rule(
    market: Session,
    monkeypatch: pytest.MonkeyPatch,
    mock_adapter: MockAdapter,
    stock: bool,
    index: bool,
    waiting: bool,
) -> None:
    pin(monkeypatch)  # no sell candidates at all
    force_signal(monkeypatch, stock=stock, index=index)
    falling = stock_where(mock_adapter, market, Scenario.DOWNTREND, AFTER_CLOSE, down=True)
    holding = hold(market, falling, 100)
    if waiting:
        sell_then_wait(market, holding)  # a cycle is open: no other sale may be proposed

    draft = next(d for d in evaluate(market, holding) if d.kind == "force_sell")

    assert draft.suggested_quantity == holding.quantity  # everything that is left
    assert draft.evidence == {"stock_ma_breakdown": stock, "kospi_ma_breakdown": index}


def test_no_forced_sale_without_shares_to_sell(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch)
    force_signal(monkeypatch, index=True)
    holding = hold(market, code, 100)
    svc.record_fill(
        market, holding.id, FillSide.SELL, D(1), 100, filled_at=AFTER_CLOSE, forced=True
    )

    assert "force_sell" not in kinds(evaluate(market, holding))


def test_after_a_forced_sale_rebuy_alerts_wait_for_the_recovery(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS))
    holding = hold(market, code, 100)
    price = last_close(market, code)
    svc.record_fill(
        market,
        holding.id,
        FillSide.SELL,
        D(str(round(price * 2, 2))),
        100,
        filled_at=AFTER_CLOSE,
        forced=True,
    )

    monkeypatch.setattr(
        engine, "ma_recovered", lambda close, short=5, long=20: pd.Series(False, index=close.index)
    )
    assert "rebuy" not in kinds(evaluate(market, holding))

    monkeypatch.setattr(
        engine, "ma_recovered", lambda close, short=5, long=20: pd.Series(True, index=close.index)
    )
    assert "rebuy" in kinds(evaluate(market, holding))


def test_both_the_stock_and_kospi_must_have_recovered(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(REBUY_FUNCTIONS))
    holding = hold(market, code, 100)
    price = last_close(market, code)
    svc.record_fill(
        market,
        holding.id,
        FillSide.SELL,
        D(str(round(price * 2, 2))),
        100,
        filled_at=AFTER_CLOSE,
        forced=True,
    )
    calls: list[str] = []

    def recovered_only_for_the_stock(close: pd.Series, short: int = 5, long: int = 20) -> pd.Series:
        calls.append("call")
        return pd.Series(len(calls) == 1, index=close.index)  # stock first, then the index

    monkeypatch.setattr(engine, "ma_recovered", recovered_only_for_the_stock)

    assert "rebuy" not in kinds(evaluate(market, holding))


# --- ATR stop (A-8) ---------------------------------------------------------------------------


def test_the_atr_stop_warns_when_the_price_falls_below_it(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch)
    price = last_close(market, code)
    holding = hold(market, code, 100, avg_price=int(price * 3))  # bought far higher

    (draft,) = [d for d in evaluate(market, holding) if d.kind == "stop_loss"]

    assert draft.evidence["stop_price"] == pytest.approx(
        draft.evidence["avg_price"] - 2 * draft.evidence["daily_atr"]
    )
    assert draft.price is not None and draft.price < draft.evidence["stop_price"]
    assert draft.suggested_quantity == 100


def test_no_stop_warning_while_the_price_is_above_the_stop(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch)

    assert "stop_loss" not in kinds(evaluate(market, hold(market, code, 100, avg_price=1)))


# --- bars, confirmation, settings -------------------------------------------------------------


def test_signals_use_the_60_minute_bars_by_default(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})

    (draft,) = [d for d in evaluate(market, hold(market, code)) if d.kind == "sell"]

    assert draft.evidence["bar_length"] == "60m"
    assert draft.bar_time is not None
    assert draft.bar_time.astimezone(KST) == datetime(
        2026, 10, 16, 15, 0, tzinfo=KST
    )  # the 30-min last bar


@pytest.mark.parametrize(
    ("length", "now", "last_bar_start"),
    [
        (BarLength.M30, "2026-10-16 10:45", "2026-10-16 10:00"),  # 10:30 bar is still running
        (BarLength.M60, "2026-10-16 10:45", "2026-10-16 09:00"),  # the 10:00 hour is still running
        (BarLength.M60, "2026-10-16 11:00", "2026-10-16 10:00"),
        (BarLength.M60, "2026-10-16 15:30", "2026-10-16 15:00"),
        (BarLength.D1, "2026-10-16 10:45", "2026-10-15 00:00"),  # today's daily bar is not final
        (BarLength.D1, "2026-10-16 15:30", "2026-10-16 00:00"),
    ],
)
def test_only_confirmed_bars_are_evaluated(
    market: Session,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    length: BarLength,
    now: str,
    last_bar_start: str,
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})
    when = datetime.fromisoformat(now).replace(tzinfo=KST)

    (draft,) = [
        d for d in evaluate(market, hold(market, code), when, bar_length=length) if d.kind == "sell"
    ]

    assert draft.bar_time is not None
    assert draft.bar_time.replace(tzinfo=None) == datetime.fromisoformat(last_bar_start)
    assert draft.evidence["bar_length"] == length.value


def test_the_bar_length_comes_from_the_settings(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})
    save_signal_bar_length(market, BarLength.M30)

    (draft,) = [d for d in evaluate(market, hold(market, code)) if d.kind == "sell"]

    assert draft.evidence["bar_length"] == "30m"


def test_the_daily_filters_apply_whatever_the_signal_bar_length(
    market: Session, monkeypatch: pytest.MonkeyPatch, mock_adapter: MockAdapter
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS))
    falling = stock_where(mock_adapter, market, Scenario.DOWNTREND, AFTER_CLOSE, down=True)
    holding = hold(market, falling)

    for length in BarLength:
        assert "sell" not in kinds(evaluate(market, holding, bar_length=length))


def test_evaluating_the_same_bar_twice_gives_the_same_alerts_and_keys(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})
    holding = hold(market, code)

    first = evaluate(market, holding)
    second = evaluate(market, holding)

    assert [d.dedupe_key for d in first] == [d.dedupe_key for d in second]
    assert first[0].dedupe_key.startswith("sell:")


def test_evaluate_all_covers_every_holding_and_survives_one_failure(
    market: Session,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    mock_adapter: MockAdapter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS))
    good = hold(market, code)
    other = stock_where(mock_adapter, market, Scenario.SIDEWAYS, AFTER_CLOSE, down=False)
    broken = hold(market, other)
    real = engine.evaluate_holding

    def flaky(session: Session, holding: Holding, **kwargs: Any) -> list[engine.AlertDraft]:
        if holding.id == broken.id:
            raise RuntimeError("boom")
        return real(session, holding, **kwargs)

    monkeypatch.setattr(engine, "evaluate_holding", flaky)

    drafts = engine.evaluate_all(market, now=AFTER_CLOSE)

    assert {d.holding_id for d in drafts} == {good.id}
    assert "alert evaluation failed" in caplog.text


# --- expiry alerts (A-7) ----------------------------------------------------------------------


def test_a_cycle_that_runs_out_produces_an_expiry_alert_with_the_two_choices(
    market: Session, code: str
) -> None:
    holding = hold(market, code)
    sell_then_wait(market, holding)
    cycle = svc.open_cycle(market, holding.id)
    assert cycle is not None and cycle.expires_at is not None

    assert engine.process_expirations(market, cycle.expires_at - timedelta(minutes=1)) == []
    (draft,) = engine.process_expirations(market, cycle.expires_at)

    assert draft.kind == "expired"
    assert draft.evidence == {"cycle_id": cycle.id, "choices": ["retry", "abandon"]}
    assert draft.rebuy_target_price == pytest.approx(float(cycle.rebuy_target_price))
    assert holding.state.value == "expired"
    assert engine.process_expirations(market, cycle.expires_at + timedelta(days=1)) == []  # once


@pytest.mark.parametrize(
    ("now", "length", "alerts"),
    [
        ("2026-10-16 15:30", BarLength.M60, True),  # the last bar closed this minute
        ("2026-10-16 16:00", BarLength.M60, True),  # half an hour ago
        ("2026-10-16 10:45", BarLength.M60, True),  # 45 minutes: the oldest still accepted
        ("2026-10-16 16:30", BarLength.M30, False),  # an hour after the last bar
        ("2026-10-19 09:30", BarLength.M30, False),  # Monday morning, Friday's bars are stale
        ("2026-10-19 09:30", BarLength.M60, False),
    ],
)
def test_only_a_bar_that_has_just_closed_is_alerted(
    market: Session,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    now: str,
    length: BarLength,
    alerts: bool,
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})
    when = datetime.fromisoformat(now).replace(tzinfo=KST)

    drafts = evaluate(market, hold(market, code), when, bar_length=length)

    assert ("sell" in kinds(drafts)) is alerts


def test_signal_bar_drafts_carry_the_bar_length_and_close_time(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true={"rsi_overbought_exit", "macd_weakening"})

    for length, end in [
        (BarLength.M30, "2026-10-16 15:30"),
        (BarLength.M60, "2026-10-16 15:30"),  # the last 60-minute bar is only 30 minutes long
        (BarLength.D1, "2026-10-16 15:30"),
    ]:
        (draft,) = [
            d for d in evaluate(market, hold(market, code), bar_length=length) if d.kind == "sell"
        ]

        assert draft.bar_length is length
        assert draft.bar_end == datetime.fromisoformat(end).replace(tzinfo=KST)


def test_the_daily_scope_only_looks_for_the_forced_sale(
    market: Session, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    pin(monkeypatch, true=set(SELL_FUNCTIONS))
    monkeypatch.setattr(engine, "force_sell", force_sell_frame(stock=True))
    holding = hold(market, code, 100, avg_price=10_000_000)  # a stop breach would also be due

    drafts = evaluate(market, holding, scope="daily")

    assert kinds(drafts) == ["force_sell"]
    assert drafts[0].bar_length is None and drafts[0].bar_end is None
