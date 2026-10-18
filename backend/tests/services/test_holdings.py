"""The holding state machine (PRD 5장 상태 흐름도) as tables, plus the A-9 numbers."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.market import KST
from app.db.enums import CycleState, FillSide, HoldingState, Market
from app.db.models import Alert, Cycle, Fill, Holding, Instrument
from app.services import holdings as svc

SOLD_AT = datetime(2026, 10, 16, 10, 30, tzinfo=KST)  # a Friday
EXPIRY = datetime(2026, 10, 23, 15, 30, tzinfo=KST)  # five trading days later
SELL, REBUY = FillSide.SELL, FillSide.REBUY
D = Decimal


@dataclass
class Scene:
    session: Session
    holding: Holding

    def sell(self, quantity: int = 30, price: int = 100_000, **kwargs: object) -> svc.FillResult:
        return svc.record_fill(
            self.session,
            self.holding.id,
            SELL,
            D(price),
            quantity,
            filled_at=SOLD_AT,
            **kwargs,  # type: ignore[arg-type]
        )

    def rebuy(self, quantity: int = 31, price: int = 95_000) -> svc.FillResult:
        return svc.record_fill(
            self.session, self.holding.id, REBUY, D(price), quantity, filled_at=SOLD_AT
        )

    def forced(self, quantity: int = 100, price: int = 100_000) -> svc.FillResult:
        return svc.record_fill(
            self.session, self.holding.id, SELL, D(price), quantity, filled_at=SOLD_AT, forced=True
        )

    def expire(self, days_later: int = 0) -> list[Cycle]:
        return svc.expire_due_cycles(self.session, EXPIRY + timedelta(days=days_later, minutes=1))

    def retry(self) -> Cycle:
        return svc.retry_cycle(self.session, self.holding.id, self.latest_cycle().id, EXPIRY)

    def abandon(self) -> Cycle:
        return svc.abandon_cycle(self.session, self.holding.id, self.latest_cycle().id)

    def latest_cycle(self) -> Cycle:
        cycle = self.session.scalars(
            select(Cycle).where(Cycle.holding_id == self.holding.id).order_by(Cycle.id.desc())
        ).first()
        assert cycle is not None
        return cycle


@pytest.fixture
def scene(session: Session) -> Scene:
    session.add(Instrument(code="900010", name="모의", market=Market.KOSPI))
    session.flush()
    holding = svc.register(session, "900010", 100, D(90_000))
    return Scene(session, holding)


# --- the state table --------------------------------------------------------------------------

# (name, steps, holding state, latest cycle state or None, quantity held)
TRANSITIONS = [
    ("registered", [], HoldingState.HOLDING, None, 100),
    ("sold", ["sell"], HoldingState.REBUY_WAIT, CycleState.REBUY_WAIT, 70),
    ("rebought", ["sell", "rebuy"], HoldingState.HOLDING, CycleState.REBUY_DONE, 101),
    ("expired", ["sell", "expire"], HoldingState.EXPIRED, CycleState.EXPIRED, 70),
    ("rebought after expiry", ["sell", "expire", "rebuy"], HoldingState.HOLDING, CycleState.REBUY_DONE, 101),
    ("retried after expiry", ["sell", "expire", "retry"], HoldingState.REBUY_WAIT, CycleState.REBUY_WAIT, 70),
    ("abandoned while waiting", ["sell", "abandon"], HoldingState.HOLDING, CycleState.ABANDONED, 70),
    ("abandoned after expiry", ["sell", "expire", "abandon"], HoldingState.HOLDING, CycleState.ABANDONED, 70),
    ("expired twice", ["sell", "expire", "retry", "expire_after_retry"], HoldingState.EXPIRED, CycleState.EXPIRED, 70),
    ("forced sale while waiting", ["sell", "forced70"], HoldingState.HOLDING, CycleState.FORCE_CLOSED, 0),
    ("forced sale while expired", ["sell", "expire", "forced70"], HoldingState.HOLDING, CycleState.FORCE_CLOSED, 0),
    ("forced sale from holding", ["forced"], HoldingState.HOLDING, CycleState.FORCE_CLOSED, 0),
    ("re-entry after a forced sale", ["forced", "rebuy"], HoldingState.HOLDING, CycleState.FORCE_CLOSED, 31),
    ("second cycle after a rebuy", ["sell", "rebuy", "sell33"], HoldingState.REBUY_WAIT, CycleState.REBUY_WAIT, 68),
    ("second cycle after abandoning", ["sell", "abandon", "sell20"], HoldingState.REBUY_WAIT, CycleState.REBUY_WAIT, 50),
]  # fmt: skip


def play(scene: Scene, steps: list[str]) -> None:
    for step in steps:
        match step:
            case "sell":
                scene.sell()
            case "rebuy":
                scene.rebuy()
            case "expire":
                assert scene.expire(), "the cycle should have expired"
            case "expire_after_retry":  # the retry window closes a week later
                assert scene.expire(days_later=14), "the retried cycle should have expired"
            case "retry":
                scene.retry()
            case "abandon":
                scene.abandon()
            case "forced":
                scene.forced()
            case "forced70":
                scene.forced(70)
            case _ if step.startswith("sell"):
                scene.sell(int(step.removeprefix("sell")))
            case _:
                raise AssertionError(step)


@pytest.mark.parametrize(
    ("name", "steps", "holding_state", "cycle_state", "quantity"),
    TRANSITIONS,
    ids=[t[0] for t in TRANSITIONS],
)
def test_state_transitions(
    scene: Scene,
    name: str,
    steps: list[str],
    holding_state: HoldingState,
    cycle_state: CycleState | None,
    quantity: int,
) -> None:
    play(scene, steps)

    assert scene.holding.state is holding_state
    assert scene.holding.quantity == quantity
    if cycle_state is None:
        assert scene.session.scalar(select(Cycle).limit(1)) is None
    else:
        assert scene.latest_cycle().state is cycle_state


# Actions that are not allowed in a state: (name, steps, action, error)
ILLEGAL = [
    ("a second sale while waiting", ["sell"], "sell", svc.InvalidTransitionError),
    ("a sale while expired", ["sell", "expire"], "sell", svc.InvalidTransitionError),
    ("a rebuy with nothing sold", [], "rebuy", svc.InvalidTransitionError),
    ("a rebuy after a completed cycle", ["sell", "rebuy"], "rebuy", svc.InvalidTransitionError),
    ("a rebuy after abandoning", ["sell", "abandon"], "rebuy", svc.InvalidTransitionError),
    ("a second rebuy after the re-entry", ["forced", "rebuy"], "rebuy", svc.InvalidTransitionError),
    ("retrying a cycle that is still waiting", ["sell"], "retry", svc.InvalidTransitionError),
    ("retrying a completed cycle", ["sell", "rebuy"], "retry", svc.InvalidTransitionError),
    ("abandoning a completed cycle", ["sell", "rebuy"], "abandon", svc.InvalidTransitionError),
    ("abandoning twice", ["sell", "abandon"], "abandon", svc.InvalidTransitionError),
    ("selling more than is held", [], "sell101", svc.InvalidFillError),
    ("a forced sale of more than is held", ["sell"], "forced71", svc.InvalidFillError),
    ("a zero-share sale", [], "sell0", svc.InvalidFillError),
]  # fmt: skip


@pytest.mark.parametrize(("name", "steps", "action", "error"), ILLEGAL, ids=[i[0] for i in ILLEGAL])
def test_illegal_actions_are_refused_and_change_nothing(
    scene: Scene, name: str, steps: list[str], action: str, error: type[Exception]
) -> None:
    play(scene, steps)
    before = (
        scene.holding.state,
        scene.holding.quantity,
        scene.session.scalar(select(Cycle.id).order_by(Cycle.id.desc())),
    )

    with pytest.raises(error):
        if action.startswith("forced"):
            scene.forced(int(action.removeprefix("forced")))
        elif action.startswith("sell"):
            scene.sell(int(action.removeprefix("sell")) if action != "sell" else 30)
        elif action == "rebuy":
            scene.rebuy()
        elif action == "retry":
            scene.retry()
        else:
            scene.abandon()

    after = (
        scene.holding.state,
        scene.holding.quantity,
        scene.session.scalar(select(Cycle.id).order_by(Cycle.id.desc())),
    )
    assert after == before


def test_a_signal_alone_never_changes_the_state(scene: Scene) -> None:
    # Only fills, expiry, retry and abandon move a holding: nothing else is in the service API.
    assert not [name for name in dir(svc) if name.startswith("apply_signal")]
    assert scene.holding.state is HoldingState.HOLDING


def test_an_unknown_stock_or_holding_is_an_error(scene: Scene) -> None:
    with pytest.raises(svc.InvalidFillError):
        svc.register(scene.session, "NOPE", 10, D(1))
    with pytest.raises(svc.HoldingNotFoundError):
        svc.record_fill(scene.session, 9999, SELL, D(1), 1)
    with pytest.raises(svc.HoldingNotFoundError):
        svc.retry_cycle(scene.session, scene.holding.id, 9999)


def test_a_rebuy_cannot_be_marked_as_a_forced_sale(scene: Scene) -> None:
    scene.sell()

    with pytest.raises(svc.InvalidFillError):
        svc.record_fill(scene.session, scene.holding.id, REBUY, D(95_000), 31, forced=True)


# --- what a sale opens ------------------------------------------------------------------------


def test_a_sale_opens_a_cycle_with_the_target_price_and_an_expiry(scene: Scene) -> None:
    result = scene.sell(30, 100_000)

    cycle = result.cycle
    assert (cycle.sell_price, cycle.sell_quantity) == (D(100_000), 30)
    assert cycle.rebuy_target_price == D("98790")  # 100,000 x (1 - 0.21% - 1%)
    assert cycle.expires_at is not None
    assert cycle.expires_at.astimezone(KST) == EXPIRY
    assert result.fill.cycle_id == cycle.id


def test_the_start_quantity_is_recorded_at_registration_and_never_changes(scene: Scene) -> None:
    assert scene.holding.start_quantity == 100

    play(scene, ["sell", "rebuy"])

    assert (scene.holding.start_quantity, scene.holding.quantity) == (100, 101)


def test_the_average_price_is_unchanged_by_a_sale_and_blended_by_a_rebuy(scene: Scene) -> None:
    scene.sell()
    assert scene.holding.avg_price == D(90_000)

    scene.rebuy()

    # (70 x 90,000 + 31 x 95,000) / 101
    assert scene.holding.avg_price == pytest.approx(D(9_245_000) / 101)


def test_fees_and_tax_default_to_the_configured_rates(scene: Scene) -> None:
    fill = scene.sell(30, 100_000).fill

    assert (fill.fee, fill.tax) == (D("450"), D("5400"))
    assert scene.rebuy(31, 95_000).fill.fee == D("441.75")  # 2,945,000 x 0.015%


def test_fees_and_tax_can_be_entered_by_hand(scene: Scene) -> None:
    fill = scene.sell(30, 100_000, fee=D(1000), tax=D(2000)).fill

    assert (fill.fee, fill.tax) == (D(1000), D(2000))


# --- expiry (A-7) -----------------------------------------------------------------------------


def test_a_cycle_does_not_expire_before_its_window_closes(scene: Scene) -> None:
    scene.sell()

    assert svc.expire_due_cycles(scene.session, EXPIRY - timedelta(minutes=1)) == []
    assert scene.holding.state is HoldingState.REBUY_WAIT
    assert len(svc.expire_due_cycles(scene.session, EXPIRY)) == 1  # at the close itself


def test_a_cycle_that_already_had_a_rebuy_alert_is_not_expired(scene: Scene) -> None:
    scene.sell()
    cycle = scene.latest_cycle()
    scene.session.add(
        Alert(kind="rebuy", code="900010", occurred_at=datetime.now(UTC) + timedelta(hours=1))
    )
    scene.session.flush()

    assert svc.expire_due_cycles(scene.session, EXPIRY + timedelta(days=30)) == []
    assert cycle.state is CycleState.REBUY_WAIT


def test_a_retry_opens_a_fresh_window(scene: Scene) -> None:
    play(scene, ["sell", "expire"])
    retry_time = datetime(2026, 10, 26, 10, 0, tzinfo=KST)  # a Monday

    cycle = svc.retry_cycle(scene.session, scene.holding.id, scene.latest_cycle().id, retry_time)

    assert cycle.expires_at is not None
    assert cycle.expires_at.astimezone(KST) == datetime(2026, 11, 2, 15, 30, tzinfo=KST)


def test_expiry_leaves_other_holdings_alone(scene: Scene) -> None:
    other = svc.register(scene.session, "900010", 50, D(80_000))
    scene.sell()

    scene.expire()

    assert other.state is HoldingState.HOLDING


# --- results (A-9) ----------------------------------------------------------------------------


def test_cycle_result_by_hand(scene: Scene) -> None:
    # sell 30 @ 100,000: fee 450, tax 5,400 -> net 2,994,150
    # rebuy 31 @ 95,000: 2,945,000 + fee 441.75 = 2,945,441.75   -> cash left 48,708.25
    play(scene, ["sell", "rebuy"])

    views, totals = svc.cycle_views(scene.session, scene.holding.id)

    (view,) = views
    assert view.quantity_increase == 1
    assert view.net_cash == D("48708.25")
    assert (view.sell_fee, view.sell_tax, view.rebuy_fee) == (D("450"), D("5400"), D("441.75"))
    assert (totals.cycles, totals.completed, totals.successful) == (1, 1, 1)
    assert (totals.cumulative_increase, totals.start_quantity, totals.current_quantity) == (
        1,
        100,
        101,
    )


def test_totals_add_up_over_cycles_and_count_losses_and_giving_up(scene: Scene) -> None:
    scene.sell(30, 100_000)
    scene.rebuy(31, 95_000)  # +1
    scene.sell(33, 100_000)
    scene.rebuy(31, 105_000)  # -2: bought higher
    scene.sell(20, 100_000)
    scene.abandon()  # 20 shares never bought back
    scene.sell(10, 100_000)  # still waiting

    views, totals = svc.cycle_views(scene.session, scene.holding.id)

    assert [v.quantity_increase for v in views] == [1, -2, None, None]
    assert totals.cycles == 4
    assert (totals.completed, totals.successful) == (2, 1)
    assert totals.cumulative_increase == -1
    assert totals.unrecovered_quantity == 20
    assert totals.pending_quantity == 10


def test_a_cycle_without_a_rebuy_has_no_increase_or_cash_result(scene: Scene) -> None:
    scene.sell()

    (view,), _ = svc.cycle_views(scene.session, scene.holding.id)

    assert (view.quantity_increase, view.net_cash, view.rebuy_fee) == (None, None, None)


def test_the_fees_entered_by_hand_flow_into_the_cash_result(scene: Scene) -> None:
    scene.sell(30, 100_000, fee=D(1000), tax=D(2000))
    svc.record_fill(
        scene.session, scene.holding.id, REBUY, D(95_000), 31, filled_at=SOLD_AT, fee=D(500)
    )

    (view,), _ = svc.cycle_views(scene.session, scene.holding.id)

    # 3,000,000 - 1,000 - 2,000 = 2,997,000 in; 2,945,000 + 500 = 2,945,500 out
    assert view.net_cash == D(51_500)


def test_a_forced_sale_cycle_counts_as_unrecovered_until_the_stock_is_bought_back(
    scene: Scene,
) -> None:
    scene.forced(100, 100_000)

    (view,), totals = svc.cycle_views(scene.session, scene.holding.id)
    assert view.quantity_increase is None
    assert totals.unrecovered_quantity == 100

    scene.rebuy(101, 95_000)
    (view,), totals = svc.cycle_views(scene.session, scene.holding.id)
    assert view.quantity_increase == 1
    assert totals.unrecovered_quantity == 0
    assert view.cycle.state is CycleState.FORCE_CLOSED


def test_a_forced_sale_during_a_cycle_keeps_the_original_sale_as_the_cycles_sale(
    scene: Scene,
) -> None:
    scene.sell(30, 100_000)
    scene.forced(70, 90_000)

    (view,), totals = svc.cycle_views(scene.session, scene.holding.id)

    assert view.cycle.sell_quantity == 30
    assert view.sell_fee == D("450")  # only the cycle's own sale is counted
    assert totals.unrecovered_quantity == 30
    assert scene.holding.quantity == 0
    forced = scene.session.scalars(select(Fill).where(Fill.forced)).all()
    assert [f.quantity for f in forced] == [70]


# --- editing ----------------------------------------------------------------------------------


def test_a_registration_mistake_can_be_corrected_and_resets_the_start_quantity(
    scene: Scene,
) -> None:
    holding = svc.correct(scene.session, scene.holding.id, 120, D(88_000))

    assert (holding.quantity, holding.start_quantity, holding.avg_price) == (120, 120, D(88_000))


def test_a_holding_with_history_keeps_its_start_quantity_when_corrected(scene: Scene) -> None:
    play(scene, ["sell", "rebuy"])

    holding = svc.correct(scene.session, scene.holding.id, 99, D(88_000))

    assert (holding.quantity, holding.start_quantity) == (99, 100)


def test_a_holding_with_an_open_cycle_cannot_be_edited(scene: Scene) -> None:
    scene.sell()

    with pytest.raises(svc.InvalidTransitionError):
        svc.correct(scene.session, scene.holding.id, 50, D(1))


def test_removing_a_holding_removes_its_cycles_and_fills(scene: Scene) -> None:
    play(scene, ["sell", "rebuy"])

    svc.remove(scene.session, scene.holding.id)

    assert scene.session.scalar(select(Cycle.id)) is None
    assert scene.session.scalar(select(Fill.id)) is None
    assert scene.session.get(Holding, scene.holding.id) is None
