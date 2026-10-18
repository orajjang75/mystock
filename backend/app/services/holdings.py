"""Holdings and their sell/rebuy cycles (PRD 5장 A-1, A-3, A-5, A-7, A-9, A-13).

The app never trades. A holding changes state only when the user records a fill, or when time
runs out (A-7), or when the user abandons / retries an expired cycle. Signals alone never
change anything.

States (``Holding.state`` mirrors the open cycle):

    HOLDING  --sell fill-->  REBUY_WAIT   (opens a cycle; one sale per cycle)
    REBUY_WAIT --rebuy fill--> HOLDING    (cycle REBUY_DONE: 수량 증가분 확정)
    REBUY_WAIT --5 trading days--> EXPIRED
    EXPIRED --rebuy fill--> HOLDING       (cycle REBUY_DONE)
    EXPIRED --retry--> REBUY_WAIT         (a fresh waiting window)
    REBUY_WAIT | EXPIRED --abandon--> HOLDING   (cycle ABANDONED)
    any --forced sell fill--> HOLDING     (cycle FORCE_CLOSED, A-13)
    HOLDING --rebuy fill--> HOLDING       (only to re-enter after a FORCE_CLOSED cycle)

The functions flush but do not commit.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.market import KST, rebuy_expiry
from app.db.enums import CycleState, FillSide, HoldingState
from app.db.models import Alert, Cycle, Fill, Holding, Instrument
from app.engine.alert_signals import rebuy_target_price
from app.engine.params import RebuyParams
from app.services import quantities as q
from app.services.settings import load_signal_params

OPEN_STATES = (CycleState.REBUY_WAIT, CycleState.EXPIRED)


class HoldingError(Exception):
    """Base class of the errors below."""


class HoldingNotFoundError(HoldingError, LookupError):
    pass


class InvalidFillError(HoldingError, ValueError):
    """The values are impossible (e.g. selling more shares than are held)."""


class InvalidTransitionError(HoldingError):
    """The action is not allowed in the holding's current state."""


@dataclass(frozen=True, slots=True)
class FillResult:
    fill: Fill
    cycle: Cycle
    holding: Holding


# --- holdings -----------------------------------------------------------------------------


def get_holding(session: Session, holding_id: int) -> Holding:
    holding = session.get(Holding, holding_id)
    if holding is None:
        raise HoldingNotFoundError(holding_id)
    return holding


def register(session: Session, code: str, quantity: int, avg_price: Decimal) -> Holding:
    """A-1: register a position; the quantity is also recorded as the 시작 수량."""
    if session.get(Instrument, code) is None:
        raise InvalidFillError(f"Unknown stock {code}")
    if quantity <= 0 or avg_price <= 0:
        raise InvalidFillError("Quantity and average price must be positive")
    holding = Holding(
        code=code,
        quantity=quantity,
        avg_price=avg_price,
        start_quantity=quantity,
        state=HoldingState.HOLDING,
    )
    session.add(holding)
    session.flush()
    return holding


def correct(session: Session, holding_id: int, quantity: int, avg_price: Decimal) -> Holding:
    """Fix a registration mistake. Only while no cycle is open; before any cycle it resets
    the 시작 수량 as well."""
    holding = get_holding(session, holding_id)
    if holding.state is not HoldingState.HOLDING:
        raise InvalidTransitionError("A holding with an open cycle cannot be edited")
    if quantity < 0 or avg_price <= 0:
        raise InvalidFillError("Invalid quantity or average price")
    has_cycles = session.scalar(
        select(func.count()).select_from(Cycle).where(Cycle.holding_id == holding_id)
    )
    holding.quantity, holding.avg_price = quantity, avg_price
    if not has_cycles:
        holding.start_quantity = quantity
    session.flush()
    return holding


def remove(session: Session, holding_id: int) -> None:
    """Delete a holding with its cycles and fills."""
    holding = get_holding(session, holding_id)
    session.execute(update(Alert).where(Alert.holding_id == holding_id).values(holding_id=None))
    session.execute(delete(Fill).where(Fill.holding_id == holding_id))
    session.execute(delete(Cycle).where(Cycle.holding_id == holding_id))
    session.delete(holding)
    session.flush()


def open_cycle(session: Session, holding_id: int) -> Cycle | None:
    """The cycle that is waiting for a rebuy (REBUY_WAIT or EXPIRED), if any."""
    return session.scalars(
        select(Cycle)
        .where(Cycle.holding_id == holding_id, Cycle.state.in_(OPEN_STATES))
        .order_by(Cycle.id.desc())
    ).first()


def reentry_cycle(session: Session, holding_id: int) -> Cycle | None:
    """The latest cycle ended by a forced sale and not yet re-entered, if it is the latest."""
    latest = session.scalars(
        select(Cycle).where(Cycle.holding_id == holding_id).order_by(Cycle.id.desc())
    ).first()
    if latest and latest.state is CycleState.FORCE_CLOSED and latest.rebuy_quantity is None:
        return latest
    return None


# --- fills ----------------------------------------------------------------------------------


def record_fill(
    session: Session,
    holding_id: int,
    side: FillSide,
    price: Decimal,
    quantity: int,
    *,
    filled_at: datetime | None = None,
    fee: Decimal | None = None,
    tax: Decimal | None = None,
    forced: bool = False,
    params: RebuyParams | None = None,
) -> FillResult:
    """Record a fill the user made at the broker and move the holding's state accordingly.

    ``fee`` and ``tax`` default to the configured rates. ``forced`` marks the A-13 forced sale,
    which is allowed in any state and ends the cycle.
    """
    if price <= 0 or quantity <= 0:
        raise InvalidFillError("Price and quantity must be positive")
    holding = get_holding(session, holding_id)
    params = params or load_signal_params(session).rebuy
    filled_at = (filled_at or datetime.now(KST)).astimezone(KST)
    fee = q.trade_fee(price, quantity, params) if fee is None else fee
    if side is FillSide.SELL:
        tax = q.sell_tax(price, quantity, params) if tax is None else tax
        if forced:
            cycle = _forced_sell(session, holding, price, quantity, params)
        else:
            cycle = _sell(session, holding, price, quantity, filled_at, params)
    else:
        tax = Decimal(0) if tax is None else tax
        if forced:
            raise InvalidFillError("A rebuy cannot be a forced sale")
        cycle = _rebuy(session, holding, price, quantity)
    fill = Fill(
        holding_id=holding.id,
        cycle_id=cycle.id,
        side=side,
        price=price,
        quantity=quantity,
        filled_at=filled_at,
        fee=fee,
        tax=tax,
        forced=forced,
    )
    session.add(fill)
    session.flush()
    return FillResult(fill, cycle, holding)


def _sell(
    session: Session,
    holding: Holding,
    price: Decimal,
    quantity: int,
    filled_at: datetime,
    params: RebuyParams,
) -> Cycle:
    if holding.state is not HoldingState.HOLDING or open_cycle(session, holding.id):
        raise InvalidTransitionError("One sale per cycle: the holding is waiting to rebuy")
    if quantity > holding.quantity:
        raise InvalidFillError(f"Cannot sell {quantity}: only {holding.quantity} held")
    cycle = Cycle(
        holding_id=holding.id,
        sell_price=price,
        sell_quantity=quantity,
        rebuy_target_price=_target(price, params),
        state=CycleState.REBUY_WAIT,
        expires_at=rebuy_expiry(filled_at, params.expiry_trading_days),
    )
    session.add(cycle)
    holding.quantity -= quantity
    holding.state = HoldingState.REBUY_WAIT
    session.flush()
    return cycle


def _forced_sell(
    session: Session, holding: Holding, price: Decimal, quantity: int, params: RebuyParams
) -> Cycle:
    if quantity > holding.quantity:
        raise InvalidFillError(f"Cannot sell {quantity}: only {holding.quantity} held")
    cycle = open_cycle(session, holding.id)
    if cycle is None:  # a forced sale from the plain holding state opens and closes a cycle
        cycle = Cycle(
            holding_id=holding.id,
            sell_price=price,
            sell_quantity=quantity,
            rebuy_target_price=_target(price, params),
        )
        session.add(cycle)
    cycle.state = CycleState.FORCE_CLOSED
    holding.quantity -= quantity
    holding.state = HoldingState.HOLDING
    session.flush()
    return cycle


def _rebuy(session: Session, holding: Holding, price: Decimal, quantity: int) -> Cycle:
    cycle = open_cycle(session, holding.id)
    reentry = cycle is None
    if cycle is None:
        cycle = reentry_cycle(session, holding.id)
    if cycle is None:
        raise InvalidTransitionError("There is no sale to rebuy: no open cycle")
    cycle.rebuy_price, cycle.rebuy_quantity = price, quantity
    if not reentry:
        cycle.state = CycleState.REBUY_DONE
    total = holding.quantity + quantity
    holding.avg_price = (holding.avg_price * holding.quantity + price * quantity) / total
    holding.quantity = total
    holding.state = HoldingState.HOLDING
    session.flush()
    return cycle


def _target(sell_price: Decimal, params: RebuyParams) -> Decimal:
    """A-4 재매수 목표가, from the engine formula (price x (1 - cost - gain))."""
    target = rebuy_target_price(float(sell_price), params.cost, params.target_gain)
    return Decimal(str(round(target, 4)))


# --- expiry, retry, abandon -----------------------------------------------------------------


def expire_due_cycles(session: Session, now: datetime) -> list[Cycle]:
    """A-7: cycles still waiting after their window become EXPIRED (a 만료 알림 is due).

    A cycle in which a rebuy alert already went out is left alone: the user was told.
    """
    due = session.scalars(
        select(Cycle).where(Cycle.state == CycleState.REBUY_WAIT, Cycle.expires_at <= now)
    ).all()
    expired = []
    for cycle in due:
        holding = get_holding(session, cycle.holding_id)
        alerted = session.scalar(
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.kind == "rebuy",
                Alert.code == holding.code,
                Alert.occurred_at >= cycle.created_at,
            )
        )
        if alerted:
            continue
        cycle.state = CycleState.EXPIRED
        holding.state = HoldingState.EXPIRED
        expired.append(cycle)
    session.flush()
    return expired


def _open_cycle_of(session: Session, holding_id: int, cycle_id: int) -> tuple[Holding, Cycle]:
    holding = get_holding(session, holding_id)
    cycle = session.get(Cycle, cycle_id)
    if cycle is None or cycle.holding_id != holding_id:
        raise HoldingNotFoundError(f"cycle {cycle_id}")
    return holding, cycle


def retry_cycle(
    session: Session, holding_id: int, cycle_id: int, now: datetime | None = None
) -> Cycle:
    """'재매수 시도': an expired cycle waits again for a fresh window."""
    holding, cycle = _open_cycle_of(session, holding_id, cycle_id)
    if cycle.state is not CycleState.EXPIRED:
        raise InvalidTransitionError("Only an expired cycle can be retried")
    params = load_signal_params(session).rebuy
    cycle.state = CycleState.REBUY_WAIT
    cycle.expires_at = rebuy_expiry((now or datetime.now(KST)), params.expiry_trading_days)
    holding.state = HoldingState.REBUY_WAIT
    session.flush()
    return cycle


def abandon_cycle(session: Session, holding_id: int, cycle_id: int) -> Cycle:
    """'사이클 포기': give up the rebuy; the holding goes back to plain holding."""
    holding, cycle = _open_cycle_of(session, holding_id, cycle_id)
    if cycle.state not in OPEN_STATES:
        raise InvalidTransitionError("Only a waiting or expired cycle can be abandoned")
    cycle.state = CycleState.ABANDONED
    holding.state = HoldingState.HOLDING
    session.flush()
    return cycle


# --- results (A-9) --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CycleView:
    cycle: Cycle
    sell_fee: Decimal
    sell_tax: Decimal
    rebuy_fee: Decimal | None
    net_cash: Decimal | None  # sale proceeds minus rebuy cost, after fees and tax
    quantity_increase: int | None  # None until shares were bought back
    sold_at: datetime | None = None  # when the user filled the sale / the rebuy (chart markers)
    rebought_at: datetime | None = None
    forced: bool = False  # closed by the A-13 forced sale


@dataclass(frozen=True, slots=True)
class Totals:
    cycles: int
    completed: int  # cycles with a rebuy
    successful: int  # completed cycles that gained shares
    cumulative_increase: int
    unrecovered_quantity: int  # sold and never bought back (abandoned, forced)
    pending_quantity: int  # sold, still waiting to rebuy
    start_quantity: int
    current_quantity: int


def cycle_views(session: Session, holding_id: int) -> tuple[list[CycleView], Totals]:
    """Every cycle of a holding, oldest first, with fees, cash result and 수량 증가분."""
    holding = get_holding(session, holding_id)
    cycles = session.scalars(
        select(Cycle).where(Cycle.holding_id == holding_id).order_by(Cycle.id)
    ).all()
    fills: dict[int, list[Fill]] = {}
    for fill in session.scalars(select(Fill).where(Fill.holding_id == holding_id)):
        if fill.cycle_id is not None:
            fills.setdefault(fill.cycle_id, []).append(fill)

    views = [_view(cycle, fills.get(cycle.id, [])) for cycle in cycles]
    completed = [v for v in views if v.quantity_increase is not None]
    totals = Totals(
        cycles=len(views),
        completed=len(completed),
        successful=sum(1 for v in completed if (v.quantity_increase or 0) > 0),
        cumulative_increase=sum(v.quantity_increase or 0 for v in completed),
        unrecovered_quantity=sum(
            v.cycle.sell_quantity
            for v in views
            if v.cycle.rebuy_quantity is None
            and v.cycle.state in (CycleState.ABANDONED, CycleState.FORCE_CLOSED)
        ),
        pending_quantity=sum(v.cycle.sell_quantity for v in views if v.cycle.state in OPEN_STATES),
        start_quantity=holding.start_quantity,
        current_quantity=holding.quantity,
    )
    return views, totals


def _view(cycle: Cycle, fills: list[Fill]) -> CycleView:
    sells = [f for f in fills if f.side is FillSide.SELL]
    cycle_sells = [f for f in sells if not f.forced] or sells  # a forced-only cycle sold by force
    rebuys = [f for f in fills if f.side is FillSide.REBUY]
    sell_fee = sum((f.fee for f in cycle_sells), Decimal(0))
    sell_tax = sum((f.tax for f in cycle_sells), Decimal(0))
    sold_at = min((f.filled_at for f in cycle_sells), default=None)
    rebought_at = min((f.filled_at for f in rebuys), default=None)
    forced = any(f.forced for f in sells)
    if cycle.rebuy_quantity is None or cycle.rebuy_price is None:
        return CycleView(cycle, sell_fee, sell_tax, None, None, None, sold_at, rebought_at, forced)
    rebuy_fee = sum((f.fee for f in rebuys), Decimal(0))
    proceeds = sum(
        (q.net_sell_proceeds(f.price, f.quantity, f.fee, f.tax) for f in cycle_sells), Decimal(0)
    )
    cost = sum((f.price * f.quantity + f.fee for f in rebuys), Decimal(0))
    return CycleView(
        cycle,
        sell_fee,
        sell_tax,
        rebuy_fee,
        proceeds - cost,
        q.quantity_increase(cycle.sell_quantity, cycle.rebuy_quantity),
        sold_at,
        rebought_at,
        forced,
    )
