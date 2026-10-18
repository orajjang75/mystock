from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, require_user
from app.db.models import ScanResult, Watchlist
from app.engine.params import SignalParams
from app.services import screener

router = APIRouter(prefix="/screener", tags=["screener"], dependencies=[Depends(require_user)])


class TagOut(BaseModel):
    key: str
    label: str


class ResultItem(BaseModel):
    code: str
    name: str
    market: str
    score: float
    tags: list[TagOut]
    close: float | None
    change_pct: float | None
    trading_value: float | None
    flow_unreflected: bool
    in_watchlist: bool
    evidence: dict[str, Any]  # indicator values behind the score, and its breakdown by section


class ResultsResponse(BaseModel):
    scan_date: date | None
    scan_dates: list[date]  # dates with saved results, newest first
    gate: dict[str, Any] | None  # how the gate was applied (mode and drawdown threshold)
    items: list[ResultItem]


@router.get("/results")
def results(
    db: DbSession, scan_date: date | None = None, min_score: float = 0.0
) -> ResultsResponse:
    """Saved scan results by score. Defaults to the latest scan date."""
    dates = screener.scan_dates(db)
    day = scan_date or (dates[0] if dates else None)
    if day is None:
        return ResultsResponse(scan_date=None, scan_dates=[], gate=None, items=[])
    rows = screener.results_for(db, day, min_score)
    watched = set(db.scalars(select(Watchlist.code)))
    first = db.scalars(
        select(ScanResult.params).where(ScanResult.scan_date == day).limit(1)
    ).first()
    return ResultsResponse(
        scan_date=day,
        scan_dates=dates,
        gate=first.get("gate") if first else None,
        items=[
            ResultItem(
                code=row.code,
                name=row.name,
                market=row.market,
                score=row.score,
                tags=[TagOut(key=t, label=screener.TAG_LABELS.get(t, t)) for t in row.tags],
                close=row.close,
                change_pct=row.change_pct,
                trading_value=row.trading_value,
                flow_unreflected=row.flow_unreflected,
                in_watchlist=row.code in watched,
                evidence=row.evidence,
            )
            for row in rows
        ],
    )


class RunRequest(BaseModel):
    scan_date: date | None = None  # default: the latest stored trading day
    params: SignalParams | None = None  # default: the saved settings


class RunResponse(BaseModel):
    scan_date: date
    universe_size: int
    gate_mode: str
    drawdown_threshold_pct: float | None
    gated: int
    saved: int
    elapsed_seconds: float


@router.post("/run")
def run(db: DbSession, body: RunRequest | None = None) -> RunResponse:
    """Scan the stored universe now and save the results (replacing that date's results)."""
    body = body or RunRequest()
    try:
        summary = screener.run_scan(db, body.scan_date, body.params)
    except screener.ScanError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    db.commit()
    return RunResponse(
        scan_date=summary.scan_date,
        universe_size=summary.universe_size,
        gate_mode=summary.gate_mode,
        drawdown_threshold_pct=summary.drawdown_threshold_pct,
        gated=summary.gated,
        saved=summary.saved,
        elapsed_seconds=summary.elapsed_seconds,
    )
