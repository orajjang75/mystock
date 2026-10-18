import logging
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession, Now
from app.core.config import get_settings
from app.db.models import OhlcvDaily, OhlcvIntraday
from app.services.freshness import evaluate_freshness
from app.services.notifier import channel_states
from app.services.settings import load_channels

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthWarning(BaseModel):
    source: str  # "intraday" or "daily"
    message: str


class SourceHealth(BaseModel):
    stale: bool
    last_success: datetime | None
    last_error: str | None


class ChannelHealth(BaseModel):
    enabled: bool
    configured: bool


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]  # degraded: the market data is stale
    db: Literal["ok", "error"]
    last_quote_update: datetime | None = None
    last_daily_update: datetime | None = None
    last_intraday_update: datetime | None = None
    latest_daily_date: date | None = None
    latest_intraday_bar: datetime | None = None
    warnings: list[HealthWarning] = []
    collection: dict[str, SourceHealth] = {}
    channels: dict[str, ChannelHealth] = {}
    scheduler: Literal["running", "disabled"] = "disabled"


@router.get("/health")
def health(db: DbSession, response: Response, request: Request, now: Now) -> HealthResponse:
    """DB connection, last quote update, data freshness warnings and notification channels."""
    settings = get_settings()
    scheduler = getattr(request.app.state, "scheduler", None)
    running: Literal["running", "disabled"] = (
        "running" if scheduler is not None and scheduler.running else "disabled"
    )
    try:
        db.execute(select(1))
        last_daily_update, latest_daily_date = db.execute(
            select(func.max(OhlcvDaily.updated_at), func.max(OhlcvDaily.trade_date))
        ).one()
        last_intraday_update, latest_intraday_bar = db.execute(
            select(func.max(OhlcvIntraday.updated_at), func.max(OhlcvIntraday.bar_time))
        ).one()
        report = evaluate_freshness(db, now, settings.daily_scan_time)
        channels = channel_states(settings, load_channels(db))
    except SQLAlchemyError as exc:
        # Log the exception type only: the message can embed the connection URL.
        logger.error("health check: database error (%s)", type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="error", db="error", scheduler=running)

    updates = [t for t in (last_daily_update, last_intraday_update) if t is not None]
    return HealthResponse(
        status="ok" if report.ok else "degraded",
        db="ok",
        last_quote_update=max(updates) if updates else None,
        last_daily_update=last_daily_update,
        last_intraday_update=last_intraday_update,
        latest_daily_date=latest_daily_date,
        latest_intraday_bar=latest_intraday_bar,
        warnings=[HealthWarning(source=w.source, message=w.message or "") for w in report.warnings],
        collection={
            name: SourceHealth(stale=s.stale, last_success=s.last_success, last_error=s.last_error)
            for name, s in report.sources.items()
        },
        channels={
            c.name: ChannelHealth(enabled=c.enabled, configured=c.configured) for c in channels
        },
        scheduler=running,
    )
