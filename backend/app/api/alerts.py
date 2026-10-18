from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import DbSession, require_user
from app.core.config import get_settings
from app.db.models import Alert, Instrument
from app.services import alerts as service
from app.services.notifier import build_notifiers
from app.services.settings import load_channels

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_user)])


class AlertOut(BaseModel):
    id: int
    kind: str
    label: str
    level: str  # "signal" or "warning": a held-back rebuy or a stop breach is a warning
    code: str | None
    name: str | None
    holding_id: int | None
    occurred_at: datetime
    bar_time: datetime | None
    suggested_quantity: int | None
    price: float | None
    rebuy_target_price: float | None
    evidence: dict[str, Any]  # the indicator values behind the signal
    params: dict[str, Any] | None  # the parameters used; only with include_params=true
    is_read: bool
    delivery: list[dict[str, Any]]


class AlertKindOut(BaseModel):
    kind: str
    label: str
    level: str


class AlertsResponse(BaseModel):
    unread: int
    items: list[AlertOut]
    kinds: list[AlertKindOut]  # what the kind filter offers, in display order


class TestResponse(BaseModel):
    channels: list[dict[str, str]]


def _out(db: DbSession, alert: Alert, include_params: bool) -> AlertOut:
    instrument = db.get(Instrument, alert.code) if alert.code else None
    return AlertOut(
        id=alert.id,
        kind=alert.kind,
        label=service.KIND_LABELS.get(alert.kind, alert.kind),
        level=service.level_of(alert.kind),
        code=alert.code,
        name=instrument.name if instrument else None,
        holding_id=alert.holding_id,
        occurred_at=alert.occurred_at,
        bar_time=alert.bar_time,
        suggested_quantity=alert.suggested_quantity,
        price=None if alert.price is None else float(alert.price),
        rebuy_target_price=None
        if alert.rebuy_target_price is None
        else float(alert.rebuy_target_price),
        evidence=alert.evidence,
        params=alert.params if include_params else None,
        is_read=alert.is_read,
        delivery=alert.delivery,
    )


@router.get("")
def list_alerts(
    db: DbSession,
    unread_only: bool = False,
    kind: str | None = None,
    code: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_params: bool = False,
) -> AlertsResponse:
    """Alerts, newest first, filterable by kind, stock and read state."""
    rows = service.list_alerts(
        db, unread_only=unread_only, kind=kind, code=code, limit=limit, offset=offset
    )
    return AlertsResponse(
        unread=service.unread_count(db),
        items=[_out(db, a, include_params) for a in rows],
        kinds=[
            AlertKindOut(kind=k, label=label, level=service.level_of(k))
            for k, label in service.KIND_LABELS.items()
            if k != "test"
        ],
    )


@router.post("/{alert_id}/read")
def read(alert_id: int, db: DbSession) -> AlertOut:
    alert = service.mark_read(db, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown alert {alert_id}")
    db.commit()
    return _out(db, alert, include_params=False)


@router.post("/test")
def send_test(db: DbSession) -> TestResponse:
    """Send a test message through every switched-on, configured outside channel."""
    notifiers = build_notifiers(get_settings(), load_channels(db))
    if not notifiers:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No outside channel is switched on and configured"
        )
    return TestResponse(channels=service.send_test(notifiers))
