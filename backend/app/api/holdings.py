from datetime import datetime
from decimal import Decimal

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import DbSession, require_user
from app.core.market import KST
from app.db.enums import CycleState, FillSide, HoldingState
from app.db.models import Cycle, Fill, Holding, Instrument
from app.engine.holding_rules import atr_stop_price, daily_downtrend
from app.engine.indicators import atr
from app.services import holdings as service
from app.services.alert_engine import load_daily_context
from app.services.settings import load_signal_params

router = APIRouter(prefix="/holdings", tags=["holdings"], dependencies=[Depends(require_user)])


def register_error_handlers(app: FastAPI) -> None:
    """Map the service errors to HTTP statuses: 404 unknown, 409 wrong state, 422 bad values."""

    def handler(status_code: int):  # type: ignore[no-untyped-def]
        async def respond(_request: Request, error: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(error)}, status_code=status_code)

        return respond

    app.add_exception_handler(service.HoldingNotFoundError, handler(status.HTTP_404_NOT_FOUND))
    app.add_exception_handler(service.InvalidTransitionError, handler(status.HTTP_409_CONFLICT))
    app.add_exception_handler(
        service.InvalidFillError, handler(status.HTTP_422_UNPROCESSABLE_CONTENT)
    )


class CycleOut(BaseModel):
    id: int
    state: CycleState
    sell_price: float
    sell_quantity: int
    rebuy_target_price: float
    rebuy_price: float | None
    rebuy_quantity: int | None
    quantity_increase: int | None  # None until shares were bought back
    net_cash: float | None
    sell_fee: float
    sell_tax: float
    rebuy_fee: float | None
    expires_at: datetime | None
    created_at: datetime
    sold_at: datetime | None  # when the sale / the rebuy was filled: where the chart markers go
    rebought_at: datetime | None
    forced: bool  # ended by the A-13 forced sale


class TotalsOut(BaseModel):
    cycles: int
    completed: int
    successful: int
    cumulative_increase: int
    unrecovered_quantity: int
    pending_quantity: int
    start_quantity: int
    current_quantity: int


class HoldingOut(BaseModel):
    id: int
    code: str
    name: str
    market: str
    quantity: int
    start_quantity: int
    avg_price: float
    state: HoldingState
    open_cycle: CycleOut | None
    last_close: float | None
    daily_downtrend: bool | None
    stop_price: float | None  # A-8: draw this as a price line
    cumulative_increase: int
    unrecovered_quantity: int


class HoldingCreate(BaseModel):
    code: str
    quantity: int = Field(gt=0)
    avg_price: Decimal = Field(gt=0)


class HoldingUpdate(BaseModel):
    quantity: int = Field(ge=0)
    avg_price: Decimal = Field(gt=0)


class FillCreate(BaseModel):
    side: FillSide
    price: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)
    filled_at: datetime | None = None
    fee: Decimal | None = Field(default=None, ge=0)  # default: from the configured rates
    tax: Decimal | None = Field(default=None, ge=0)
    forced: bool = False  # the A-13 forced sale


class FillOut(BaseModel):
    id: int
    side: FillSide
    price: float
    quantity: int
    filled_at: datetime
    fee: float
    tax: float
    forced: bool


class FillResponse(BaseModel):
    fill: FillOut
    cycle: CycleOut
    holding: HoldingOut


class CyclesResponse(BaseModel):
    holding_id: int
    cycles: list[CycleOut]
    totals: TotalsOut


def _cycle_out(view: service.CycleView) -> CycleOut:
    c = view.cycle
    return CycleOut(
        id=c.id,
        state=c.state,
        sell_price=float(c.sell_price),
        sell_quantity=c.sell_quantity,
        rebuy_target_price=float(c.rebuy_target_price),
        rebuy_price=None if c.rebuy_price is None else float(c.rebuy_price),
        rebuy_quantity=c.rebuy_quantity,
        quantity_increase=view.quantity_increase,
        net_cash=None if view.net_cash is None else float(view.net_cash),
        sell_fee=float(view.sell_fee),
        sell_tax=float(view.sell_tax),
        rebuy_fee=None if view.rebuy_fee is None else float(view.rebuy_fee),
        expires_at=c.expires_at,
        created_at=c.created_at,
        sold_at=view.sold_at,
        rebought_at=view.rebought_at,
        forced=view.forced,
    )


def _holding_out(db: DbSession, holding: Holding) -> HoldingOut:
    instrument = db.get(Instrument, holding.code)
    views, totals = service.cycle_views(db, holding.id)
    open_cycle = next((v for v in views if v.cycle.state in service.OPEN_STATES), None)
    last_close = downtrend = stop = None
    ctx = load_daily_context(db, holding.code, datetime.now(KST))
    if not ctx.bars.empty:
        params = load_signal_params(db)
        close = ctx.bars["close"]
        last_close = float(close.iloc[-1])
        downtrend = bool(
            daily_downtrend(close, params.trend.ma_window, params.trend.slope_bars).iloc[-1]
        )
        daily_atr = atr(ctx.bars["high"], ctx.bars["low"], close, params.indicators.atr_period)
        value = atr_stop_price(float(holding.avg_price), daily_atr, params.stop.atr_multiple)
        stop = None if pd.isna(value.iloc[-1]) else float(value.iloc[-1])
    return HoldingOut(
        id=holding.id,
        code=holding.code,
        name=instrument.name if instrument else holding.code,
        market=instrument.market.value if instrument else "",
        quantity=holding.quantity,
        start_quantity=holding.start_quantity,
        avg_price=float(holding.avg_price),
        state=holding.state,
        open_cycle=_cycle_out(open_cycle) if open_cycle else None,
        last_close=last_close,
        daily_downtrend=downtrend,
        stop_price=stop,
        cumulative_increase=totals.cumulative_increase,
        unrecovered_quantity=totals.unrecovered_quantity,
    )


@router.get("")
def list_holdings(db: DbSession) -> list[HoldingOut]:
    from sqlalchemy import select

    return [_holding_out(db, h) for h in db.scalars(select(Holding).order_by(Holding.id))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_holding(body: HoldingCreate, db: DbSession) -> HoldingOut:
    """A-1: register a position. Its quantity is recorded as the 시작 수량."""
    holding = service.register(db, body.code, body.quantity, body.avg_price)
    db.commit()
    return _holding_out(db, holding)


@router.put("/{holding_id}")
def update_holding(holding_id: int, body: HoldingUpdate, db: DbSession) -> HoldingOut:
    """Correct the quantity or average price (only while no cycle is open)."""
    holding = service.correct(db, holding_id, body.quantity, body.avg_price)
    db.commit()
    return _holding_out(db, holding)


@router.delete("/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(holding_id: int, db: DbSession) -> Response:
    service.remove(db, holding_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{holding_id}/fills", status_code=status.HTTP_201_CREATED)
def record_fill(holding_id: int, body: FillCreate, db: DbSession) -> FillResponse:
    """Record a sale or rebuy the user made. This is what moves the holding's state."""
    result = service.record_fill(
        db,
        holding_id,
        body.side,
        body.price,
        body.quantity,
        filled_at=body.filled_at,
        fee=body.fee,
        tax=body.tax,
        forced=body.forced,
    )
    db.commit()
    views, _ = service.cycle_views(db, holding_id)
    view = next(v for v in views if v.cycle.id == result.cycle.id)
    fill: Fill = result.fill
    return FillResponse(
        fill=FillOut(
            id=fill.id,
            side=fill.side,
            price=float(fill.price),
            quantity=fill.quantity,
            filled_at=fill.filled_at,
            fee=float(fill.fee),
            tax=float(fill.tax),
            forced=fill.forced,
        ),
        cycle=_cycle_out(view),
        holding=_holding_out(db, result.holding),
    )


@router.get("/{holding_id}/cycles")
def list_cycles(holding_id: int, db: DbSession) -> CyclesResponse:
    """Every sell/rebuy cycle with its 수량 증가분, and the running totals (A-9)."""
    views, totals = service.cycle_views(db, holding_id)
    return CyclesResponse(
        holding_id=holding_id,
        cycles=[_cycle_out(v) for v in views],
        totals=TotalsOut(**{name: getattr(totals, name) for name in TotalsOut.model_fields}),
    )


def _single_cycle(db: DbSession, holding_id: int, cycle: Cycle) -> CycleOut:
    views, _ = service.cycle_views(db, holding_id)
    return _cycle_out(next(v for v in views if v.cycle.id == cycle.id))


@router.post("/{holding_id}/cycles/{cycle_id}/retry")
def retry_cycle(holding_id: int, cycle_id: int, db: DbSession) -> CycleOut:
    """'재매수 시도': an expired cycle waits for another window."""
    cycle = service.retry_cycle(db, holding_id, cycle_id)
    db.commit()
    return _single_cycle(db, holding_id, cycle)


@router.post("/{holding_id}/cycles/{cycle_id}/abandon")
def abandon_cycle(holding_id: int, cycle_id: int, db: DbSession) -> CycleOut:
    """'사이클 포기': stop waiting to rebuy."""
    cycle = service.abandon_cycle(db, holding_id, cycle_id)
    db.commit()
    return _single_cycle(db, holding_id, cycle)
